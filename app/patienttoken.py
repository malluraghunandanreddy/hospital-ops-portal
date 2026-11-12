"""What patients see about their own turn, without logging in.

- Every token gets a random, unguessable code. The token slip (or the reception screen) shows a QR code
  for it; the patient scans it and sees their token, the token being called now, how many are ahead and
  about how long it will take. No names or medical details are shown. The page only works on the day of the visit.
- The waiting-hall TV shows the same numbers for everyone.
- The waiting time is worked out from how long the doctor took per patient today (or a default the
  hospital can change).
"""
import datetime
import secrets

from core import ApiError, clean, route, to_int, today

ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'


def next_token(app, dept_id, day):
    """Next token number for a department and day, after every number already given or reserved by a phone booking."""
    v = app.one('SELECT COALESCE(MAX(token_no), 0) n FROM visits WHERE dept_id=? AND visit_date=?', (dept_id, day))['n']
    a = app.one("SELECT COALESCE(MAX(token_no), 0) n FROM appointments WHERE dept_id=? AND appt_date=? AND status IN ('booked','arrived')", (dept_id, day))['n']
    return max(v, a) + 1


def migrate(app):
    have = [r['name'] for r in app.q('PRAGMA table_info(visits)')]
    if 'public_code' not in have:
        app.run('ALTER TABLE visits ADD COLUMN public_code TEXT')
    ah = [r['name'] for r in app.q('PRAGMA table_info(appointments)')]
    if 'token_no' not in ah:
        app.run('ALTER TABLE appointments ADD COLUMN token_no INTEGER')
        app.run('ALTER TABLE appointments ADD COLUMN token_code TEXT')
    for a in app.q("SELECT a.id, a.dept_id, a.appt_date, d.code FROM appointments a JOIN departments d ON d.id=a.dept_id "
                   "WHERE a.token_no IS NULL AND a.status='booked' AND a.appt_date>=? ORDER BY a.appt_date, a.appt_time, a.id", (today(),)):
        n = next_token(app, a['dept_id'], a['appt_date'])
        app.run('UPDATE appointments SET token_no=?, token_code=? WHERE id=?', (n, '%s-%02d' % (a['code'], n), a['id']))
    app.run('CREATE UNIQUE INDEX IF NOT EXISTS ux_visit_public ON visits(public_code)')
    for r in app.q('SELECT id FROM visits WHERE public_code IS NULL AND visit_date=?', (today(),)):
        app.run('UPDATE visits SET public_code=? WHERE id=?', (new_code(), r['id']))


def new_code():
    return ''.join(secrets.choice(ALPHABET) for _ in range(10))


def minutes_per_patient(app, dept_id, day=None):
    """Average minutes from 'called in' to 'seen' today in this department; the hospital default if too few yet."""
    rows = app.q("SELECT called_at, done_at FROM visits WHERE dept_id=? AND visit_date=? AND status='done' AND called_at IS NOT NULL "
                 "AND done_at IS NOT NULL ORDER BY done_at DESC LIMIT 10", (dept_id, day or today()))
    mins = []
    for r in rows:
        try:
            m = (datetime.datetime.fromisoformat(r['done_at']) - datetime.datetime.fromisoformat(r['called_at'])).total_seconds() / 60
        except ValueError:
            continue
        if 1 <= m <= 60:
            mins.append(m)
    default = to_int(app.setting('consult_minutes', '8'), 8)
    return round(sum(mins) / len(mins)) if len(mins) >= 3 else default


def base_url(app):
    """The address patients' phones use: set in Settings, otherwise this laptop's Wi-Fi address."""
    return (app.setting('public_url') or getattr(app, 'public_base', '') or '').rstrip('/')


@route('GET', r'/api/token', None)
def token_status(app, staff, p, b):
    code = clean(p.get('c'), 20).lower()
    if len(code) < 8:
        raise ApiError(404, 'This token link is not valid')
    v = app.one('SELECT v.*, d.name dept, d.name_te dept_te, dr.name doctor, dr.status doctor_status, dr.status_note '
                'FROM visits v JOIN departments d ON d.id=v.dept_id LEFT JOIN doctors dr ON dr.id=v.doctor_id WHERE v.public_code=?', (code,))
    if not v:
        raise ApiError(404, 'This token link is not valid')
    if v['visit_date'] != today():
        return {'expired': True, 'token': v['token_code'], 'hospital': app.setting('hospital_name')}
    ahead = app.one("SELECT COUNT(*) n FROM visits WHERE dept_id=? AND visit_date=? AND status='waiting' AND token_no<?",
                    (v['dept_id'], v['visit_date'], v['token_no']))['n']
    now_row = app.one("SELECT token_code FROM visits WHERE dept_id=? AND visit_date=? AND status='called' ORDER BY called_at DESC LIMIT 1",
                      (v['dept_id'], v['visit_date']))
    per = minutes_per_patient(app, v['dept_id'])
    with_doctor = 1 if now_row and v['status'] == 'waiting' else 0
    return {'hospital': app.setting('hospital_name'), 'token': v['token_code'], 'dept': v['dept'], 'dept_te': v['dept_te'],
            'status': v['status'], 'ahead': ahead if v['status'] == 'waiting' else 0, 'now': now_row['token_code'] if now_row else None,
            'minutes': (ahead + with_doctor) * per if v['status'] == 'waiting' else 0, 'per': per,
            'doctor': v['doctor'], 'doctor_status': v['doctor_status'], 'doctor_note': v['status_note'],
            'casualty': app.setting('casualty_phone')}
