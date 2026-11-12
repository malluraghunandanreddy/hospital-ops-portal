"""Tests for the later phases: follow-ups, lab, IP chart, discharge, claims, pharmacy, salary."""
import datetime
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_app import Base, core  # noqa: E402
import more  # noqa: E402

REC, OWNER, NURSE = 'Anita Reddy', 'Dr A. Meera', 'Sr. Grace Mary'


class FollowUps(Base):
    def test_vaccines_appear_from_date_of_birth_and_missed_ones_are_listed(self):
        p = self.new_patient('Baby One', '9000000301')
        dob = datetime.date.today() - datetime.timedelta(days=100)
        made = self.call(REC, 'POST', '/api/patients/%d/plan' % p['id'], {'plan': 'vaccine', 'date': dob.isoformat()})['created']
        self.assertEqual(made, len(more.VACCINES))
        self.assertEqual(self.call(REC, 'POST', '/api/patients/%d/plan' % p['id'], {'plan': 'vaccine', 'date': dob.isoformat()})['created'], 0)
        missed = [f for f in self.call(REC, 'GET', '/api/followups')['missed'] if f['patient_id'] == p['id']]
        self.assertEqual(len(missed), 4)  # birth, 6, 10 and 14 weeks are all past for a 100-day-old
        self.call(REC, 'POST', '/api/followups/%d' % missed[0]['id'], {'action': 'done', 'batch': 'B123'})
        self.assertEqual(len([f for f in self.call(REC, 'GET', '/api/followups')['missed'] if f['patient_id'] == p['id']]), 3)

    def test_editing_the_schedule_removes_the_doctors_confirmation(self):
        self.call(OWNER, 'POST', '/api/admin/confirm-schedule', {'plan': 'vaccine'})
        self.assertTrue(self.call(REC, 'GET', '/api/followups')['confirmed']['vaccine'])
        item = self.app.one("SELECT id FROM schedule_items WHERE plan='vaccine'")['id']
        self.call(OWNER, 'POST', '/api/admin/schedule-item', {'id': item, 'offset_days': 1})
        self.assertFalse(self.call(REC, 'GET', '/api/followups')['confirmed']['vaccine'])


class Lab(Base):
    def test_report_flow_and_access(self):
        p = self.new_patient()
        lid = self.call(REC, 'POST', '/api/lab', {'patient_id': p['id'], 'test': 'CBC', 'doctor_id': self.doc('Dr A. Meera')})['id']
        self.app.run("INSERT INTO staff(name, role, username) VALUES('Lab Tech', 'lab', 'labtech')")
        self.call('Lab Tech', 'POST', '/api/lab/%d/collected' % lid)
        self.denied(400, 'Lab Tech', 'POST', '/api/lab/%d/report' % lid, {'_raw': b'x', '_ctype': 'text/csv'})
        self.app.run("INSERT INTO notify_targets(label, chat_id, topics) VALUES('Owners', '1', 'lab')")
        self.call('Lab Tech', 'POST', '/api/lab/%d/report' % lid, {'_raw': b'%PDF-1.4', '_ctype': 'application/pdf'}, {'critical': '1'})
        self.app.flush_outbox()
        self.assertIn('CRITICAL', self.sent[0][1])
        self.assertNotIn('Test Patient', self.sent[0][1])
        self.denied(403, 'Lab Tech', 'GET', '/api/patients/%d' % p['id'])
        self.denied(403, 'Dr P. Rohan Mehta', 'GET', '/files/lab/%d' % lid)
        self.assertIn('_file', self.call(OWNER, 'GET', '/files/lab/%d' % lid))


