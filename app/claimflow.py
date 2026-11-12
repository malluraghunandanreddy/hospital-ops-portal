"""Insurance hand-off and follow-up.

- The doctors (IP billing) press "Send to insurance desk" on an inpatient's bill. The claim then shows
  on the insurance desk as "New from inpatients", with who sent it and when.
- Every step is kept on the claim's timeline: sent, documents, claim file made, status changes,
  follow-up calls. Nothing is removed from it.
- A follow-up has a note and the next date to check. When that date comes the claim shows under
  "Follow-up due" for the desk and under "Needs attention" for the doctors.
- The desk's work today (submitted, documents, follow-ups) is counted per person.
"""
import datetime

from core import ApiError, clean, now, route, to_int, today

SCHEMA = """
CREATE TABLE IF NOT EXISTS claim_events(
  id INTEGER PRIMARY KEY, claim_id INTEGER NOT NULL, at TEXT NOT NULL, staff_name TEXT, kind TEXT NOT NULL, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_claim_events ON claim_events(claim_id);
"""
OPEN = ('preparing', 'submitted', 'queried', 'approved')
KIND_NAMES = {'started': 'Claim started', 'sent': 'Sent to insurance desk', 'doc': 'Document attached', 'file': 'Claim file made',
              'status': 'Status changed', 'followup': 'Follow-up', 'note': 'Details updated'}


def migrate(app):
    have = [r['name'] for r in app.q('PRAGMA table_info(claims)')]
    for col, decl in (('sent_at', 'TEXT'), ('sent_by', 'TEXT'), ('next_followup', 'TEXT'), ('last_activity_at', 'TEXT'), ('picked_at', 'TEXT')):
        if col not in have:
            app.run('ALTER TABLE claims ADD COLUMN %s %s' % (col, decl))


def event(app, staff, cid, kind, detail=''):
    """Caller holds a transaction or not; one row, never edited."""
    app.run('INSERT INTO claim_events(claim_id, at, staff_name, kind, detail) VALUES(?,?,?,?,?)',
            (cid, now(), staff['name'] if staff else 'system', kind, clean(detail, 300)))
    app.run('UPDATE claims SET last_activity_at=? WHERE id=?', (now(), cid))
    if staff and staff.get('role') == 'insurance':
        app.run('UPDATE claims SET picked_at=COALESCE(picked_at, ?) WHERE id=?', (now(), cid))


@route('POST', r'/api/admissions/(\d+)/send-to-insurance', ('ipbill',))
def send_to_insurance(app, staff, p, b, aid):
    a = app.one('SELECT * FROM admissions WHERE id=?', (aid,))
    if not a:
        raise ApiError(404, 'Admission not found')
    if (a['payer'] or 'Cash') == 'Cash':
        raise ApiError(400, 'This patient is paying cash. Change "Scheme / cash" at admission if a scheme or insurer pays.')
    with app.tx():
        c = app.one('SELECT * FROM claims WHERE admission_id=?', (aid,))
        if not c:
            cid = app.run('INSERT INTO claims(admission_id, scheme, status_at, created_at) VALUES(?,?,?,?)', (aid, a['payer'], now(), now()))
            event(app, None, cid, 'started', a['payer'])
        else:
            cid = c['id']
        if c and c['sent_at']:
            raise ApiError(409, 'Already sent to the insurance desk on %s by %s' % (c['sent_at'][:10], c['sent_by']))
        app.run('UPDATE claims SET sent_at=?, sent_by=? WHERE id=?', (now(), staff['name'], cid))
        event(app, staff, cid, 'sent', clean(b.get('note'), 200))
        app.audit(staff, 'claim.sent', 'claim', cid)
    app.notify('ip', 'Claim sent to the insurance desk (bed admission #%d, %s).' % (aid, a['payer']))
    return {'id': cid}


@route('POST', r'/api/claims/(\d+)/followup', ('claims',))
def followup(app, staff, p, b, cid):
    c = app.one('SELECT * FROM claims WHERE id=?', (cid,))
    if not c:
        raise ApiError(404, 'Not found')
    note = clean(b.get('note'), 300)
    nxt = clean(b.get('next_followup'), 10) or None
    if len(note) < 3:
        raise ApiError(400, 'Write what happened, for example "Called TPA, approval expected Friday"')
    if nxt:
        try:
            if datetime.date.fromisoformat(nxt) < datetime.date.today():
                raise ApiError(400, 'The next follow-up date cannot be in the past')
        except ValueError:
            raise ApiError(400, 'The next follow-up date is not valid')
    with app.tx():
        app.run('UPDATE claims SET next_followup=? WHERE id=?', (nxt, cid))
        event(app, staff, cid, 'followup', note + (' · next on ' + nxt if nxt else ''))
        app.audit(staff, 'claim.followup', 'claim', cid)
    return {'ok': True}


@route('GET', r'/api/claims/(\d+)/events', ('claims', 'ipbill'))
def events(app, staff, p, b, cid):
    rows = app.q('SELECT * FROM claim_events WHERE claim_id=? ORDER BY id DESC', (cid,))
    for r in rows:
        r['label'] = KIND_NAMES.get(r['kind'], r['kind'])
    return {'events': rows}


