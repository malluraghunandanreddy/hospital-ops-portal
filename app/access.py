"""Logins, passwords, sessions and who-can-see-what.

- Everyone has their own username and password (no shared PINs, no list of names on the login page).
- New logins and password resets get a one-time password; the person must set their own on first login.
- Each role has a set of screens. Full-access doctors can change those sets, and can give one person
  more or fewer screens than their role. The server checks this on every request, so a hidden screen
  cannot be opened by typing its address.
- Fixed rules that never change with settings:
    * full-access doctors always see everything (so nobody can lock the hospital out);
    * Settings, logins and inpatient billing are only for full-access doctors;
    * only doctor logins can order discharge, sign a discharge summary or write round notes;
    * a visiting consultant only ever sees their own patients.
"""
import hashlib
import hmac
import re
import secrets
import time

from core import ApiError, DOCS, clean, now, route, to_int

ROLE_NAMES = {'owner': 'Doctor (full access)', 'doctor': 'In-house doctor', 'consultant': 'Visiting consultant',
              'reception': 'Reception', 'nurse': 'Nursing', 'pharmacy': 'Pharmacy / accounts',
              'insurance': 'Insurance desk', 'lab': 'Lab', 'support': 'Support staff (no login)'}

# key, what it lets a person do, roles that have it by default
SCREENS = [
    ('today', 'Hospital overview (all departments)', ()),
    ('accounts', 'Accounts check (fees, deposits, payouts to compare with Essel)', ()),
    ('myday', 'My day (own OP patients, inpatients, reports, OT)', ('doctor', 'consultant')),
    ('desk', 'OP Desk: register patients and give tokens', ('reception',)),
    ('ward', 'Ward duty list, bed cleaning, patient leaving', ('nurse',)),
    ('queue', 'OP queue: call tokens to the doctor, mark seen (reception; tick for doctors only if they call their own patients)', ('reception',)),
    ('appointments', 'Phone bookings', ('reception',)),
    ('doctors', 'Doctor attendance (visiting doctors came / left)', ('reception',)),
    ('followups', 'Follow-ups and vaccine reminder lists', ('reception',)),
    ('beds', 'Bed board', ('reception', 'doctor', 'consultant', 'nurse')),
    ('admit', 'Admit patients to a bed', ('reception',)),
    ('chart', 'Inpatient charts: vitals, medicines, services, rounds, discharge steps', ('doctor', 'consultant', 'nurse')),
    ('records', 'Patient records and OP history', ('reception', 'doctor', 'consultant')),
    ('iphistory', 'Admission history (past inpatients)', ('reception', 'doctor', 'insurance')),
    ('ot', 'Operation theatre bookings and pre-op checklist', ('reception', 'doctor', 'consultant', 'nurse')),
    ('lab', 'Lab: samples and reports', ('reception', 'lab')),
    ('claims', 'Insurance and scheme claims', ('insurance',)),
    ('pharmsale', 'Pharmacy counter: quick medicine sales, to enter in Pharmasoft later', ('pharmacy',)),
    ('pharmacy', 'Pharmacy stock alerts and dose check', ('pharmacy',)),
    ('rx', 'Prescription photos: photograph the paper prescription after the doctor sees the patient', ('pharmacy', 'reception')),
    ('essel', 'Enter OP registrations in Essel', ('reception',)),
    ('ipbill', 'Inpatient billing: check ward charge slips, advances, payments, final bill (full-access doctors only)', ()),
    ('staff', 'Staff attendance, duty roster, salary, consultant payments', ()),
    ('settings', 'Settings and logins (full-access doctors only)', ()),
]
SCREEN_KEYS = [s[0] for s in SCREENS]
LOCKED = ('settings', 'ipbill')  # only full-access doctors, never given to anyone else
FULL = 'owner'
COMMON = {'password', 'password1', '12345678', '123456789', '1234567890', 'qwerty123', 'abcd1234', 'sunrise123',
          'sunrise@123', 'hospital1', 'hospital123', 'welcome1', 'welcome123', 'india123', 'admin123'}
SESSION_SHORT = 12 * 3600       # shared computers: until the browser closes, at most 12 hours
SESSION_LONG = 30 * 86400       # "keep me signed in on this phone"
OPEN_WHEN_MUST_CHANGE = {'bootstrap', 'logout', 'change_password'}


