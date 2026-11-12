"""Later phases: follow-ups and vaccines, lab reports, IP chart, OT, discharge,
claims, pharmacy assist, attendance, roster, salary and consultant payouts.

Clinical safety: this module never diagnoses or prescribes. The vaccine and
antenatal schedules are drafts until a full-access doctor confirms them, and the
dose reference starts empty: doctors enter and confirm every line themselves.
"""
import calendar
import csv
import datetime
import io
import json
import os
import re
import secrets

from core import ApiError, DOCS, age_text, clean, now, route, to_int, today
from access import require_doctor
import charges
import billing
import claimflow

SCHEMA = """
CREATE TABLE IF NOT EXISTS schedule_items(
  id INTEGER PRIMARY KEY, plan TEXT NOT NULL, title TEXT NOT NULL, offset_days INTEGER NOT NULL, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS followups(
  id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id), kind TEXT NOT NULL, title TEXT NOT NULL,
  due_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'due', done_at TEXT, batch TEXT, note TEXT,
  calls INTEGER DEFAULT 0, last_call TEXT, created_at TEXT, created_by INTEGER);
CREATE INDEX IF NOT EXISTS ix_followup_due ON followups(status, due_date);
CREATE TABLE IF NOT EXISTS lab_orders(
  id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id), doctor_id INTEGER, test TEXT NOT NULL,
  outsourced INTEGER DEFAULT 0, status TEXT NOT NULL DEFAULT 'ordered', ordered_at TEXT, ordered_by INTEGER,
  collected_at TEXT, reported_at TEXT, file TEXT, ctype TEXT, critical INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ip_events(
  id INTEGER PRIMARY KEY, admission_id INTEGER NOT NULL REFERENCES admissions(id), kind TEXT NOT NULL, data TEXT,
  at TEXT, staff_id INTEGER, staff_name TEXT, billed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS discharge_steps(
  admission_id INTEGER NOT NULL, step TEXT NOT NULL, done_at TEXT, done_by TEXT, PRIMARY KEY(admission_id, step));
CREATE TABLE IF NOT EXISTS discharge_summaries(
  admission_id INTEGER PRIMARY KEY, data TEXT, final INTEGER DEFAULT 0, signed_by TEXT, signed_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS ot_bookings(
  id INTEGER PRIMARY KEY, patient_name TEXT NOT NULL, procedure TEXT, surgeon_id INTEGER, anesthetist TEXT,
  ot_date TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL, checklist TEXT DEFAULT '[]',
  status TEXT DEFAULT 'planned', created_by INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS scheme_docs(id INTEGER PRIMARY KEY, scheme TEXT NOT NULL, item TEXT NOT NULL, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS claims(
  id INTEGER PRIMARY KEY, admission_id INTEGER UNIQUE NOT NULL REFERENCES admissions(id), scheme TEXT, claim_no TEXT,
  status TEXT NOT NULL DEFAULT 'preparing', status_at TEXT, reason TEXT, checked TEXT DEFAULT '[]', created_at TEXT);
CREATE TABLE IF NOT EXISTS stock(id INTEGER PRIMARY KEY, item TEXT, batch TEXT, expiry TEXT, qty REAL, supplier TEXT);
CREATE TABLE IF NOT EXISTS import_runs(id INTEGER PRIMARY KEY, at TEXT, staff_name TEXT, source TEXT, rows INTEGER, errors TEXT);
CREATE TABLE IF NOT EXISTS dose_refs(
  id INTEGER PRIMARY KEY, drug TEXT NOT NULL, min_mg_kg REAL, max_mg_kg REAL, per TEXT DEFAULT 'dose', max_mg REAL,
  note TEXT, confirmed_by TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS attendance(
  staff_id INTEGER NOT NULL, day TEXT NOT NULL, in_at TEXT, out_at TEXT, status TEXT, PRIMARY KEY(staff_id, day));
CREATE TABLE IF NOT EXISTS roster(staff_id INTEGER NOT NULL, day TEXT NOT NULL, shift TEXT, PRIMARY KEY(staff_id, day));
CREATE TABLE IF NOT EXISTS deductions(id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, value REAL, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS doctor_days(
  doctor_id INTEGER NOT NULL, day TEXT NOT NULL, arrived_at TEXT, left_at TEXT, marked_by TEXT, PRIMARY KEY(doctor_id, day));
CREATE TABLE IF NOT EXISTS claim_docs(
  id INTEGER PRIMARY KEY, claim_id INTEGER NOT NULL REFERENCES claims(id), item TEXT NOT NULL, file TEXT NOT NULL, ctype TEXT,
  uploaded_by TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS accounts_checks(day TEXT PRIMARY KEY, result TEXT, note TEXT, checked_by TEXT, at TEXT);
"""

EVENT_KINDS = ('vitals', 'medicine', 'service', 'io', 'note', 'round')
STEPS = [('summary', 'Discharge summary signed'), ('medicines', 'Discharge medicines given'),
         ('bill', 'Final bill made and paid'), ('scheme', 'Scheme / insurance papers')]
CLAIM_STATES = ('preparing', 'submitted', 'queried', 'approved', 'settled', 'rejected')
FILE_TYPES = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'application/pdf': '.pdf'}
FOLLOWUP_KINDS = ('vaccine', 'antenatal', 'surgery', 'ortho', 'skin', 'other')

VACCINES = [  # DRAFT from the national schedule. The pediatrician must check and confirm in Settings.
    (0, 'At birth: BCG, OPV-0, Hepatitis B'),
    (42, '6 weeks: OPV-1, Pentavalent-1, Rotavirus-1, fIPV-1, PCV-1'),
    (70, '10 weeks: OPV-2, Pentavalent-2, Rotavirus-2'),
    (98, '14 weeks: OPV-3, Pentavalent-3, Rotavirus-3, fIPV-2, PCV-2'),
    (270, '9 months: MR-1, JE-1, PCV booster, Vitamin A'),
    (487, '16 months: MR-2, JE-2, DPT booster-1, OPV booster'),
    (1826, '5 years: DPT booster-2'),
    (3652, '10 years: Td'),
    (5844, '16 years: Td'),
]
ANTENATAL = [(84, 'Antenatal check-up (12 weeks)'), (140, 'Antenatal check-up and scan (20 weeks)'),
             (182, 'Antenatal check-up (26 weeks)'), (210, 'Antenatal check-up (30 weeks)'),
             (238, 'Antenatal check-up (34 weeks)'), (252, 'Antenatal check-up (36 weeks)'),
             (266, 'Antenatal check-up (38 weeks)'), (280, 'Expected delivery date')]
GOVT_DOCS = ['Aadhaar / ID proof', 'Scheme card', 'Pre-authorisation approval', 'Admission notes', 'Investigation reports',
             'Operation / procedure notes', 'Clinical photos required by the scheme', 'Discharge summary (signed)', 'Final bill']
TPA_DOCS = ['ID proof', 'Insurance card / policy copy', 'Pre-authorisation approval', 'Signed claim form',
            'Investigation reports', 'Discharge summary (signed)', 'Final bill with break-up', 'Pharmacy bills']


def migrate(app):
    def add(table, col, decl):
        if col not in [r['name'] for r in app.q('PRAGMA table_info(%s)' % table)]:
            app.run('ALTER TABLE %s ADD COLUMN %s %s' % (table, col, decl))
    add('admissions', 'discharge_ordered_at', 'TEXT')
    add('visits', 'bought', 'INTEGER')
    add('visits', 'not_bought_reason', 'TEXT')
    add('staff', 'salary', 'INTEGER DEFAULT 0')
    add('doctors', 'payout_kind', "TEXT DEFAULT ''")
    add('doctors', 'payout_rate', 'INTEGER DEFAULT 0')
    add('doctors', 'visit_days', "TEXT DEFAULT ''")
    add('doctors', 'visit_time', "TEXT DEFAULT ''")
    add('staff', 'username', 'TEXT')
    add('staff', 'pw_salt', 'TEXT')
    add('staff', 'pw_hash', 'TEXT')
    add('staff', 'must_change', 'INTEGER DEFAULT 0')
    add('staff', 'screens', 'TEXT')
    add('claims', 'member_id', 'TEXT')
    add('stock', 'mrp', 'REAL')
    app.run('CREATE UNIQUE INDEX IF NOT EXISTS ux_staff_username ON staff(username)')
    import access
    for r in app.q('SELECT id, name FROM staff WHERE username IS NULL AND pin_hash IS NOT NULL'):
        app.run('UPDATE staff SET username=? WHERE id=?', (access.username_from(r['name'], app), r['id']))


def seed(app):
    if app.one('SELECT id FROM schedule_items LIMIT 1'):
        return
    for plan, items in (('vaccine', VACCINES), ('antenatal', ANTENATAL)):
        for days, title in items:
            app.run('INSERT INTO schedule_items(plan, title, offset_days) VALUES(?,?,?)', (plan, title, days))
    for scheme, docs in (('Dr NTR Vaidya Seva', GOVT_DOCS), ('PM-JAY', GOVT_DOCS), ('Insurance / TPA', TPA_DOCS)):
        for d in docs:
            app.run('INSERT INTO scheme_docs(scheme, item) VALUES(?,?)', (scheme, d))
    for a in app.q("SELECT id FROM admissions WHERE payer<>'Cash'"):
        after_admit(app, a['id'])
    if app.setting('demo') == '1':
        demo(app)