def summary(app):
    """Today's work by the insurance desk and what is waiting."""
    td = today()
    ev = app.q("SELECT kind, detail, staff_name FROM claim_events WHERE substr(at, 1, 10)=?", (td,))
    by_person = {}
    for e in ev:
        if e['staff_name'] in (None, 'system'):
            continue
        d = by_person.setdefault(e['staff_name'], {'submitted': 0, 'docs': 0, 'followups': 0, 'files': 0, 'updates': 0})
        if e['kind'] == 'status' and (e['detail'] or '').startswith('submitted'):
            d['submitted'] += 1
        elif e['kind'] == 'doc':
            d['docs'] += 1
        elif e['kind'] == 'followup':
            d['followups'] += 1
        elif e['kind'] == 'file':
            d['files'] += 1
        elif e['kind'] in ('status', 'note'):
            d['updates'] += 1
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    open_rows = app.q("SELECT c.*, b.label bed, p.name patient FROM claims c JOIN admissions a ON a.id=c.admission_id JOIN beds b ON b.id=a.bed_id "
                      "JOIN patients p ON p.id=a.patient_id WHERE c.status IN ('preparing','submitted','queried','approved')")
    new = [r for r in open_rows if r['sent_at'] and not r['picked_at']]
    due = [r for r in open_rows if r['next_followup'] and r['next_followup'] <= td]
    stale = [r for r in open_rows if r['status'] in ('submitted', 'queried') and (r['last_activity_at'] or r['status_at'] or '')[:10] < week_ago]
    not_sent = app.q("SELECT a.id, b.label bed, p.name patient FROM admissions a JOIN beds b ON b.id=a.bed_id JOIN patients p ON p.id=a.patient_id "
                     "LEFT JOIN claims c ON c.admission_id=a.id WHERE a.status='discharged' AND COALESCE(a.payer,'Cash')<>'Cash' AND (c.id IS NULL OR c.sent_at IS NULL)")
    pending = app.one("SELECT COALESCE(SUM(ib.scheme_amount), 0) n FROM claims c JOIN ip_bills ib ON ib.admission_id=c.admission_id "
                      "WHERE c.status IN ('preparing','submitted','queried','approved') AND ib.reopened=0")['n']
    statuses = {s: 0 for s in ('preparing', 'submitted', 'queried', 'approved', 'settled', 'rejected')}
    for r in app.q('SELECT status, COUNT(*) n FROM claims GROUP BY status'):
        statuses[r['status']] = r['n']
    short = lambda rows: [{'id': r['id'], 'bed': r.get('bed'), 'patient': r.get('patient'), 'next_followup': r.get('next_followup')} for r in rows]  # noqa: E731
    return {'today': {'submitted': sum(d['submitted'] for d in by_person.values()), 'docs': sum(d['docs'] for d in by_person.values()),
                      'followups': sum(d['followups'] for d in by_person.values()), 'files': sum(d['files'] for d in by_person.values()),
                      'by_person': by_person},
            'new': short(new), 'due': short(due), 'stale': short(stale), 'not_sent': not_sent, 'pending_amount': pending, 'statuses': statuses}


@route('GET', r'/api/claims/summary', ('claims', 'today'))
def summary_route(app, staff, p, b):
    return summary(app)


def seed_demo(app):
    """Give the demo claims a believable history."""
    if app.setting('demo') != '1' or app.one("SELECT id FROM claim_events WHERE kind<>'started' LIMIT 1"):
        return
    rows = app.q('SELECT id FROM claims ORDER BY id')
    owner = {'name': 'Dr A. Meera', 'role': 'owner'}
    desk = {'name': 'K. Prakash Rao', 'role': 'insurance'}
    td = datetime.date.today()
    for i, r in enumerate(rows):
        if i == 0:
            app.run('UPDATE claims SET sent_at=?, sent_by=? WHERE id=?', (now(), owner['name'], r['id']))
            event(app, owner, r['id'], 'sent', 'Discharge tomorrow, please start the papers')
        if i == 1:
            app.run('UPDATE claims SET sent_at=?, sent_by=?, status=?, status_at=?, claim_no=? WHERE id=?',
                    ((td - datetime.timedelta(days=3)).isoformat() + 'T11:00:00', owner['name'], 'submitted', now(), 'TPA-882104', r['id']))
            app.run('INSERT INTO claim_events(claim_id, at, staff_name, kind, detail) VALUES(?,?,?,?,?)',
                    (r['id'], (td - datetime.timedelta(days=3)).isoformat() + 'T11:00:00', owner['name'], 'sent', ''))
            event(app, desk, r['id'], 'status', 'submitted')
            app.run('UPDATE claims SET next_followup=? WHERE id=?', (td.isoformat(), r['id']))
            event(app, desk, r['id'], 'followup', 'Called the TPA, approval expected today · next on ' + td.isoformat())