def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac('sha256', str(pw).encode(), bytes.fromhex(salt), 200000).hex()


def temp_password():
    """Easy to read out and type once, e.g. kfmt-4821. Must be changed at first login."""
    letters = 'abcdefghjkmnpqrstuvwxyz'
    return ''.join(secrets.choice(letters) for _ in range(4)) + '-' + ''.join(secrets.choice('23456789') for _ in range(4))


def check_strength(pw, username='', name=''):
    pw = str(pw or '')
    low = pw.lower()
    if len(pw) < 8:
        raise ApiError(400, 'Password must be at least 8 characters')
    if not re.search(r'[A-Za-z]', pw) or not re.search(r'\d', pw):
        raise ApiError(400, 'Use both letters and numbers in the password')
    if low in COMMON or len(set(low)) < 4:
        raise ApiError(400, 'This password is too easy to guess. Choose another.')
    for part in [username] + re.split(r'\W+', name or ''):
        if part and len(part) >= 4 and part.lower() in low:
            raise ApiError(400, 'Do not use your own name in the password')


def set_password(app, sid, pw, must_change):
    salt = secrets.token_hex(16)
    app.run('UPDATE staff SET pw_salt=?, pw_hash=?, must_change=? WHERE id=?', (salt, hash_pw(pw, salt), 1 if must_change else 0, sid))
    end_sessions(app, sid)


def new_temp_password(app, sid):
    pw = temp_password()
    set_password(app, sid, pw, True)
    return pw


def username_from(name, app):
    base = re.sub(r'^(dr|sr|mr|mrs|ms|sk|ch)\.?\s+', '', name.strip(), flags=re.I)
    words = [w for w in re.split(r'[^A-Za-z]+', base) if len(w) > 2] or [w for w in re.split(r'[^A-Za-z]+', base) if w] or ['user']
    stem = words[0].lower()[:12]
    cand, n = stem, 1
    while app.one('SELECT id FROM staff WHERE username=?', (cand,)):
        n += 1
        cand = '%s%d' % (stem, n)
    return cand


# ---------- permissions ----------
def role_screens(app, role):
    if role == FULL:
        return list(SCREEN_KEYS)
    saved = app.setting('screens_' + role, None)
    if saved is None:
        return [k for k, _, roles in SCREENS if role in roles]
    return [k for k in saved.split(',') if k in SCREEN_KEYS and k not in LOCKED]


def screens_of(app, staff):
    if not staff:
        return []
    if staff['role'] == FULL:
        return list(SCREEN_KEYS)
    row = app.one('SELECT screens FROM staff WHERE id=?', (staff['id'],))
    if row and row['screens'] is not None:
        return [k for k in row['screens'].split(',') if k in SCREEN_KEYS and k not in LOCKED]
    return role_screens(app, staff['role'])


def allowed(app, staff, *screens):
    mine = staff.get('screens') if isinstance(staff, dict) and 'screens' in staff else screens_of(app, staff)
    return any(s in mine for s in screens)


def check(app, staff, screens, fn):
    """Called for every request before the handler runs."""
    if screens is None:
        return
    if not staff:
        raise ApiError(401, 'Please log in')
    if staff.get('must_change') and fn.__name__ not in OPEN_WHEN_MUST_CHANGE:
        raise ApiError(403, 'Set your own password first')
    if screens == '*':
        return
    staff['screens'] = screens_of(app, staff)
    if not any(s in staff['screens'] for s in screens):
        raise ApiError(403, 'Your login does not have access to this.')


def require_doctor(staff):
    if staff['role'] not in (FULL,) + DOCS:
        raise ApiError(403, 'Only a doctor can do this')