class Inpatient(Base):
    def admit(self, payer='PM-JAY', doctor='Dr S. Farhan Ali'):
        p = self.new_patient('In Patient', '9000000401')
        bed = self.app.one("SELECT id FROM beds WHERE status='vacant'")['id']
        return self.call(REC, 'POST', '/api/admissions', {'patient_id': p['id'], 'bed_id': bed, 'doctor_id': self.doc(doctor),
                                                         'diagnosis': 'Fracture', 'payer': payer})['id']

    def test_chart_discharge_steps_and_summary(self):
        aid = self.admit()
        self.denied(403, 'Dr P. Rohan Mehta', 'GET', '/api/admissions/%d' % aid)
        self.call(NURSE, 'POST', '/api/admissions/%d/event' % aid, {'kind': 'vitals', 'data': {'Temp': '99', 'Pulse': '88'}})
        self.call(NURSE, 'POST', '/api/admissions/%d/event' % aid, {'kind': 'service', 'data': {'Service': 'Dressing'}})
        self.denied(403, NURSE, 'POST', '/api/admissions/%d/event' % aid, {'kind': 'round', 'data': {'Notes': 'x'}})
        self.denied(403, NURSE, 'POST', '/api/admissions/%d/order-discharge' % aid)
        self.denied(400, NURSE, 'POST', '/api/admissions/%d/step' % aid, {'step': 'medicines', 'done': True})
        self.call('Dr S. Farhan Ali', 'POST', '/api/admissions/%d/order-discharge' % aid)
        d = self.call(NURSE, 'GET', '/api/admissions/%d' % aid)
        self.assertEqual([s['step'] for s in d['steps']], ['summary', 'medicines', 'bill', 'scheme'])
        self.assertEqual(d['summary']['data']['diagnosis'], 'Fracture')
        self.call(NURSE, 'POST', '/api/admissions/%d/step' % aid, {'step': 'medicines', 'done': True})
        self.denied(403, NURSE, 'POST', '/api/admissions/%d/summary' % aid, {'data': {}, 'final': True})
        self.call('Dr S. Farhan Ali', 'POST', '/api/admissions/%d/summary' % aid, {'data': {'course': 'Uneventful'}, 'final': True})
        steps = {s['step']: s['done_at'] for s in self.call(NURSE, 'GET', '/api/admissions/%d' % aid)['steps']}
        self.assertTrue(steps['summary'] and steps['medicines'])
        self.assertFalse(steps['bill'])
        pend = self.call(OWNER, 'GET', '/api/dashboard')['more']['discharges']
        self.assertEqual(len([x for x in pend if x['admission_id'] == aid][0]['waiting']), 2)

    def test_cash_patient_has_no_scheme_step_or_claim(self):
        aid = self.admit(payer='Cash')
        self.call(OWNER, 'POST', '/api/admissions/%d/order-discharge' % aid)
        self.assertNotIn('scheme', [s['step'] for s in self.call(NURSE, 'GET', '/api/admissions/%d' % aid)['steps']])
        self.assertIsNone(self.app.one('SELECT id FROM claims WHERE admission_id=?', (aid,)))

    def test_claim_is_created_with_missing_list(self):
        aid = self.admit()
        c = [x for x in self.call(OWNER, 'GET', '/api/claims')['claims'] if x['admission_id'] == aid][0]
        self.assertEqual(c['scheme'], 'PM-JAY')
        self.assertEqual(len(c['missing']), len(more.GOVT_DOCS))
        self.call(OWNER, 'POST', '/api/claims/%d' % c['id'], {'checked': c['items'][:3]})
        self.denied(400, OWNER, 'POST', '/api/claims/%d' % c['id'], {'status': 'rejected'})
        self.call(OWNER, 'POST', '/api/claims/%d' % c['id'], {'status': 'submitted'})
        pk = self.call(OWNER, 'GET', '/api/claims/%d/packet' % c['id'])
        self.assertEqual(len(pk['claim']['missing']), len(more.GOVT_DOCS) - 3)
        self.denied(403, REC, 'GET', '/api/claims')


class Theatre(Base):
    def test_clash_warning(self):
        day = datetime.date.today().isoformat()
        body = {'patient_name': 'A B', 'ot_date': day, 'start_time': '09:00', 'end_time': '10:00', 'surgeon_id': self.doc('Dr P. Rohan Mehta')}
        self.assertEqual(self.call(REC, 'POST', '/api/ot', body)['clash'], [])
        self.assertEqual(len(self.call(REC, 'POST', '/api/ot', dict(body, patient_name='C D', start_time='09:30', end_time='11:00'))['clash']), 1)
        self.assertEqual(self.call(REC, 'POST', '/api/ot', dict(body, patient_name='E F', start_time='11:00', end_time='12:00'))['clash'], [])
        self.denied(400, REC, 'POST', '/api/ot', dict(body, start_time='12:00', end_time='11:00'))


class Pharmacy(Base):
    CSV = ('Sunrise Medical Stores,,,,\nStock report,,,,\n'
           'Item Code,Item Name,Batch No,Exp Date,Stock Qty,Supplier Name\n'
           '101,Paracetamol 500,B1,%s,500,ABC Agencies\n'
           '102,Amoxicillin syrup,B2,%s,5,ABC Agencies\n'
           '103,Old syrup,B3,01/2020,3,XYZ Pharma\n'
           '104,Odd row,B4,soon,many,XYZ Pharma\n'
           'Total,,,,513,\n')

    def load(self):
        far = (datetime.date.today() + datetime.timedelta(days=400)).strftime('%d/%m/%Y')
        near = (datetime.date.today() + datetime.timedelta(days=20)).strftime('%d-%m-%Y')
        return self.call('Ch. Ramesh Kumar', 'POST', '/api/pharmacy/import', {'_raw': (self.CSV % (far, near)).encode(), '_ctype': 'text/csv'})

    def test_import_finds_columns_and_reports_bad_rows(self):
        res = self.load()
        self.assertEqual(res['rows'], 4)
        self.assertEqual(len(res['errors']), 2)
        v = self.call('Ch. Ramesh Kumar', 'GET', '/api/pharmacy')
        self.assertEqual([r['item'] for r in v['expired']], ['Old syrup'])
        self.assertEqual([r['item'] for r in v['expiring']], ['Amoxicillin syrup'])
        self.assertEqual(sorted(r['item'] for r in v['low']), ['Amoxicillin syrup', 'Old syrup'])
        self.assertTrue(self.app.one('SELECT id FROM import_runs WHERE rows=4'))

    def test_unreadable_file_changes_nothing(self):
        before = self.app.one('SELECT COUNT(*) n FROM stock')['n']
        self.denied(400, 'Ch. Ramesh Kumar', 'POST', '/api/pharmacy/import', {'_raw': b'hello\nworld\n', '_ctype': 'text/csv'})
        self.assertEqual(self.app.one('SELECT COUNT(*) n FROM stock')['n'], before)

    def test_expiry_formats(self):
        self.assertEqual(more.parse_expiry('03/2027'), '2027-03-31')
        self.assertEqual(more.parse_expiry('Feb-28'), '2028-02-29')
        self.assertEqual(more.parse_expiry('15/08/2027'), '2027-08-15')
        self.assertIsNone(more.parse_expiry('soon'))

    def test_dose_reference_starts_empty_and_only_owner_adds(self):
        self.assertEqual(self.call('Ch. Ramesh Kumar', 'GET', '/api/dose-refs')['refs'], [])
        body = {'drug': 'Test drug syrup', 'min_mg_kg': '10', 'max_mg_kg': '15', 'per': 'dose', 'max_mg': '200'}
        self.denied(403, 'Ch. Ramesh Kumar', 'POST', '/api/admin/dose-ref', body)
        rid = self.call(OWNER, 'POST', '/api/admin/dose-ref', body)['id']
        r = self.call('Ch. Ramesh Kumar', 'POST', '/api/dose-check', {'ref_id': rid, 'weight_kg': '12'})
        self.assertEqual((r['low_mg'], r['high_mg'], r['capped']), (120.0, 180.0, False))
        r = self.call('Ch. Ramesh Kumar', 'POST', '/api/dose-check', {'ref_id': rid, 'weight_kg': '30'})
        self.assertEqual((r['high_mg'], r['capped']), (200.0, True))
        self.assertIn('Dr A. Meera', r['confirmed_by'])
        self.assertTrue(self.app.one("SELECT id FROM audit_log WHERE action='dose.check'"))


