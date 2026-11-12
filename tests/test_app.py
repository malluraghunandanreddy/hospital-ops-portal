"""Run with:  python -m unittest discover tests

Covers access control, token numbering, the audit log, beds and the update queue.
"""
import os
import sqlite3
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app'))
import core  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = core.App(self.tmp.name, demo=True)
        self.sent = []
        self.app.sender = lambda chat, text: self.sent.append((chat, text))

    def tearDown(self):
        self.app.db.close()
        self.tmp.cleanup()

    def who(self, name):
        return self.app.one('SELECT id, name, role, doctor_id FROM staff WHERE name=?', (name,))

    def call(self, staff, method, path, body=None, params=None):
        return self.app.handle(method, path, params or {}, body or {}, self.who(staff) if staff else None)

    def denied(self, status, *args, **kw):
        with self.assertRaises(core.ApiError) as cm:
            self.call(*args, **kw)
        self.assertEqual(cm.exception.status, status)

    def new_patient(self, name='Test Patient', phone='9000000001'):
        return self.call('Anita Reddy', 'POST', '/api/patients',
                         {'name': name, 'sex': 'F', 'age_y': 30, 'phone': phone})['patient']

    def dept(self, code):
        return self.app.one('SELECT id FROM departments WHERE code=?', (code,))['id']

    def doc(self, name):
        return self.app.one('SELECT id FROM doctors WHERE name=?', (name,))['id']


class Login(Base):
    def login(self, user, pw, **kw):
        return self.call(None, 'POST', '/api/login', dict({'username': user, 'password': pw, '_ip': '10.0.0.5'}, **kw))

    def test_username_and_password(self):
        self.denied(401, None, 'POST', '/api/login', {'username': 'meera', 'password': 'wrong-pass1'})
        res = self.login('Meera', 'Demo@2026')
        self.assertEqual(self.app.staff_for(res['_set_cookie'])['name'], 'Dr A. Meera')
        self.assertFalse(res['_remember'])

    def test_no_list_of_names_before_login(self):
        self.denied(404, None, 'GET', '/api/staff-list')
        self.app.set_setting('demo', '0')
        self.assertEqual(self.call(None, 'GET', '/api/demo-logins')['people'], [])     # a real copy shows nobody

    def test_lockout_after_five_wrong_passwords(self):
        for _ in range(5):
            self.denied(401, None, 'POST', '/api/login', {'username': 'kavya', 'password': 'nope12345'})
        self.denied(429, None, 'POST', '/api/login', {'username': 'kavya', 'password': 'Demo@2026'})

    def test_passwords_are_not_stored_in_plain_text(self):
        for s in self.app.q('SELECT * FROM staff WHERE username IS NOT NULL'):
            self.assertEqual(len(s['pw_hash']), 64)
            self.assertNotIn('Demo', s['pw_hash'])

    def test_sessions_survive_restart_and_end_on_logout(self):
        tok = self.login('anita', 'Demo@2026', remember=True)['_set_cookie']
        again = core.App(self.tmp.name)
        self.assertEqual(again.staff_for(tok)['name'], 'Anita Reddy')
        again.db.close()
        self.app.handle('POST', '/api/logout', {}, {}, self.app.staff_for(tok), tok)
        self.assertIsNone(self.app.staff_for(tok))

    def test_new_login_gets_one_time_password_and_must_change_it(self):
        res = self.call('Dr A. Meera', 'POST', '/api/admin/staff', {'name': 'Sr. Mary Rani', 'role': 'nurse', 'active': 1})
        self.assertEqual(res['username'], 'mary')
        tok = self.login('mary', res['temp_password'])['_set_cookie']
        me = self.app.staff_for(tok)
        self.assertTrue(me['must_change'])
        with self.assertRaises(core.ApiError) as cm:
            self.app.handle('GET', '/api/beds', {}, {}, me, tok)
        self.assertEqual(cm.exception.status, 403)
        for weak in ('short1', 'onlyletters', '12345678', 'Password1x'.replace('x', '') + 'mary'):
            with self.assertRaises(core.ApiError):
                self.app.handle('POST', '/api/password', {}, {'old': res['temp_password'], 'new': weak}, me, tok)
        out = self.app.handle('POST', '/api/password', {}, {'old': res['temp_password'], 'new': 'Ward7tulasi'}, me, tok)
        self.assertIsNone(self.app.staff_for(tok))          # old sessions end
        me = self.app.staff_for(out['_set_cookie'])
        self.assertFalse(me['must_change'])
        self.assertIn('beds', self.app.handle('GET', '/api/bootstrap', {}, {}, me)['me']['screens'])

    def test_reset_password_signs_out_everywhere(self):
        tok = self.login('grace', 'Demo@2026', remember=True)['_set_cookie']
        sid = self.who('Sr. Grace Mary')['id']
        res = self.call('Dr A. Meera', 'POST', '/api/admin/staff/%d/reset-password' % sid)
        self.assertIsNone(self.app.staff_for(tok))
        self.denied(401, None, 'POST', '/api/login', {'username': 'grace', 'password': 'Demo@2026'})
        self.assertTrue(self.login('grace', res['temp_password'])['must_change'])
        self.denied(403, 'Anita Reddy', 'POST', '/api/admin/staff/%d/reset-password' % sid)

    def test_everything_needs_login(self):
        for method, rx, fn, roles in core.ROUTES:
            if roles is not None:
                path = rx.pattern.replace(r'(\d+)', '1')
                self.denied(401, None, method, path)