def demo(app):
    """Made-up examples so every new screen has something to show."""
    td = datetime.date.today()
    demo_history(app)
    kids = app.q('SELECT id FROM patients WHERE age_y < 3 ORDER BY id LIMIT 3')
    for i, k in enumerate(kids):
        dob = td - datetime.timedelta(days=[75, 280, 44][i])
        app.run('UPDATE patients SET dob=? WHERE id=?', (dob.isoformat(), k['id']))
        make_plan(app, None, k['id'], 'vaccine', dob)
    adults = app.q('SELECT id FROM patients WHERE age_y > 18 ORDER BY id LIMIT 6')
    for i, (kind, title, days) in enumerate([('surgery', 'Suture removal', 0), ('ortho', 'Plaster check', -2),
                                             ('skin', 'Laser session 3 of 6', 1), ('surgery', 'Dressing', 3)]):
        app.run('INSERT INTO followups(patient_id, kind, title, due_date, created_at) VALUES(?,?,?,?,?)',
                (adults[i]['id'], kind, title, (td + datetime.timedelta(days=days)).isoformat(), now()))
    for i, test in enumerate(['CBC', 'Dengue NS1', 'Thyroid profile']):
        app.run("INSERT INTO lab_orders(patient_id, test, outsourced, status, ordered_at, collected_at) VALUES(?,?,?,?,?,?)",
                (adults[i]['id'], test, 1 if i == 2 else 0, 'collected' if i == 1 else 'ordered', now(), now() if i == 1 else None))
    surgeon = app.one("SELECT id FROM doctors WHERE kind='consultant' ORDER BY id")
    if surgeon:
        app.run('INSERT INTO ot_bookings(patient_name, procedure, surgeon_id, anesthetist, ot_date, start_time, end_time, checklist, created_at) '
                'VALUES(?,?,?,?,?,?,?,?,?)', ('Polisetty Himabindu', 'Lap appendicectomy', surgeon['id'], 'Dr Anesthetist (visiting)',
                                              td.isoformat(), '14:00', '15:30', '["consent","fasting"]', now()))
    exp = lambda d: (td + datetime.timedelta(days=d)).isoformat()  # noqa: E731
    for item, batch, days, qty, sup, mrp in [('Paracetamol 500mg tab (10s)', 'PC2291', 400, 120, 'Sri Venkateswara Agencies', 18),
                                             ('Paracetamol 250mg/5ml syrup 60ml', 'PCS410', 300, 40, 'Sri Venkateswara Agencies', 42),
                                             ('Amoxicillin 250mg syrup 60ml', 'AMX118', 22, 14, 'Sri Venkateswara Agencies', 68),
                                             ('ORS sachet', 'ORS77', 55, 6, 'Sampletown Medical Distributors', 22),
                                             ('Cetirizine syrup 30ml', 'CTZ09', -6, 9, 'Sampletown Medical Distributors', 35),
                                             ('Cetirizine syrup 30ml', 'CTZ14', 260, 25, 'Sampletown Medical Distributors', 35),
                                             ('Ondansetron 4mg inj', 'OND51', 80, 40, 'Lakshmi Pharma', 14),
                                             ('Normal saline 500ml', 'NS5510', 300, 4, 'Lakshmi Pharma', 32),
                                             ('Zinc 20mg dispersible tab (10s)', 'ZN220', 500, 60, 'Lakshmi Pharma', 30),
                                             ('Mupirocin 2% ointment 5g', 'MUP31', 410, 18, 'Sampletown Medical Distributors', 98),
                                             ('Calamine lotion 100ml', 'CAL88', 380, 22, 'Sampletown Medical Distributors', 85),
                                             ('Iron and folic acid tab (10s)', 'IFA07', 450, 90, 'Lakshmi Pharma', 25)]:
        app.run('INSERT INTO stock(item, batch, expiry, qty, supplier, mrp) VALUES(?,?,?,?,?,?)', (item, batch, exp(days), qty, sup, mrp))
    app.run('INSERT INTO import_runs(at, staff_name, source, rows, errors) VALUES(?,?,?,?,?)', (now(), 'demo', 'demo data', 6, '[]'))
    for s in app.q("SELECT id, role FROM staff WHERE role NOT IN ('owner','consultant')"):
        app.run('UPDATE staff SET salary=? WHERE id=?', ({'doctor': 90000, 'nurse': 18000, 'pharmacy': 16000}.get(s['role'], 14000), s['id']))
        for d in range(1, td.day):
            day = td.replace(day=d)
            status = 'O' if day.weekday() == 6 else ('L' if (d + s['id']) % 13 == 0 else 'P')
            app.run('INSERT INTO attendance(staff_id, day, status) VALUES(?,?,?)', (s['id'], day.isoformat(), status))
    app.run("UPDATE doctors SET payout_kind='visit', payout_rate=250 WHERE kind='consultant'")


# ---------- follow-ups and vaccines ----------
def make_plan(app, staff, pid, plan, anchor):
    have = {r['title'] for r in app.q('SELECT title FROM followups WHERE patient_id=? AND kind=?', (pid, plan))}
    n = 0
    for it in app.q('SELECT * FROM schedule_items WHERE plan=? AND active=1 ORDER BY offset_days', (plan,)):
        if it['title'] in have:
            continue
        app.run('INSERT INTO followups(patient_id, kind, title, due_date, created_at, created_by) VALUES(?,?,?,?,?,?)',
                (pid, plan, it['title'], (anchor + datetime.timedelta(days=it['offset_days'])).isoformat(), now(),
                 staff['id'] if staff else None))
        n += 1
    return n


def as_date(text, message):
    try:
        return datetime.date.fromisoformat(clean(text, 10))
    except ValueError:
        raise ApiError(400, message)


@route('POST', r'/api/patients/(\d+)/plan', ('followups', 'records'))
def start_plan(app, staff, p, b, pid):
    pat = app.one('SELECT * FROM patients WHERE id=?', (pid,))
    plan = b.get('plan')
    if not pat or plan not in ('vaccine', 'antenatal'):
        raise ApiError(400, 'Choose the patient and the schedule')
    if staff['role'] in DOCS and not app.doctor_has_patient(staff, pid):
        raise ApiError(403, 'This is not your patient')
    anchor = as_date(b.get('date'), 'Enter the date of birth' if plan == 'vaccine' else 'Enter the LMP date')
    if anchor > datetime.date.today():
        raise ApiError(400, 'Date cannot be in the future')
    with app.tx():
        if plan == 'vaccine' and pat['dob'] != anchor.isoformat():
            app.run('UPDATE patients SET dob=? WHERE id=?', (anchor.isoformat(), pid))
        n = make_plan(app, staff, pid, plan, anchor)
        app.audit(staff, 'followup.plan', 'patient', pid, {'plan': plan, 'items': n})
    return {'created': n}


@route('POST', r'/api/followups', ('followups', 'records'))
def add_followup(app, staff, p, b):
    pid, kind, title = to_int(b.get('patient_id')), b.get('kind'), clean(b.get('title'))
    if kind not in FOLLOWUP_KINDS or len(title) < 2 or not app.one('SELECT id FROM patients WHERE id=?', (pid,)):
        raise ApiError(400, 'Enter what the follow-up is for')
    if staff['role'] in DOCS and not app.doctor_has_patient(staff, pid):
        raise ApiError(403, 'This is not your patient')
    due = as_date(b.get('due_date'), 'Choose the date')
    with app.tx():
        fid = app.run('INSERT INTO followups(patient_id, kind, title, due_date, note, created_at, created_by) VALUES(?,?,?,?,?,?,?)',
                      (pid, kind, title, due.isoformat(), clean(b.get('note'), 200), now(), staff['id']))
        app.audit(staff, 'followup.create', 'followup', fid)
    return {'id': fid}


@route('GET', r'/api/followups', ('followups',))
def list_followups(app, staff, p, b):
    td = datetime.date.today()
    rows = app.q(
        "SELECT f.*, p.name, p.phone, p.guardian, p.area, p.dob, p.age_y, p.age_m, p.age_on FROM followups f "
        "JOIN patients p ON p.id=f.patient_id WHERE f.status='due' AND f.due_date<=? ORDER BY f.due_date",
        ((td + datetime.timedelta(days=7)).isoformat(),))
    for r in rows:
        r['age'] = age_text(r)
        r['late_days'] = (td - datetime.date.fromisoformat(r['due_date'])).days
    return {'missed': [r for r in rows if r['late_days'] > 0], 'today': [r for r in rows if r['late_days'] == 0],
            'upcoming': [r for r in rows if r['late_days'] < 0],
            'confirmed': {k: app.setting('schedule_confirmed_' + k) for k in ('vaccine', 'antenatal')}}


@route('POST', r'/api/followups/(\d+)', ('followups', 'records'))
def update_followup(app, staff, p, b, fid):
    f = app.one('SELECT * FROM followups WHERE id=?', (fid,))
    if not f:
        raise ApiError(404, 'Not found')
    if staff['role'] in DOCS and not app.doctor_has_patient(staff, f['patient_id']):
        raise ApiError(403, 'This is not your patient')
    action = b.get('action')
    with app.tx():
        if action == 'done':
            app.run("UPDATE followups SET status='done', done_at=?, batch=?, note=COALESCE(NULLIF(?, ''), note) WHERE id=?",
                    (now(), clean(b.get('batch'), 60), clean(b.get('note'), 200), fid))
        elif action == 'called':
            app.run('UPDATE followups SET calls=calls+1, last_call=?, note=COALESCE(NULLIF(?, \'\'), note) WHERE id=?',
                    (now(), clean(b.get('note'), 200), fid))
        elif action == 'move':
            app.run('UPDATE followups SET due_date=? WHERE id=?', (as_date(b.get('due_date'), 'Choose the new date').isoformat(), fid))
        elif action == 'cancel':
            app.run("UPDATE followups SET status='cancelled' WHERE id=?", (fid,))
        elif action == 'reopen':
            app.run("UPDATE followups SET status='due', done_at=NULL WHERE id=?", (fid,))
        else:
            raise ApiError(400, 'Unknown action')
        app.audit(staff, 'followup.' + action, 'followup', fid)
    return {'ok': True}


@route('POST', r'/api/admin/schedule-item', ('settings',))
def save_schedule_item(app, staff, p, b):
    if 'plan' in b and b['plan'] not in ('vaccine', 'antenatal'):
        raise ApiError(400, 'Unknown schedule')
    if 'offset_days' in b:
        b['offset_days'] = to_int(b['offset_days'])
        if b['offset_days'] is None or not 0 <= b['offset_days'] <= 8000:
            raise ApiError(400, 'Enter the number of days')
    if 'title' in b and len(clean(b['title'])) < 2:
        raise ApiError(400, 'Enter what is due')
    rid = app.upsert(staff, 'schedule_items', b, ('plan', 'title', 'offset_days', 'active'))
    plan = app.one('SELECT plan FROM schedule_items WHERE id=?', (rid,))['plan']
    app.set_setting('schedule_confirmed_' + plan, '')  # any edit needs a fresh confirmation
    return {'id': rid}


@route('POST', r'/api/admin/confirm-schedule', ('settings',))
def confirm_schedule(app, staff, p, b):
    if b.get('plan') not in ('vaccine', 'antenatal'):
        raise ApiError(400, 'Unknown schedule')
    app.set_setting('schedule_confirmed_' + b['plan'], '%s on %s' % (staff['name'], today()))
    app.audit(staff, 'schedule.confirm', None, None, {'plan': b['plan']})
    return {'ok': True}


# ---------- lab and scan reports ----------
@route('POST', r'/api/lab', ('records', 'lab', 'myday'))
def order_lab(app, staff, p, b):
    pid, test = to_int(b.get('patient_id')), clean(b.get('test'))
    if len(test) < 2 or not app.one('SELECT id FROM patients WHERE id=?', (pid,)):
        raise ApiError(400, 'Enter the test name')
    if staff['role'] in DOCS and not app.doctor_has_patient(staff, pid):
        raise ApiError(403, 'This is not your patient')
    with app.tx():
        lid = app.run('INSERT INTO lab_orders(patient_id, doctor_id, test, outsourced, ordered_at, ordered_by) VALUES(?,?,?,?,?,?)',
                      (pid, to_int(b.get('doctor_id')) or staff['doctor_id'], test, 1 if b.get('outsourced') else 0, now(), staff['id']))
        app.audit(staff, 'lab.order', 'lab_order', lid)
    return {'id': lid}


@route('GET', r'/api/lab', ('lab',))
def list_lab(app, staff, p, b):
    since = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    rows = app.q(
        "SELECT l.id, l.test, l.outsourced, l.status, l.ordered_at, l.collected_at, l.reported_at, l.critical, l.patient_id, "
        "p.name, p.uhid, p.sex, p.dob, p.age_y, p.age_m, p.age_on, dr.name doctor FROM lab_orders l "
        "JOIN patients p ON p.id=l.patient_id LEFT JOIN doctors dr ON dr.id=l.doctor_id "
        "WHERE l.status<>'reported' OR l.reported_at>=? ORDER BY l.status='reported', l.id DESC", (since,))
    for r in rows:
        r['age'] = age_text(r)
        for k in ('dob', 'age_y', 'age_m', 'age_on'):
            r.pop(k)
    return {'orders': rows}


@route('POST', r'/api/lab/(\d+)/collected', ('lab',))
def lab_collected(app, staff, p, b, lid):
    with app.tx():
        app.run("UPDATE lab_orders SET status='collected', collected_at=? WHERE id=? AND status='ordered'", (now(), lid))
        app.audit(staff, 'lab.collected', 'lab_order', lid)
    return {'ok': True}