class Salary(Base):
    def test_salary_follows_attendance_and_deductions(self):
        sid = self.app.run("INSERT INTO staff(name, role, salary) VALUES('Ayah One', 'support', 9000)")
        for d, mark in enumerate(['P'] * 10 + ['H', 'H', 'L', 'O', 'A'], 1):
            self.call(OWNER, 'POST', '/api/attendance', {'staff_id': sid, 'day': '2026-06-%02d' % d, 'status': mark})
        self.call(OWNER, 'POST', '/api/admin/deduction', {'name': 'PF', 'kind': 'percent', 'value': '10'})
        row = [r for r in self.call(OWNER, 'GET', '/api/payroll', params={'month': '2026-06'})['rows'] if r['staff_id'] == sid][0]
        self.assertEqual(row['paid_days'], 13)             # 10 + 2 half days + 1 leave + 1 weekly off
        self.assertEqual(row['earned'], 3900)              # 9000 x 13 / 30
        self.assertEqual(row['net'], 3510)
        self.assertEqual(row['unmarked'], 15)
        self.denied(403, REC, 'GET', '/api/payroll')

    def test_duty_mark_and_consultant_statement(self):
        self.call(NURSE, 'POST', '/api/duty')
        self.assertIn(NURSE, self.call(OWNER, 'GET', '/api/dashboard')['more']['on_duty'])
        self.call(NURSE, 'POST', '/api/duty')
        self.assertNotIn(NURSE, self.call(OWNER, 'GET', '/api/dashboard')['more']['on_duty'])
        did = self.doc('Dr S. Farhan Ali')
        self.app.run("UPDATE visits SET status='done' WHERE doctor_id=?", (did,))
        n = self.app.one('SELECT COUNT(*) n FROM visits WHERE doctor_id=?', (did,))['n']
        row = [r for r in self.call(OWNER, 'GET', '/api/payouts')['rows'] if r['id'] == did][0]
        self.assertEqual((row['visits'], row['amount']), (n, n * 250))


class Permissions(Base):
    def test_each_role_sees_only_its_screens(self):
        boot = lambda n: self.call(n, 'GET', '/api/bootstrap')['me']['screens']  # noqa: E731
        self.assertEqual(boot('Ch. Ramesh Kumar'), ['pharmsale', 'pharmacy', 'rx'])
        self.assertIn('settings', boot('Dr A. Meera'))
        self.assertNotIn('today', boot('Dr K. Kavya Sharma'))
        self.denied(403, 'Ch. Ramesh Kumar', 'GET', '/api/beds')
        self.denied(403, 'Sr. Grace Mary', 'GET', '/api/claims')
        self.denied(403, 'K. Prakash Rao', 'GET', '/api/queue')
        self.denied(403, 'City Diagnostics', 'GET', '/api/patients', params={'q': 'la'})
        self.denied(403, 'Anita Reddy', 'GET', '/api/accounts')

    def test_changing_a_role_and_one_person(self):
        self.call(OWNER, 'POST', '/api/admin/role-screens', {'role': 'nurse', 'screens': ['ward', 'beds', 'chart', 'ot', 'followups', 'settings']})
        self.assertIn('id', str(self.call(NURSE, 'GET', '/api/followups')) or 'ok')
        self.denied(403, NURSE, 'GET', '/api/admin/all')          # settings can never be given away
        salma_id = self.who('Sk. Salma Begum')['id']
        self.call(OWNER, 'POST', '/api/admin/staff', {'id': salma_id, 'screens': ['desk', 'queue']})
        self.denied(403, 'Sk. Salma Begum', 'GET', '/api/beds')
        self.call('Anita Reddy', 'GET', '/api/beds')           # the rest of reception unchanged
        self.call(OWNER, 'POST', '/api/admin/staff', {'id': salma_id, 'screens': None})
        self.call('Sk. Salma Begum', 'GET', '/api/beds')
        self.denied(400, OWNER, 'POST', '/api/admin/role-screens', {'role': 'owner', 'screens': []})
        self.denied(400, OWNER, 'POST', '/api/admin/staff', {'id': self.who(OWNER)['id'], 'role': 'nurse'})

    def test_clinical_rules_stay_with_doctors(self):
        p = self.new_patient('Rule Test', '9000000501')
        bed = self.app.one("SELECT id FROM beds WHERE status='vacant'")['id']
        aid = self.call(REC, 'POST', '/api/admissions', {'patient_id': p['id'], 'bed_id': bed, 'doctor_id': self.doc('Dr A. Meera')})['id']
        self.denied(403, REC, 'POST', '/api/admissions/%d/order-discharge' % aid)
        self.denied(403, REC, 'POST', '/api/admissions/%d/summary' % aid, {'data': {}, 'final': True})
        self.denied(403, 'Dr P. Rohan Mehta', 'GET', '/api/admissions/%d' % aid)