class Tokens(Base):
    def test_numbers_run_per_department(self):
        ort, pls = self.dept('ORT'), self.dept('PLS')
        start = __import__('patienttoken').next_token(self.app, ort, core.today()) - 1   # after numbers kept for phone bookings
        codes = []
        for i in range(3):
            p = self.new_patient('Ortho %d' % i, '900000001%d' % i)
            v = self.call('Anita Reddy', 'POST', '/api/visits', {'patient_id': p['id'], 'dept_id': ort, 'source': 'walkin'})
            codes.append(v['visit']['token_code'])
        self.assertEqual(codes, ['ORT-%02d' % (start + i) for i in (1, 2, 3)])
        p = self.new_patient('Plastic', '9000000020')
        v = self.call('Anita Reddy', 'POST', '/api/visits', {'patient_id': p['id'], 'dept_id': pls, 'source': 'phone'})
        self.assertEqual(v['visit']['token_code'], 'PLS-01')

    def test_fee_follows_source(self):
        pls = self.dept('PLS')
        a, b = self.new_patient('A A', '9000000031'), self.new_patient('B B', '9000000032')
        walk = self.call('Anita Reddy', 'POST', '/api/visits', {'patient_id': a['id'], 'dept_id': pls, 'source': 'walkin'})
        phone = self.call('Anita Reddy', 'POST', '/api/visits', {'patient_id': b['id'], 'dept_id': pls, 'source': 'phone'})
        self.assertEqual((walk['visit']['fee_shown'], phone['visit']['fee_shown']), (500, 600))

    def test_no_second_token_while_waiting(self):
        p, pls = self.new_patient(), self.dept('PLS')
        body = {'patient_id': p['id'], 'dept_id': pls, 'source': 'walkin'}
        self.call('Anita Reddy', 'POST', '/api/visits', body)
        self.denied(409, 'Anita Reddy', 'POST', '/api/visits', body)

    def test_no_duplicates_when_two_desks_work_together(self):
        pls = self.dept('PLS')
        pats = [self.new_patient('Rush %d' % i, '90000001%02d' % i) for i in range(12)]
        desks = ['Anita Reddy', 'Sk. Salma Begum']
        out, errors = [], []

        def work(i):
            try:
                out.append(self.call(desks[i % 2], 'POST', '/api/visits',
                                     {'patient_id': pats[i]['id'], 'dept_id': pls, 'source': 'walkin'})['visit']['token_no'])
            except Exception as e:  # pragma: no cover
                errors.append(e)
        threads = [threading.Thread(target=work, args=(i,)) for i in range(12)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(sorted(out), list(range(1, 13)))

    def test_display_shows_names_only_when_switched_on(self):
        names = [p['name'] for p in self.app.q('SELECT name FROM patients')]
        self.assertTrue(any(n in str(self.call(None, 'GET', '/api/display')) for n in names))
        self.call('Dr A. Meera', 'POST', '/api/admin/settings', {'display_mode': 'token'})
        text = str(self.call(None, 'GET', '/api/display'))
        self.assertFalse(any(n in text for n in names))


class Access(Base):
    def test_consultant_cannot_open_another_doctors_patient(self):
        p = self.new_patient()
        self.call('Anita Reddy', 'POST', '/api/visits',
                  {'patient_id': p['id'], 'dept_id': self.dept('ORT'), 'doctor_id': self.doc('Dr S. Farhan Ali'), 'source': 'walkin'})
        self.assertEqual(self.call('Dr S. Farhan Ali', 'GET', '/api/patients/%d' % p['id'])['patient']['id'], p['id'])
        self.denied(403, 'Dr P. Rohan Mehta', 'GET', '/api/patients/%d' % p['id'])
        self.assertTrue(self.app.one("SELECT id FROM audit_log WHERE action='patient.denied' AND entity_id=?", (p['id'],)))

    def test_doctors_see_their_list_but_do_not_run_the_queue(self):
        d = self.call('Dr S. Farhan Ali', 'GET', '/api/myday')
        self.assertTrue(d['visits'])
        self.assertEqual({v['token_code'][:3] for v in d['visits']}, {'ORT'})
        mine = self.doc('Dr S. Farhan Ali')
        self.assertTrue(all(x['doctor_id'] == mine for x in self.call('Dr S. Farhan Ali', 'GET', '/api/queue')['visits']))   # read-only, own only
        self.assertNotIn('queue', self.call('Dr S. Farhan Ali', 'GET', '/api/bootstrap')['me']['screens'])
        v = d['visits'][0]['id']
        self.denied(403, 'Dr S. Farhan Ali', 'POST', '/api/visits/%d/status' % v, {'status': 'called'})
        self.call('Anita Reddy', 'POST', '/api/visits/%d/status' % v, {'status': 'called'})

    def test_consultant_cannot_change_another_doctors_visit_or_see_their_prescription(self):
        v = self.app.one('SELECT id FROM visits WHERE doctor_id=?', (self.doc('Dr A. Meera'),))
        self.denied(403, 'Dr P. Rohan Mehta', 'POST', '/api/visits/%d/status' % v['id'], {'status': 'done'})
        rid = self.call('Anita Reddy', 'POST', '/api/visits/%d/prescription' % v['id'],
                        {'_raw': b'\xff\xd8fake', '_ctype': 'image/jpeg'})['id']
        self.denied(403, 'Dr P. Rohan Mehta', 'GET', '/files/rx/%d' % rid)
        self.assertIn('_file', self.call('Dr A. Meera', 'GET', '/files/rx/%d' % rid))

    def test_consultant_sees_beds_but_not_other_doctors_patients(self):
        mine = self.doc('Dr P. Rohan Mehta')
        beds = [b for b in self.call('Dr P. Rohan Mehta', 'GET', '/api/beds')['beds'] if b['status'] == 'occupied']
        self.assertTrue(any(b['doctor_id'] == mine and b['patient'] for b in beds))
        for b in beds:
            if b['doctor_id'] != mine:
                self.assertIsNone(b['patient'])
                self.assertIsNone(b['diagnosis'])

    def test_role_limits(self):
        self.denied(403, 'Sr. Grace Mary', 'POST', '/api/visits', {})
        self.denied(403, 'Sr. Grace Mary', 'GET', '/api/queue')
        self.denied(403, 'Anita Reddy', 'GET', '/api/dashboard')
        self.denied(403, 'Anita Reddy', 'GET', '/api/audit')
        self.denied(403, 'Anita Reddy', 'POST', '/api/admin/staff', {'name': 'X Y', 'role': 'owner'})
        self.denied(403, 'Ch. Ramesh Kumar', 'GET', '/api/patients', params={'q': 'la'})
        self.denied(403, 'Dr K. Kavya Sharma', 'POST', '/api/admissions', {})
        self.assertIn('op', self.call('Dr A. Meera', 'GET', '/api/dashboard'))

    def test_doctor_changes_only_own_status(self):
        self.denied(403, 'Dr P. Rohan Mehta', 'POST', '/api/doctors/%d/status' % self.doc('Dr A. Meera'), {'status': 'out'})
        self.call('Dr P. Rohan Mehta', 'POST', '/api/doctors/%d/status' % self.doc('Dr P. Rohan Mehta'), {'status': 'in'})

    def test_switched_off_staff_is_logged_out(self):
        nurse = self.who('Sr. Grace Mary')
        tok = self.call(None, 'POST', '/api/login', {'username': 'grace', 'password': 'Demo@2026'})['_set_cookie']
        self.call('Dr A. Meera', 'POST', '/api/admin/staff', {'id': nurse['id'], 'active': 0})
        self.assertIsNone(self.app.staff_for(tok))


class Audit(Base):
    def test_actions_are_recorded_with_name(self):
        p = self.new_patient()
        row = self.app.one("SELECT * FROM audit_log WHERE action='patient.create' AND entity_id=?", (p['id'],))
        self.assertEqual(row['staff_name'], 'Anita Reddy')
        self.assertNotIn('Test Patient', row['detail'])

    def test_audit_log_cannot_be_changed_or_deleted(self):
        self.new_patient()
        for sql in ('UPDATE audit_log SET staff_name=\'x\'', 'DELETE FROM audit_log'):
            with self.assertRaises(sqlite3.DatabaseError):
                self.app.db.execute(sql)
        self.assertTrue(self.app.one('SELECT COUNT(*) n FROM audit_log')['n'] > 0)

    def test_password_is_never_written_to_the_log(self):
        res = self.call('Dr A. Meera', 'POST', '/api/admin/staff', {'name': 'New Nurse', 'role': 'nurse', 'active': 1})
        for r in self.app.q('SELECT detail FROM audit_log'):
            self.assertNotIn(res['temp_password'], r['detail'] or '')
            self.assertNotIn('Demo@2026', r['detail'] or '')


class Beds(Base):
    def test_admit_and_discharge(self):
        p = self.new_patient()
        bed = self.app.one("SELECT id FROM beds WHERE status='vacant'")['id']
        body = {'patient_id': p['id'], 'bed_id': bed, 'doctor_id': self.doc('Dr A. Meera'), 'diagnosis': 'Cellulitis'}
        aid = self.call('Anita Reddy', 'POST', '/api/admissions', body)['id']
        self.assertEqual(self.app.one('SELECT status FROM beds WHERE id=?', (bed,))['status'], 'occupied')
        other = self.new_patient('Other One', '9000000077')
        self.denied(409, 'Anita Reddy', 'POST', '/api/admissions', dict(body, patient_id=other['id']))
        self.denied(409, 'Sr. Grace Mary', 'POST', '/api/beds/%d/status' % bed, {'status': 'vacant'})
        self.call('Sr. Grace Mary', 'POST', '/api/admissions/%d/discharge' % aid)
        self.assertEqual(self.app.one('SELECT status FROM beds WHERE id=?', (bed,))['status'], 'cleaning')
        self.call('Sr. Grace Mary', 'POST', '/api/beds/%d/status' % bed, {'status': 'vacant'})


class Updates(Base):
    def setUp(self):
        super().setUp()
        owner = 'Dr A. Meera'
        self.call(owner, 'POST', '/api/admin/target', {'label': 'Owners', 'chat_id': '111', 'topics': ['summary', 'ip', 'doctor'], 'dept_ids': []})
        self.call(owner, 'POST', '/api/admin/target', {'label': 'Ortho group', 'chat_id': '-222', 'topics': ['doctor'], 'dept_ids': [self.dept('ORT')]})

    def test_department_filter_and_no_patient_names(self):
        self.call('Anita Reddy', 'POST', '/api/doctors/%d/status' % self.doc('Dr A. Meera'), {'status': 'surgery'})
        self.call('Anita Reddy', 'POST', '/api/doctors/%d/status' % self.doc('Dr S. Farhan Ali'), {'status': 'in'})
        p = self.new_patient('Secret Name')
        bed = self.app.one("SELECT id FROM beds WHERE status='vacant'")['id']
        self.call('Anita Reddy', 'POST', '/api/admissions', {'patient_id': p['id'], 'bed_id': bed, 'doctor_id': self.doc('Dr A. Meera')})
        self.call('Dr A. Meera', 'POST', '/api/admin/summary-now')
        self.app.flush_outbox()
        self.assertEqual(len([m for m in self.sent if m[0] == '111']), 4)
        ortho = [m for m in self.sent if m[0] == '-222']
        self.assertEqual(len(ortho), 1)
        self.assertIn('Farhan', ortho[0][1])
        self.assertTrue(all('Secret Name' not in text for _, text in self.sent))

    def test_messages_wait_when_internet_is_down(self):
        def offline(chat, text):
            raise OSError('no internet')
        self.app.sender = offline
        self.call('Dr A. Meera', 'POST', '/api/admin/summary-now')
        self.assertEqual(self.app.flush_outbox(), 0)
        self.app.sender = lambda chat, text: self.sent.append((chat, text))
        self.assertEqual(self.app.flush_outbox(), 1)
        self.assertEqual(self.app.flush_outbox(), 0)

    def test_bot_token_is_never_sent_to_the_browser(self):
        self.call('Dr A. Meera', 'POST', '/api/admin/settings', {'tg_token': '123:SECRET'})
        self.assertNotIn('SECRET', str(self.call('Dr A. Meera', 'GET', '/api/admin/all')))


class Backup(Base):
    def test_backup_can_be_opened(self):
        path = self.app.backup()
        con = sqlite3.connect(path)
        self.assertTrue(con.execute('SELECT COUNT(*) FROM patients').fetchone()[0] > 0)
        con.close()


if __name__ == '__main__':
    unittest.main()
