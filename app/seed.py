"""First-run data.

Always created: departments, the two owner logins, beds, hospital details.
Demo mode adds made-up doctors, staff, patients and today's activity so the
system can be shown to the owners. Nothing here is real patient data.

ASSUMPTIONS to confirm with the hospital (all editable in Settings):
  - which department each owner-doctor sits in
  - consultation fees
  - ward names and bed numbers
  - names of all doctors and staff other than the two owners
"""
import datetime
import random

import core

DEPARTMENTS = [
    # code, name, Telugu name, walk-in fee, phone-booking fee (fees are placeholders)
    ('PED', 'Pediatrics', 'పిల్లల విభాగం', 300, 400),
    ('DER', 'Dermatology & Cosmetology', 'చర్మ వ్యాధుల విభాగం', 400, 500),
    ('OBG', 'Obstetrics & Gynecology', 'స్త్రీ వ్యాధులు & ప్రసూతి', 400, 500),
    ('GSU', 'General Surgery', 'జనరల్ సర్జరీ', 400, 500),
    ('PLS', 'Plastic Surgery', 'ప్లాస్టిక్ సర్జరీ', 500, 600),
    ('PSU', 'Pediatric Surgery', 'పిల్లల సర్జరీ', 500, 600),
    ('ORT', 'Orthopedics', 'ఎముకల విభాగం', 400, 500),
]

BEDS = ([('General Ward', 'G-%d' % i) for i in range(1, 7)] +
        [('Rooms', 'R-10%d' % i) for i in range(1, 7)] +
        [('Deluxe Rooms', 'D-20%d' % i) for i in range(1, 3)] +
        [('ICU', 'ICU-%d' % i) for i in range(1, 3)])

# name, dept code, kind, status
DOCTORS = [
    ('Dr A. Arjun Rao', 'PED', 'owner', 'in'),
    ('Dr A. Meera', 'DER', 'owner', 'in'),
    ('Dr K. Kavya Sharma', 'OBG', 'inhouse', 'in'),
    ('Dr P. Rohan Mehta', 'GSU', 'consultant', 'surgery'),
    ('Dr V. Nisha Kapoor', 'PLS', 'consultant', 'out'),
    ('Dr M. Vikram Joshi', 'PSU', 'consultant', 'out'),
    ('Dr S. Farhan Ali', 'ORT', 'consultant', 'delayed'),
]

# name, role, username, doctor index (or None). The demo password is in DEMO_LOGINS.txt.
OWNERS = [('Dr A. Arjun Rao', 'owner', 'arjun', 0), ('Dr A. Meera', 'owner', 'meera', 1)]
DEMO_STAFF = [
    ('Dr K. Kavya Sharma', 'doctor', 'kavya', 2),
    ('Dr P. Rohan Mehta', 'consultant', 'rohan', 3),
    ('Dr S. Farhan Ali', 'consultant', 'farhan', 6),
    ('Anita Reddy', 'reception', 'anita', None),
    ('Sk. Salma Begum', 'reception', 'salma', None),
    ('Sr. Grace Mary', 'nurse', 'grace', None),
    ('Ch. Ramesh Kumar', 'pharmacy', 'ramesh', None),
    ('K. Prakash Rao', 'insurance', 'prakash', None),
    ('City Diagnostics', 'lab', 'citylab', None),
    ('B. Savitri', 'support', None, None),
]
DEMO_PASSWORD = 'Demo@2026'
VISIT_DAYS = {'Dr P. Rohan Mehta': ('Mon,Wed,Fri', '10:00'), 'Dr V. Nisha Kapoor': ('Tue,Sat', '16:00'),
              'Dr M. Vikram Joshi': ('Thu', '11:00'), 'Dr S. Farhan Ali': ('Mon,Tue,Wed,Thu,Fri,Sat', '11:00')}