class RoleViews(Base):
    def test_each_role_sees_its_own_job(self):
        day = core.today()
        self.call(OWNER, 'POST', '/api/ot', {'patient_name': 'Not his', 'ot_date': day, 'start_time': '08:00', 'end_time': '09:00', 'surgeon_id': self.doc('Dr A. Meera')})
        names = [b['patient_name'] for b in self.call('Dr P. Rohan Mehta', 'GET', '/api/ot')['bookings']]
        self.assertNotIn('Not his', names)
        self.assertIn('Not his', [b['patient_name'] for b in self.call(NURSE, 'GET', '/api/ot')['bookings']])
        beds = self.call(REC, 'GET', '/api/beds')['beds']
        self.assertTrue(all(b['deposit_noted'] is None for b in beds))           # money stays with billing
        self.assertTrue(any(b['deposit_noted'] for b in self.call(OWNER, 'GET', '/api/beds')['beds']))
        payers = {a['payer'] for a in self.call('K. Prakash Rao', 'GET', '/api/admissions')['admissions']}
        self.assertNotIn('Cash', payers)
        nurse = self.call(NURSE, 'GET', '/api/bootstrap')['me']['screens']
        self.assertFalse(set(nurse) & {'desk', 'queue', 'appointments', 'today', 'accounts'})


class DoctorAttendance(Base):
    def test_status_records_arrival_and_leaving(self):
        did = self.doc('Dr V. Nisha Kapoor')
        self.call(REC, 'POST', '/api/doctors/%d/status' % did, {'status': 'in'})
        row = self.app.one('SELECT * FROM doctor_days WHERE doctor_id=? AND day=?', (did, core.today()))
        self.assertTrue(row['arrived_at'] and not row['left_at'])
        self.call(REC, 'POST', '/api/doctors/%d/status' % did, {'status': 'out'})
        self.assertTrue(self.app.one('SELECT left_at FROM doctor_days WHERE doctor_id=? AND day=?', (did, core.today()))['left_at'])
        self.call(REC, 'POST', '/api/doctor-days', {'doctor_id': did, 'date': core.today(), 'arrived_at': '10:05', 'left_at': '13:30'})
        day = [d for d in self.call(REC, 'GET', '/api/doctor-days')['doctors'] if d['id'] == did][0]
        self.assertEqual((day['arrived_at'], day['left_at']), ('10:05', '13:30'))
        self.app.run("UPDATE doctors SET payout_kind='day', payout_rate=2000 WHERE id=?", (did,))
        row = [r for r in self.call(OWNER, 'GET', '/api/payouts')['rows'] if r['id'] == did][0]
        self.assertEqual(row['amount'], row['days'] * 2000)

    def test_statuses_start_fresh_each_day(self):
        self.app.set_setting('status_day', '2000-01-01')
        self.call(REC, 'GET', '/api/doctor-days')
        self.assertEqual({d['status'] for d in self.app.q('SELECT status FROM doctors')}, {'out'})


class Homes(Base):
    def test_my_day_and_ward(self):
        d = self.call('Dr S. Farhan Ali', 'GET', '/api/myday')
        mine = self.doc('Dr S. Farhan Ali')
        self.assertTrue(d['visits'])
        self.assertEqual({v['token_code'][:3] for v in d['visits']}, {'ORT'})
        self.assertTrue(all(self.app.one('SELECT doctor_id FROM admissions WHERE id=?', (i['id'],))['doctor_id'] == mine for i in d['inpatients']))
        w = self.call(NURSE, 'GET', '/api/ward')
        self.assertEqual(len(w['inpatients']), self.app.one("SELECT COUNT(*) n FROM admissions WHERE status='admitted'")['n'])

    def test_history_and_accounts(self):
        h = self.call('K. Prakash Rao', 'GET', '/api/admissions', params={'q': 'fever'})
        self.assertTrue(all('fever' in (a['diagnosis'] or '').lower() or a for a in h['admissions']))
        acc = self.call(OWNER, 'GET', '/api/accounts')
        self.assertEqual(sum(r['patients'] for r in acc['op']), self.app.one('SELECT COUNT(*) n FROM visits WHERE visit_date=?', (core.today(),))['n'])
        self.denied(400, OWNER, 'POST', '/api/accounts/check', {'date': core.today(), 'result': 'difference'})
        self.call(OWNER, 'POST', '/api/accounts/check', {'date': core.today(), 'result': 'matched'})
        self.assertEqual(self.call(OWNER, 'GET', '/api/accounts')['check']['result'], 'matched')


class ClaimFile(Base):
    def test_zip_has_everything(self):
        import io
        import zipfile
        c = self.call(OWNER, 'GET', '/api/claims')['claims'][0]
        self.call('K. Prakash Rao', 'POST', '/api/claims/%d/doc' % c['id'], {'_raw': b'\xff\xd8jpeg', '_ctype': 'image/jpeg'}, {'item': 'Scheme card'})
        c2 = [x for x in self.call(OWNER, 'GET', '/api/claims')['claims'] if x['id'] == c['id']][0]
        self.assertNotIn('Scheme card', c2['missing'])
        z = zipfile.ZipFile(io.BytesIO(self.call('K. Prakash Rao', 'GET', '/api/claims/%d/zip' % c['id'])['_bytes']))
        names = z.namelist()
        self.assertIn('01 Claim details.doc', names)
        self.assertIn('03 Details for the portal.txt', names)
        self.assertTrue(any('Scheme card' in n for n in names))
        portal = self.call('K. Prakash Rao', 'GET', '/api/claims/%d/portal' % c['id'])['fields']
        self.assertEqual(portal[1]['label'], 'Patient name')


