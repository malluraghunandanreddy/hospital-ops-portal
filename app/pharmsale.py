"""Quick medicine sales at the pharmacy counter.

The counter is too busy to make each bill in Pharmasoft while the patient waits, so staff
wrote sales on paper and typed them into Pharmasoft later. This replaces the paper:

- The pharmacist taps the patient (today's OP patient with their prescription photo,
  an inpatient, or a walk-in), picks medicines from the stock list (batch, expiry, MRP),
  takes the money and the patient leaves. Expired batches cannot be sold.
- Inpatient sales take no money: they go onto the patient's hospital bill.
- Later, "To enter in Pharmasoft" lists each sale with its fields ready to copy into
  Pharmasoft's Counter Sales screen; the Pharmasoft bill number is noted to close it.
- Pharmasoft stays the pharmacy's official billing software.
"""
import datetime

from core import ApiError, clean, now, route, to_int, today
import billing

SCHEMA = """
CREATE TABLE IF NOT EXISTS pharmacy_sales(
  id INTEGER PRIMARY KEY, sale_no TEXT UNIQUE NOT NULL, at TEXT, kind TEXT NOT NULL, patient_id INTEGER, visit_id INTEGER,
  admission_id INTEGER, name TEXT, phone TEXT, doctor_id INTEGER, total INTEGER NOT NULL, mode TEXT, ref TEXT, sold_by TEXT,
  pharmasoft_no TEXT, entered_by TEXT, entered_at TEXT, cancelled INTEGER DEFAULT 0, cancelled_by TEXT, cancel_reason TEXT,
  ip_charge_id INTEGER);
CREATE TABLE IF NOT EXISTS pharmacy_sale_items(
  id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES pharmacy_sales(id), item TEXT NOT NULL, batch TEXT, expiry TEXT,
  qty REAL NOT NULL, rate REAL NOT NULL, amount REAL NOT NULL);
"""
MODES = ('Cash', 'UPI', 'Card')


@route('GET', r'/api/pharmacy/items', ('pharmsale',))
def items(app, staff, p, b):
    q = clean(p.get('q'), 40)
    if len(q) < 2:
        return {'items': []}
    rows = app.q('SELECT item, batch, expiry, qty, mrp FROM stock WHERE item LIKE ? ORDER BY item, expiry LIMIT 30', ('%' + q + '%',))
    td = today()
    for r in rows:
        r['expired'] = bool(r['expiry'] and r['expiry'] < td)
    return {'items': rows}


@route('GET', r'/api/pharmacy/customers', ('pharmsale',))
def customers(app, staff, p, b):
    """Who can be picked at the counter: today's OP patients (with prescription photos) and inpatients."""
    op = app.q("SELECT v.id visit_id, v.patient_id, v.token_code, v.doctor_id, v.status, p.name, p.phone, dr.name doctor, "
               "(SELECT GROUP_CONCAT(r.id) FROM prescriptions r WHERE r.visit_id=v.id) rx, "
               "(SELECT COUNT(*) FROM pharmacy_sales s WHERE s.visit_id=v.id AND s.cancelled=0) sales "
               "FROM visits v JOIN patients p ON p.id=v.patient_id LEFT JOIN doctors dr ON dr.id=v.doctor_id "
               "WHERE v.visit_date=? AND v.status<>'skipped' ORDER BY (v.status='done') DESC, v.done_at DESC, v.id DESC", (today(),))
    for r in op:
        r['rx'] = [int(x) for x in (r['rx'] or '').split(',') if x]
    ip = app.q("SELECT a.id admission_id, a.patient_id, b.label bed, p.name, dr.name doctor FROM admissions a JOIN beds b ON b.id=a.bed_id "
               "JOIN patients p ON p.id=a.patient_id LEFT JOIN doctors dr ON dr.id=a.doctor_id WHERE a.status='admitted' ORDER BY b.id")
    return {'op': op, 'ip': ip, 'modes': MODES}


