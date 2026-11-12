"""Sunrise Hospital operations layer: database and all business rules.

No web code lives here, so every rule can be tested directly (see tests/).
Uses only the Python standard library, so there is nothing to install.
"""
import contextlib
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.parse
import urllib.request

ROLES = ('owner', 'doctor', 'consultant', 'reception', 'nurse', 'pharmacy', 'insurance', 'lab', 'support')
DESK = ('owner', 'reception')
DOCS = ('doctor', 'consultant')
VISIT_STATES = ('waiting', 'called', 'done', 'skipped')
DOCTOR_STATES = ('in', 'delayed', 'surgery', 'out')
BED_STATES = ('vacant', 'occupied', 'cleaning', 'reserved')
TOPICS = ('summary', 'ip', 'doctor', 'lab', 'pharmacy')
IMAGE_TYPES = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS departments(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, name_te TEXT DEFAULT '',
  fee_walkin INTEGER DEFAULT 0, fee_phone INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS doctors(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, dept_id INTEGER NOT NULL REFERENCES departments(id),
  kind TEXT NOT NULL DEFAULT 'consultant', status TEXT NOT NULL DEFAULT 'out', status_note TEXT DEFAULT '',
  active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS staff(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, pin_salt TEXT, pin_hash TEXT,
  doctor_id INTEGER REFERENCES doctors(id), active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS patients(
  id INTEGER PRIMARY KEY, uhid TEXT UNIQUE, name TEXT NOT NULL, dob TEXT, age_y INTEGER, age_m INTEGER,
  age_on TEXT, sex TEXT, phone TEXT, guardian TEXT, area TEXT, referral TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_patient_phone ON patients(phone);
CREATE TABLE IF NOT EXISTS visits(
  id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id),
  dept_id INTEGER NOT NULL REFERENCES departments(id), doctor_id INTEGER REFERENCES doctors(id),
  visit_date TEXT NOT NULL, source TEXT NOT NULL, token_no INTEGER NOT NULL, token_code TEXT NOT NULL,
  fee_shown INTEGER, status TEXT NOT NULL DEFAULT 'waiting', created_at TEXT, called_at TEXT, done_at TEXT,
  created_by INTEGER, essel_done INTEGER DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS ux_token ON visits(dept_id, visit_date, token_no);
CREATE INDEX IF NOT EXISTS ix_visit_date ON visits(visit_date);
CREATE TABLE IF NOT EXISTS appointments(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT, dept_id INTEGER NOT NULL REFERENCES departments(id),
  doctor_id INTEGER REFERENCES doctors(id), appt_date TEXT NOT NULL, appt_time TEXT, note TEXT,
  status TEXT NOT NULL DEFAULT 'booked', visit_id INTEGER, created_at TEXT, created_by INTEGER);
CREATE TABLE IF NOT EXISTS beds(
  id INTEGER PRIMARY KEY, ward TEXT NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'vacant',
  note TEXT DEFAULT '', active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS admissions(
  id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id),
  bed_id INTEGER NOT NULL REFERENCES beds(id), doctor_id INTEGER REFERENCES doctors(id),
  admitted_at TEXT, diagnosis TEXT, procedure TEXT, payer TEXT, attendant_name TEXT, attendant_phone TEXT,
  expected_days INTEGER, deposit_noted INTEGER, discharged_at TEXT, status TEXT NOT NULL DEFAULT 'admitted');
CREATE TABLE IF NOT EXISTS prescriptions(
  id INTEGER PRIMARY KEY, visit_id INTEGER NOT NULL REFERENCES visits(id),
  patient_id INTEGER NOT NULL REFERENCES patients(id), file TEXT NOT NULL, ctype TEXT NOT NULL,
  uploaded_by INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS notify_targets(
  id INTEGER PRIMARY KEY, label TEXT NOT NULL, chat_id TEXT NOT NULL, topics TEXT DEFAULT 'summary',
  dept_ids TEXT DEFAULT '', active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY, chat_id TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT, sent_at TEXT,
  tries INTEGER DEFAULT 0, error TEXT);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, staff_id INTEGER, staff_name TEXT, action TEXT NOT NULL,
  entity TEXT, entity_id INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY, staff_id INTEGER NOT NULL, created_at TEXT, last_seen REAL, expires REAL, remember INTEGER);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit log cannot be changed'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit log cannot be changed'); END;
"""


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def today():
    return datetime.date.today().isoformat()


def hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac('sha256', str(pin).encode(), bytes.fromhex(salt), 100000).hex()


def age_text(p):
    """Age as shown to staff: '8m', '3y 4m', '34y'. Grows with time."""
    td = datetime.date.today()
    try:
        if p.get('dob'):
            d = datetime.date.fromisoformat(p['dob'])
            months = (td.year - d.year) * 12 + td.month - d.month - (1 if td.day < d.day else 0)
        elif p.get('age_on') and (p.get('age_y') is not None or p.get('age_m') is not None):
            d = datetime.date.fromisoformat(p['age_on'])
            months = (p.get('age_y') or 0) * 12 + (p.get('age_m') or 0)
            months += (td.year - d.year) * 12 + td.month - d.month - (1 if td.day < d.day else 0)
        else:
            return ''
    except ValueError:
        return ''
    months = max(months, 0)
    y, m = divmod(months, 12)
    if y >= 5:
        return '%dy' % y
    if y >= 1:
        return '%dy %dm' % (y, m) if m else '%dy' % y
    return '%dm' % m if m else 'Newborn'


def clean(value, limit=120):
    return str(value or '').strip()[:limit]


def to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


ROUTES = []


def route(method, pattern, screens):
    """screens: None = no login needed, '*' = any login, or a tuple of screens (any one of them is enough).
    Who has which screen is decided in access.py."""
    def wrap(fn):
        ROUTES.append((method, re.compile(pattern), fn, screens))
        return fn
    return wrap


class App:
    def __init__(self, data_dir, demo=True):
        self.data_dir = data_dir
        self.upload_dir = os.path.join(data_dir, 'prescriptions')
        self.backup_dir = os.path.join(data_dir, 'backups')
        for d in (data_dir, self.upload_dir, self.backup_dir):
            os.makedirs(d, exist_ok=True)
        self.db_path = os.path.join(data_dir, 'sunrise.db')
        self.db = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.lock = threading.RLock()
        self.sender = self.telegram_send
        with self.lock:
            self.db.executescript(SCHEMA + more.SCHEMA + charges.SCHEMA + billing.SCHEMA + pharmsale.SCHEMA + claimflow.SCHEMA)
        more.migrate(self)
        claimflow.migrate(self)
        patienttoken.migrate(self)
        if not self.one('SELECT id FROM staff LIMIT 1'):
            import seed
            seed.run(self, demo)
        more.seed(self)
        charges.seed(self)
        if self.setting('demo') == '1':
            pharmsale.demo(self)
            claimflow.seed_demo(self)
        patienttoken.migrate(self)   # codes for any visits created above

    # ---------- database helpers ----------
    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def run(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).lastrowid

    @contextlib.contextmanager
    def tx(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def audit(self, staff, action, entity=None, entity_id=None, detail=None):
        """Who did what and when. Details hold ids and field names, not patient data."""
        self.run('INSERT INTO audit_log(at, staff_id, staff_name, action, entity, entity_id, detail) VALUES(?,?,?,?,?,?,?)',
                 (now(), staff['id'] if staff else None, staff['name'] if staff else 'system', action, entity,
                  entity_id, json.dumps(detail) if detail else None))

    def setting(self, key, default=''):
        r = self.one('SELECT value FROM settings WHERE key=?', (key,))
        return r['value'] if r and r['value'] is not None else default

    def set_setting(self, key, value):
        self.run('INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                 (key, value))

    # ---------- sessions and permissions (details in access.py) ----------
    def staff_for(self, token):
        return access.staff_for(self, token)

    def allowed(self, staff, *screens):
        return access.allowed(self, staff, *screens)

    def handle(self, method, path, params, body, staff, token=None):
        for m, rx, fn, screens in ROUTES:
            if m != method:
                continue
            match = rx.fullmatch(path)
            if not match:
                continue
            staff = dict(staff) if staff else None
            access.check(self, staff, screens, fn)
            body = dict(body or {})
            body['_token'] = token
            return fn(self, staff, params or {}, body, *[int(g) for g in match.groups()])
        raise ApiError(404, 'Not found')

    @route('GET', r'/api/bootstrap', '*')
    def bootstrap(self, staff, p, b):
        more.daily_reset(self)
        me = dict(staff, screens=access.screens_of(self, staff), role_name=access.ROLE_NAMES.get(staff['role']))
        return {
            'me': me,
            'departments': self.q('SELECT * FROM departments WHERE active=1 ORDER BY id'),
            'doctors': self.q('SELECT id, name, dept_id, kind, status, status_note FROM doctors WHERE active=1 ORDER BY id'),
            'hospital': self.setting('hospital_name', 'Sunrise Hospital'),
            'address': self.setting('hospital_addr'),
            'token_print': self.setting('token_print', '1') == '1', 'token_base': patienttoken.base_url(self),
            'areas': [r['area'] for r in self.q(
                "SELECT area, COUNT(*) n FROM patients WHERE area<>'' GROUP BY area ORDER BY n DESC LIMIT 60")],
        }

    # ---------- patients ----------
    def patient_out(self, p):
        p = dict(p)
        p['age'] = age_text(p)
        return p

    @route('GET', r'/api/patients', ('desk', 'admit', 'records'))
    def search_patients(self, staff, p, b):
        text = clean(p.get('q'))
        if len(text) < 2:
            return {'patients': []}
        digits = re.sub(r'\D', '', text)
        if digits and len(digits) >= 3 and digits == text.replace(' ', ''):
            rows = self.q('SELECT * FROM patients WHERE phone LIKE ? ORDER BY id DESC LIMIT 20', (digits + '%',))
        elif text.upper().startswith('HH'):
            rows = self.q('SELECT * FROM patients WHERE uhid LIKE ? ORDER BY id DESC LIMIT 20', (text.upper() + '%',))
        else:
            rows = self.q('SELECT * FROM patients WHERE name LIKE ? ORDER BY name LIMIT 20', ('%' + text + '%',))
        out = [self.patient_out(r) for r in rows]
        for r in out:   # so reception sees at once that this is a returning patient
            last = self.one('SELECT v.visit_date, dr.name doctor FROM visits v LEFT JOIN doctors dr ON dr.id=v.doctor_id '
                            'WHERE v.patient_id=? ORDER BY v.visit_date DESC, v.id DESC LIMIT 1', (r['id'],))
            r['last_visit'], r['last_doctor'] = (last['visit_date'], last['doctor']) if last else (None, None)
            r['visit_count'] = self.one('SELECT COUNT(*) n FROM visits WHERE patient_id=?', (r['id'],))['n']
        return {'patients': out}

    def patient_fields(self, b):
        name = clean(b.get('name'))
        if len(name) < 2:
            raise ApiError(400, 'Enter the patient name')
        sex = clean(b.get('sex'), 1).upper()
        if sex not in ('M', 'F', 'O'):
            raise ApiError(400, 'Choose male, female or other')
        phone = re.sub(r'\D', '', str(b.get('phone') or ''))
        if phone and len(phone) != 10:
            raise ApiError(400, 'Phone number must be 10 digits')
        dob = clean(b.get('dob'), 10) or None
        if dob:
            try:
                if datetime.date.fromisoformat(dob) > datetime.date.today():
                    raise ValueError
            except ValueError:
                raise ApiError(400, 'Date of birth is not valid')
        age_y, age_m = to_int(b.get('age_y')), to_int(b.get('age_m'))
        if not dob and age_y is None and age_m is None:
            raise ApiError(400, 'Enter the age or date of birth')
        if (age_y is not None and not 0 <= age_y <= 120) or (age_m is not None and not 0 <= age_m <= 11):
            raise ApiError(400, 'Age is not valid')
        return {'name': name, 'sex': sex, 'phone': phone, 'dob': dob, 'age_y': age_y, 'age_m': age_m,
                'guardian': clean(b.get('guardian')), 'area': clean(b.get('area')), 'referral': clean(b.get('referral'))}

    @route('POST', r'/api/patients', ('desk',))
    def create_patient(self, staff, p, b):
        f = self.patient_fields(b)
        with self.tx():
            pid = self.run(
                'INSERT INTO patients(name, sex, phone, dob, age_y, age_m, age_on, guardian, area, referral, created_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (f['name'], f['sex'], f['phone'], f['dob'], f['age_y'], f['age_m'], today(), f['guardian'],
                 f['area'], f['referral'], now()))
            uhid = 'HH-%06d' % pid
            self.run('UPDATE patients SET uhid=? WHERE id=?', (uhid, pid))
            self.audit(staff, 'patient.create', 'patient', pid, {'uhid': uhid})
        return {'patient': self.patient_out(self.one('SELECT * FROM patients WHERE id=?', (pid,)))}

    @route('PUT', r'/api/patients/(\d+)', ('desk',))
    def update_patient(self, staff, p, b, pid):
        old = self.one('SELECT * FROM patients WHERE id=?', (pid,))
        if not old:
            raise ApiError(404, 'Patient not found')
        f = self.patient_fields(b)
        changed = [k for k in f if (f[k] or None) != (old[k] or None)]
        if changed:
            with self.tx():
                self.run('UPDATE patients SET name=?, sex=?, phone=?, dob=?, age_y=?, age_m=?, guardian=?, area=?, referral=? WHERE id=?',
                         (f['name'], f['sex'], f['phone'], f['dob'], f['age_y'], f['age_m'], f['guardian'], f['area'],
                          f['referral'], pid))
                if 'age_y' in changed or 'age_m' in changed:
                    self.run('UPDATE patients SET age_on=? WHERE id=?', (today(), pid))
                self.audit(staff, 'patient.update', 'patient', pid, {'fields': changed})
        return {'patient': self.patient_out(self.one('SELECT * FROM patients WHERE id=?', (pid,)))}

    def doctor_has_patient(self, staff, pid):
        return bool(self.one(
            'SELECT 1 x FROM visits WHERE patient_id=? AND doctor_id=? UNION '
            "SELECT 1 FROM admissions WHERE patient_id=? AND doctor_id=?",
            (pid, staff['doctor_id'], pid, staff['doctor_id'])))

    @route('GET', r'/api/patients/(\d+)', ('records',))
    def get_patient(self, staff, p, b, pid):
        pat = self.one('SELECT * FROM patients WHERE id=?', (pid,))
        if not pat:
            raise ApiError(404, 'Patient not found')
        role = staff['role']
        if role in DOCS and not self.doctor_has_patient(staff, pid):
            self.audit(staff, 'patient.denied', 'patient', pid)
            raise ApiError(403, 'This is not your patient')
        # A visiting consultant sees only their own visits; the in-house doctor sees the full history.
        only = ' AND v.doctor_id=%d' % staff['doctor_id'] if role == 'consultant' else ''
        visits = self.q(
            'SELECT v.id, v.visit_date, v.token_code, v.status, v.source, v.doctor_id, d.name dept, dr.name doctor '
            'FROM visits v JOIN departments d ON d.id=v.dept_id LEFT JOIN doctors dr ON dr.id=v.doctor_id '
            'WHERE v.patient_id=?' + only + ' ORDER BY v.id DESC', (pid,))
        rx = self.q('SELECT r.id, r.visit_id, r.created_at, v.visit_date, v.doctor_id FROM prescriptions r JOIN visits v ON v.id=r.visit_id '
                    'WHERE r.patient_id=?' + only + ' ORDER BY r.id', (pid,))
        adm = self.q(
            'SELECT a.id, a.admitted_at, a.discharged_at, a.status, a.diagnosis, a.procedure, a.payer, b.label bed, '
            '(SELECT final FROM discharge_summaries s WHERE s.admission_id=a.id) signed, '
            'dr.name doctor FROM admissions a JOIN beds b ON b.id=a.bed_id LEFT JOIN doctors dr ON dr.id=a.doctor_id '
            'WHERE a.patient_id=?' + (' AND a.doctor_id=%d' % staff['doctor_id'] if role == 'consultant' else '') +
            ' ORDER BY a.id DESC', (pid,))
        self.audit(staff, 'patient.view', 'patient', pid)
        out = {'patient': self.patient_out(pat), 'visits': visits, 'prescriptions': rx, 'admissions': adm}
        out.update(more.patient_extra(self, staff, pid))
        return out

    # ---------- OP visits and tokens ----------
    @route('POST', r'/api/visits', ('desk',))
    def create_visit(self, staff, p, b):
        pid, dept_id = to_int(b.get('patient_id')), to_int(b.get('dept_id'))
        doctor_id, appt_id = to_int(b.get('doctor_id')), to_int(b.get('appointment_id'))
        source = b.get('source')
        if source not in ('walkin', 'phone'):
            raise ApiError(400, 'Choose walk-in or phone booking')
        dept = self.one('SELECT * FROM departments WHERE id=? AND active=1', (dept_id,))
        if not dept:
            raise ApiError(400, 'Choose a department')
        if not self.one('SELECT id FROM patients WHERE id=?', (pid,)):
            raise ApiError(400, 'Choose a patient')
        if doctor_id and not self.one('SELECT id FROM doctors WHERE id=? AND dept_id=? AND active=1', (doctor_id, dept_id)):
            raise ApiError(400, 'That doctor is not in this department')
        day = today()
        with self.tx():
            dup = self.one("SELECT token_code FROM visits WHERE patient_id=? AND dept_id=? AND visit_date=? "
                           "AND status IN ('waiting','called')", (pid, dept_id, day))
            if dup:
                raise ApiError(409, 'This patient already has token %s today' % dup['token_code'])
            # A phone booking keeps the number it was given on the phone, so booked patients come before later walk-ins.
            appt = self.one("SELECT * FROM appointments WHERE id=? AND status='booked'", (appt_id,)) if appt_id else None
            n, late = None, False
            if appt and appt['appt_time']:
                grace = to_int(self.setting('booking_grace', '30'), 30)
                try:
                    late = datetime.datetime.now() > datetime.datetime.fromisoformat(appt['appt_date'] + 'T' + appt['appt_time']) + datetime.timedelta(minutes=grace)
                except ValueError:
                    late = False
            if appt and not late and appt['token_no'] and appt['appt_date'] == day and appt['dept_id'] == dept_id and \
                    not self.one('SELECT id FROM visits WHERE dept_id=? AND visit_date=? AND token_no=?', (dept_id, day, appt['token_no'])):
                n = appt['token_no']
            if n is None:
                n = patienttoken.next_token(self, dept_id, day)
            code = '%s-%02d' % (dept['code'], n)
            fee = dept['fee_phone'] if source == 'phone' else dept['fee_walkin']
            vid = self.run(
                'INSERT INTO visits(patient_id, dept_id, doctor_id, visit_date, source, token_no, token_code, fee_shown, '
                'created_at, created_by, public_code) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (pid, dept_id, doctor_id, day, source, n, code, fee, now(), staff['id'], patienttoken.new_code()))
            if appt_id:
                self.run("UPDATE appointments SET status='arrived', visit_id=? WHERE id=?", (vid, appt_id))
            self.audit(staff, 'visit.create', 'visit', vid, {'token': code, 'source': source})
        if late:
            self.audit(staff, 'visit.booking_late', 'visit', vid, {'booked': appt['token_code']})
        v = self.one(
            'SELECT v.*, p.name, p.uhid, d.name dept, d.name_te dept_te, dr.name doctor FROM visits v '
            'JOIN patients p ON p.id=v.patient_id JOIN departments d ON d.id=v.dept_id '
            'LEFT JOIN doctors dr ON dr.id=v.doctor_id WHERE v.id=?', (vid,))
        return {'visit': v, 'late_booking': appt['token_code'] if late else None}

    @route('GET', r'/api/queue', ('queue', 'desk', 'essel', 'rx', 'myday'))
    def queue(self, staff, p, b):
        day = clean(p.get('date'), 10) or today()
        sql = ('SELECT v.id, v.token_code, v.token_no, v.status, v.source, v.created_at, v.called_at, v.dept_id, '
               'v.doctor_id, v.essel_done, v.fee_shown, v.bought, v.not_bought_reason, p.id patient_id, p.name, p.uhid, p.sex, p.dob, p.age_y, '
               'p.age_m, p.age_on, p.phone, p.area, p.guardian, p.referral, '
               '(SELECT GROUP_CONCAT(r.id) FROM prescriptions r WHERE r.visit_id=v.id) rx, '
               '(SELECT COUNT(*) FROM visits o WHERE o.patient_id=v.patient_id AND o.visit_date<v.visit_date) prev_visits, '
               '(SELECT MAX(o.visit_date) FROM visits o WHERE o.patient_id=v.patient_id AND o.visit_date<v.visit_date) last_visit '
               'FROM visits v JOIN patients p ON p.id=v.patient_id WHERE v.visit_date=?')
        args = [day]
        if staff['role'] in DOCS:
            sql += ' AND v.doctor_id=?'
            args.append(staff['doctor_id'])
        rows = self.q(sql + ' ORDER BY v.dept_id, v.token_no', args)
        booked = []
        if self.allowed(staff, 'desk', 'queue', 'appointments'):
            booked = self.q("SELECT id, dept_id, token_code, token_no, appt_time, name FROM appointments WHERE appt_date=? AND status='booked' AND token_no IS NOT NULL "
                            "ORDER BY dept_id, token_no", (day,))
        for r in rows:
            r['age'] = age_text(r)
            r['rx'] = [int(x) for x in str(r['rx'] or '').split(',') if x]
            for k in ('dob', 'age_y', 'age_m', 'age_on'):
                r.pop(k)
            if not self.allowed(staff, 'desk', 'essel', 'accounts'):
                for k in ('fee_shown', 'phone', 'area', 'guardian', 'referral'):
                    r.pop(k)
        return {'visits': rows, 'date': day, 'booked_not_arrived': booked}

    def visit_for(self, staff, vid):
        v = self.one('SELECT * FROM visits WHERE id=?', (vid,))
        if not v:
            raise ApiError(404, 'Visit not found')
        if staff['role'] in DOCS and v['doctor_id'] != staff['doctor_id']:
            raise ApiError(403, 'This is not your patient')
        return v

    @route('POST', r'/api/visits/(\d+)/status', ('queue',))
    def visit_status(self, staff, p, b, vid):
        v = self.visit_for(staff, vid)
        status = b.get('status')
        if status not in VISIT_STATES:
            raise ApiError(400, 'Unknown status')
        with self.tx():
            self.run('UPDATE visits SET status=?, called_at=CASE WHEN ?=\'called\' THEN ? ELSE called_at END, '
                     'done_at=CASE WHEN ?=\'done\' THEN ? ELSE done_at END WHERE id=?',
                     (status, status, now(), status, now(), vid))
            self.audit(staff, 'visit.status', 'visit', vid, {'from': v['status'], 'to': status})
        return {'ok': True}

    @route('POST', r'/api/visits/(\d+)/essel', ('essel',))
    def visit_essel(self, staff, p, b, vid):
        self.visit_for(staff, vid)
        done = 1 if b.get('done') else 0
        with self.tx():
            self.run('UPDATE visits SET essel_done=? WHERE id=?', (done, vid))
            self.audit(staff, 'visit.essel', 'visit', vid, {'done': done})
        return {'ok': True}

    # ---------- paper prescriptions (photo only, never typed) ----------
    @route('POST', r'/api/visits/(\d+)/prescription', ('queue', 'rx', 'records'))
    def add_prescription(self, staff, p, b, vid):
        v = self.visit_for(staff, vid)
        if not self.allowed(staff, 'records', 'queue') and v['visit_date'] != today():
            raise ApiError(403, 'Only today\'s visits')
        ext = IMAGE_TYPES.get(b.get('_ctype'))
        raw = b.get('_raw')
        if not ext or not raw:
            raise ApiError(400, 'Send a photo (JPG or PNG)')
        name = secrets.token_hex(16) + ext
        with open(os.path.join(self.upload_dir, name), 'wb') as fh:
            fh.write(raw)
        with self.tx():
            rid = self.run('INSERT INTO prescriptions(visit_id, patient_id, file, ctype, uploaded_by, created_at) '
                           'VALUES(?,?,?,?,?,?)', (vid, v['patient_id'], name, b['_ctype'], staff['id'], now()))
            if v['status'] in ('waiting', 'called'):  # a prescription means the doctor has seen them
                self.run("UPDATE visits SET status='done', done_at=? WHERE id=?", (now(), vid))
            self.audit(staff, 'prescription.add', 'visit', vid, {'prescription': rid})
        return {'id': rid}

    @route('GET', r'/files/rx/(\d+)', ('queue', 'rx', 'records'))
    def prescription_file(self, staff, p, b, rid):
        r = self.one('SELECT r.*, v.doctor_id, v.visit_date FROM prescriptions r JOIN visits v ON v.id=r.visit_id '
                     'WHERE r.id=?', (rid,))
        if not r:
            raise ApiError(404, 'Not found')
        role = staff['role']
        if role == 'consultant':
            allowed = r['doctor_id'] == staff['doctor_id']
        elif role == 'doctor':
            allowed = self.doctor_has_patient(staff, r['patient_id'])
        else:
            allowed = self.allowed(staff, 'records', 'queue') or r['visit_date'] == today()
        if not allowed:
            self.audit(staff, 'prescription.denied', 'prescription', rid)
            raise ApiError(403, 'This is not your patient')
        return {'_file': os.path.join(self.upload_dir, r['file']), '_ctype': r['ctype']}

    # ---------- appointments ----------
    @route('GET', r'/api/appointments', ('appointments',))
    def list_appointments(self, staff, p, b):
        day = clean(p.get('date'), 10) or today()
        return {'date': day, 'appointments': self.q(
            'SELECT a.*, v.token_code visit_token FROM appointments a LEFT JOIN visits v ON v.id=a.visit_id '
            'WHERE a.appt_date=? ORDER BY a.appt_time, a.id', (day,))}

    @route('POST', r'/api/appointments', ('appointments',))
    def create_appointment(self, staff, p, b):
        name, phone = clean(b.get('name')), re.sub(r'\D', '', str(b.get('phone') or ''))
        dept_id, doctor_id = to_int(b.get('dept_id')), to_int(b.get('doctor_id'))
        day, tm = clean(b.get('appt_date'), 10), clean(b.get('appt_time'), 5)
        if len(name) < 2:
            raise ApiError(400, 'Enter the patient name')
        if len(phone) != 10:
            raise ApiError(400, 'Phone number must be 10 digits')
        if not self.one('SELECT id FROM departments WHERE id=? AND active=1', (dept_id,)):
            raise ApiError(400, 'Choose a department')
        try:
            if datetime.date.fromisoformat(day) < datetime.date.today():
                raise ApiError(400, 'Date is in the past')
        except ValueError:
            raise ApiError(400, 'Choose a date')
        with self.tx():
            n = patienttoken.next_token(self, dept_id, day)       # reserve the token number now; tell the caller
            code = '%s-%02d' % (self.one('SELECT code FROM departments WHERE id=?', (dept_id,))['code'], n)
            aid = self.run('INSERT INTO appointments(name, phone, dept_id, doctor_id, appt_date, appt_time, note, '
                           'created_at, created_by, token_no, token_code) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (name, phone, dept_id, doctor_id, day, tm, clean(b.get('note'), 200), now(), staff['id'], n, code))
            self.audit(staff, 'appointment.create', 'appointment', aid, {'token': code})
        return {'id': aid, 'token_code': code}

    @route('POST', r'/api/appointments/(\d+)/status', ('appointments',))
    def appointment_status(self, staff, p, b, aid):
        status = b.get('status')
        if status not in ('booked', 'cancelled', 'noshow'):
            raise ApiError(400, 'Unknown status')
        a = self.one('SELECT * FROM appointments WHERE id=?', (aid,))
        if not a:
            raise ApiError(404, 'Not found')
        if a['status'] == 'arrived':
            raise ApiError(409, 'A token was already given for this booking')
        with self.tx():
            self.run('UPDATE appointments SET status=? WHERE id=?', (status, aid))
            self.audit(staff, 'appointment.status', 'appointment', aid, {'from': a['status'], 'to': status})
        return {'ok': True}

    # ---------- doctors ----------
    @route('POST', r'/api/doctors/(\d+)/status', ('queue', 'doctors', 'myday'))
    def doctor_status(self, staff, p, b, did):
        if staff['role'] in DOCS and staff['doctor_id'] != did:
            raise ApiError(403, 'You can change only your own status')
        status = b.get('status')
        if status not in DOCTOR_STATES:
            raise ApiError(400, 'Unknown status')
        d = self.one('SELECT d.*, dep.name dept FROM doctors d JOIN departments dep ON dep.id=d.dept_id WHERE d.id=?', (did,))
        if not d:
            raise ApiError(404, 'Doctor not found')
        note = clean(b.get('note'), 80)
        with self.tx():
            self.run('UPDATE doctors SET status=?, status_note=? WHERE id=?', (status, note, did))
            self.audit(staff, 'doctor.status', 'doctor', did, {'from': d['status'], 'to': status})
            more.doctor_day(self, did, status, staff)
        if status != d['status']:
            words = {'in': 'In', 'delayed': 'Delayed', 'surgery': 'In surgery', 'out': 'Not in'}
            self.notify('doctor', '%s (%s): %s%s' % (d['name'], d['dept'], words[status], ' - ' + note if note else ''),
                        d['dept_id'])
        return {'ok': True}

    # ---------- beds and admissions ----------
    @route('GET', r'/api/beds', ('beds',))
    def beds(self, staff, p, b):
        rows = self.q(
            "SELECT b.id, b.ward, b.label, b.status, b.note, a.id admission_id, a.patient_id, a.doctor_id, "
            "a.admitted_at, a.discharge_ordered_at, a.diagnosis, a.procedure, a.payer, a.expected_days, a.attendant_name, a.attendant_phone, "
            "a.deposit_noted, p.name patient, p.uhid, p.sex, p.dob, p.age_y, p.age_m, p.age_on, dr.name doctor "
            "FROM beds b LEFT JOIN admissions a ON a.bed_id=b.id AND a.status='admitted' "
            "LEFT JOIN patients p ON p.id=a.patient_id LEFT JOIN doctors dr ON dr.id=a.doctor_id "
            "WHERE b.active=1 ORDER BY b.id")
        private = ('patient_id', 'patient', 'uhid', 'sex', 'age', 'diagnosis', 'procedure', 'payer',
                   'attendant_name', 'attendant_phone', 'deposit_noted', 'admission_id')
        for r in rows:
            r['age'] = age_text(r) if r['patient'] else ''
            for k in ('dob', 'age_y', 'age_m', 'age_on'):
                r.pop(k)
            if staff['role'] == 'consultant' and r['admission_id'] and r['doctor_id'] != staff['doctor_id']:
                for k in private:
                    r[k] = None
            if not self.allowed(staff, 'ipbill', 'accounts'):
                r['deposit_noted'] = None
        return {'beds': rows}

    @route('POST', r'/api/beds/(\d+)/status', ('ward',))
    def bed_status(self, staff, p, b, bid):
        bed = self.one('SELECT * FROM beds WHERE id=? AND active=1', (bid,))
        status = b.get('status')
        if not bed:
            raise ApiError(404, 'Bed not found')
        if status not in ('vacant', 'cleaning', 'reserved'):
            raise ApiError(400, 'Unknown status')
        if bed['status'] == 'occupied':
            raise ApiError(409, 'Discharge the patient first')
        with self.tx():
            self.run('UPDATE beds SET status=?, note=? WHERE id=?', (status, clean(b.get('note'), 80), bid))
            self.audit(staff, 'bed.status', 'bed', bid, {'from': bed['status'], 'to': status})
        return {'ok': True}

    def bed_counts(self):
        c = {s: 0 for s in BED_STATES}
        for r in self.q('SELECT status, COUNT(*) n FROM beds WHERE active=1 GROUP BY status'):
            c[r['status']] = r['n']
        c['total'] = sum(c[s] for s in BED_STATES)
        return c

    @route('POST', r'/api/admissions', ('admit',))
    def admit(self, staff, p, b):
        pid, bid, did = to_int(b.get('patient_id')), to_int(b.get('bed_id')), to_int(b.get('doctor_id'))
        if not self.one('SELECT id FROM patients WHERE id=?', (pid,)):
            raise ApiError(400, 'Choose a patient')
        if not self.one('SELECT id FROM doctors WHERE id=? AND active=1', (did,)):
            raise ApiError(400, 'Choose the admitting doctor')
        with self.tx():
            bed = self.one('SELECT * FROM beds WHERE id=? AND active=1', (bid,))
            if not bed:
                raise ApiError(404, 'Bed not found')
            if bed['status'] == 'occupied':
                raise ApiError(409, 'This bed is already occupied')
            if self.one("SELECT id FROM admissions WHERE patient_id=? AND status='admitted'", (pid,)):
                raise ApiError(409, 'This patient is already admitted')
            aid = self.run(
                'INSERT INTO admissions(patient_id, bed_id, doctor_id, admitted_at, diagnosis, procedure, payer, '
                'attendant_name, attendant_phone, expected_days, deposit_noted) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (pid, bid, did, now(), clean(b.get('diagnosis'), 200), clean(b.get('procedure'), 200),
                 clean(b.get('payer'), 40) or 'Cash', clean(b.get('attendant_name')),
                 re.sub(r'\D', '', str(b.get('attendant_phone') or ''))[:10], to_int(b.get('expected_days')),
                 to_int(b.get('deposit_noted'))))
            self.run("UPDATE beds SET status='occupied', note='' WHERE id=?", (bid,))
            self.audit(staff, 'admission.create', 'admission', aid, {'bed': bed['label']})
            receipt = None
            if to_int(b.get('deposit_noted')):
                if not self.allowed(staff, 'ipbill'):
                    raise ApiError(403, 'Your login cannot take money. Leave the advance empty and send them to the billing desk.')
                receipt = billing.record_payment(self, staff, aid, 'advance', b.get('deposit_noted'), b.get('deposit_mode') or 'Cash', b.get('deposit_ref'))[1]
            more.after_admit(self, aid)
        dr = self.one('SELECT name, dept_id FROM doctors WHERE id=?', (did,))
        c = self.bed_counts()
        self.notify('ip', 'Admission: bed %s (%s), under %s.\nBeds occupied: %d of %d.' % (
            bed['label'], bed['ward'], dr['name'], c['occupied'], c['total']), dr['dept_id'])
        return {'id': aid, 'receipt_no': receipt}

    @route('POST', r'/api/admissions/(\d+)/discharge', ('ward',))
    def discharge(self, staff, p, b, aid):
        with self.tx():
            a = self.one("SELECT a.*, b.label, b.ward FROM admissions a JOIN beds b ON b.id=a.bed_id "
                         "WHERE a.id=? AND a.status='admitted'", (aid,))
            if not a:
                raise ApiError(404, 'Admission not found')
            self.run("UPDATE admissions SET status='discharged', discharged_at=? WHERE id=?", (now(), aid))
            self.run("UPDATE beds SET status='cleaning' WHERE id=?", (a['bed_id'],))
            self.audit(staff, 'admission.discharge', 'admission', aid, {'bed': a['label']})
        dr = self.one('SELECT dept_id FROM doctors WHERE id=?', (a['doctor_id'],)) or {'dept_id': None}
        c = self.bed_counts()
        self.notify('ip', 'Discharge: bed %s (%s) is now being cleaned.\nBeds occupied: %d of %d.' % (
            a['label'], a['ward'], c['occupied'], c['total']), dr['dept_id'])
        return {'ok': True}

    # ---------- owner dashboard ----------
    def op_by_dept(self, day):
        rows = self.q(
            "SELECT d.id, d.code, d.name, COUNT(v.id) total, "
            "COALESCE(SUM(v.status='waiting'), 0) waiting, COALESCE(SUM(v.status='called'), 0) called, "
            "COALESCE(SUM(v.status='done'), 0) done "
            "FROM departments d LEFT JOIN visits v ON v.dept_id=d.id AND v.visit_date=? "
            "WHERE d.active=1 GROUP BY d.id ORDER BY d.id", (day,))
        return rows

    @route('GET', r'/api/dashboard', ('today',))
    def dashboard(self, staff, p, b):
        day = today()
        return {
            'date': day,
            'op': self.op_by_dept(day),
            'beds': self.bed_counts(),
            'inpatients': [r for r in self.beds(staff, {}, {})['beds'] if r['status'] == 'occupied'],
            'not_ready': self.q("SELECT ward, label, status, note FROM beds WHERE active=1 AND status IN ('cleaning','reserved') ORDER BY id"),
            'appointments': self.one(
                "SELECT COUNT(*) total, COALESCE(SUM(status='booked'), 0) pending, "
                "COALESCE(SUM(status='arrived'), 0) arrived FROM appointments WHERE appt_date=?", (day,)),
            'essel_pending': self.one('SELECT COUNT(*) n FROM visits WHERE essel_done=0 AND visit_date=?', (day,))['n'],
            'unsent': self.one('SELECT COUNT(*) n FROM outbox WHERE sent_at IS NULL AND tries < 20')['n'],
            'more': more.dashboard_extra(self),
        }

    @route('GET', r'/api/display', None)
    def display(self, staff, p, b):
        """Waiting-hall screen. Shows the name beside the token only if the owners switched that on."""
        more.daily_reset(self)
        day = today()
        mode = self.display_mode()
        names = mode != 'token'
        out = []
        for d in self.q('SELECT id, code, name, name_te FROM departments WHERE active=1 ORDER BY id'):
            vs = self.q("SELECT v.token_code, v.token_no, v.status, v.called_at, p.name FROM visits v "
                        "JOIN patients p ON p.id=v.patient_id WHERE v.dept_id=? AND v.visit_date=? "
                        "AND v.status IN ('waiting','called') ORDER BY v.token_no", (d['id'], day))
            if not names:
                for v in vs:
                    v['name'] = None
            called = sorted([v for v in vs if v['status'] == 'called'], key=lambda v: v['called_at'] or '')
            docs = self.q("SELECT name, status, status_note FROM doctors WHERE dept_id=? AND active=1", (d['id'],))
            if not vs and not any(x['status'] != 'out' for x in docs):
                continue
            out.append({'code': d['code'], 'name': d['name'], 'name_te': d['name_te'], 'per': patienttoken.minutes_per_patient(self, d['id']),
                        'now': called[-1] if called else None,
                        'next': [v['token_code'] for v in vs if v['status'] == 'waiting'][:4],
                        'waiting': len([v for v in vs if v['status'] == 'waiting']), 'doctors': docs})
        return {'departments': out, 'hospital': self.setting('hospital_name', 'Sunrise Hospital'), 'mode': mode,
                'casualty': self.setting('casualty_phone'), 'time': now()}

    def display_mode(self):
        """What the waiting-hall TV shows: 'both' (token and name), 'name' (name only) or 'token' (number only)."""
        mode = self.setting('display_mode', '')
        if mode in ('both', 'name', 'token'):
            return mode
        return 'token' if self.setting('display_names', '1') == '0' else 'both'

    # ---------- settings (owners only) ----------
    @route('GET', r'/api/admin/all', ('settings',))
    def admin_all(self, staff, p, b):
        return {
            'departments': self.q('SELECT * FROM departments ORDER BY id'),
            'doctors': self.q('SELECT id, name, dept_id, kind, active, payout_kind, payout_rate, visit_days, visit_time FROM doctors ORDER BY id'),
            'staff': self.q('SELECT id, name, role, doctor_id, active, salary, username, screens, must_change, '
                            '(SELECT MAX(at) FROM audit_log a WHERE a.staff_id=staff.id AND a.action=\'login\') last_login '
                            'FROM staff ORDER BY active DESC, role, name'),
            'access': access.admin_view(self),
            'beds': self.q('SELECT id, ward, label, status, active FROM beds ORDER BY id'),
            'targets': self.q('SELECT * FROM notify_targets ORDER BY id'),
            'settings': {'hospital_name': self.setting('hospital_name'), 'hospital_addr': self.setting('hospital_addr'),
                         'casualty_phone': self.setting('casualty_phone'),
                         'summary_time': self.setting('summary_time', '21:00'),
                         'telegram_set': bool(self.setting('tg_token')), 'demo': self.setting('demo') == '1',
                         'display_names': self.setting('display_names', '1'), 'display_mode': self.display_mode(),
                         'token_print': self.setting('token_print', '1'),
                         'public_url': self.setting('public_url'), 'consult_minutes': self.setting('consult_minutes', '8'), 'booking_grace': self.setting('booking_grace', '30'), 'public_base': getattr(self, 'public_base', ''),
                         'expiry_days': self.setting('expiry_days', '90'), 'low_qty': self.setting('low_qty', '10')},
            'more': more.admin_extra(self),
            'outbox': self.q('SELECT created_at, sent_at, tries, error FROM outbox ORDER BY id DESC LIMIT 10'),
        }

    def upsert(self, staff, table, b, fields):
        vals = {k: b[k] for k in fields if k in b}
        rid = to_int(b.get('id'))
        if not vals:
            raise ApiError(400, 'Nothing to save')
        try:
            with self.tx():
                if rid:
                    self.run('UPDATE %s SET %s WHERE id=?' % (table, ', '.join(k + '=?' for k in vals)),
                             list(vals.values()) + [rid])
                    self.audit(staff, table + '.update', table, rid, {'fields': sorted(vals)})
                else:
                    rid = self.run('INSERT INTO %s(%s) VALUES(%s)' % (table, ', '.join(vals), ', '.join('?' * len(vals))),
                                   list(vals.values()))
                    self.audit(staff, table + '.create', table, rid)
        except sqlite3.IntegrityError:
            raise ApiError(400, 'Could not save. Check that the code is not already used and nothing is left blank.')
        return rid

    @route('POST', r'/api/admin/department', ('settings',))
    def save_department(self, staff, p, b):
        if 'code' in b:
            b['code'] = clean(b['code'], 4).upper()
            if not re.fullmatch(r'[A-Z]{2,4}', b['code']):
                raise ApiError(400, 'Code must be 2 to 4 letters, for example PED')
        for k in ('fee_walkin', 'fee_phone'):
            if k in b:
                b[k] = to_int(b[k], 0)
                if not 0 <= b[k] <= 100000:
                    raise ApiError(400, 'Fee is not valid')
        if 'name' in b and len(clean(b['name'])) < 2:
            raise ApiError(400, 'Enter the department name')
        return {'id': self.upsert(staff, 'departments', b, ('code', 'name', 'name_te', 'fee_walkin', 'fee_phone', 'active'))}

    @route('POST', r'/api/admin/doctor', ('settings',))
    def save_doctor(self, staff, p, b):
        if 'name' in b and len(clean(b['name'])) < 2:
            raise ApiError(400, 'Enter the doctor name')
        if 'kind' in b and b['kind'] not in ('owner', 'inhouse', 'consultant'):
            raise ApiError(400, 'Unknown doctor type')
        if 'visit_days' in b:
            b['visit_days'] = ','.join(d for d in ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun') if d in (b['visit_days'] or []))
        if b.get('visit_time') and not re.fullmatch(r'[0-2]\d:[0-5]\d', str(b['visit_time'])):
            raise ApiError(400, 'Time must look like 10:30')
        if 'payout_kind' in b and b['payout_kind'] not in ('', 'visit', 'case', 'day', 'fixed'):
            raise ApiError(400, 'Unknown payment type')
        if 'payout_rate' in b:
            b['payout_rate'] = to_int(b['payout_rate'], 0)
        return {'id': self.upsert(staff, 'doctors', b, ('name', 'dept_id', 'kind', 'active', 'payout_kind', 'payout_rate', 'visit_days', 'visit_time'))}

    @route('POST', r'/api/admin/bed', ('settings',))
    def save_bed(self, staff, p, b):
        for k in ('ward', 'label'):
            if k in b and not clean(b[k]):
                raise ApiError(400, 'Enter the ward and bed name')
        return {'id': self.upsert(staff, 'beds', b, ('ward', 'label', 'active'))}

    @route('POST', r'/api/admin/settings', ('settings',))
    def save_settings(self, staff, p, b):
        saved = []
        if 'display_mode' in b and b['display_mode'] not in ('both', 'name', 'token'):
            raise ApiError(400, 'Choose what the waiting-hall TV shows')
        if 'token_print' in b and str(b['token_print']) not in ('0', '1'):
            raise ApiError(400, 'Choose print or no print')
        if b.get('public_url') and not re.fullmatch(r'https?://[A-Za-z0-9.\-:]+(/[^\s]*)?', str(b['public_url']).strip()):
            raise ApiError(400, 'The address must look like http://192.168.1.20:8080 or https://sunrise.example.in')
        if 'consult_minutes' in b and not 1 <= to_int(b['consult_minutes'], 0) <= 60:
            raise ApiError(400, 'Minutes per patient must be between 1 and 60')
        if 'booking_grace' in b and not 0 <= to_int(b['booking_grace'], -1) <= 240:
            raise ApiError(400, 'Grace time must be between 0 and 240 minutes')
        for k in ('hospital_name', 'hospital_addr', 'casualty_phone', 'summary_time', 'display_names', 'display_mode', 'token_print', 'expiry_days', 'low_qty', 'public_url', 'consult_minutes', 'booking_grace'):
            if k in b:
                if k == 'summary_time' and not re.fullmatch(r'[0-2]\d:[0-5]\d', str(b[k])):
                    raise ApiError(400, 'Time must look like 21:00')
                self.set_setting(k, clean(b[k], 200))
                saved.append(k)
        if 'tg_token' in b:
            self.set_setting('tg_token', clean(b['tg_token'], 100))
            saved.append('tg_token')
        self.audit(staff, 'settings.update', 'settings', None, {'fields': saved})
        return {'ok': True}

    @route('POST', r'/api/admin/target', ('settings',))
    def save_target(self, staff, p, b):
        if 'topics' in b:
            b['topics'] = ','.join(t for t in TOPICS if t in (b['topics'] or []))
        if 'dept_ids' in b:
            b['dept_ids'] = ','.join(str(int(x)) for x in (b['dept_ids'] or []))
        if 'chat_id' in b and not re.fullmatch(r'-?\d+', str(b['chat_id']).strip()):
            raise ApiError(400, 'Chat ID must be a number. Use "Find chats" to pick it.')
        if 'label' in b and not clean(b['label']):
            raise ApiError(400, 'Enter a name for this person or group')
        return {'id': self.upsert(staff, 'notify_targets', b, ('label', 'chat_id', 'topics', 'dept_ids', 'active'))}

    @route('POST', r'/api/admin/telegram-chats', ('settings',))
    def telegram_chats(self, staff, p, b):
        """People and groups who have recently written to the hospital's bot."""
        res = self.telegram_call('getUpdates', {})
        chats = {}
        for u in res.get('result', []):
            m = u.get('message') or u.get('my_chat_member') or u.get('channel_post') or {}
            c = m.get('chat')
            if c:
                chats[c['id']] = c.get('title') or ' '.join(x for x in (c.get('first_name'), c.get('last_name')) if x)
        return {'chats': [{'chat_id': str(k), 'name': v} for k, v in chats.items()]}

    @route('POST', r'/api/admin/telegram-test', ('settings',))
    def telegram_test(self, staff, p, b):
        t = self.one('SELECT * FROM notify_targets WHERE id=?', (to_int(b.get('id')),))
        if not t:
            raise ApiError(404, 'Not found')
        self.telegram_send(t['chat_id'], 'Test message from %s. Updates will arrive here.' % self.setting('hospital_name'))
        return {'ok': True}

    @route('POST', r'/api/admin/summary-now', ('settings',))
    def summary_now(self, staff, p, b):
        n = self.notify('summary', self.summary_text())
        if not n:
            raise ApiError(400, 'Nobody is set to receive the daily summary yet')
        return {'queued': n}

    @route('GET', r'/api/audit', ('settings',))
    def audit_list(self, staff, p, b):
        return {'rows': self.q('SELECT * FROM audit_log ORDER BY id DESC LIMIT ?', (min(to_int(p.get('limit'), 200), 1000),))}

    # ---------- updates to phones (Telegram) ----------
    def notify(self, topic, text, dept_id=None):
        """Queue a message for everyone who asked for this kind of update. Never contains patient names."""
        n = 0
        for t in self.q('SELECT * FROM notify_targets WHERE active=1'):
            if topic not in (t['topics'] or '').split(','):
                continue
            depts = [x for x in (t['dept_ids'] or '').split(',') if x]
            if depts and dept_id is not None and str(dept_id) not in depts:
                continue
            self.run('INSERT INTO outbox(chat_id, text, created_at) VALUES(?,?,?)', (t['chat_id'], text, now()))
            n += 1
        return n

    def summary_text(self):
        day = today()
        op = self.op_by_dept(day)
        c = self.bed_counts()
        adm = self.one('SELECT COUNT(*) n FROM admissions WHERE admitted_at LIKE ?', (day + '%',))['n']
        dis = self.one('SELECT COUNT(*) n FROM admissions WHERE discharged_at LIKE ?', (day + '%',))['n']
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        appts = self.one("SELECT COUNT(*) n FROM appointments WHERE appt_date=? AND status='booked'", (tomorrow,))['n']
        lines = ['%s - summary for %s' % (self.setting('hospital_name', 'Sunrise Hospital'),
                                          datetime.date.today().strftime('%d %b %Y')),
                 '', 'OP patients today: %d' % sum(r['total'] for r in op)]
        lines += ['  %s: %d' % (r['name'], r['total']) for r in op if r['total']]
        waiting = sum(r['waiting'] + r['called'] for r in op)
        if waiting:
            lines.append('Still waiting: %d' % waiting)
        lines += ['', 'Beds: %d of %d occupied, %d cleaning, %d vacant' % (c['occupied'], c['total'], c['cleaning'], c['vacant']),
                  'Admitted today: %d, discharged today: %d' % (adm, dis),
                  'Phone bookings for tomorrow: %d' % appts]
        lines += more.summary_lines(self)
        return '\n'.join(lines)

    def telegram_call(self, method, params):
        token = self.setting('tg_token')
        if not token:
            raise ApiError(400, 'Save the Telegram bot token first')
        req = urllib.request.Request('https://api.telegram.org/bot%s/%s' % (token, method),
                                     data=urllib.parse.urlencode(params).encode())
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # network down, wrong token and so on
            code = getattr(e, 'code', None)
            raise ApiError(502, 'Telegram did not accept this (%s). Check the bot token and the internet connection.'
                           % (code or 'no connection'))

    def telegram_send(self, chat_id, text):
        self.telegram_call('sendMessage', {'chat_id': chat_id, 'text': text})

    def flush_outbox(self):
        """Send waiting messages. If the internet is down they stay queued and are retried."""
        if not self.setting('tg_token') and self.sender == self.telegram_send:
            return 0
        sent = 0
        for m in self.q('SELECT * FROM outbox WHERE sent_at IS NULL AND tries < 20 ORDER BY id LIMIT 20'):
            try:
                self.sender(m['chat_id'], m['text'])
                self.run('UPDATE outbox SET sent_at=?, error=NULL WHERE id=?', (now(), m['id']))
                sent += 1
            except Exception as e:
                self.run('UPDATE outbox SET tries=tries+1, error=? WHERE id=?', (str(e)[:200], m['id']))
                break
        return sent

    def daily_summary_if_due(self):
        t = self.setting('summary_time', '21:00')
        if datetime.datetime.now().strftime('%H:%M') >= t and self.setting('last_summary') != today():
            self.set_setting('last_summary', today())
            self.notify('summary', self.summary_text())

    # ---------- backups ----------
    def backup(self):
        """One safe copy of the database per day; the last 30 days are kept."""
        dest = os.path.join(self.backup_dir, 'sunrise-%s.db' % today())
        tmp = dest + '.tmp'
        with self.lock:
            out = sqlite3.connect(tmp)
            self.db.backup(out)
            out.close()
        os.replace(tmp, dest)
        for old in sorted(f for f in os.listdir(self.backup_dir) if f.endswith('.db'))[:-30]:
            os.remove(os.path.join(self.backup_dir, old))
        return dest


import more  # noqa: E402  (the later-phase modules; registers its own routes)
import access  # noqa: E402  (logins, passwords and who-can-see-what)
import charges  # noqa: E402  (price list and inpatient charge slip)
import billing  # noqa: E402  (inpatient bill, receipts)
import pharmsale  # noqa: E402  (quick sales at the pharmacy counter)
import claimflow  # noqa: E402  (insurance hand-off and follow-up)
import patienttoken  # noqa: E402  (patients follow their own turn)