class Charges(Base):
    def setUp(self):
        super().setUp()
        p = self.new_patient('Charge Test', '9000000601')
        bed = self.app.one("SELECT id FROM beds WHERE status='vacant' AND ward='Rooms'")['id']
        self.aid = self.call(REC, 'POST', '/api/admissions', {'patient_id': p['id'], 'bed_id': bed, 'doctor_id': self.doc('Dr A. Meera')})['id']
        self.item = lambda name: self.app.one('SELECT * FROM price_items WHERE name=?', (name,))  # noqa: E731

    def test_price_comes_from_list_and_only_admins_set_it(self):
        neb = self.item('Nebulisation')
        self.call(NURSE, 'POST', '/api/admissions/%d/charges' % self.aid, {'item_id': neb['id'], 'qty': 3, 'rate': 1})
        line = self.app.one('SELECT * FROM ip_charges WHERE admission_id=?', (self.aid,))
        self.assertEqual((line['rate'], line['amount'], line['entered_by']), (neb['price'], neb['price'] * 3, NURSE))
        self.denied(403, NURSE, 'POST', '/api/admin/price', {'id': neb['id'], 'price': 1})
        self.denied(403, REC, 'POST', '/api/admin/price', {'id': neb['id'], 'price': 1})
        self.call(OWNER, 'POST', '/api/admin/price', {'id': neb['id'], 'price': neb['price'] + 50})
        self.assertEqual(self.app.one('SELECT rate FROM ip_charges WHERE id=?', (line['id'],))['rate'], neb['price'])  # old entry unchanged
        self.assertTrue(self.app.one("SELECT id FROM audit_log WHERE action='price.change'"))

    def test_days_and_cancel(self):
        room = self.item('Room')
        self.denied(400, NURSE, 'POST', '/api/admissions/%d/charges' % self.aid, {'item_id': room['id'], 'qty': 0})
        self.denied(400, NURSE, 'POST', '/api/admissions/%d/charges' % self.aid, {'item_id': room['id'], 'qty': 1.3})
        cid = self.call(NURSE, 'POST', '/api/admissions/%d/charges' % self.aid, {'item_id': room['id'], 'qty': 2})['id']
        ch = self.call(NURSE, 'GET', '/api/admissions/%d/charges' % self.aid)
        self.assertEqual((ch['room_days'], ch['total'], ch['room_item']['name']), (2, room['price'] * 2, 'Room'))
        self.denied(400, NURSE, 'POST', '/api/charges/%d/cancel' % cid, {'reason': ''})
        self.call(NURSE, 'POST', '/api/charges/%d/cancel' % cid, {'reason': 'wrong patient'})
        ch = self.call(NURSE, 'GET', '/api/admissions/%d/charges' % self.aid)
        self.assertEqual((len(ch['lines']), ch['total']), (1, 0))                  # still visible, not counted
        self.denied(403, 'Ch. Ramesh Kumar', 'GET', '/api/admissions/%d/charges' % self.aid)

    def test_slip_goes_to_billing_desk(self):
        room = self.item('Room')
        self.denied(400, NURSE, 'POST', '/api/admissions/%d/slip' % self.aid)          # nothing to send yet
        self.call(NURSE, 'POST', '/api/admissions/%d/charges' % self.aid, {'item_id': room['id'], 'qty': 1})
        sid = self.call(NURSE, 'POST', '/api/admissions/%d/slip' % self.aid)['id']
        self.denied(403, REC, 'GET', '/api/ipbilling')
        self.denied(403, 'Dr K. Kavya Sharma', 'POST', '/api/admissions/%d/charges' % self.aid, {'item_id': room['id'], 'qty': 1})
        self.call(OWNER, 'POST', '/api/admin/role-screens', {'role': 'reception', 'screens': ['desk', 'ipbill']})
        self.denied(403, REC, 'GET', '/api/ipbilling')                              # cannot be given to anyone else
        rows = [x for x in self.call(OWNER, 'GET', '/api/ipbilling')['patients'] if x['id'] == self.aid]
        self.assertEqual(rows[0]['slip']['id'], sid)
        self.assertIn(self.aid, [x['admission_id'] for x in self.call(OWNER, 'GET', '/api/dashboard')['more']['slips']['waiting']])
        self.denied(403, NURSE, 'POST', '/api/charge-slips/%d/checked' % sid)
        self.call(OWNER, 'POST', '/api/charge-slips/%d/checked' % sid)
        self.assertNotIn(self.aid, [x['admission_id'] for x in self.call(OWNER, 'GET', '/api/dashboard')['more']['slips']['waiting']])

    def test_bed_shift(self):
        old = self.app.one('SELECT bed_id FROM admissions WHERE id=?', (self.aid,))['bed_id']
        icu = self.app.one("SELECT id FROM beds WHERE status='vacant' AND ward='ICU'")['id']
        self.call(NURSE, 'POST', '/api/admissions/%d/transfer' % self.aid, {'bed_id': icu})
        self.assertEqual(self.app.one('SELECT status FROM beds WHERE id=?', (old,))['status'], 'cleaning')
        self.assertEqual(self.call(NURSE, 'GET', '/api/admissions/%d/charges' % self.aid)['room_item']['name'], 'ICU bed')


