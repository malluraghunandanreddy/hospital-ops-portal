"""Inpatient charges: replaces the nurse's handwritten charge slip.

- Only full-access doctors set prices (Settings > Price list). Nobody else can type a price.
- Nurses and reception record WHAT was given and HOW MANY days / times. The amount is
  worked out from the price list, and the price at that moment is stored with the entry,
  so a later price change never alters past entries.
- Nothing is deleted: a wrong entry is cancelled with a reason and stays visible, struck through.
- Essel is not used for inpatients, so these lines make the inpatient bill (see billing.py).
"""
import datetime
import json
import math

from core import ApiError, clean, now, route, to_int, today

SCHEMA = """
CREATE TABLE IF NOT EXISTS price_items(
  id INTEGER PRIMARY KEY, category TEXT NOT NULL, name TEXT NOT NULL, unit TEXT NOT NULL, price INTEGER NOT NULL,
  ward TEXT DEFAULT '', active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS ip_charges(
  id INTEGER PRIMARY KEY, admission_id INTEGER NOT NULL REFERENCES admissions(id), price_item_id INTEGER,
  category TEXT, name TEXT NOT NULL, unit TEXT, qty REAL NOT NULL, rate INTEGER NOT NULL, amount INTEGER NOT NULL,
  for_date TEXT, note TEXT, entered_by TEXT, entered_at TEXT, billed INTEGER DEFAULT 0, billed_by TEXT, billed_at TEXT,
  cancelled INTEGER DEFAULT 0, cancelled_by TEXT, cancel_reason TEXT);
CREATE INDEX IF NOT EXISTS ix_charges_adm ON ip_charges(admission_id);
CREATE TABLE IF NOT EXISTS charge_slips(
  id INTEGER PRIMARY KEY, admission_id INTEGER NOT NULL REFERENCES admissions(id), sent_by TEXT, sent_at TEXT, total INTEGER,
  lines INTEGER, note TEXT, checked_by TEXT, checked_at TEXT, check_note TEXT);
"""

CATEGORIES = {'room': 'Room / bed', 'nursing': 'Nursing care', 'visit': 'Doctor visits', 'procedure': 'Procedures and OT',
              'service': 'Ward services', 'investigation': 'Investigations done in the hospital', 'other': 'Other',
              'pharmacy': 'Pharmacy (medicines)', 'outside': 'Outside lab / scan'}
PRICE_CATEGORIES = ('room', 'nursing', 'visit', 'procedure', 'service', 'investigation', 'other')
UNITS = {'day': 'per day', 'each': 'each time', 'hour': 'per hour'}

# PLACEHOLDER prices so the screens can be shown. The full-access doctors must set the real ones.
DEFAULT_PRICES = [
    ('room', 'General ward bed', 'day', 800, 'General Ward'), ('room', 'Room', 'day', 1500, 'Rooms'),
    ('room', 'Deluxe room', 'day', 2500, 'Deluxe Rooms'), ('room', 'ICU bed', 'day', 4000, 'ICU'),
    ('nursing', 'Nursing charges', 'day', 300, ''), ('nursing', 'ICU nursing and monitoring', 'day', 1000, ''),
    ('visit', 'Doctor visit (hospital doctor)', 'each', 300, ''), ('visit', 'Visiting specialist visit', 'each', 600, ''),
    ('procedure', 'OT charges - minor', 'each', 3000, ''), ('procedure', 'OT charges - major', 'each', 8000, ''),
    ('procedure', 'Anesthesia charges', 'each', 3000, ''), ('procedure', 'Labour room charges', 'each', 2500, ''),
    ('service', 'Dressing - small', 'each', 200, ''), ('service', 'Dressing - large', 'each', 400, ''),
    ('service', 'Nebulisation', 'each', 100, ''), ('service', 'Injection (giving)', 'each', 50, ''),
    ('service', 'IV cannula / IV line', 'each', 150, ''), ('service', 'Catheterisation', 'each', 300, ''),
    ('service', 'Oxygen', 'hour', 100, ''), ('service', 'Suture removal', 'each', 150, ''),
    ('service', 'Blood transfusion (procedure)', 'each', 1000, ''), ('service', 'Physiotherapy session', 'each', 300, ''),
    ('service', 'Phototherapy (newborn)', 'day', 800, ''),
    ('investigation', 'ECG', 'each', 250, ''), ('investigation', 'Bedside glucose (GRBS)', 'each', 50, ''),
]


