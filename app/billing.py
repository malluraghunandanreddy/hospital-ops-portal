"""Inpatient billing. The existing software (Essel, Pharmasoft) is not used for inpatients,
so the inpatient bill is made here.

- Charges come from the price list (see charges.py); pharmacy and outside-lab bills are added
  with their own bill number by the pharmacy or the billing desk.
- Advances, payments and refunds get a numbered receipt (R/2026-27/0001).
- The final bill gets a bill number (IP/2026-27/0001) and locks the charges.
- Only full-access doctors give discounts or reopen a final bill, always with a reason.
- Nothing is deleted. A wrong receipt is cancelled with a reason and stays on record.
"""
import datetime

from core import ApiError, clean, now, route, to_int, today
import charges

SCHEMA = """
CREATE TABLE IF NOT EXISTS ip_payments(
  id INTEGER PRIMARY KEY, admission_id INTEGER NOT NULL REFERENCES admissions(id), kind TEXT NOT NULL, amount INTEGER NOT NULL,
  mode TEXT NOT NULL, ref TEXT, receipt_no TEXT UNIQUE NOT NULL, received_by TEXT, at TEXT,
  cancelled INTEGER DEFAULT 0, cancelled_by TEXT, cancel_reason TEXT);
CREATE TABLE IF NOT EXISTS ip_discounts(
  id INTEGER PRIMARY KEY, admission_id INTEGER NOT NULL REFERENCES admissions(id), amount INTEGER NOT NULL, reason TEXT NOT NULL,
  given_by TEXT, at TEXT, cancelled INTEGER DEFAULT 0, cancelled_by TEXT, cancel_reason TEXT);
CREATE TABLE IF NOT EXISTS ip_bills(
  admission_id INTEGER PRIMARY KEY REFERENCES admissions(id), bill_no TEXT UNIQUE NOT NULL, scheme_amount INTEGER DEFAULT 0,
  total INTEGER, discount INTEGER, finalised_by TEXT, finalised_at TEXT, reopened INTEGER DEFAULT 0, reopened_by TEXT, reopen_reason TEXT);
"""
MODES = ('Cash', 'UPI', 'Card', 'Cheque', 'Bank transfer')
KINDS = {'advance': 'Advance', 'payment': 'Payment', 'refund': 'Refund'}
FULL = 'owner'


def fin_year(d=None):
    d = d or datetime.date.today()
    y = d.year if d.month >= 4 else d.year - 1
    return '%d-%02d' % (y, (y + 1) % 100)


def next_number(app, prefix):
    """Gap-free running number for the financial year. Call inside a transaction."""
    key = 'seq_%s_%s' % (prefix, fin_year())
    n = int(app.setting(key, '0')) + 1
    app.set_setting(key, str(n))
    return '%s/%s/%04d' % (prefix, fin_year(), n)


def record_payment(app, staff, aid, kind, amount, mode, ref):
    """Caller must hold a transaction."""
    if kind not in KINDS:
        raise ApiError(400, 'Choose advance, payment or refund')
    amount = to_int(str(amount or '').replace(',', '').strip())
    if not amount or not 0 < amount <= 10000000:
        raise ApiError(400, 'Enter the amount in rupees')
    if mode not in MODES:
        raise ApiError(400, 'Choose how it was paid')
    if mode != 'Cash' and kind != 'refund' and not clean(ref):
        raise ApiError(400, 'Enter the UPI / card / cheque reference number')
    if kind == 'refund':
        s = state(app, aid)
        if amount > s['paid'] - max(s['payable'], 0):
            raise ApiError(400, 'Refund is more than the extra amount paid (%d)' % max(s['paid'] - max(s['payable'], 0), 0))
    no = next_number(app, 'R')
    pid = app.run('INSERT INTO ip_payments(admission_id, kind, amount, mode, ref, receipt_no, received_by, at) VALUES(?,?,?,?,?,?,?,?)',
                  (aid, kind, amount, mode, clean(ref, 60), no, staff['name'], now()))
    app.audit(staff, 'payment.' + kind, 'admission', aid, {'receipt': no, 'amount': amount, 'mode': mode})
    settle_step(app, aid, staff)
    return pid, no