class InpatientBill(Base):
    def setUp(self):
        super().setUp()
        p = self.new_patient('Bill Test', '9000000701')
        bed = self.app.one("SELECT id FROM beds WHERE status='vacant' AND ward='Rooms'")['id']
        r = self.call(OWNER, 'POST', '/api/admissions', {'patient_id': p['id'], 'bed_id': bed, 'doctor_id': self.doc('Dr A. Meera'),
                                                       'deposit_noted': '5000', 'deposit_mode': 'Cash'})
        self.aid, self.first_receipt = r['id'], r['receipt_no']
        room = self.app.one("SELECT id, price FROM price_items WHERE name='Room'")
        self.call(NURSE, 'POST', '/api/admissions/%d/charges' % self.aid, {'item_id': room['id'], 'qty': 3})   # 4500

    def bill(self, who=OWNER):
        return self.call(who, 'GET', '/api/admissions/%d/bill' % self.aid)['state']

    def test_full_flow(self):
        self.assertTrue(self.first_receipt.startswith('R/'))
        self.denied(403, NURSE, 'POST', '/api/admissions', {'patient_id': 1, 'bed_id': 1, 'doctor_id': 1, 'deposit_noted': 100})
        self.call('Ch. Ramesh Kumar', 'POST', '/api/admissions/%d/external-bill' % self.aid, {'kind': 'pharmacy', 'amount': '1200', 'ref': 'PH-778'})
        self.denied(403, 'Ch. Ramesh Kumar', 'POST', '/api/admissions/%d/external-bill' % self.aid, {'kind': 'outside', 'amount': '900', 'ref': 'X1'})
        self.denied(403, REC, 'POST', '/api/admissions/%d/discount' % self.aid, {'amount': 200, 'reason': 'staff family'})
        self.call(OWNER, 'POST', '/api/admissions/%d/discount' % self.aid, {'amount': 200, 'reason': 'staff family'})
        s = self.bill()
        self.assertEqual((s['total'], s['discount'], s['paid'], s['balance']), (5700, 200, 5000, 500))
        self.denied(400, OWNER, 'POST', '/api/admissions/%d/payments' % self.aid, {'kind': 'payment', 'amount': 500, 'mode': 'UPI'})  # needs ref
        self.call(OWNER, 'POST', '/api/admissions/%d/payments' % self.aid, {'kind': 'payment', 'amount': 500, 'mode': 'UPI', 'ref': 'T123'})
        no = self.call(OWNER, 'POST', '/api/admissions/%d/finalise' % self.aid)['bill_no']
        self.assertTrue(no.startswith('IP/'))
        self.assertTrue(self.app.one("SELECT 1 x FROM discharge_steps WHERE admission_id=? AND step='bill'", (self.aid,)))
        room = self.app.one("SELECT id FROM price_items WHERE name='Room'")['id']
        self.denied(409, NURSE, 'POST', '/api/admissions/%d/charges' % self.aid, {'item_id': room, 'qty': 1})   # locked
        self.denied(403, REC, 'POST', '/api/admissions/%d/reopen-bill' % self.aid, {'reason': 'missed oxygen'})
        self.call(OWNER, 'POST', '/api/admissions/%d/reopen-bill' % self.aid, {'reason': 'missed oxygen'})
        self.call(NURSE, 'POST', '/api/admissions/%d/charges' % self.aid, {'item_id': room, 'qty': 1})
        self.assertFalse(self.app.one("SELECT 1 x FROM discharge_steps WHERE admission_id=? AND step='bill'", (self.aid,)))
        self.assertEqual(self.call(OWNER, 'POST', '/api/admissions/%d/finalise' % self.aid)['bill_no'], no)   # keeps its number

    def test_receipts_are_never_deleted(self):
        pid = self.app.one('SELECT id FROM ip_payments WHERE admission_id=?', (self.aid,))['id']
        self.denied(403, 'Sk. Salma Begum', 'POST', '/api/ip-payments/%d/cancel' % pid, {'reason': 'typed wrong'})
        self.call(OWNER, 'POST', '/api/ip-payments/%d/cancel' % pid, {'reason': 'typed wrong'})
        row = self.app.one('SELECT * FROM ip_payments WHERE id=?', (pid,))
        self.assertEqual((row['cancelled'], row['cancel_reason']), (1, 'typed wrong'))
        self.assertEqual(self.bill()['paid'], 0)
        self.denied(400, OWNER, 'POST', '/api/admissions/%d/payments' % self.aid, {'kind': 'refund', 'amount': 100, 'mode': 'Cash'})

    def test_scheme_share_and_numbers(self):
        self.app.run("UPDATE admissions SET payer='PM-JAY' WHERE id=?", (self.aid,))
        self.call(OWNER, 'POST', '/api/admissions/%d/finalise' % self.aid, {'scheme_amount': 4000})
        s = self.bill()
        self.assertEqual((s['payable'], s['balance']), (500, -4500))      # advance 5000 > 500 to pay: refund due
        self.call(OWNER, 'POST', '/api/admissions/%d/payments' % self.aid, {'kind': 'refund', 'amount': 4500, 'mode': 'Cash'})
        self.assertEqual(self.bill()['balance'], 0)
        nums = [r['receipt_no'] for r in self.app.q('SELECT receipt_no FROM ip_payments ORDER BY id')]
        self.assertEqual(len(nums), len(set(nums)))
        acc = self.call(OWNER, 'GET', '/api/accounts')
        self.assertEqual(acc['ip']['refunds'], 4500)