@route('POST', r'/api/lab/(\d+)/report', ('lab',))
def lab_report(app, staff, p, b, lid):
    order = app.one('SELECT l.*, dr.name doctor, dr.dept_id FROM lab_orders l LEFT JOIN doctors dr ON dr.id=l.doctor_id WHERE l.id=?', (lid,))
    ext = FILE_TYPES.get(b.get('_ctype'))
    if not order:
        raise ApiError(404, 'Not found')
    if not ext or not b.get('_raw'):
        raise ApiError(400, 'Send the report as a photo or PDF')
    name = 'lab-' + secrets.token_hex(16) + ext
    with open(os.path.join(app.upload_dir, name), 'wb') as fh:
        fh.write(b['_raw'])
    critical = 1 if p.get('critical') == '1' else 0
    with app.tx():
        app.run("UPDATE lab_orders SET status='reported', reported_at=?, collected_at=COALESCE(collected_at, ?), file=?, ctype=?, critical=? WHERE id=?",
                (now(), now(), name, b['_ctype'], critical, lid))
        app.audit(staff, 'lab.report', 'lab_order', lid, {'critical': critical})
    if critical:
        app.notify('lab', 'CRITICAL lab value flagged%s. Please open the patient record now.' %
                   (' for a patient of ' + order['doctor'] if order['doctor'] else ''), order['dept_id'])
    return {'ok': True}


@route('GET', r'/files/lab/(\d+)', ('lab', 'records', 'chart', 'iphistory', 'claims', 'myday'))
def lab_file(app, staff, p, b, lid):
    r = app.one('SELECT * FROM lab_orders WHERE id=? AND file IS NOT NULL', (lid,))
    if not r:
        raise ApiError(404, 'Not found')
    if staff['role'] in DOCS and not app.doctor_has_patient(staff, r['patient_id']):
        app.audit(staff, 'lab.denied', 'lab_order', lid)
        raise ApiError(403, 'This is not your patient')
    return {'_file': os.path.join(app.upload_dir, r['file']), '_ctype': r['ctype']}


def patient_extra(app, staff, pid):
    only = ' AND doctor_id=%d' % staff['doctor_id'] if staff['role'] == 'consultant' else ''
    return {'followups': app.q("SELECT id, kind, title, due_date, status, done_at, batch, note FROM followups "
                               "WHERE patient_id=? AND status<>'cancelled' ORDER BY due_date", (pid,)),
            'labs': app.q('SELECT l.id, l.test, l.status, l.ordered_at, l.reported_at, l.critical, l.file IS NOT NULL has_file, dr.name doctor '
                          'FROM lab_orders l LEFT JOIN doctors dr ON dr.id=l.doctor_id WHERE l.patient_id=?' + only.replace('doctor_id', 'l.doctor_id') +
                          ' ORDER BY l.id DESC', (pid,))}


def sheet_png(seed):
    """A plain ruled sheet used as the demo 'prescription photo' (real copies hold real photos)."""
    import struct
    import zlib
    w, hgt = 360, 480
    rows = []
    for y in range(hgt):
        line = bytearray([0])
        for x in range(w):
            v = 250
            if y < 60:
                v = 222                                   # printed letterhead
            elif y % 28 == 0 and 30 < x < 330:
                v = 200                                   # ruled lines
            elif (y % 28) in (12, 13, 14) and 50 < x < 120 + ((seed * 37 + y * 11) % 190):
                v = 60                                    # 'handwriting'
            line.append(v)
        rows.append(bytes(line))
    raw = zlib.compress(b''.join(rows), 9)
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, hgt, 8, 0, 0, 0, 0)) + chunk(b'IDAT', raw) + chunk(b'IEND', b'')


def demo_history(app):
    """Earlier visits for some of today's patients, so returning patients can be shown."""
    td = datetime.date.today()
    rec = app.one("SELECT id FROM staff WHERE role='reception' ORDER BY id")
    for n, v in enumerate(app.q("SELECT v.patient_id, v.dept_id, v.doctor_id, d.code FROM visits v JOIN departments d ON d.id=v.dept_id "
                                "WHERE v.visit_date=? ORDER BY v.id LIMIT 8", (today(),))):
        if n % 2:
            continue
        for back in ((35, 92) if n % 4 == 0 else (21,)):
            day = (td - datetime.timedelta(days=back)).isoformat()
            vid = app.run("INSERT INTO visits(patient_id, dept_id, doctor_id, visit_date, source, token_no, token_code, fee_shown, status, created_at, done_at, essel_done) "
                          "VALUES(?,?,?,?,'walkin',?,?,0,'done',?,?,1)", (v['patient_id'], v['dept_id'], v['doctor_id'], day, 1 + n, '%s-%02d' % (v['code'], 1 + n),
                                                                          day + 'T10:00:00', day + 'T10:20:00'))
            name = 'demo-rx-%d-%d.png' % (vid, back)
            with open(os.path.join(app.upload_dir, name), 'wb') as fh:
                fh.write(sheet_png(vid + back))
            app.run('INSERT INTO prescriptions(visit_id, patient_id, file, ctype, uploaded_by, created_at) VALUES(?,?,?,?,?,?)',
                    (vid, v['patient_id'], name, 'image/png', rec['id'] if rec else None, day + 'T10:25:00'))
        if n == 0:
            lab = 'demo-lab-%d.png' % v['patient_id']
            with open(os.path.join(app.upload_dir, lab), 'wb') as fh:
                fh.write(sheet_png(99))
            day = (td - datetime.timedelta(days=34)).isoformat()
            app.run("INSERT INTO lab_orders(patient_id, doctor_id, test, status, ordered_at, collected_at, reported_at, file, ctype) "
                    "VALUES(?,?,?,'reported',?,?,?,?,'image/png')", (v['patient_id'], v['doctor_id'], 'CBC', day, day, day, lab))


# ---------- inpatient chart, discharge ----------
def admission_for(app, staff, aid):
    a = app.one(
        'SELECT a.*, b.label bed, b.ward, p.name patient, p.uhid, p.sex, p.dob, p.age_y, p.age_m, p.age_on, p.phone, '
        'p.area, p.guardian, dr.name doctor, dr.dept_id FROM admissions a JOIN beds b ON b.id=a.bed_id '
        'JOIN patients p ON p.id=a.patient_id LEFT JOIN doctors dr ON dr.id=a.doctor_id WHERE a.id=?', (aid,))
    if not a:
        raise ApiError(404, 'Admission not found')
    if staff['role'] == 'consultant' and a['doctor_id'] != staff['doctor_id']:
        app.audit(staff, 'admission.denied', 'admission', aid)
        raise ApiError(403, 'This is not your patient')
    a['age'] = age_text(a)
    return a


def steps_for(app, a):
    done = {r['step']: r for r in app.q('SELECT * FROM discharge_steps WHERE admission_id=?', (a['id'],))}
    return [{'step': k, 'label': label, 'done_at': done.get(k, {}).get('done_at'), 'done_by': done.get(k, {}).get('done_by')}
            for k, label in STEPS if k != 'scheme' or (a['payer'] or 'Cash') != 'Cash']


def summary_for(app, a):
    s = app.one('SELECT * FROM discharge_summaries WHERE admission_id=?', (a['id'],))
    if s:
        return {'data': json.loads(s['data']), 'final': s['final'], 'signed_by': s['signed_by'], 'signed_at': s['signed_at']}
    return {'data': {'diagnosis': a['diagnosis'] or '', 'procedure': a['procedure'] or '', 'course': '', 'condition': '',
                     'medicines': '', 'advice': '', 'followup': ''}, 'final': 0, 'signed_by': None, 'signed_at': None}


@route('GET', r'/api/admissions/(\d+)', ('chart', 'iphistory', 'claims'))
def get_admission(app, staff, p, b, aid):
    a = admission_for(app, staff, aid)
    events = app.q('SELECT * FROM ip_events WHERE admission_id=? ORDER BY id DESC', (aid,))
    for e in events:
        e['data'] = json.loads(e['data'] or '{}')
    if not app.allowed(staff, 'ipbill', 'accounts'):
        a['deposit_noted'] = None
    app.audit(staff, 'admission.view', 'admission', aid)
    return {'admission': a, 'events': events, 'steps': steps_for(app, a), 'summary': summary_for(app, a),
            'claim': app.one('SELECT id, status FROM claims WHERE admission_id=?', (aid,)),
            'labs': app.q('SELECT id, test, status, critical, file IS NOT NULL has_file FROM lab_orders WHERE patient_id=? AND ordered_at>=? ORDER BY id',
                          (a['patient_id'], a['admitted_at'][:10]))}


@route('POST', r'/api/admissions/(\d+)/event', ('chart',))
def add_event(app, staff, p, b, aid):
    a = admission_for(app, staff, aid)
    kind = b.get('kind')
    if kind not in EVENT_KINDS:
        raise ApiError(400, 'Unknown entry')
    if kind == 'round' and staff['role'] not in DOCS + ('owner',):
        raise ApiError(403, 'Only doctors write round notes')
    if a['status'] != 'admitted':
        raise ApiError(409, 'This patient is already discharged')
    data = {k: clean(v, 400) for k, v in (b.get('data') or {}).items() if clean(v, 400)}
    if not data:
        raise ApiError(400, 'Nothing entered')
    with app.tx():
        eid = app.run('INSERT INTO ip_events(admission_id, kind, data, at, staff_id, staff_name) VALUES(?,?,?,?,?,?)',
                      (aid, kind, json.dumps(data), now(), staff['id'], staff['name']))
        app.audit(staff, 'ip.' + kind, 'admission', aid, {'event': eid})
    return {'id': eid}


@route('POST', r'/api/admissions/(\d+)/order-discharge', ('chart',))
def order_discharge(app, staff, p, b, aid):
    require_doctor(staff)
    a = admission_for(app, staff, aid)
    if a['status'] != 'admitted':
        raise ApiError(409, 'Already discharged')
    cancel = bool(b.get('cancel'))
    with app.tx():
        app.run('UPDATE admissions SET discharge_ordered_at=? WHERE id=?', (None if cancel else now(), aid))
        if cancel:
            app.run('DELETE FROM discharge_steps WHERE admission_id=?', (aid,))
        app.audit(staff, 'discharge.cancel' if cancel else 'discharge.order', 'admission', aid)
    if not cancel:
        app.notify('ip', 'Discharge ordered: bed %s (%s) by %s. Summary, medicines and bill are now pending.' %
                   (a['bed'], a['ward'], staff['name']), a['dept_id'])
    return {'ok': True}


@route('POST', r'/api/admissions/(\d+)/step', ('chart',))
def discharge_step(app, staff, p, b, aid):
    a = admission_for(app, staff, aid)
    step = b.get('step')
    if step not in [s['step'] for s in steps_for(app, a)] or not a['discharge_ordered_at']:
        raise ApiError(400, 'The doctor has not ordered discharge yet')
    if step == 'summary':
        raise ApiError(400, 'This is ticked automatically when the doctor signs the summary')
    if step == 'bill':
        raise ApiError(400, 'This is ticked automatically when the final bill is made and paid')
    with app.tx():
        if b.get('done'):
            app.run('INSERT OR REPLACE INTO discharge_steps(admission_id, step, done_at, done_by) VALUES(?,?,?,?)',
                    (aid, step, now(), staff['name']))
        else:
            app.run('DELETE FROM discharge_steps WHERE admission_id=? AND step=?', (aid, step))
        app.audit(staff, 'discharge.step', 'admission', aid, {'step': step, 'done': bool(b.get('done'))})
    return {'ok': True}