@route('POST', r'/api/pharmacy/sales', ('pharmsale',))
def make_sale(app, staff, p, b):
    kind = b.get('kind')
    if kind not in ('op', 'ip', 'walkin'):
        raise ApiError(400, 'Choose the customer')
    lines = []
    for x in (b.get('items') or [])[:60]:
        name = clean(x.get('item'), 120)
        try:
            qty, rate = float(x.get('qty')), float(x.get('rate'))
        except (TypeError, ValueError):
            raise ApiError(400, 'Check the quantity and rate of %s' % (name or 'each medicine'))
        if not name or not 0 < qty <= 1000 or not 0 <= rate <= 100000:
            raise ApiError(400, 'Check the quantity and rate of %s' % (name or 'each medicine'))
        expiry = clean(x.get('expiry'), 10) or None
        if expiry and expiry < today():
            raise ApiError(400, '%s batch %s is expired. Do not sell it.' % (name, clean(x.get('batch'))))
        lines.append((name, clean(x.get('batch'), 40), expiry, qty, rate, round(qty * rate, 2)))
    if not lines:
        raise ApiError(400, 'Add at least one medicine')
    total = round(sum(x[5] for x in lines))
    vals = {'kind': kind, 'name': clean(b.get('name')), 'phone': ''.join(c for c in str(b.get('phone') or '') if c.isdigit())[:10],
            'patient_id': None, 'visit_id': None, 'admission_id': None, 'doctor_id': None, 'mode': None, 'ref': None}
    if kind == 'op':
        v = app.one('SELECT v.*, p.name, p.phone FROM visits v JOIN patients p ON p.id=v.patient_id WHERE v.id=?', (to_int(b.get('visit_id')),))
        if not v:
            raise ApiError(400, 'Choose the patient')
        vals.update(patient_id=v['patient_id'], visit_id=v['id'], doctor_id=v['doctor_id'], name=v['name'], phone=v['phone'])
    elif kind == 'ip':
        a = app.one("SELECT a.*, p.name, p.phone FROM admissions a JOIN patients p ON p.id=a.patient_id WHERE a.id=? AND a.status='admitted'",
                    (to_int(b.get('admission_id')),))
        if not a:
            raise ApiError(400, 'Choose the inpatient')
        if billing.is_final(app, a['id']):
            raise ApiError(409, 'This patient\'s final bill is already made. Ask the billing desk.')
        vals.update(patient_id=a['patient_id'], admission_id=a['id'], doctor_id=a['doctor_id'], name=a['name'], phone=a['phone'])
    if kind != 'ip':
        if b.get('mode') not in MODES:
            raise ApiError(400, 'Choose how the patient paid')
        if b.get('mode') != 'Cash' and not clean(b.get('ref')):
            raise ApiError(400, 'Enter the UPI / card reference')
        vals.update(mode=b['mode'], ref=clean(b.get('ref'), 60))
    with app.tx():
        no = billing.next_number(app, 'PS')
        sid = app.run('INSERT INTO pharmacy_sales(sale_no, at, kind, patient_id, visit_id, admission_id, name, phone, doctor_id, total, mode, ref, sold_by) '
                      'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (no, now(), kind, vals['patient_id'], vals['visit_id'], vals['admission_id'], vals['name'],
                                                            vals['phone'], vals['doctor_id'], total, vals['mode'], vals['ref'], staff['name']))
        for x in lines:
            app.run('INSERT INTO pharmacy_sale_items(sale_id, item, batch, expiry, qty, rate, amount) VALUES(?,?,?,?,?,?,?)', (sid,) + x)
        if kind == 'ip':
            cid = app.run("INSERT INTO ip_charges(admission_id, category, name, unit, qty, rate, amount, for_date, note, entered_by, entered_at) "
                          "VALUES(?,'pharmacy',?,'each',1,?,?,?,?,?,?)", (vals['admission_id'], 'Pharmacy sale ' + no, total, total, today(),
                                                                          '; '.join('%s x%g' % (x[0], x[3]) for x in lines)[:200], staff['name'], now()))
            app.run('UPDATE pharmacy_sales SET ip_charge_id=? WHERE id=?', (cid, sid))
        if kind == 'op' and vals['visit_id']:
            app.run('UPDATE visits SET bought=1, not_bought_reason=NULL WHERE id=?', (vals['visit_id'],))
        app.audit(staff, 'pharmacy.sale', 'pharmacy_sale', sid, {'sale': no, 'total': total, 'kind': kind, 'lines': len(lines)})
    return {'id': sid, 'sale_no': no, 'total': total}


def sale_rows(app, where, args):
    rows = app.q('SELECT s.*, dr.name doctor FROM pharmacy_sales s LEFT JOIN doctors dr ON dr.id=s.doctor_id WHERE ' + where + ' ORDER BY s.id DESC LIMIT 300', args)
    for r in rows:
        r['items'] = app.q('SELECT item, batch, expiry, qty, rate, amount FROM pharmacy_sale_items WHERE sale_id=? ORDER BY id', (r['id'],))
    return rows


@route('GET', r'/api/pharmacy/sales', ('pharmsale',))
def list_sales(app, staff, p, b):
    day = clean(p.get('date'), 10) or today()
    if p.get('pending') == '1':
        rows = sale_rows(app, 's.pharmasoft_no IS NULL AND s.cancelled=0', ())
    else:
        rows = sale_rows(app, 'substr(s.at, 1, 10)=?', (day,))
    return {'sales': rows, 'day': day_totals(app, day),
            'pending': app.one('SELECT COUNT(*) n FROM pharmacy_sales WHERE pharmasoft_no IS NULL AND cancelled=0')['n']}