def state(app, aid):
    """Running totals for one admission."""
    live = app.q('SELECT category, amount FROM ip_charges WHERE admission_id=? AND cancelled=0', (aid,))
    total = sum(x['amount'] for x in live)
    discount = app.one('SELECT COALESCE(SUM(amount), 0) n FROM ip_discounts WHERE admission_id=? AND cancelled=0', (aid,))['n']
    pays = app.q('SELECT kind, amount FROM ip_payments WHERE admission_id=? AND cancelled=0', (aid,))
    paid = sum(p['amount'] for p in pays if p['kind'] != 'refund') - sum(p['amount'] for p in pays if p['kind'] == 'refund')
    bill = app.one('SELECT * FROM ip_bills WHERE admission_id=?', (aid,))
    scheme = bill['scheme_amount'] if bill else 0
    payable = total - discount - scheme
    return {'total': total, 'discount': discount, 'scheme_amount': scheme, 'payable': payable, 'paid': paid,
            'balance': payable - paid, 'bill': bill, 'final': bool(bill and not bill['reopened'])}


def is_final(app, aid):
    b = app.one('SELECT reopened FROM ip_bills WHERE admission_id=?', (aid,))
    return bool(b and not b['reopened'])


def settle_step(app, aid, staff):
    """Discharge step 'final bill' ticks itself once the final bill is made and nothing is left to pay."""
    s = state(app, aid)
    if s['final'] and s['balance'] <= 0:
        app.run('INSERT OR REPLACE INTO discharge_steps(admission_id, step, done_at, done_by) VALUES(?,?,?,?)', (aid, 'bill', now(), staff['name']))
    else:
        app.run("DELETE FROM discharge_steps WHERE admission_id=? AND step='bill'", (aid,))


def admission(app, staff, aid):
    import more
    return more.admission_for(app, staff, aid)


@route('GET', r'/api/admissions/(\d+)/bill', ('ipbill', 'claims', 'accounts'))
def get_bill(app, staff, p, b, aid):
    a = admission(app, staff, aid)
    s = state(app, aid)
    return {'admission': a, 'state': s, 'charges': charges.summary(app, a), 'categories': charges.CATEGORIES,
            'payments': app.q('SELECT * FROM ip_payments WHERE admission_id=? ORDER BY id', (aid,)),
            'discounts': app.q('SELECT * FROM ip_discounts WHERE admission_id=? ORDER BY id', (aid,)),
            'modes': MODES, 'can_discount': staff['role'] == FULL,
            'claim_sent': app.one('SELECT id, sent_at, sent_by, status, next_followup FROM claims WHERE admission_id=? AND sent_at IS NOT NULL', (aid,))}


@route('POST', r'/api/admissions/(\d+)/payments', ('ipbill',))
def add_payment(app, staff, p, b, aid):
    admission(app, staff, aid)
    with app.tx():
        pid, no = record_payment(app, staff, aid, b.get('kind'), b.get('amount'), b.get('mode'), b.get('ref'))
    return {'id': pid, 'receipt_no': no}


@route('POST', r'/api/ip-payments/(\d+)/cancel', ('ipbill',))
def cancel_payment(app, staff, p, b, pid):
    pay = app.one('SELECT * FROM ip_payments WHERE id=? AND cancelled=0', (pid,))
    if not pay:
        raise ApiError(404, 'Not found')
    if staff['role'] != FULL and not (pay['received_by'] == staff['name'] and pay['at'][:10] == today()):
        raise ApiError(403, 'Only the person who took it can cancel a receipt, and only on the same day. Otherwise a full-access doctor must do it.')
    reason = clean(b.get('reason'), 200)
    if len(reason) < 3:
        raise ApiError(400, 'Write why this receipt is cancelled')
    with app.tx():
        app.run('UPDATE ip_payments SET cancelled=1, cancelled_by=?, cancel_reason=? WHERE id=?', (staff['name'], reason, pid))
        app.audit(staff, 'payment.cancel', 'admission', pay['admission_id'], {'receipt': pay['receipt_no'], 'reason': reason})
        settle_step(app, pay['admission_id'], staff)
    return {'ok': True}