def seed(app):
    if app.one('SELECT id FROM price_items LIMIT 1'):
        return
    for cat, name, unit, price, ward in DEFAULT_PRICES:
        app.run('INSERT INTO price_items(category, name, unit, price, ward) VALUES(?,?,?,?,?)', (cat, name, unit, price, ward))
    if app.setting('demo') == '1':
        demo(app)


def demo(app):
    items = {r['name']: r for r in app.q('SELECT * FROM price_items')}
    for a in app.q("SELECT a.id, a.admitted_at, b.ward FROM admissions a JOIN beds b ON b.id=a.bed_id WHERE a.status='admitted'"):
        days = stay_days(a['admitted_at'])
        room = next((r for r in items.values() if r['category'] == 'room' and r['ward'] == a['ward']), None)
        lines = [(room, max(days - 1, 1)), (items['Nursing charges'], max(days - 1, 1)), (items['Doctor visit (hospital doctor)'], days)]
        if a['id'] % 2:
            lines.append((items['Nebulisation'], 3))
        if a['id'] % 3 == 0:
            lines.append((items['Dressing - large'], 2))
        for item, qty in lines:
            if item:
                add_line(app, a['id'], item, qty, today(), '', 'Sr. Grace Mary')
    import billing
    desk = {'id': None, 'name': 'Anita Reddy'}
    for a in app.q("SELECT id, deposit_noted FROM admissions WHERE status='admitted' AND deposit_noted>0"):
        billing.record_payment(app, desk, a['id'], 'advance', a['deposit_noted'], 'Cash' if a['id'] % 2 else 'UPI',
                               '' if a['id'] % 2 else 'UPI%06d' % (a['id'] * 7919))


def stay_days(admitted_at, until=None):
    """Each 24 hours or part of it counts as one day."""
    start = datetime.datetime.fromisoformat(admitted_at)
    end = datetime.datetime.fromisoformat(until) if until else datetime.datetime.now()
    return max(1, math.ceil((end - start).total_seconds() / 86400))