@route('POST', r'/api/pharmacy/sales/(\d+)/entered', ('pharmsale',))
def entered(app, staff, p, b, sid):
    s = app.one('SELECT * FROM pharmacy_sales WHERE id=? AND cancelled=0', (sid,))
    if not s:
        raise ApiError(404, 'Not found')
    no = clean(b.get('pharmasoft_no'), 30)
    if not no:
        raise ApiError(400, 'Enter the bill number Pharmasoft gave')
    with app.tx():
        app.run('UPDATE pharmacy_sales SET pharmasoft_no=?, entered_by=?, entered_at=? WHERE id=?', (no, staff['name'], now(), sid))
        app.audit(staff, 'pharmacy.entered', 'pharmacy_sale', sid, {'pharmasoft_no': no})
    return {'ok': True}


@route('POST', r'/api/pharmacy/sales/(\d+)/cancel', ('pharmsale',))
def cancel(app, staff, p, b, sid):
    s = app.one('SELECT * FROM pharmacy_sales WHERE id=? AND cancelled=0', (sid,))
    if not s:
        raise ApiError(404, 'Not found')
    if staff['role'] != 'owner' and not (s['sold_by'] == staff['name'] and s['at'][:10] == today()):
        raise ApiError(403, 'Only the person who made the sale can cancel it, on the same day. Otherwise a full-access doctor must.')
    reason = clean(b.get('reason'), 200)
    if len(reason) < 3:
        raise ApiError(400, 'Write why this sale is cancelled (for example: medicine returned)')
    if s['admission_id'] and billing.is_final(app, s['admission_id']):
        raise ApiError(409, 'The patient\'s final bill is already made. Ask a full-access doctor to reopen it first.')
    with app.tx():
        app.run('UPDATE pharmacy_sales SET cancelled=1, cancelled_by=?, cancel_reason=? WHERE id=?', (staff['name'], reason, sid))
        if s['ip_charge_id']:
            app.run('UPDATE ip_charges SET cancelled=1, cancelled_by=?, cancel_reason=? WHERE id=?', (staff['name'], 'Pharmacy sale cancelled: ' + reason, s['ip_charge_id']))
        app.audit(staff, 'pharmacy.cancel', 'pharmacy_sale', sid, {'sale': s['sale_no'], 'reason': reason})
    return {'ok': True}


def day_totals(app, day):
    rows = app.q('SELECT kind, mode, total, sold_by FROM pharmacy_sales WHERE cancelled=0 AND substr(at, 1, 10)=?', (day,))
    by_mode, cash_by = {}, {}
    for r in rows:
        if r['kind'] == 'ip':
            continue
        by_mode[r['mode']] = by_mode.get(r['mode'], 0) + r['total']
        if r['mode'] == 'Cash':
            cash_by[r['sold_by']] = cash_by.get(r['sold_by'], 0) + r['total']
    return {'count': len(rows), 'counter': sum(by_mode.values()), 'by_mode': by_mode, 'cash_by_person': cash_by,
            'to_ip_bills': sum(r['total'] for r in rows if r['kind'] == 'ip'),
            'pending': app.one('SELECT COUNT(*) n FROM pharmacy_sales WHERE pharmasoft_no IS NULL AND cancelled=0')['n']}


def demo(app):
    if app.one('SELECT id FROM pharmacy_sales LIMIT 1'):
        return
    desk = {'id': None, 'name': 'Ch. Ramesh Kumar', 'role': 'pharmacy'}
    v = app.q("SELECT id FROM visits WHERE visit_date=? AND status='done' ORDER BY id LIMIT 3", (today(),))
    stock = {r['batch']: r for r in app.q('SELECT * FROM stock')}
    plan = [('PCS410', 1, 'ZN220', 1), ('CTZ14', 1, 'CAL88', 1), ('PC2291', 2, 'IFA07', 3)]
    for i, vis in enumerate(v):
        a, qa, c, qc = plan[i]
        make_sale(app, desk, {}, {'kind': 'op', 'visit_id': vis['id'], 'mode': 'Cash' if i != 1 else 'UPI', 'ref': '' if i != 1 else 'UPI482211',
                                   'items': [dict(item=stock[a]['item'], batch=a, expiry=stock[a]['expiry'], qty=qa, rate=stock[a]['mrp']),
                                             dict(item=stock[c]['item'], batch=c, expiry=stock[c]['expiry'], qty=qc, rate=stock[c]['mrp'])]})