@route('POST', r'/api/admissions/(\d+)/summary', ('chart',))
def save_summary(app, staff, p, b, aid):
    require_doctor(staff)
    a = admission_for(app, staff, aid)
    if staff['role'] == 'doctor' and a['doctor_id'] != staff['doctor_id']:
        raise ApiError(403, 'Only the treating doctor signs this summary')
    old = summary_for(app, a)
    final = 1 if b.get('final') else 0
    if old['final'] and final:
        raise ApiError(409, 'Already signed. Re-open it first to make changes.')
    data = {k: clean((b.get('data') or {}).get(k), 4000) for k in old['data']}
    with app.tx():
        app.run('INSERT OR REPLACE INTO discharge_summaries(admission_id, data, final, signed_by, signed_at, updated_at) VALUES(?,?,?,?,?,?)',
                (aid, json.dumps(data), final, staff['name'] if final else None, now() if final else None, now()))
        if final:
            app.run('INSERT OR REPLACE INTO discharge_steps(admission_id, step, done_at, done_by) VALUES(?,?,?,?)',
                    (aid, 'summary', now(), staff['name']))
        else:
            app.run("DELETE FROM discharge_steps WHERE admission_id=? AND step='summary'", (aid,))
        app.audit(staff, 'summary.sign' if final else 'summary.save', 'admission', aid)
    return {'ok': True}


def pending_discharges(app):
    out = []
    for a in app.q("SELECT a.*, b.label bed FROM admissions a JOIN beds b ON b.id=a.bed_id "
                   "WHERE a.status='admitted' AND a.discharge_ordered_at IS NOT NULL ORDER BY a.discharge_ordered_at"):
        waiting = [s['label'] for s in steps_for(app, a) if not s['done_at']]
        out.append({'admission_id': a['id'], 'bed': a['bed'], 'ordered_at': a['discharge_ordered_at'], 'waiting': waiting})
    return out


# ---------- operation theatre ----------
def minutes(text):
    m = re.fullmatch(r'([01]?\d|2[0-3]):([0-5]\d)', clean(text, 5))
    if not m:
        raise ApiError(400, 'Enter start and end time')
    return int(m.group(1)) * 60 + int(m.group(2))


@route('GET', r'/api/ot', ('ot', 'myday'))
def list_ot(app, staff, p, b):
    day = clean(p.get('date'), 10) or today()
    rows = app.q("SELECT o.*, dr.name surgeon FROM ot_bookings o LEFT JOIN doctors dr ON dr.id=o.surgeon_id "
                 "WHERE o.ot_date=? AND o.status<>'cancelled' ORDER BY o.start_time", (day,))
    for r in rows:
        r['checklist'] = json.loads(r['checklist'] or '[]')
        r['clash'] = any(x['id'] != r['id'] and x['start_time'] < r['end_time'] and r['start_time'] < x['end_time'] for x in rows)
    if staff['role'] == 'consultant':   # a visiting doctor sees only their own operations
        rows = [r for r in rows if r['surgeon_id'] == staff['doctor_id']]
    return {'date': day, 'bookings': rows}


@route('POST', r'/api/ot', ('ot',))
def save_ot(app, staff, p, b):
    rid = to_int(b.get('id'))
    if rid and set(b) - {'_token'} <= {'id', 'checklist', 'status'}:
        vals = {}
        if 'checklist' in b:
            vals['checklist'] = json.dumps([clean(x, 30) for x in b['checklist']][:10])
        if b.get('status') in ('planned', 'done', 'cancelled'):
            vals['status'] = b['status']
        return {'id': app.upsert(staff, 'ot_bookings', dict(vals, id=rid), tuple(vals))}
    name = clean(b.get('patient_name'))
    day = as_date(b.get('ot_date'), 'Choose the date')
    start, end = minutes(b.get('start_time')), minutes(b.get('end_time'))
    if len(name) < 2:
        raise ApiError(400, 'Enter the patient name')
    if end <= start:
        raise ApiError(400, 'End time must be after start time')
    vals = {'patient_name': name, 'procedure': clean(b.get('procedure'), 200), 'surgeon_id': to_int(b.get('surgeon_id')),
            'anesthetist': clean(b.get('anesthetist')), 'ot_date': day.isoformat(),
            'start_time': '%02d:%02d' % divmod(start, 60), 'end_time': '%02d:%02d' % divmod(end, 60)}
    if not rid:
        vals.update(created_by=staff['id'], created_at=now())
    rid = app.upsert(staff, 'ot_bookings', dict(vals, id=rid), tuple(vals))
    clash = app.q("SELECT patient_name, start_time, end_time FROM ot_bookings WHERE ot_date=? AND id<>? AND status<>'cancelled' "
                  "AND start_time<? AND ?<end_time", (vals['ot_date'], rid, vals['end_time'], vals['start_time']))
    return {'id': rid, 'clash': clash}


# ---------- insurance and scheme claims ----------
def after_admit(app, aid):
    a = app.one('SELECT payer FROM admissions WHERE id=?', (aid,))
    if a and (a['payer'] or 'Cash') != 'Cash':
        cid = app.run('INSERT OR IGNORE INTO claims(admission_id, scheme, status_at, created_at) VALUES(?,?,?,?)', (aid, a['payer'], now(), now()))
        if cid and app.one('SELECT id FROM claims WHERE id=? AND admission_id=?', (cid, aid)):
            app.run('INSERT INTO claim_events(claim_id, at, staff_name, kind, detail) VALUES(?,?,?,?,?)', (cid, now(), 'system', 'started', a['payer']))


AUTO_ITEMS = {  # documents this system already has, ticked without anyone uploading them
    'Discharge summary (signed)': lambda app, c: bool(app.one('SELECT 1 x FROM discharge_summaries WHERE admission_id=? AND final=1', (c['admission_id'],))),
    'Investigation reports': lambda app, c: bool(claim_labs(app, c)),
    'Admission notes': lambda app, c: bool(app.one("SELECT 1 x FROM ip_events WHERE admission_id=? AND kind IN ('round','note')", (c['admission_id'],))),
}


def claim_labs(app, c):
    a = app.one('SELECT patient_id, admitted_at FROM admissions WHERE id=?', (c['admission_id'],))
    return app.q('SELECT id, test, file, ctype, reported_at FROM lab_orders WHERE patient_id=? AND ordered_at>=? AND file IS NOT NULL ORDER BY id',
                 (a['patient_id'], a['admitted_at'][:10]))


def claim_out(app, c):
    c['checked'] = json.loads(c['checked'] or '[]')
    c['items'] = [r['item'] for r in app.q('SELECT item FROM scheme_docs WHERE scheme=? AND active=1 ORDER BY id', (c['scheme'],))]
    c['docs'] = app.q('SELECT id, item, ctype, uploaded_by, at FROM claim_docs WHERE claim_id=? ORDER BY id', (c['id'],))
    have = {d['item'] for d in c['docs']}
    c['auto'] = [i for i in c['items'] if i in AUTO_ITEMS and AUTO_ITEMS[i](app, c)]
    c['missing'] = [i for i in c['items'] if i not in c['checked'] and i not in have and i not in c['auto']]
    signed = app.one('SELECT final FROM discharge_summaries WHERE admission_id=?', (c['admission_id'],))
    if not (signed and signed['final']) and 'Discharge summary (signed)' not in c['missing']:
        c['missing'].append('Discharge summary is not signed by the doctor yet')
    c['days'] = (datetime.date.today() - datetime.date.fromisoformat((c['status_at'] or c['created_at'])[:10])).days
    return c


@route('GET', r'/api/claims', ('claims',))
def list_claims(app, staff, p, b):
    rows = app.q('SELECT c.*, p.name patient, p.uhid, b.label bed, a.admitted_at, a.discharged_at, a.diagnosis, a.procedure, dr.name doctor '
                 'FROM claims c JOIN admissions a ON a.id=c.admission_id JOIN patients p ON p.id=a.patient_id '
                 'JOIN beds b ON b.id=a.bed_id LEFT JOIN doctors dr ON dr.id=a.doctor_id ORDER BY c.id DESC LIMIT 200')
    out = [claim_out(app, c) for c in rows]
    for c in out:
        last = (c.get('last_activity_at') or c.get('status_at') or c['created_at'])[:10]
        c['idle_days'] = (datetime.date.today() - datetime.date.fromisoformat(last)).days
        c['bill'] = app.one('SELECT bill_no, scheme_amount FROM ip_bills WHERE admission_id=? AND reopened=0', (c['admission_id'],))
    return {'claims': out}


@route('POST', r'/api/claims/(\d+)', ('claims',))
def update_claim(app, staff, p, b, cid):
    c = app.one('SELECT * FROM claims WHERE id=?', (cid,))
    if not c:
        raise ApiError(404, 'Not found')
    with app.tx():
        if 'checked' in b:
            app.run('UPDATE claims SET checked=? WHERE id=?', (json.dumps([clean(x, 120) for x in b['checked']][:40]), cid))
        if 'claim_no' in b:
            app.run('UPDATE claims SET claim_no=? WHERE id=?', (clean(b['claim_no'], 40), cid))
        if 'member_id' in b:
            app.run('UPDATE claims SET member_id=? WHERE id=?', (clean(b['member_id'], 40), cid))
        if 'status' in b:
            if b['status'] not in CLAIM_STATES:
                raise ApiError(400, 'Unknown status')
            if b['status'] in ('queried', 'rejected') and not clean(b.get('reason')):
                raise ApiError(400, 'Enter the reason given by the insurer')
            app.run('UPDATE claims SET status=?, status_at=?, reason=? WHERE id=?', (b['status'], now(), clean(b.get('reason'), 300), cid))
            if b['status'] != c['status']:
                claimflow.event(app, staff, cid, 'status', b['status'] + (': ' + clean(b.get('reason'), 200) if clean(b.get('reason')) else ''))
            if b['status'] in ('settled', 'rejected'):
                app.run('UPDATE claims SET next_followup=NULL WHERE id=?', (cid,))
        if ('claim_no' in b and clean(b['claim_no'], 40) != (c['claim_no'] or '')) or ('member_id' in b and clean(b['member_id'], 40) != (c['member_id'] or '')):
            claimflow.event(app, staff, cid, 'note', 'Card / claim number updated')
        if 'checked' in b:
            claimflow.event(app, staff, cid, 'doc', 'Checklist updated')
        app.audit(staff, 'claim.update', 'claim', cid, {'fields': sorted(k for k in b if k in ('checked', 'claim_no', 'member_id', 'status'))})
    return {'ok': True}


@route('GET', r'/api/claims/(\d+)/packet', ('claims',))
def claim_packet(app, staff, p, b, cid):
    c = app.one('SELECT * FROM claims WHERE id=?', (cid,))
    if not c:
        raise ApiError(404, 'Not found')
    a = admission_for(app, staff, c['admission_id'])
    ev = app.q("SELECT kind, data, at, staff_name FROM ip_events WHERE admission_id=? AND kind IN ('service','round') ORDER BY id", (a['id'],))
    for e in ev:
        e['data'] = json.loads(e['data'] or '{}')
    app.audit(staff, 'claim.packet', 'claim', cid)
    return {'claim': claim_out(app, c), 'admission': a, 'summary': summary_for(app, a), 'events': ev,
            'labs': app.q('SELECT test, status, reported_at FROM lab_orders WHERE patient_id=? AND ordered_at>=? ORDER BY id',
                          (a['patient_id'], a['admitted_at'][:10]))}


@route('POST', r'/api/admin/scheme-doc', ('settings',))
def save_scheme_doc(app, staff, p, b):
    for k in ('scheme', 'item'):
        if k in b and not clean(b[k]):
            raise ApiError(400, 'Enter the scheme and the document name')
    return {'id': app.upsert(staff, 'scheme_docs', b, ('scheme', 'item', 'active'))}