NAMES = [
    ('Kondaveeti Lakshmi', 'F'), ('Shaik Mastan Vali', 'M'), ('Yarlagadda Venkata Rao', 'M'),
    ('Gudipati Sravani', 'F'), ('Mekala Anjaneyulu', 'M'), ('Pothuri Nagamani', 'F'),
    ('Bandaru Sai Charan', 'M'), ('Nallapati Bhavya', 'F'), ('Chintala Ramesh Babu', 'M'),
    ('Dasari Padmavathi', 'F'), ('Tummala Harsha', 'M'), ('Vemuri Aaradhya', 'F'),
    ('Koneru Jyothi', 'F'), ('Syed Rizwana', 'F'), ('Maddineni Srinivasa Rao', 'M'),
    ('Gorantla Divya', 'F'), ('Pasupuleti Karthik', 'M'), ('Addanki Sujatha', 'F'),
    ('Katta Venkateswarlu', 'M'), ('Mopidevi Anusha', 'F'), ('Ravipati Teja', 'M'),
    ('Boddu Mary Kumari', 'F'), ('Namburi Subba Rao', 'M'), ('Alla Navya', 'F'),
    ('Kolla Mohan Krishna', 'M'), ('Uppala Swathi', 'F'), ('Jonnalagadda Akhil', 'M'),
    ('Thota Rajeswari', 'F'), ('Garikapati Yashwanth', 'M'), ('Polisetty Himabindu', 'F'),
    ('Vallabhaneni Rishik', 'M'), ('Chilakala Sai Pallavi', 'F'), ('Mannava Bhargav', 'M'),
    ('Parvathaneni Keerthi', 'F'),
]
AREAS = ['Main Road', 'North Colony', 'Station Road', 'Market Street', 'Gandhi Nagar', 'Lake View', 'Temple Street',
         'Ward 4', 'Ward 7', 'Nehru Nagar', 'Vidya Nagar', 'Old Town', 'River Side', 'Bus Stand Road',
         'Green Park', 'Hill Colony', 'New Town']
CHILD_FIRST = ('Sai Charan', 'Harsha', 'Aaradhya', 'Karthik', 'Teja', 'Navya', 'Akhil', 'Yashwanth', 'Rishik', 'Bhargav')