@route('POST', r'/api/admissions/(\d+)/discount', ('ipbill',))
def add_discount(app, staff, p, b, aid):
    if staff['role'] != FULL:
        raise ApiError(403, 'Only a full-access doctor can give a discount')
    admission(app, staff, aid)
    if is_final(app, aid):
        raise ApiError(409, 'Final bill already made. Reopen it first.')
    amount = to_int(str(b.get('amount') or '').replace(',', ''))
    reason = clean(b.get('reason'), 200)
    s = state(app, aid)
    if not amount or not 0 < amount <= s['total'] - s['discount']:
        raise ApiError(400, 'Enter a discount amount up to the bill total')
    if len(reason) < 3:
        raise ApiError(400, 'Write the reason for the discount')
    with app.tx():
        did = app.run('INSERT INTO ip_discounts(admission_id, amount, reason, given_by, at) VALUES(?,?,?,?,?)', (aid, amount, reason, staff['name'], now()))
        app.audit(staff, 'discount.add', 'admission', aid, {'amount': amount, 'reason': reason})
    return {'id': did}


@route('POST', r'/api/ip-discounts/(\d+)/cancel', ('ipbill',))
def cancel_discount(app, staff, p, b, did):
    if staff['role'] != FULL:
        raise ApiError(403, 'Only a full-access doctor can do this')
    d = app.one('SELECT * FROM ip_discounts WHERE id=? AND cancelled=0', (did,))
    if not d:
        raise ApiError(404, 'Not found')
    if is_final(app, d['admission_id']):
        raise ApiError(409, 'Final bill already made. Reopen it first.')
    with app.tx():
        app.run('UPDATE ip_discounts SET cancelled=1, cancelled_by=?, cancel_reason=? WHERE id=?', (staff['name'], clean(b.get('reason'), 200) or 'removed', did))
        app.audit(staff, 'discount.cancel', 'admission', d['admission_id'], {'discount': did})
    return {'ok': True}


@route('POST', r'/api/admissions/(\d+)/external-bill', ('pharmacy', 'ipbill'))
def external_bill(app, staff, p, b, aid):
    """Pharmacy medicines issued to the ward, or an outside lab / scan bill, added with its own bill number."""
    a = admission(app, staff, aid)
    kind = b.get('kind')
    if kind not in ('pharmacy', 'outside'):
        raise ApiError(400, 'Choose pharmacy or outside lab / scan')
    if kind == 'outside' and not app.allowed(staff, 'ipbill'):
        raise ApiError(403, 'The billing desk adds outside bills')
    if is_final(app, aid):
        raise ApiError(409, 'Final bill already made. Ask a full-access doctor to reopen it.')
    amount = to_int(str(b.get('amount') or '').replace(',', ''))
    ref = clean(b.get('ref'), 40)
    if not amount or not 0 < amount <= 1000000:
        raise ApiError(400, 'Enter the bill amount')
    if not ref:
        raise ApiError(400, 'Enter the bill number')
    name = ('Pharmacy bill ' if kind == 'pharmacy' else 'Outside lab / scan bill ') + ref
    with app.tx():
        cid = app.run('INSERT INTO ip_charges(admission_id, category, name, unit, qty, rate, amount, for_date, note, entered_by, entered_at) '
                      'VALUES(?,?,?,?,?,?,?,?,?,?,?)', (aid, kind, name, 'each', 1, amount, amount, today(), clean(b.get('note'), 200), staff['name'], now()))
        app.audit(staff, 'charge.external', 'admission', aid, {'charge': cid, 'kind': kind, 'amount': amount, 'ref': ref})
    return {'id': cid, 'bed': a['bed']}


@route('POST', r'/api/admissions/(\d+)/finalise', ('ipbill',))
def finalise(app, staff, p, b, aid):
    a = admission(app, staff, aid)
    if is_final(app, aid):
        raise ApiError(409, 'Final bill already made')
    s = state(app, aid)
    if not s['total']:
        raise ApiError(400, 'There are no charges on this bill')
    scheme = to_int(str(b.get('scheme_amount') or '0').replace(',', ''), 0)
    if (a['payer'] or 'Cash') == 'Cash':
        scheme = 0
    if not 0 <= scheme <= s['total'] - s['discount']:
        raise ApiError(400, 'Scheme / insurance amount cannot be more than the bill')
    with app.tx():
        old = app.one('SELECT * FROM ip_bills WHERE admission_id=?', (aid,))
        no = old['bill_no'] if old else next_number(app, 'IP')      # a reopened bill keeps its number
        app.run('INSERT OR REPLACE INTO ip_bills(admission_id, bill_no, scheme_amount, total, discount, finalised_by, finalised_at, reopened) '
                'VALUES(?,?,?,?,?,?,?,0)', (aid, no, scheme, s['total'], s['discount'], staff['name'], now()))
        app.audit(staff, 'bill.final', 'admission', aid, {'bill': no, 'total': s['total'], 'scheme': scheme})
        settle_step(app, aid, staff)
    return {'bill_no': no, 'state': state(app, aid)}