# ---------- sessions ----------
def token_hash(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


def staff_for(app, tok):
    if not tok:
        return None
    s = app.one('SELECT * FROM sessions WHERE token_hash=?', (token_hash(tok),))
    if not s or s['expires'] < time.time():
        if s:
            app.run('DELETE FROM sessions WHERE token_hash=?', (s['token_hash'],))
        return None
    if time.time() - (s['last_seen'] or 0) > 300:
        app.run('UPDATE sessions SET last_seen=? WHERE token_hash=?', (time.time(), s['token_hash']))
    return app.one('SELECT id, name, role, doctor_id, username, must_change FROM staff WHERE id=? AND active=1', (s['staff_id'],))


def end_sessions(app, sid):
    app.run('DELETE FROM sessions WHERE staff_id=?', (sid,))


FAILS = {}  # key -> (count, until)


def too_many(key, limit, block):
    n, until = FAILS.get(key, (0, 0))
    if n >= limit and time.time() < until:
        raise ApiError(429, 'Too many wrong attempts. Wait %d minutes and try again.' % max(1, round((until - time.time()) / 60)))


def failed(key, block):
    n, until = FAILS.get(key, (0, 0))
    if time.time() > until + 1800:
        n = 0
    FAILS[key] = (n + 1, time.time() + block)


@route('POST', r'/api/login', None)
def login(app, staff, p, b):
    user = clean(b.get('username'), 40).lower()
    ip = b.get('_ip') or '-'
    too_many('u:' + user, 5, 300)
    too_many('ip:' + ip, 20, 900)
    s = app.one('SELECT * FROM staff WHERE username=? AND active=1', (user,)) if user else None
    ok = bool(s and s['pw_hash'] and hmac.compare_digest(s['pw_hash'], hash_pw(b.get('password', ''), s['pw_salt'])))
    if not ok:
        failed('u:' + user, 300)
        failed('ip:' + ip, 900)
        if s:
            app.audit(s, 'login.failed', 'staff', s['id'])
        raise ApiError(401, 'Username or password is wrong')
    FAILS.pop('u:' + user, None)
    remember = bool(b.get('remember'))
    tok = secrets.token_urlsafe(32)
    app.run('DELETE FROM sessions WHERE expires<?', (time.time(),))
    app.run('INSERT INTO sessions(token_hash, staff_id, created_at, last_seen, expires, remember) VALUES(?,?,?,?,?,?)',
            (token_hash(tok), s['id'], now(), time.time(), time.time() + (SESSION_LONG if remember else SESSION_SHORT), 1 if remember else 0))
    app.audit(s, 'login', 'staff', s['id'], {'remember': remember})
    return {'ok': True, 'must_change': bool(s['must_change']), '_set_cookie': tok, '_remember': remember}


@route('GET', r'/api/demo-logins', None)
def demo_logins(app, staff, p, b):
    """Only in the demo copy: who can be tried, so every role can be checked in one click. A real copy returns nothing."""
    if app.setting('demo') != '1':
        return {'demo': False, 'people': []}
    rows = app.q("SELECT name, role, username FROM staff WHERE active=1 AND username IS NOT NULL AND must_change=0 ORDER BY id")
    return {'demo': True, 'password': 'Demo@2026', 'people': [dict(r, role_name=ROLE_NAMES.get(r['role'])) for r in rows]}


@route('POST', r'/api/logout', '*')
def logout(app, staff, p, b):
    if b.get('_token'):
        app.run('DELETE FROM sessions WHERE token_hash=?', (token_hash(b['_token']),))
    if b.get('everywhere'):
        end_sessions(app, staff['id'])
    app.audit(staff, 'logout', 'staff', staff['id'])
    return {'ok': True, '_clear_cookie': True}


@route('POST', r'/api/password', '*')
def change_password(app, staff, p, b):
    s = app.one('SELECT * FROM staff WHERE id=?', (staff['id'],))
    if not hmac.compare_digest(s['pw_hash'] or '', hash_pw(b.get('old', ''), s['pw_salt'] or '00')):
        raise ApiError(400, 'Your current password is not right')
    if b.get('new') == b.get('old'):
        raise ApiError(400, 'Choose a new password, different from the old one')
    check_strength(b.get('new'), s['username'], s['name'])
    set_password(app, s['id'], b['new'], False)  # signs out every device
    tok = secrets.token_urlsafe(32)
    app.run('INSERT INTO sessions(token_hash, staff_id, created_at, last_seen, expires, remember) VALUES(?,?,?,?,?,0)',
            (token_hash(tok), s['id'], now(), time.time(), time.time() + SESSION_SHORT))
    app.audit(staff, 'password.change', 'staff', s['id'])
    return {'ok': True, '_set_cookie': tok}


# ---------- managing logins (full-access doctors) ----------
@route('POST', r'/api/admin/staff', ('settings',))
def save_staff(app, staff, p, b):
    sid = to_int(b.get('id'))
    old = app.one('SELECT * FROM staff WHERE id=?', (sid,)) if sid else None
    if sid and not old:
        raise ApiError(404, 'Not found')
    role = b.get('role', old['role'] if old else None)
    if role not in ROLE_NAMES:
        raise ApiError(400, 'Choose the role')
    if 'name' in b and len(clean(b['name'])) < 2:
        raise ApiError(400, 'Enter the name')
    if 'doctor_id' in b:
        b['doctor_id'] = to_int(b['doctor_id'])
    if role in DOCS and not (b.get('doctor_id') if 'doctor_id' in b else (old or {}).get('doctor_id')):
        raise ApiError(400, 'Choose which doctor this login belongs to')
    if 'salary' in b:
        b['salary'] = to_int(b['salary'], 0)
    if sid == staff['id'] and (b.get('active') in (0, False, '0') or role != FULL):
        raise ApiError(400, 'You cannot switch off or lower your own login')
    if 'username' in b:
        b['username'] = clean(b['username'], 30).lower() or None
        if b['username'] and not re.fullmatch(r'[a-z][a-z0-9._]{2,29}', b['username']):
            raise ApiError(400, 'Username: 3 to 30 small letters or numbers, starting with a letter')
        if b['username'] and app.one('SELECT id FROM staff WHERE username=? AND id<>?', (b['username'], sid or 0)):
            raise ApiError(400, 'This username is already taken')
    if 'screens' in b:
        b['screens'] = None if b['screens'] is None else ','.join(k for k in SCREEN_KEYS if k in (b['screens'] or []) and k not in LOCKED)
    if role != 'support' and not b.get('username') and not (old and old['username']):
        b['username'] = username_from(clean(b.get('name')) or old['name'], app)
    fields = ('name', 'role', 'doctor_id', 'active', 'salary', 'username', 'screens')
    out = {'id': app.upsert(staff, 'staff', dict(b, role=role), fields)}
    sid = out['id']
    row = app.one('SELECT * FROM staff WHERE id=?', (sid,))
    if role == 'support':
        app.run('UPDATE staff SET pw_hash=NULL, pw_salt=NULL WHERE id=?', (sid,))
        end_sessions(app, sid)
    elif not row['pw_hash']:
        out['temp_password'] = new_temp_password(app, sid)
        app.audit(staff, 'staff.password_reset', 'staff', sid)
    if not row['active'] or (old and old['role'] != role):
        end_sessions(app, sid)
    out['username'] = row['username']
    return out


@route('POST', r'/api/admin/staff/(\d+)/reset-password', ('settings',))
def reset_password(app, staff, p, b, sid):
    row = app.one('SELECT * FROM staff WHERE id=?', (sid,))
    if not row or row['role'] == 'support':
        raise ApiError(400, 'This person has no login')
    pw = new_temp_password(app, sid)
    app.audit(staff, 'staff.password_reset', 'staff', sid)
    return {'temp_password': pw, 'username': row['username']}


@route('POST', r'/api/admin/role-screens', ('settings',))
def save_role_screens(app, staff, p, b):
    role = b.get('role')
    if role not in ROLE_NAMES or role in (FULL, 'support'):
        raise ApiError(400, 'This role cannot be changed')
    keys = [k for k in SCREEN_KEYS if k in (b.get('screens') or []) and k not in LOCKED]
    app.set_setting('screens_' + role, ','.join(keys))
    app.audit(staff, 'permissions.role', None, None, {'role': role, 'screens': keys})
    return {'ok': True}


def admin_view(app):
    return {'screens': [{'key': k, 'label': label} for k, label, _ in SCREENS], 'locked': list(LOCKED),
            'roles': [{'key': r, 'name': n, 'screens': role_screens(app, r)} for r, n in ROLE_NAMES.items() if r != 'support'],
            'role_names': ROLE_NAMES}