def run(app, demo):
    rnd = random.Random(7)
    s = app.set_setting
    s('hospital_name', 'Sunrise Hospital')
    s('hospital_addr', 'Main Road, Sampletown')
    s('casualty_phone', '')
    s('summary_time', '21:00')
    s('demo', '1' if demo else '0')

    dept = {}
    for code, name, te, walk, phone in DEPARTMENTS:
        dept[code] = app.run('INSERT INTO departments(code, name, name_te, fee_walkin, fee_phone) VALUES(?,?,?,?,?)',
                             (code, name, te, walk, phone))
    for ward, label in BEDS:
        app.run('INSERT INTO beds(ward, label) VALUES(?,?)', (ward, label))

    doc_ids = []
    for name, code, kind, status in (DOCTORS if demo else DOCTORS[:2]):
        doc_ids.append(app.run('INSERT INTO doctors(name, dept_id, kind, status, status_note) VALUES(?,?,?,?,?)',
                               (name, dept[code], kind, status if demo else 'out',
                                'Expected by 11:30' if demo and status == 'delayed' else '')))
    import access
    app.first_passwords = []
    for name, role, user, di in OWNERS + (DEMO_STAFF if demo else []):
        sid = app.run('INSERT INTO staff(name, role, doctor_id, username) VALUES(?,?,?,?)',
                      (name, role, doc_ids[di] if di is not None else None, user))
        if not user:
            continue
        if demo:
            access.set_password(app, sid, DEMO_PASSWORD, False)
        else:
            app.first_passwords.append((name, user, access.new_temp_password(app, sid)))
    app.audit(None, 'system.first_run', None, None, {'demo': bool(demo)})
    if not demo:
        return
    today_iso = datetime.date.today().isoformat()
    app.set_setting('status_day', today_iso)
    for name, (days, at) in VISIT_DAYS.items():
        app.run('UPDATE doctors SET visit_days=?, visit_time=? WHERE name=?', (days, at, name))
    for d in app.q("SELECT id, status, kind FROM doctors"):
        if d['status'] in ('in', 'surgery'):
            app.run('INSERT INTO doctor_days(doctor_id, day, arrived_at, marked_by) VALUES(?,?,?,?)',
                    (d['id'], today_iso, '09:%02d' % (5 + d['id'] * 7), 'Anita Reddy'))
        if d['kind'] == 'consultant':  # earlier visits this month
            for back in range(1, datetime.date.today().day):
                day = datetime.date.today() - datetime.timedelta(days=back)
                if (day.day + d['id']) % 3 == 0:
                    app.run('INSERT INTO doctor_days(doctor_id, day, arrived_at, left_at, marked_by) VALUES(?,?,?,?,?)',
                            (d['id'], day.isoformat(), '10:1%d' % (back % 10), '13:4%d' % (back % 10), 'Anita Reddy'))

    today = datetime.date.today()
    pids = []
    for i, (name, sex) in enumerate(NAMES):
        child = any(c in name for c in CHILD_FIRST)
        age_y = rnd.randint(0, 9) if child else rnd.randint(19, 68)
        age_m = rnd.randint(0, 11) if child and age_y < 5 else None
        phone = '9%09d' % rnd.randint(100000000, 899999999)
        guardian = (name.split()[0] + ' ' + rnd.choice(['Srinivas', 'Ramana', 'Lakshmi', 'Venkatesh'])) if child else ''
        pid = app.run(
            'INSERT INTO patients(name, sex, phone, age_y, age_m, age_on, guardian, area, referral, created_at) '
            'VALUES(?,?,?,?,?,?,?,?,?,?)',
            (name, sex, phone, age_y, age_m, today.isoformat(), guardian, rnd.choice(AREAS),
             rnd.choice(['', '', 'Family', 'Dr Prasad, Nearby Town', 'Neighbour']), core.now()))
        app.run('UPDATE patients SET uhid=? WHERE id=?', ('HH-%06d' % pid, pid))
        pids.append((pid, child, sex, name))

    # Today's OP: children to Pediatrics, others spread across departments.
    doc_for = {code: doc_ids[i] for i, (_, code, _, _) in enumerate(DOCTORS)}
    counters = {}
    base = datetime.datetime.combine(today, datetime.time(9, 5))
    for n, (pid, child, sex, _) in enumerate(pids[:22]):
        code = 'PED' if child else rnd.choice(['DER', 'OBG', 'GSU', 'ORT', 'DER'] if sex == 'F' else ['DER', 'GSU', 'ORT'])
        counters[code] = counters.get(code, 0) + 1
        k = counters[code]
        status = 'done' if n < 11 else ('called' if k == max(1, counters[code]) and n in (11, 12, 13) else 'waiting')
        t = (base + datetime.timedelta(minutes=7 * n)).isoformat(timespec='seconds')
        source = 'phone' if n % 4 == 0 else 'walkin'
        fee = [d for d in DEPARTMENTS if d[0] == code][0][4 if source == 'phone' else 3]
        app.run('INSERT INTO visits(patient_id, dept_id, doctor_id, visit_date, source, token_no, token_code, fee_shown, '
                'status, created_at, called_at, done_at, essel_done) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (pid, dept[code], doc_for[code], today.isoformat(), source, k, '%s-%02d' % (code, k), fee, status, t,
                 t if status != 'waiting' else None, t if status == 'done' else None, 1 if n < 8 else 0))

    # Phone bookings for today and tomorrow.
    for i, (pid, child, sex, name) in enumerate(pids[24:30]):
        code = 'PED' if child else (['OBG', 'DER', 'ORT'] if sex == 'F' else ['ORT', 'DER', 'GSU'])[i % 3]
        day = today if i < 4 else today + datetime.timedelta(days=1)
        phone = app.one('SELECT phone FROM patients WHERE id=?', (pid,))['phone']
        app.run('INSERT INTO appointments(name, phone, dept_id, doctor_id, appt_date, appt_time, note, created_at) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (name, phone, dept[code], doc_for[code], day.isoformat(), '%02d:%02d' % (16 + i // 2, 30 * (i % 2)),
                 '', core.now()))

    # Inpatients.
    cases = [('G-2', 'Dengue fever', '', 'Cash', 3), ('G-5', 'Acute gastroenteritis', '', 'Cash', 2),
             ('R-101', 'Post LSCS', 'LSCS', 'Dr NTR Vaidya Seva', 5), ('R-103', 'Fracture right tibia', 'ORIF', 'Insurance / TPA', 6),
             ('R-104', 'Appendicitis', 'Lap appendicectomy', 'Cash', 3), ('D-201', 'Normal delivery', '', 'Cash', 2),
             ('ICU-1', 'Bronchopneumonia', '', 'PM-JAY', 5)]
    used = set()
    for i, (label, dx, proc, payer, days) in enumerate(cases):
        want_child, want_sex = [(True, None), (True, None), (False, 'F'), (False, 'M'), (False, None), (False, 'F'), (True, None)][i]
        pick = [x for x in pids[22:] if x[1] == want_child and (want_sex is None or x[2] == want_sex) and x[0] not in used]
        pid = (pick or [x for x in pids if x[0] not in used])[0][0]
        used.add(pid)
        bed = app.one('SELECT id FROM beds WHERE label=?', (label,))['id']
        doc = doc_ids[[0, 0, 2, 6, 3, 2, 0][i]]
        at = (datetime.datetime.now() - datetime.timedelta(days=i % 4, hours=3 + i)).isoformat(timespec='seconds')
        app.run('INSERT INTO admissions(patient_id, bed_id, doctor_id, admitted_at, diagnosis, procedure, payer, '
                'attendant_name, attendant_phone, expected_days, deposit_noted) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (pid, bed, doc, at, dx, proc, payer, 'Attendant ' + str(i + 1), '9%09d' % rnd.randint(100000000, 899999999),
                 days, 5000 if payer == 'Cash' else 0))
        app.run("UPDATE beds SET status='occupied' WHERE id=?", (bed,))
    app.run("UPDATE beds SET status='cleaning' WHERE label='G-3'")
    app.run("UPDATE beds SET status='reserved', note='Planned delivery tomorrow' WHERE label='R-106'")