def add_line(app, aid, item, qty, for_date, note, by):
    amount = round(item['price'] * qty)
    return app.run('INSERT INTO ip_charges(admission_id, price_item_id, category, name, unit, qty, rate, amount, for_date, note, entered_by, entered_at) '
                   'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   (aid, item['id'], item['category'], item['name'], item['unit'], qty, item['price'], amount, for_date, note, by, now()))


def admission(app, staff, aid):
    import more
    return more.admission_for(app, staff, aid)   # also blocks a visiting doctor from other doctors' patients


# ---------- price list (full-access doctors only) ----------
@route('GET', r'/api/prices', ('chart', 'ipbill', 'settings'))
def prices(app, staff, p, b):
    return {'items': app.q('SELECT * FROM price_items WHERE active=1 ORDER BY category, name'), 'categories': CATEGORIES, 'units': UNITS}


@route('POST', r'/api/admin/price', ('settings',))
def save_price(app, staff, p, b):
    rid = to_int(b.get('id'))
    old = app.one('SELECT * FROM price_items WHERE id=?', (rid,)) if rid else None
    if rid and not old:
        raise ApiError(404, 'Not found')
    if 'category' in b and b['category'] not in PRICE_CATEGORIES:
        raise ApiError(400, 'Choose the type of charge')
    if 'unit' in b and b['unit'] not in UNITS:
        raise ApiError(400, 'Choose per day, each time or per hour')
    if 'name' in b and len(clean(b['name'])) < 2:
        raise ApiError(400, 'Enter the name of the charge')
    if 'price' in b:
        b['price'] = to_int(str(b['price']).replace(',', '').replace('₹', '').strip())
        if b['price'] is None or not 0 <= b['price'] <= 1000000:
            raise ApiError(400, 'Enter the price in rupees')
    if not rid and any(k not in b for k in ('category', 'name', 'unit', 'price')):
        raise ApiError(400, 'Fill in the type, name, unit and price')
    rid = app.upsert(staff, 'price_items', b, ('category', 'name', 'unit', 'price', 'ward', 'active'))
    if old and 'price' in b and b['price'] != old['price']:
        app.audit(staff, 'price.change', 'price_item', rid, {'name': old['name'], 'from': old['price'], 'to': b['price']})
    return {'id': rid}


# ---------- charges on an admission ----------
def lines_for(app, aid):
    return app.q('SELECT * FROM ip_charges WHERE admission_id=? ORDER BY COALESCE(for_date, substr(entered_at, 1, 10)), id', (aid,))


def summary(app, a):
    lines = lines_for(app, a['id'])
    live = [x for x in lines if not x['cancelled']]
    by_cat = {}
    for x in live:
        by_cat[x['category']] = by_cat.get(x['category'], 0) + x['amount']
    days = stay_days(a['admitted_at'], a['discharged_at'])
    room_days = sum(x['qty'] for x in live if x['category'] == 'room')
    return {'lines': lines, 'total': sum(x['amount'] for x in live), 'by_category': by_cat,
            'stay_days': days, 'room_days': room_days, 'nursing_days': sum(x['qty'] for x in live if x['category'] == 'nursing'),
            'room_item': app.one("SELECT * FROM price_items WHERE category='room' AND active=1 AND ward=? ORDER BY id LIMIT 1", (a['ward'],))}


@route('GET', r'/api/admissions/(\d+)/charges', ('chart', 'ipbill', 'iphistory', 'claims'))
def get_charges(app, staff, p, b, aid):
    a = admission(app, staff, aid)
    import billing
    st = billing.state(app, aid)
    return dict(summary(app, a), categories=CATEGORIES, units=UNITS, paid=st['paid'], discount=st['discount'],
                scheme_amount=st['scheme_amount'], balance=st['balance'], final=st['final'], slips=slips_for(app, aid))


def slips_for(app, aid):
    return app.q('SELECT * FROM charge_slips WHERE admission_id=? ORDER BY id DESC LIMIT 10', (aid,))


@route('POST', r'/api/admissions/(\d+)/slip', ('chart',))
def send_slip(app, staff, p, b, aid):
    if staff['role'] in ('doctor', 'consultant'):
        raise ApiError(403, 'The nurses send the charge slip')
    """The nurse sends the day's charge slip to the billing desk, inside the system (replaces the paper slip)."""
    a = admission(app, staff, aid)
    s = summary(app, a)
    if not s['total']:
        raise ApiError(400, 'No charges recorded yet')
    with app.tx():
        sid = app.run('INSERT INTO charge_slips(admission_id, sent_by, sent_at, total, lines, note) VALUES(?,?,?,?,?,?)',
                      (aid, staff['name'], now(), s['total'], len([x for x in s['lines'] if not x['cancelled']]), clean(b.get('note'), 200)))
        app.audit(staff, 'slip.send', 'admission', aid, {'slip': sid, 'total': s['total']})
    return {'id': sid}


@route('POST', r'/api/charge-slips/(\d+)/checked', ('ipbill',))
def slip_checked(app, staff, p, b, sid):
    row = app.one('SELECT * FROM charge_slips WHERE id=?', (sid,))
    if not row:
        raise ApiError(404, 'Not found')
    with app.tx():
        app.run('UPDATE charge_slips SET checked_by=?, checked_at=?, check_note=? WHERE id=?', (staff['name'], now(), clean(b.get('note'), 200), sid))
        app.audit(staff, 'slip.checked', 'admission', row['admission_id'], {'slip': sid})
    return {'ok': True}


def slip_status(app):
    """For the dashboard: slips waiting for billing, and inpatients whose ward has not sent a slip today."""
    waiting = app.q("SELECT s.id, s.admission_id, s.sent_by, s.sent_at, b.label bed FROM charge_slips s JOIN admissions a ON a.id=s.admission_id "
                    "JOIN beds b ON b.id=a.bed_id WHERE s.checked_at IS NULL ORDER BY s.id")
    not_sent = app.q("SELECT a.id, b.label bed FROM admissions a JOIN beds b ON b.id=a.bed_id WHERE a.status='admitted' AND NOT EXISTS "
                     "(SELECT 1 FROM charge_slips s WHERE s.admission_id=a.id AND substr(s.sent_at, 1, 10)=?) ORDER BY b.id", (today(),))
    return {'waiting': waiting, 'not_sent_today': not_sent}


@route('POST', r'/api/admissions/(\d+)/charges', ('chart',))
def add_charge(app, staff, p, b, aid):
    if staff['role'] in ('doctor', 'consultant'):
        raise ApiError(403, 'Charges are recorded by the nurses')
    a = admission(app, staff, aid)
    item = app.one('SELECT * FROM price_items WHERE id=? AND active=1', (to_int(b.get('item_id')),))
    if not item:
        raise ApiError(400, 'Choose the charge from the list')
    try:
        qty = float(b.get('qty'))
    except (TypeError, ValueError):
        qty = 0
    limit = {'day': 120, 'hour': 24 * 120, 'each': 200}[item['unit']]
    if not 0 < qty <= limit or (item['unit'] != 'hour' and qty * 2 != int(qty * 2)):
        raise ApiError(400, 'Enter how many %s' % {'day': 'days (half days allowed)', 'hour': 'hours', 'each': 'times'}[item['unit']])
    for_date = clean(b.get('for_date'), 10) or today()
    try:
        d = datetime.date.fromisoformat(for_date)
    except ValueError:
        raise ApiError(400, 'Date is not valid')
    if d > datetime.date.today() or d < datetime.date.fromisoformat(a['admitted_at'][:10]):
        raise ApiError(400, 'Date must be during this admission')
    import billing
    if billing.is_final(app, aid):
        raise ApiError(409, 'The final bill is already made, so charges are locked. A full-access doctor can reopen it.')
    if a['status'] != 'admitted' and not app.allowed(staff, 'ipbill'):
        raise ApiError(409, 'This patient is already discharged. Ask the billing desk to add late charges.')
    with app.tx():
        cid = add_line(app, aid, item, qty, for_date, clean(b.get('note'), 200), staff['name'])
        app.run('INSERT INTO ip_events(admission_id, kind, data, at, staff_id, staff_name) VALUES(?,?,?,?,?,?)',
                (aid, 'service', json.dumps({'Charge': item['name'], 'Quantity': '%g %s' % (qty, item['unit'] if qty == 1 else item['unit'] + 's')}),
                 now(), staff['id'], staff['name']))
        app.audit(staff, 'charge.add', 'admission', aid, {'charge': cid, 'item': item['name'], 'qty': qty, 'rate': item['price']})
    return {'id': cid}


@route('POST', r'/api/charges/(\d+)/cancel', ('chart', 'ipbill'))
def cancel_charge(app, staff, p, b, cid):
    if staff['role'] in ('doctor', 'consultant'):
        raise ApiError(403, 'Charges are corrected by the nurses or at IP billing')
    c = app.one('SELECT * FROM ip_charges WHERE id=?', (cid,))
    if not c or c['cancelled']:
        raise ApiError(404, 'Not found')
    admission(app, staff, c['admission_id'])
    import billing
    if billing.is_final(app, c['admission_id']):
        raise ApiError(409, 'The final bill is already made, so charges are locked. A full-access doctor can reopen it.')
    if c['category'] in ('pharmacy', 'outside') and not app.allowed(staff, 'ipbill', 'pharmacy'):
        raise ApiError(403, 'Pharmacy and outside bills are corrected by the pharmacy or billing desk')
    reason = clean(b.get('reason'), 200)
    if len(reason) < 3:
        raise ApiError(400, 'Write why this entry is being cancelled')
    with app.tx():
        app.run('UPDATE ip_charges SET cancelled=1, cancelled_by=?, cancel_reason=? WHERE id=?', (staff['name'], reason, cid))
        app.audit(staff, 'charge.cancel', 'admission', c['admission_id'], {'charge': cid, 'reason': reason})
    return {'ok': True}


# ---------- shifting a patient to another bed ----------
@route('POST', r'/api/admissions/(\d+)/transfer', ('admit', 'ward'))
def transfer(app, staff, p, b, aid):
    a = admission(app, staff, aid)
    if a['status'] != 'admitted':
        raise ApiError(409, 'This patient is already discharged')
    with app.tx():
        new = app.one('SELECT * FROM beds WHERE id=? AND active=1', (to_int(b.get('bed_id')),))
        if not new:
            raise ApiError(400, 'Choose the new bed')
        if new['status'] == 'occupied':
            raise ApiError(409, 'That bed is occupied')
        app.run("UPDATE beds SET status='cleaning' WHERE id=?", (a['bed_id'],))
        app.run("UPDATE beds SET status='occupied', note='' WHERE id=?", (new['id'],))
        app.run('UPDATE admissions SET bed_id=? WHERE id=?', (new['id'], aid))
        app.run('INSERT INTO ip_events(admission_id, kind, data, at, staff_id, staff_name) VALUES(?,?,?,?,?,?)',
                (aid, 'note', json.dumps({'Shifted': '%s (%s) to %s (%s)' % (a['bed'], a['ward'], new['label'], new['ward'])}), now(), staff['id'], staff['name']))
        app.audit(staff, 'admission.transfer', 'admission', aid, {'from': a['bed'], 'to': new['label']})
    app.notify('ip', 'Bed shift: %s to %s.' % (a['bed'], new['label']), a['dept_id'])
    return {'ok': True}


def statement_rows(app, aid):
    return [(x['for_date'] or x['entered_at'][:10], x['name'], '%g' % x['qty'], x['rate'], x['amount'])
            for x in lines_for(app, aid) if not x['cancelled']]