@route('POST', r'/api/admissions/(\d+)/reopen-bill', ('ipbill',))
def reopen(app, staff, p, b, aid):
    if staff['role'] != FULL:
        raise ApiError(403, 'Only a full-access doctor can reopen a final bill')
    reason = clean(b.get('reason'), 200)
    if len(reason) < 3:
        raise ApiError(400, 'Write why the bill is reopened')
    if not is_final(app, aid):
        raise ApiError(409, 'There is no final bill to reopen')
    with app.tx():
        app.run('UPDATE ip_bills SET reopened=1, reopened_by=?, reopen_reason=? WHERE admission_id=?', (staff['name'], reason, aid))
        app.audit(staff, 'bill.reopen', 'admission', aid, {'reason': reason})
        settle_step(app, aid, staff)
    return {'ok': True}


@route('GET', r'/api/ipbilling', ('ipbill', 'pharmacy'))
def billing_list(app, staff, p, b):
    """Billing desk list: everyone in hospital, plus discharged patients whose bill is not settled."""
    rows = []
    for a in app.q("SELECT a.id, a.status, a.payer, a.admitted_at, a.discharged_at, a.discharge_ordered_at, b.label bed, b.ward, p.name, p.uhid "
                   "FROM admissions a JOIN beds b ON b.id=a.bed_id JOIN patients p ON p.id=a.patient_id "
                   "WHERE a.status='admitted' OR a.discharged_at>=? ORDER BY a.status<>'admitted', a.discharge_ordered_at IS NULL, b.id",
                   ((datetime.date.today() - datetime.timedelta(days=60)).isoformat(),)):
        s = state(app, a['id'])
        if a['status'] != 'admitted' and s['final'] and s['balance'] == 0:
            continue
        s.pop('bill')
        slip = app.one('SELECT id, sent_by, sent_at, total FROM charge_slips WHERE admission_id=? AND checked_at IS NULL ORDER BY id DESC LIMIT 1', (a['id'],))
        rows.append(dict(a, **s, slip=slip, bill_no=(app.one('SELECT bill_no FROM ip_bills WHERE admission_id=?', (a['id'],)) or {}).get('bill_no')))
    if not app.allowed(staff, 'ipbill'):   # the pharmacy only needs who is in hospital
        rows = [{k: r[k] for k in ('id', 'status', 'bed', 'ward', 'name', 'uhid')} for r in rows if r['status'] == 'admitted']
    return {'patients': rows}


def money_day(app, day):
    pays = app.q('SELECT kind, mode, amount, received_by FROM ip_payments WHERE cancelled=0 AND substr(at, 1, 10)=?', (day,))
    by_mode, by_person = {}, {}
    for x in pays:
        sign = -1 if x['kind'] == 'refund' else 1
        by_mode[x['mode']] = by_mode.get(x['mode'], 0) + sign * x['amount']
        if x['mode'] == 'Cash':
            by_person[x['received_by']] = by_person.get(x['received_by'], 0) + sign * x['amount']
    due = []
    for a in app.q("SELECT a.id, b.label bed, p.name, a.discharged_at FROM admissions a JOIN beds b ON b.id=a.bed_id JOIN patients p ON p.id=a.patient_id "
                   "WHERE a.status='discharged'"):
        s = state(app, a['id'])
        if s['balance'] > 0 or not s['final']:
            due.append(dict(a, balance=s['balance'], final=s['final']))
    return {'collected': sum(by_mode.values()), 'by_mode': by_mode, 'cash_by_person': by_person,
            'refunds': sum(x['amount'] for x in pays if x['kind'] == 'refund'),
            'discounts': app.one('SELECT COALESCE(SUM(amount), 0) n FROM ip_discounts WHERE cancelled=0 AND substr(at, 1, 10)=?', (day,))['n'],
            'cancelled': app.q('SELECT receipt_no, amount, cancelled_by, cancel_reason FROM ip_payments WHERE cancelled=1 AND substr(at, 1, 10)=?', (day,)),
            'bills': app.one('SELECT COUNT(*) n FROM ip_bills WHERE substr(finalised_at, 1, 10)=?', (day,))['n'], 'due_after_discharge': due}