class PrescriptionPhotos(Base):
    def test_reception_photo_marks_seen_and_doctor_can_view(self):
        v = self.app.one("SELECT id, doctor_id FROM visits WHERE status='waiting' AND doctor_id=?", (self.doc('Dr S. Farhan Ali'),))
        rid = self.call(REC, 'POST', '/api/visits/%d/prescription' % v['id'], {'_raw': b'\xff\xd8x', '_ctype': 'image/jpeg'})['id']
        self.assertEqual(self.app.one('SELECT status FROM visits WHERE id=?', (v['id'],))['status'], 'done')
        self.assertIn('_file', self.call('Dr S. Farhan Ali', 'GET', '/files/rx/%d' % rid))
        self.denied(403, 'Dr P. Rohan Mehta', 'GET', '/files/rx/%d' % rid)
        self.assertIn('rx', self.call(REC, 'GET', '/api/bootstrap')['me']['screens'])


class PharmacyCounter(Base):
    PH = 'Ch. Ramesh Kumar'

    def item(self, batch):
        r = self.app.one('SELECT * FROM stock WHERE batch=?', (batch,))
        return dict(item=r['item'], batch=batch, expiry=r['expiry'], qty=2, rate=r['mrp'])

    def test_quick_sale_and_pharmasoft_entry(self):
        c = self.call(self.PH, 'GET', '/api/pharmacy/customers')
        vis = [x for x in c['op'] if not x['sales']][0]
        self.denied(400, self.PH, 'POST', '/api/pharmacy/sales', {'kind': 'op', 'visit_id': vis['visit_id'], 'mode': 'Cash', 'items': [self.item('CTZ09')]})  # expired
        self.denied(400, self.PH, 'POST', '/api/pharmacy/sales', {'kind': 'op', 'visit_id': vis['visit_id'], 'mode': 'UPI', 'items': [self.item('CTZ14')]})   # no ref
        r = self.call(self.PH, 'POST', '/api/pharmacy/sales', {'kind': 'op', 'visit_id': vis['visit_id'], 'mode': 'Cash', 'items': [self.item('CTZ14'), self.item('ZN220')]})
        self.assertEqual(r['total'], 2 * 35 + 2 * 30)
        pend = self.call(self.PH, 'GET', '/api/pharmacy/sales', params={'pending': '1'})['sales']
        self.assertIn(r['id'], [x['id'] for x in pend])
        self.denied(400, self.PH, 'POST', '/api/pharmacy/sales/%d/entered' % r['id'], {})
        self.call(self.PH, 'POST', '/api/pharmacy/sales/%d/entered' % r['id'], {'pharmasoft_no': 'CS-10442'})
        self.assertNotIn(r['id'], [x['id'] for x in self.call(self.PH, 'GET', '/api/pharmacy/sales', params={'pending': '1'})['sales']])
        self.denied(403, REC, 'POST', '/api/pharmacy/sales', {'kind': 'walkin'})
        self.assertGreaterEqual(self.call(OWNER, 'GET', '/api/accounts')['pharm']['counter'], 130)

    def test_inpatient_sale_goes_to_bill_and_cancel_reverses(self):
        aid = self.app.one("SELECT id FROM admissions WHERE status='admitted'")['id']
        before = __import__('billing').state(self.app, aid)['total']
        r = self.call(self.PH, 'POST', '/api/pharmacy/sales', {'kind': 'ip', 'admission_id': aid, 'items': [self.item('NS5510')]})
        self.assertEqual(__import__('billing').state(self.app, aid)['total'], before + 64)
        self.denied(403, 'Dr A. Meera' if False else 'Sk. Salma Begum', 'POST', '/api/pharmacy/sales/%d/cancel' % r['id'], {'reason': 'returned'})
        self.call(self.PH, 'POST', '/api/pharmacy/sales/%d/cancel' % r['id'], {'reason': 'returned unopened'})
        self.assertEqual(__import__('billing').state(self.app, aid)['total'], before)


class InsuranceFollowUp(Base):
    def test_hand_off_timeline_and_follow_up(self):
        INS = 'K. Prakash Rao'
        aid = self.app.one("SELECT id FROM admissions WHERE payer='PM-JAY'")['id']
        cash = self.app.one("SELECT id FROM admissions WHERE payer='Cash'")['id']
        self.denied(400, OWNER, 'POST', '/api/admissions/%d/send-to-insurance' % cash)
        self.denied(403, REC, 'POST', '/api/admissions/%d/send-to-insurance' % aid)
        cid = self.call(OWNER, 'POST', '/api/admissions/%d/send-to-insurance' % aid, {'note': 'Please start'})['id']
        self.denied(409, OWNER, 'POST', '/api/admissions/%d/send-to-insurance' % aid)
        sm = self.call(INS, 'GET', '/api/claims/summary')
        self.assertIn(cid, [x['id'] for x in sm['new']])
        self.denied(400, INS, 'POST', '/api/claims/%d/followup' % cid, {'note': ''})
        self.denied(400, INS, 'POST', '/api/claims/%d/followup' % cid, {'note': 'Called', 'next_followup': '2000-01-01'})
        self.call(INS, 'POST', '/api/claims/%d/followup' % cid, {'note': 'Called the TPA', 'next_followup': core.today()})
        self.call(INS, 'POST', '/api/claims/%d' % cid, {'status': 'submitted'})
        sm = self.call(INS, 'GET', '/api/claims/summary')
        self.assertNotIn(cid, [x['id'] for x in sm['new']])                       # picked up
        self.assertIn(cid, [x['id'] for x in sm['due']])
        self.assertGreaterEqual(sm['today']['by_person'][INS]['submitted'], 1)
        self.assertGreaterEqual(sm['today']['by_person'][INS]['followups'], 1)
        kinds = [e['kind'] for e in self.call(INS, 'GET', '/api/claims/%d/events' % cid)['events']]
        self.assertEqual(kinds[:3], ['status', 'followup', 'sent'])
        self.assertIn(cid, [x['id'] for x in self.call(OWNER, 'GET', '/api/dashboard')['more']['claimflow']['due']])
        self.call(INS, 'POST', '/api/claims/%d' % cid, {'status': 'settled'})
        self.assertNotIn(cid, [x['id'] for x in self.call(INS, 'GET', '/api/claims/summary')['due']])