# ---------- pharmacy assist ----------
def parse_expiry(text):
    t = clean(text, 20)
    if not t:
        return None
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%d-%m-%y', '%d-%b-%Y', '%d-%b-%y', '%d.%m.%Y'):
        try:
            return datetime.datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    for fmt in ('%m/%Y', '%m-%Y', '%m/%y', '%m-%y', '%b-%y', '%b-%Y', '%b %Y', '%b %y', '%b/%y'):  # month only: valid till month end
        try:
            d = datetime.datetime.strptime(t, fmt).date()
            return d.replace(day=calendar.monthrange(d.year, d.month)[1]).isoformat()
        except ValueError:
            pass
    return None


def parse_stock(text):
    """Read a stock list exported from the pharmacy software. Column names are guessed from the header row."""
    try:
        dialect = csv.Sniffer().sniff(text[:3000], delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel
    table = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    words = [('supplier', ('supplier', 'party', 'vendor', 'distributor', 'mfr', 'company')), ('batch', ('batch',)),
             ('expiry', ('exp',)), ('mrp', ('mrp', 'm.r.p', 'sale rate', 'selling', 's.rate', 'srate')), ('qty', ('qty', 'quantity', 'stock', 'bal')),
             ('item', ('item', 'drug', 'product', 'description', 'particular', 'name'))]
    cols, head = {}, None
    for hi, row in enumerate(table[:15]):
        cols = {}
        for ci, cell in enumerate(row):
            c = cell.strip().lower()
            for key, keys in words:
                if key not in cols and any(k in c for k in keys) and not (key == 'item' and ('code' in c or c.endswith(' id'))):
                    cols[key] = ci
                    break
        if 'item' in cols and ('qty' in cols or 'expiry' in cols):
            head = hi
            break
    if head is None:
        raise ApiError(400, 'Could not find the columns. The file needs a heading row with an item or drug name, and quantity or expiry.')
    rows, errors = [], []
    get = lambda row, key: row[cols[key]].strip() if key in cols and cols[key] < len(row) else ''  # noqa: E731
    for n, row in enumerate(table[head + 1:], head + 2):
        item = get(row, 'item')
        if not item or item.lower().startswith('total'):
            continue
        exp_text, qty_text = get(row, 'expiry'), get(row, 'qty').replace(',', '')
        expiry = parse_expiry(exp_text)
        if exp_text and not expiry:
            errors.append('Row %d: could not read expiry "%s"' % (n, exp_text[:20]))
        try:
            qty = float(qty_text) if qty_text else None
        except ValueError:
            qty = None
            errors.append('Row %d: could not read quantity "%s"' % (n, qty_text[:20]))
        try:
            mrp = float(get(row, 'mrp').replace(',', '').replace('₹', '')) if get(row, 'mrp') else None
        except ValueError:
            mrp = None
        rows.append((item[:120], get(row, 'batch')[:40], expiry, qty, get(row, 'supplier')[:80], mrp))
    return rows, errors, sorted(cols)


def pharmacy_view(app):
    td = datetime.date.today()
    window = to_int(app.setting('expiry_days', '90'), 90)
    low_qty = to_int(app.setting('low_qty', '10'), 10)
    exp = app.q("SELECT item, batch, expiry, qty, supplier FROM stock WHERE expiry IS NOT NULL AND expiry<=? AND COALESCE(qty, 1)>0 ORDER BY expiry",
                ((td + datetime.timedelta(days=window)).isoformat(),))
    for r in exp:
        r['days'] = (datetime.date.fromisoformat(r['expiry']) - td).days
    low = app.q("SELECT item, SUM(qty) qty, MAX(supplier) supplier FROM stock WHERE qty IS NOT NULL GROUP BY item HAVING SUM(qty)<=? ORDER BY supplier, item", (low_qty,))
    return {'expired': [r for r in exp if r['days'] < 0], 'expiring': [r for r in exp if r['days'] >= 0], 'low': low,
            'window': window, 'low_qty': low_qty, 'items': app.one('SELECT COUNT(*) n FROM stock')['n'],
            'last_import': app.one('SELECT at, staff_name, rows, errors FROM import_runs ORDER BY id DESC LIMIT 1')}


@route('GET', r'/api/pharmacy', ('pharmacy',))
def get_pharmacy(app, staff, p, b):
    return pharmacy_view(app)


@route('POST', r'/api/pharmacy/import', ('pharmacy',))
def import_stock(app, staff, p, b):
    raw = b.get('_raw')
    if not raw:
        raise ApiError(400, 'Choose the stock file exported from Pharmasoft (CSV)')
    text = None
    for enc in ('utf-8-sig', 'cp1252'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    if text is None or '\x00' in text:
        raise ApiError(400, 'This is not a CSV text file. In Pharmasoft or Excel choose "Save as CSV" and try again.')
    rows, errors, cols = parse_stock(text)
    if not rows:
        raise ApiError(400, 'No stock rows found in the file')
    with app.tx():
        app.run('DELETE FROM stock')
        for r in rows:
            app.run('INSERT INTO stock(item, batch, expiry, qty, supplier, mrp) VALUES(?,?,?,?,?,?)', r)
        app.run('INSERT INTO import_runs(at, staff_name, source, rows, errors) VALUES(?,?,?,?,?)',
                (now(), staff['name'], 'stock csv', len(rows), json.dumps(errors[:30])))
        app.audit(staff, 'pharmacy.import', None, None, {'rows': len(rows), 'errors': len(errors)})
    v = pharmacy_view(app)
    soon = len([r for r in v['expiring'] if r['days'] <= 30])
    app.notify('pharmacy', 'Pharmacy stock updated (%d lines).\nExpired: %d\nExpiring within 30 days: %d\nWithin %d days: %d\nLow stock: %d items'
               % (len(rows), len(v['expired']), soon, v['window'], len(v['expiring']), len(v['low'])))
    return {'rows': len(rows), 'errors': errors[:30], 'columns': cols}


@route('GET', r'/api/dose-refs', ('pharmacy', 'myday'))
def dose_refs(app, staff, p, b):
    return {'refs': app.q('SELECT * FROM dose_refs WHERE active=1 ORDER BY drug')}


@route('POST', r'/api/admin/dose-ref', ('settings',))
def save_dose_ref(app, staff, p, b):
    for k in ('min_mg_kg', 'max_mg_kg', 'max_mg'):
        if k in b:
            try:
                b[k] = float(b[k]) if str(b[k]).strip() != '' else None
            except ValueError:
                raise ApiError(400, 'Enter numbers only for the dose')
    if not to_int(b.get('id')) and (not clean(b.get('drug')) or b.get('min_mg_kg') is None or b.get('max_mg_kg') is None):
        raise ApiError(400, 'Enter the drug and its mg/kg range')
    if 'per' in b and b['per'] not in ('dose', 'day'):
        raise ApiError(400, 'Choose per dose or per day')
    b['confirmed_by'] = '%s on %s' % (staff['name'], today())
    return {'id': app.upsert(staff, 'dose_refs', b, ('drug', 'min_mg_kg', 'max_mg_kg', 'per', 'max_mg', 'note', 'confirmed_by', 'active'))}


@route('POST', r'/api/dose-check', ('pharmacy', 'myday'))
def dose_check(app, staff, p, b):
    ref = app.one('SELECT * FROM dose_refs WHERE id=? AND active=1', (to_int(b.get('ref_id')),))
    try:
        kg = float(b.get('weight_kg'))
    except (TypeError, ValueError):
        kg = 0
    if not ref or not 0.4 <= kg <= 150:
        raise ApiError(400, 'Choose the drug and enter the weight in kg')
    lo, hi = ref['min_mg_kg'] * kg, ref['max_mg_kg'] * kg
    capped = bool(ref['max_mg'] and hi > ref['max_mg'])
    if capped:
        hi, lo = ref['max_mg'], min(lo, ref['max_mg'])
    app.audit(staff, 'dose.check', 'dose_ref', ref['id'], {'weight_kg': kg})
    return {'drug': ref['drug'], 'weight_kg': kg, 'low_mg': round(lo, 1), 'high_mg': round(hi, 1), 'per': ref['per'],
            'capped': capped, 'note': ref['note'], 'confirmed_by': ref['confirmed_by']}


@route('POST', r'/api/visits/(\d+)/bought', ('rx',))
def visit_bought(app, staff, p, b, vid):
    if not app.one('SELECT id FROM visits WHERE id=?', (vid,)):
        raise ApiError(404, 'Visit not found')
    bought = None if b.get('bought') is None else (1 if b['bought'] else 0)
    with app.tx():
        app.run('UPDATE visits SET bought=?, not_bought_reason=? WHERE id=?', (bought, clean(b.get('reason'), 120) if bought == 0 else None, vid))
        app.audit(staff, 'visit.bought', 'visit', vid, {'bought': bought})
    return {'ok': True}


# ---------- attendance, roster, salary, consultant payouts ----------
def month_of(p):
    m = re.fullmatch(r'(\d{4})-(\d{2})', clean(p.get('month'), 7) or today()[:7])
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ApiError(400, 'Choose the month')
    y, mo = int(m.group(1)), int(m.group(2))
    return y, mo, calendar.monthrange(y, mo)[1]


@route('GET', r'/api/duty', '*')
def my_duty(app, staff, p, b):
    return {'today': app.one('SELECT in_at, out_at FROM attendance WHERE staff_id=? AND day=?', (staff['id'], today())),
            'shift': (app.one('SELECT shift FROM roster WHERE staff_id=? AND day=?', (staff['id'], today())) or {}).get('shift')}


@route('POST', r'/api/duty', '*')
def mark_duty(app, staff, p, b):
    row = app.one('SELECT * FROM attendance WHERE staff_id=? AND day=?', (staff['id'], today()))
    with app.tx():
        if not row or not row['in_at']:
            app.run("INSERT INTO attendance(staff_id, day, in_at, status) VALUES(?,?,?,'P') "
                    "ON CONFLICT(staff_id, day) DO UPDATE SET in_at=excluded.in_at, status='P'", (staff['id'], today(), now()))
            app.audit(staff, 'duty.in', 'staff', staff['id'])
        else:
            app.run('UPDATE attendance SET out_at=? WHERE staff_id=? AND day=?', (now(), staff['id'], today()))
            app.audit(staff, 'duty.out', 'staff', staff['id'])
    return my_duty(app, staff, p, b)


def month_sheet(app, y, mo, days):
    first, last = '%04d-%02d-01' % (y, mo), '%04d-%02d-%02d' % (y, mo, days)
    marks = {}
    for r in app.q('SELECT staff_id, day, shift FROM roster WHERE day BETWEEN ? AND ?', (first, last)):
        if r['shift'] == 'Off':
            marks[(r['staff_id'], r['day'])] = 'O'
    for r in app.q('SELECT staff_id, day, status FROM attendance WHERE day BETWEEN ? AND ?', (first, last)):
        if r['status']:
            marks[(r['staff_id'], r['day'])] = r['status']
    return marks


@route('GET', r'/api/attendance', ('staff',))
def attendance(app, staff, p, b):
    y, mo, days = month_of(p)
    marks = month_sheet(app, y, mo, days)
    people = app.q("SELECT id, name, role FROM staff WHERE active=1 AND role<>'consultant' ORDER BY role, name")
    for s in people:
        s['days'] = [marks.get((s['id'], '%04d-%02d-%02d' % (y, mo, d)), '') for d in range(1, days + 1)]
    return {'month': '%04d-%02d' % (y, mo), 'days': days, 'staff': people}


@route('POST', r'/api/attendance', ('staff',))
def set_attendance(app, staff, p, b):
    sid, status = to_int(b.get('staff_id')), b.get('status')
    day = as_date(b.get('day'), 'Choose the day').isoformat()
    if status not in ('P', 'A', 'L', 'H', 'O', ''):
        raise ApiError(400, 'Unknown mark')
    with app.tx():
        app.run('INSERT INTO attendance(staff_id, day, status) VALUES(?,?,?) ON CONFLICT(staff_id, day) DO UPDATE SET status=excluded.status',
                (sid, day, status or None))
        app.audit(staff, 'attendance.set', 'staff', sid, {'day': day, 'status': status})
    return {'ok': True}


@route('GET', r'/api/roster', '*')
def get_roster(app, staff, p, b):
    start = as_date(p.get('week') or today(), 'Choose the week')
    start -= datetime.timedelta(days=start.weekday())
    days = [(start + datetime.timedelta(days=i)).isoformat() for i in range(7)]
    shifts = {(r['staff_id'], r['day']): r['shift'] for r in app.q('SELECT * FROM roster WHERE day BETWEEN ? AND ?', (days[0], days[6]))}
    people = app.q("SELECT id, name, role FROM staff WHERE active=1 AND role NOT IN ('owner','consultant') ORDER BY role, name")
    for s in people:
        s['shifts'] = [shifts.get((s['id'], d), '') for d in days]
    gaps = []
    for i, d in enumerate(days):
        for role, label in (('nurse', 'nurse'), ('reception', 'reception')):
            on = [s for s in people if s['role'] == role and s['shifts'][i] not in ('', 'Off')]
            if any(s['shifts'][i] for s in people) and not on:
                gaps.append('%s: no %s on duty' % (d, label))
    return {'days': days, 'staff': people, 'gaps': gaps}


@route('POST', r'/api/roster', ('staff',))
def set_roster(app, staff, p, b):
    sid, shift = to_int(b.get('staff_id')), b.get('shift')
    day = as_date(b.get('day'), 'Choose the day').isoformat()
    if shift not in ('Morning', 'Evening', 'Night', 'Full day', 'Off', ''):
        raise ApiError(400, 'Unknown shift')
    with app.tx():
        app.run('INSERT INTO roster(staff_id, day, shift) VALUES(?,?,?) ON CONFLICT(staff_id, day) DO UPDATE SET shift=excluded.shift', (sid, day, shift))
        app.audit(staff, 'roster.set', 'staff', sid, {'day': day, 'shift': shift})
    return {'ok': True}


def payroll_rows(app, y, mo, days):
    marks = month_sheet(app, y, mo, days)
    deds = app.q('SELECT * FROM deductions WHERE active=1 ORDER BY id')
    out = []
    for s in app.q("SELECT id, name, role, salary FROM staff WHERE active=1 AND COALESCE(salary, 0)>0 ORDER BY role, name"):
        count = {k: 0 for k in 'PALHO'}
        for d in range(1, days + 1):
            m = marks.get((s['id'], '%04d-%02d-%02d' % (y, mo, d)))
            if m:
                count[m] += 1
        paid = min(days, count['P'] + count['L'] + count['O'] + 0.5 * count['H'])
        earned = round(s['salary'] * paid / days)
        lines = [{'name': d['name'], 'amount': round(earned * d['value'] / 100) if d['kind'] == 'percent' else round(min(d['value'], earned))} for d in deds]
        out.append({'staff_id': s['id'], 'name': s['name'], 'role': s['role'], 'salary': s['salary'], 'days': days, 'paid_days': paid,
                    'present': count['P'], 'leave': count['L'], 'half': count['H'], 'off': count['O'], 'absent': count['A'],
                    'unmarked': days - sum(count.values()), 'earned': earned, 'deductions': lines,
                    'net': earned - sum(x['amount'] for x in lines)})
    return out


@route('GET', r'/api/payroll', ('staff', 'accounts'))
def payroll(app, staff, p, b):
    y, mo, days = month_of(p)
    app.audit(staff, 'payroll.view', None, None, {'month': '%04d-%02d' % (y, mo)})
    return {'month': '%04d-%02d' % (y, mo), 'rows': payroll_rows(app, y, mo, days)}


@route('GET', r'/api/payouts', ('staff', 'accounts', 'doctors'))
def payouts(app, staff, p, b):
    y, mo, days = month_of(p)
    like = '%04d-%02d%%' % (y, mo)
    out = []
    for d in app.q("SELECT d.id, d.name, d.payout_kind, d.payout_rate, dep.name dept FROM doctors d JOIN departments dep ON dep.id=d.dept_id "
                   "WHERE d.kind='consultant' AND d.active=1 ORDER BY d.name"):
        visits = app.one("SELECT COUNT(*) n FROM visits WHERE doctor_id=? AND status='done' AND visit_date LIKE ?", (d['id'], like))['n']
        cases = app.one('SELECT COUNT(*) n FROM admissions WHERE doctor_id=? AND admitted_at LIKE ?', (d['id'], like))['n']
        came = app.one('SELECT COUNT(*) n FROM doctor_days WHERE doctor_id=? AND day LIKE ? AND arrived_at IS NOT NULL', (d['id'], like))['n']
        rate = d['payout_rate'] or 0
        amount = {'visit': visits * rate, 'case': (visits + cases) * rate, 'day': came * rate, 'fixed': rate}.get(d['payout_kind'], 0)
        out.append(dict(d, visits=visits, admissions=cases, days=came, amount=amount))
    return {'month': '%04d-%02d' % (y, mo), 'rows': out}


@route('POST', r'/api/admin/deduction', ('settings',))
def save_deduction(app, staff, p, b):
    if 'kind' in b and b['kind'] not in ('percent', 'fixed'):
        raise ApiError(400, 'Choose percent or fixed amount')
    if 'value' in b:
        try:
            b['value'] = float(b['value'])
        except (TypeError, ValueError):
            raise ApiError(400, 'Enter a number')
    if 'name' in b and not clean(b['name']):
        raise ApiError(400, 'Enter the name, for example PF')
    return {'id': app.upsert(staff, 'deductions', b, ('name', 'kind', 'value', 'active'))}


# ---------- pieces used by the first-phase screens ----------
def admin_extra(app):
    return {'prices': app.q('SELECT * FROM price_items ORDER BY active DESC, category, name'),'schedule': app.q('SELECT * FROM schedule_items ORDER BY plan DESC, offset_days'),
            'confirmed': {k: app.setting('schedule_confirmed_' + k) for k in ('vaccine', 'antenatal')},
            'scheme_docs': app.q('SELECT * FROM scheme_docs ORDER BY scheme, id'),
            'dose_refs': app.q('SELECT * FROM dose_refs ORDER BY drug'),
            'deductions': app.q('SELECT * FROM deductions ORDER BY id')}


def followup_counts(app):
    td = today()
    return {'missed': app.one("SELECT COUNT(*) n FROM followups WHERE status='due' AND due_date<?", (td,))['n'],
            'today': app.one("SELECT COUNT(*) n FROM followups WHERE status='due' AND due_date=?", (td,))['n']}


def dashboard_extra(app):
    ph = pharmacy_view(app)
    claims = {s: 0 for s in CLAIM_STATES}
    for r in app.q('SELECT status, COUNT(*) n FROM claims GROUP BY status'):
        claims[r['status']] = r['n']
    daily_reset(app)
    missing = [d['name'] for d in app.q("SELECT d.* FROM doctors d LEFT JOIN doctor_days dd ON dd.doctor_id=d.id AND dd.day=? "
                                        "WHERE d.active=1 AND d.kind='consultant' AND dd.arrived_at IS NULL", (today(),)) if expected_today(d)]
    td = today()
    return {'followups': followup_counts(app), 'discharges': pending_discharges(app), 'claims': claims, 'consultants_not_in': missing,
            'op_fees': app.one("SELECT COALESCE(SUM(fee_shown), 0) n FROM visits WHERE visit_date=? AND status<>'skipped'", (td,))['n'],
            'critical_labs': app.q("SELECT l.test, p.name, dr.name doctor FROM lab_orders l JOIN patients p ON p.id=l.patient_id LEFT JOIN doctors dr ON dr.id=l.doctor_id "
                                   "WHERE l.critical=1 AND substr(l.reported_at, 1, 10)=?", (td,)),
            'unsigned': app.one("SELECT COUNT(*) n FROM admissions a WHERE a.status='discharged' AND NOT EXISTS "
                                "(SELECT 1 FROM discharge_summaries s WHERE s.admission_id=a.id AND s.final=1)")['n'],
            'doctor_days': app.q('SELECT d.id, dd.arrived_at, dd.left_at FROM doctors d LEFT JOIN doctor_days dd ON dd.doctor_id=d.id AND dd.day=? WHERE d.active=1', (td,)),
            'slips': charges.slip_status(app),
            'claimflow': claimflow.summary(app),
            'rx_missing': app.one("SELECT COUNT(*) n FROM visits v WHERE v.visit_date=? AND v.status='done' AND NOT EXISTS (SELECT 1 FROM prescriptions r WHERE r.visit_id=v.id)", (td,))['n'],
            'pharmacy': {'expired': len(ph['expired']), 'expiring': len(ph['expiring']), 'low': len(ph['low']), 'window': ph['window']},
            'ip_money': billing.money_day(app, today()),
            'pharm': __import__('pharmsale').day_totals(app, today()),
            'labs_open': app.one("SELECT COUNT(*) n FROM lab_orders WHERE status<>'reported'")['n'],
            'on_duty': [r['name'] for r in app.q('SELECT s.name FROM attendance a JOIN staff s ON s.id=a.staff_id '
                                                 'WHERE a.day=? AND a.in_at IS NOT NULL AND a.out_at IS NULL ORDER BY s.name', (today(),))]}


def summary_lines(app):
    f, ph = followup_counts(app), pharmacy_view(app)
    m = billing.money_day(app, today())
    lines = ['', 'Inpatient money received today: Rs %d' % m['collected'],
             '', 'Follow-ups missed: %d, due today and not done: %d' % (f['missed'], f['today'])]
    pend = pending_discharges(app)
    if pend:
        lines.append('Discharges ordered but not finished: %d (beds %s)' % (len(pend), ', '.join(x['bed'] for x in pend)))
    if ph['items']:
        lines.append('Pharmacy: %d expired, %d expiring in %d days, %d low stock' % (len(ph['expired']), len(ph['expiring']), ph['window'], len(ph['low'])))
    open_claims = app.one("SELECT COUNT(*) n FROM claims WHERE status IN ('preparing','queried')")['n']
    if open_claims:
        lines.append('Claims needing work: %d' % open_claims)
    return lines


# ---------- doctor attendance (mostly automatic) ----------
WEEKDAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')


def daily_reset(app):
    """Each morning every doctor starts as 'Not in', so yesterday's status never shows today."""
    if app.setting('status_day') != today():
        app.set_setting('status_day', today())
        app.run("UPDATE doctors SET status='out', status_note='' WHERE status<>'out'")


def doctor_day(app, did, status, staff):
    """Called when anyone changes a doctor's status: 'In' or 'In surgery' records arrival, 'Not in' records leaving."""
    row = app.one('SELECT * FROM doctor_days WHERE doctor_id=? AND day=?', (did, today()))
    t = now()[11:16]
    if status in ('in', 'surgery') and not (row and row['arrived_at']):
        app.run('INSERT INTO doctor_days(doctor_id, day, arrived_at, marked_by) VALUES(?,?,?,?) '
                'ON CONFLICT(doctor_id, day) DO UPDATE SET arrived_at=excluded.arrived_at, left_at=NULL, marked_by=excluded.marked_by',
                (did, today(), t, staff['name']))
    elif status in ('in', 'surgery') and row['left_at']:
        app.run('UPDATE doctor_days SET left_at=NULL WHERE doctor_id=? AND day=?', (did, today()))  # came back
    elif status == 'out' and row and row['arrived_at'] and not row['left_at']:
        app.run('UPDATE doctor_days SET left_at=?, marked_by=? WHERE doctor_id=? AND day=?', (t, staff['name'], did, today()))


def expected_today(d, day=None):
    day = day or datetime.date.today()
    if d['kind'] != 'consultant':
        return day.weekday() != 6
    return WEEKDAYS[day.weekday()] in (d.get('visit_days') or '').split(',')


@route('GET', r'/api/doctor-days', ('doctors', 'today'))
def doctor_days(app, staff, p, b):
    daily_reset(app)
    day = as_date(p.get('date') or today(), 'Choose the date')
    rows = app.q('SELECT d.id, d.name, d.kind, d.status, d.status_note, d.visit_days, d.visit_time, dep.name dept, '
                 'dd.arrived_at, dd.left_at, dd.marked_by FROM doctors d JOIN departments dep ON dep.id=d.dept_id '
                 'LEFT JOIN doctor_days dd ON dd.doctor_id=d.id AND dd.day=? WHERE d.active=1 ORDER BY d.kind DESC, d.name', (day.isoformat(),))
    for r in rows:
        r['expected'] = expected_today(r, day)
        if day.isoformat() != today():
            r['status'] = None
    like = day.isoformat()[:7] + '%'
    month = app.q("SELECT d.id, d.name, COUNT(dd.arrived_at) days, GROUP_CONCAT(substr(dd.day, 9, 2)) dates FROM doctors d "
                  "LEFT JOIN doctor_days dd ON dd.doctor_id=d.id AND dd.day LIKE ? AND dd.arrived_at IS NOT NULL "
                  "WHERE d.active=1 AND d.kind='consultant' GROUP BY d.id ORDER BY d.name", (like,))
    return {'date': day.isoformat(), 'doctors': rows, 'month': month}


@route('POST', r'/api/doctor-days', ('doctors',))
def fix_doctor_day(app, staff, p, b):
    did = to_int(b.get('doctor_id'))
    day = as_date(b.get('date'), 'Choose the date').isoformat()
    if not app.one('SELECT id FROM doctors WHERE id=?', (did,)):
        raise ApiError(404, 'Doctor not found')
    times = {}
    for k in ('arrived_at', 'left_at'):
        v = clean(b.get(k), 5)
        if v and not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', v):
            raise ApiError(400, 'Time must look like 10:30')
        times[k] = v or None
    if times['left_at'] and not times['arrived_at']:
        raise ApiError(400, 'Enter the arrival time first')
    with app.tx():
        app.run('INSERT INTO doctor_days(doctor_id, day, arrived_at, left_at, marked_by) VALUES(?,?,?,?,?) '
                'ON CONFLICT(doctor_id, day) DO UPDATE SET arrived_at=excluded.arrived_at, left_at=excluded.left_at, marked_by=excluded.marked_by',
                (did, day, times['arrived_at'], times['left_at'], staff['name']))
        app.audit(staff, 'doctor.attendance', 'doctor', did, dict(times, day=day))
    return {'ok': True}


# ---------- "My day" for doctors ----------
@route('GET', r'/api/myday', ('myday',))
def myday(app, staff, p, b):
    daily_reset(app)
    did = staff['doctor_id']
    if not did:
        raise ApiError(400, 'This login is not linked to a doctor yet.')
    td = today()
    me = app.one('SELECT d.*, dep.name dept FROM doctors d JOIN departments dep ON dep.id=d.dept_id WHERE d.id=?', (did,))
    visits = app.q("SELECT v.id, v.token_code, v.status, v.created_at, v.patient_id, p.name, p.sex, p.dob, p.age_y, p.age_m, p.age_on, "
                   "(SELECT COUNT(*) FROM prescriptions r WHERE r.visit_id=v.id) rx, "
                   "(SELECT MAX(o.visit_date) FROM visits o WHERE o.patient_id=v.patient_id AND o.visit_date<v.visit_date) last_visit, "
                   "(SELECT COUNT(*) FROM lab_orders l WHERE l.patient_id=v.patient_id AND l.file IS NOT NULL) reports "
                   "FROM visits v JOIN patients p ON p.id=v.patient_id "
                   "WHERE v.doctor_id=? AND v.visit_date=? ORDER BY v.token_no", (did, td))
    ips = app.q("SELECT a.id, a.admitted_at, a.diagnosis, a.procedure, a.payer, a.discharge_ordered_at, b.label bed, p.name, p.sex, p.dob, "
                "p.age_y, p.age_m, p.age_on, (SELECT MAX(at) FROM ip_events e WHERE e.admission_id=a.id AND e.kind='round') last_round, "
                "(SELECT MAX(at) FROM ip_events e WHERE e.admission_id=a.id AND e.kind='vitals') last_vitals "
                "FROM admissions a JOIN beds b ON b.id=a.bed_id JOIN patients p ON p.id=a.patient_id "
                "WHERE a.doctor_id=? AND a.status='admitted' ORDER BY b.id", (did,))
    since = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    labs = app.q("SELECT l.id, l.test, l.status, l.critical, l.reported_at, l.patient_id, p.name, l.file IS NOT NULL has_file FROM lab_orders l "
                 "JOIN patients p ON p.id=l.patient_id WHERE l.doctor_id=? AND (l.status<>'reported' OR l.reported_at>=?) "
                 "ORDER BY l.critical DESC, l.status='reported' DESC, l.id DESC", (did, since))
    ot = app.q("SELECT id, patient_name, procedure, ot_date, start_time, end_time, anesthetist, checklist FROM ot_bookings "
               "WHERE surgeon_id=? AND status='planned' AND ot_date BETWEEN ? AND ? ORDER BY ot_date, start_time",
               (did, td, (datetime.date.today() + datetime.timedelta(days=7)).isoformat()))
    for r in visits + ips:
        r['age'] = age_text(r)
        for k in ('dob', 'age_y', 'age_m', 'age_on'):
            r.pop(k)
    for o in ot:
        o['checklist'] = json.loads(o['checklist'] or '[]')
    like = td[:7] + '%'
    month = {'seen': app.one("SELECT COUNT(*) n FROM visits WHERE doctor_id=? AND status='done' AND visit_date LIKE ?", (did, like))['n'],
             'days': app.one('SELECT COUNT(*) n FROM doctor_days WHERE doctor_id=? AND day LIKE ? AND arrived_at IS NOT NULL', (did, like))['n'],
             'admitted': app.one('SELECT COUNT(*) n FROM admissions WHERE doctor_id=? AND admitted_at LIKE ?', (did, like))['n']}
    return {'doctor': me, 'today': app.one('SELECT arrived_at, left_at FROM doctor_days WHERE doctor_id=? AND day=?', (did, td)),
            'visits': visits, 'inpatients': ips, 'labs': labs, 'ot': ot, 'month': month}


# ---------- ward duty list for nurses ----------
@route('GET', r'/api/ward', ('ward',))
def ward(app, staff, p, b):
    sql = ("SELECT a.id, a.admitted_at, a.diagnosis, a.payer, a.discharge_ordered_at, a.doctor_id, b.label bed, b.ward, p.name, p.sex, "
           "p.dob, p.age_y, p.age_m, p.age_on, dr.name doctor FROM admissions a JOIN beds b ON b.id=a.bed_id JOIN patients p ON p.id=a.patient_id "
           "LEFT JOIN doctors dr ON dr.id=a.doctor_id WHERE a.status='admitted'")
    args = []
    if staff['role'] == 'consultant':
        sql += ' AND a.doctor_id=?'
        args.append(staff['doctor_id'])
    rows = app.q(sql + ' ORDER BY b.id', args)
    for r in rows:
        r['age'] = age_text(r)
        for k in ('dob', 'age_y', 'age_m', 'age_on'):
            r.pop(k)
        v = app.one("SELECT data, at, staff_name FROM ip_events WHERE admission_id=? AND kind='vitals' ORDER BY id DESC LIMIT 1", (r['id'],))
        r['vitals'] = dict(v, data=json.loads(v['data'])) if v else None
        rd = app.one("SELECT data, at, staff_name FROM ip_events WHERE admission_id=? AND kind='round' ORDER BY id DESC LIMIT 1", (r['id'],))
        r['round'] = dict(rd, data=json.loads(rd['data'])) if rd else None
        a = app.one('SELECT * FROM admissions WHERE id=?', (r['id'],))
        r['waiting'] = [s['label'] for s in steps_for(app, a) if not s['done_at']] if r['discharge_ordered_at'] else []
    return {'inpatients': rows, 'cleaning': app.q("SELECT id, ward, label, status, note FROM beds WHERE active=1 AND status IN ('cleaning','reserved') ORDER BY id"),
            'ot': app.q("SELECT o.patient_name, o.procedure, o.start_time, o.end_time, o.checklist, dr.name surgeon FROM ot_bookings o "
                        "LEFT JOIN doctors dr ON dr.id=o.surgeon_id WHERE o.ot_date=? AND o.status='planned' ORDER BY o.start_time", (today(),))}


# ---------- admission history ----------
@route('GET', r'/api/admissions', ('iphistory',))
def admission_history(app, staff, p, b):
    sql = ("SELECT a.id, a.admitted_at, a.discharged_at, a.status, a.diagnosis, a.procedure, a.payer, b.label bed, p.name, p.uhid, p.phone, "
           "dr.name doctor, c.status claim_status, (SELECT final FROM discharge_summaries s WHERE s.admission_id=a.id) signed "
           "FROM admissions a JOIN beds b ON b.id=a.bed_id JOIN patients p ON p.id=a.patient_id LEFT JOIN doctors dr ON dr.id=a.doctor_id "
           "LEFT JOIN claims c ON c.admission_id=a.id WHERE 1=1")
    args = []
    q = clean(p.get('q'))
    if q:
        sql += ' AND (p.name LIKE ? OR p.uhid LIKE ? OR p.phone LIKE ? OR a.diagnosis LIKE ?)'
        args += ['%' + q + '%'] * 4
    if p.get('from'):
        sql += ' AND a.admitted_at>=?'
        args.append(as_date(p['from'], 'From date is not valid').isoformat())
    if p.get('to'):
        sql += ' AND substr(a.admitted_at, 1, 10)<=?'
        args.append(as_date(p['to'], 'To date is not valid').isoformat())
    if staff['role'] == 'insurance':   # the insurance desk only works on scheme and insurance patients
        sql += " AND COALESCE(a.payer, 'Cash')<>'Cash'"
    if p.get('status') in ('admitted', 'discharged'):
        sql += ' AND a.status=?'
        args.append(p['status'])
    if staff['role'] == 'consultant':
        sql += ' AND a.doctor_id=?'
        args.append(staff['doctor_id'])
    return {'admissions': app.q(sql + ' ORDER BY a.id DESC LIMIT 300', args)}


# ---------- claim documents, portal details and the full claim file ----------
@route('POST', r'/api/claims/(\d+)/doc', ('claims',))
def upload_claim_doc(app, staff, p, b, cid):
    if not app.one('SELECT id FROM claims WHERE id=?', (cid,)):
        raise ApiError(404, 'Not found')
    item, ext = clean(p.get('item'), 120), FILE_TYPES.get(b.get('_ctype'))
    if not item:
        raise ApiError(400, 'Say which document this is')
    if not ext or not b.get('_raw'):
        raise ApiError(400, 'Send a photo or PDF')
    name = 'claim-' + secrets.token_hex(16) + ext
    with open(os.path.join(app.upload_dir, name), 'wb') as fh:
        fh.write(b['_raw'])
    with app.tx():
        did = app.run('INSERT INTO claim_docs(claim_id, item, file, ctype, uploaded_by, at) VALUES(?,?,?,?,?,?)',
                      (cid, item, name, b['_ctype'], staff['name'], now()))
        app.audit(staff, 'claim.doc_add', 'claim', cid, {'doc': did})
        claimflow.event(app, staff, cid, 'doc', item)
    return {'id': did}


@route('POST', r'/api/claim-docs/(\d+)/remove', ('claims',))
def remove_claim_doc(app, staff, p, b, did):
    d = app.one('SELECT * FROM claim_docs WHERE id=?', (did,))
    if not d:
        raise ApiError(404, 'Not found')
    with app.tx():
        app.run('DELETE FROM claim_docs WHERE id=?', (did,))
        app.audit(staff, 'claim.doc_remove', 'claim', d['claim_id'], {'doc': did})
    return {'ok': True}


@route('GET', r'/files/claimdoc/(\d+)', ('claims',))
def claim_doc_file(app, staff, p, b, did):
    d = app.one('SELECT * FROM claim_docs WHERE id=?', (did,))
    if not d:
        raise ApiError(404, 'Not found')
    return {'_file': os.path.join(app.upload_dir, d['file']), '_ctype': d['ctype']}


def portal_fields(app, staff, c):
    a = admission_for(app, staff, c['admission_id'])
    s = summary_for(app, a)['data']
    return [('Hospital', app.setting('hospital_name')), ('Patient name', a['patient']), ('Age', a['age']),
            ('Sex', {'M': 'Male', 'F': 'Female', 'O': 'Other'}.get(a['sex'], '')), ('Mobile', a['phone']), ('Address / village', a['area']),
            ('Scheme / insurer', c['scheme']), ('Card / member ID', c.get('member_id')), ('Pre-auth / claim number', c['claim_no']),
            ('UHID', a['uhid']), ('Treating doctor', a['doctor']), ('Date of admission', a['admitted_at'][:10]),
            ('Date of discharge', (a['discharged_at'] or '')[:10]), ('Diagnosis', s.get('diagnosis') or a['diagnosis']),
            ('Procedure / surgery', s.get('procedure') or a['procedure']), ('Course in hospital', s.get('course')),
            ('Condition at discharge', s.get('condition')), ('Discharge medicines', s.get('medicines')), ('Follow-up advice', s.get('followup'))]


@route('GET', r'/api/claims/(\d+)/portal', ('claims',))
def claim_portal(app, staff, p, b, cid):
    c = app.one('SELECT * FROM claims WHERE id=?', (cid,))
    if not c:
        raise ApiError(404, 'Not found')
    app.audit(staff, 'claim.portal_view', 'claim', cid)
    return {'fields': [{'label': k, 'value': v or ''} for k, v in portal_fields(app, staff, c)]}


def claim_word(app, staff, c, title, rows, sections):
    import html
    e = lambda x: html.escape(str(x or ''))  # noqa: E731
    out = ['<html><head><meta charset="utf-8"><style>body{font-family:Arial;font-size:11pt}table{border-collapse:collapse;width:100%}'
           'td,th{border:1px solid #999;padding:4px;text-align:left;vertical-align:top}th{width:35%}h1{font-size:15pt;text-align:center}'
           'h2{font-size:12pt;margin-top:14px}.c{text-align:center}</style></head><body>',
           '<p class="c"><b style="font-size:16pt">%s</b><br>%s</p><h1>%s</h1><table>' % (e(app.setting('hospital_name')), e(app.setting('hospital_addr')), e(title))]
    out += ['<tr><th>%s</th><td>%s</td></tr>' % (e(k), e(v).replace('\n', '<br>')) for k, v in rows]
    out.append('</table>')
    for head, body in sections:
        out.append('<h2>%s</h2><p>%s</p>' % (e(head), e(body).replace('\n', '<br>') or '—'))
    out.append('</body></html>')
    return '\n'.join(out).encode('utf-8')


@route('GET', r'/api/claims/(\d+)/zip', ('claims',))
def claim_zip(app, staff, p, b, cid):
    """Everything for one claim in a single file the insurance desk can share or upload: no retyping into Word."""
    import zipfile
    c = app.one('SELECT * FROM claims WHERE id=?', (cid,))
    if not c:
        raise ApiError(404, 'Not found')
    c = claim_out(app, c)
    a = admission_for(app, staff, c['admission_id'])
    summ = summary_for(app, a)
    fields = portal_fields(app, staff, c)
    ev = app.q("SELECT kind, data, at, staff_name FROM ip_events WHERE admission_id=? AND kind IN ('service','round') ORDER BY id", (a['id'],))
    services = '\n'.join('%s  %s  (%s)' % (e['at'][:16].replace('T', ' '), ' · '.join(json.loads(e['data']).values()), e['staff_name']) for e in ev)
    safe = lambda t: re.sub(r'[^A-Za-z0-9 ._()-]+', '', t)[:60].strip() or 'document'  # noqa: E731
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('01 Claim details.doc', claim_word(app, staff, c, 'Claim details - ' + (c['scheme'] or ''), fields,
                                                      [('Services and doctor rounds', services),
                                                       ('Documents still missing', '\n'.join(c['missing']) or 'None')]))
        sd = summ['data']
        z.writestr('02 Discharge summary.doc', claim_word(app, staff, c, 'Discharge Summary' + ('' if summ['final'] else ' (DRAFT - not signed)'),
                                                         fields[1:6] + fields[9:14],
                                                         [('Course in hospital', sd.get('course')), ('Condition at discharge', sd.get('condition')),
                                                          ('Medicines on discharge', sd.get('medicines')), ('Advice', sd.get('advice')),
                                                          ('Follow-up', sd.get('followup')),
                                                          ('Signed', '%s, %s' % (summ['signed_by'], (summ['signed_at'] or '')[:10]) if summ['final'] else 'Not signed')]))
        bill = billing.state(app, a['id'])
        rows = charges.statement_rows(app, a['id'])
        if rows:
            stmt = '\n'.join('%s   %s   %s x Rs %s = Rs %s' % r for r in rows) + '\nTOTAL Rs %s' % sum(r[4] for r in rows)
            if bill['bill']:
                stmt += '\nFinal bill %s · discount Rs %s · payable by scheme / insurer Rs %s · paid by patient Rs %s' % (
                    bill['bill']['bill_no'], bill['discount'], bill['scheme_amount'], bill['paid'])
            z.writestr('06 Charge statement.doc', claim_word(app, staff, c, 'Inpatient charge statement (from the hospital price list)',
                                                              fields[1:3] + fields[9:13], [('Charges', stmt)]))
        z.writestr('03 Details for the portal.txt', '\r\n'.join('%s: %s' % (k, v or '') for k, v in fields).encode('utf-8'))
        for i, l in enumerate(claim_labs(app, c), 1):
            z.write(os.path.join(app.upload_dir, l['file']), '04 Lab %d - %s%s' % (i, safe(l['test']), os.path.splitext(l['file'])[1]))
        for i, d in enumerate(app.q('SELECT item, file FROM claim_docs WHERE claim_id=? ORDER BY id', (cid,)), 1):
            z.write(os.path.join(app.upload_dir, d['file']), '05 %02d %s%s' % (i, safe(d['item']), os.path.splitext(d['file'])[1]))
    app.audit(staff, 'claim.zip', 'claim', cid)
    claimflow.event(app, staff, cid, 'file', 'Claim file downloaded')
    return {'_bytes': buf.getvalue(), '_ctype': 'application/zip', '_name': 'Claim-%s.zip' % a['uhid']}


# ---------- accounts check (compare with Essel; money itself stays in Essel) ----------
@route('GET', r'/api/accounts', ('accounts',))
def accounts(app, staff, p, b):
    day = as_date(p.get('date') or today(), 'Choose the date').isoformat()
    op = app.q("SELECT d.name dept, COUNT(v.id) patients, COALESCE(SUM(v.source='walkin'), 0) walkin, COALESCE(SUM(v.source='phone'), 0) phone, "
               "COALESCE(SUM(CASE WHEN v.status<>'skipped' THEN v.fee_shown ELSE 0 END), 0) expected, COALESCE(SUM(v.status='skipped'), 0) skipped "
               "FROM departments d JOIN visits v ON v.dept_id=d.id AND v.visit_date=? GROUP BY d.id ORDER BY d.id", (day,))
    adm = app.q("SELECT a.id, b.label bed, p.name, a.payer, a.deposit_noted FROM admissions a JOIN beds b ON b.id=a.bed_id "
                "JOIN patients p ON p.id=a.patient_id WHERE substr(a.admitted_at, 1, 10)=? ORDER BY a.id", (day,))
    dis = app.q("SELECT a.id, b.label bed, p.name, a.payer, (SELECT done_by FROM discharge_steps s WHERE s.admission_id=a.id AND s.step='bill') bill_by "
                "FROM admissions a JOIN beds b ON b.id=a.bed_id JOIN patients p ON p.id=a.patient_id WHERE substr(a.discharged_at, 1, 10)=? ORDER BY a.id", (day,))
    services = app.one("SELECT COUNT(*) n, COALESCE(SUM(billed), 0) billed, COALESCE(SUM(amount), 0) amount, "
                       "COALESCE(SUM(CASE WHEN billed=0 THEN amount ELSE 0 END), 0) unbilled FROM ip_charges "
                       "WHERE cancelled=0 AND COALESCE(for_date, substr(entered_at, 1, 10))=?", (day,))
    ip = billing.money_day(app, day)
    import pharmsale
    pharm = pharmsale.day_totals(app, day)
    y, mo, days = int(day[:4]), int(day[5:7]), calendar.monthrange(int(day[:4]), int(day[5:7]))[1]
    pay = payouts(app, staff, {'month': day[:7]}, {})['rows']
    sal = payroll_rows(app, y, mo, days)
    month_fees = app.one("SELECT COALESCE(SUM(fee_shown), 0) n, COUNT(*) c FROM visits WHERE visit_date LIKE ? AND status<>'skipped'", (day[:7] + '%',))
    app.audit(staff, 'accounts.view', None, None, {'day': day})
    return {'date': day, 'op': op, 'admissions': adm, 'discharges': dis, 'services': services, 'ip': ip, 'pharm': pharm,
            'essel_pending': app.one('SELECT COUNT(*) n FROM visits WHERE visit_date=? AND essel_done=0', (day,))['n'],
            'month': {'fees': month_fees['n'], 'visits': month_fees['c'], 'payouts': sum(r['amount'] for r in pay),
                      'salary_net': sum(r['net'] for r in sal), 'salary_people': len(sal)},
            'check': app.one('SELECT * FROM accounts_checks WHERE day=?', (day,)),
            'recent': app.q('SELECT * FROM accounts_checks ORDER BY day DESC LIMIT 14')}


@route('POST', r'/api/accounts/check', ('accounts',))
def accounts_check(app, staff, p, b):
    day = as_date(b.get('date'), 'Choose the date').isoformat()
    result = b.get('result')
    if result not in ('matched', 'difference'):
        raise ApiError(400, 'Choose matched or difference')
    if result == 'difference' and not clean(b.get('note')):
        raise ApiError(400, 'Write what the difference is')
    with app.tx():
        app.run('INSERT OR REPLACE INTO accounts_checks(day, result, note, checked_by, at) VALUES(?,?,?,?,?)',
                (day, result, clean(b.get('note'), 300), staff['name'], now()))
        app.audit(staff, 'accounts.check', None, None, {'day': day, 'result': result})
    return {'ok': True}