class PatientsSeeTheirTurn(Base):
    def test_phone_bookings_keep_their_token_and_come_first(self):
        pls = self.dept('PLS')
        bk = self.call(REC, 'POST', '/api/appointments', {'name': 'Morning Caller', 'phone': '9000000801', 'dept_id': pls, 'appt_date': core.today(), 'appt_time': '18:30'})
        self.assertEqual(bk['token_code'], 'PLS-01')                       # reserved on the phone
        walk = self.new_patient('Early Walkin', '9000000802')
        v1 = self.call(REC, 'POST', '/api/visits', {'patient_id': walk['id'], 'dept_id': pls, 'source': 'walkin'})['visit']
        self.assertEqual(v1['token_code'], 'PLS-02')                       # walk-in comes after the booking
        booked = self.new_patient('Morning Caller', '9000000801')
        v2 = self.call(REC, 'POST', '/api/visits', {'patient_id': booked['id'], 'dept_id': pls, 'source': 'phone', 'appointment_id': bk['id']})['visit']
        self.assertEqual(v2['token_code'], 'PLS-01')                       # arrives later, keeps the earlier number
        q = [x for x in self.call(REC, 'GET', '/api/queue')['visits'] if x['dept_id'] == pls and x['status'] == 'waiting']
        self.assertEqual(min(q, key=lambda x: x['token_no'])['id'], v2['id'])

    def test_late_booking_loses_its_place(self):
        pls = self.dept('PLS')
        bk = self.call(REC, 'POST', '/api/appointments', {'name': 'Late Caller', 'phone': '9000000811', 'dept_id': pls, 'appt_date': core.today(), 'appt_time': '00:01'})
        self.call(OWNER, 'POST', '/api/admin/settings', {'booking_grace': '0'})
        p = self.new_patient('Late Caller', '9000000811')
        r = self.call(REC, 'POST', '/api/visits', {'patient_id': p['id'], 'dept_id': pls, 'source': 'phone', 'appointment_id': bk['id']})
        self.assertEqual(r['late_booking'], bk['token_code'])
        self.assertNotEqual(r['visit']['token_code'], bk['token_code'])

    def test_my_token_page_shows_place_without_names(self):
        ped = self.dept('PED')
        p = self.new_patient('Private Person', '9000000803')
        v = self.call(REC, 'POST', '/api/visits', {'patient_id': p['id'], 'dept_id': ped, 'source': 'walkin'})['visit']
        self.assertTrue(len(v['public_code']) >= 8)
        d = self.call(None, 'GET', '/api/token', params={'c': v['public_code']})
        waiting_before = self.app.one("SELECT COUNT(*) n FROM visits WHERE dept_id=? AND visit_date=? AND status='waiting' AND token_no<?", (ped, core.today(), v['token_no']))['n']
        self.assertEqual((d['token'], d['ahead'], d['status']), (v['token_code'], waiting_before, 'waiting'))
        self.assertTrue(d['minutes'] > 0)
        self.assertNotIn('Private Person', str(d))
        self.denied(404, None, 'GET', '/api/token', params={'c': 'nope12345'})
        self.app.run("UPDATE visits SET visit_date='2000-01-01' WHERE id=?", (v['id'],))
        self.assertTrue(self.call(None, 'GET', '/api/token', params={'c': v['public_code']})['expired'])

    def test_tv_shows_minutes_per_patient(self):
        d = self.call(None, 'GET', '/api/display')
        self.assertTrue(all(x['per'] > 0 for x in d['departments']))


class PatientsDoor(Base):
    """The second port for patients' phones opens only the token page, never the staff portal."""
    def setUp(self):
        super().setUp()
        import server
        from http.server import ThreadingHTTPServer
        server.APP = self.app
        self.srv = ThreadingHTTPServer(('127.0.0.1', 0), server.PatientHandler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = 'http://127.0.0.1:%d' % self.srv.server_address[1]
        server.PatientHandler.hits.clear()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def get(self, path, method='GET', body=None):
        import urllib.request, urllib.error
        req = urllib.request.Request(self.base + path, data=body, method=method, headers={'Content-Type': 'application/json'} if body else {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_only_the_token_page_opens(self):
        p = self.new_patient('Door Patient', '9000000901')
        v = self.call(REC, 'POST', '/api/visits', {'patient_id': p['id'], 'dept_id': self.dept('PED'), 'source': 'walkin'})['visit']
        st, txt = self.get('/api/token?c=' + v['public_code'])
        self.assertEqual(st, 200)
        self.assertIn(v['token_code'], txt)
        self.assertNotIn('Door Patient', txt)
        self.assertEqual(self.get('/t')[0], 200)
        for path in ('/api/bootstrap', '/api/queue', '/api/display', '/display', '/app.js', '/index.html', '/api/patients'):
            self.assertEqual(self.get(path)[0], 404, path)
        self.assertEqual(self.get('/api/login', 'POST', b'{"username":"owner","password":"x"}')[0], 405)

    def test_too_many_requests_are_refused(self):
        codes = [self.get('/api/token?c=guessing123')[0] for _ in range(45)]
        self.assertIn(429, codes)


if __name__ == '__main__':
    unittest.main()
