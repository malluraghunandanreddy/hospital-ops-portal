# Changelog

## 0.12.0 – 11 Nov 2026

- Patients follow their turn: "My token" page on any smartphone (QR code on the slip or on the reception screen), in Telugu and English, with patients ahead, about how many minutes, and the token now with the doctor. No names are shown. The page works only on the day of the visit.
- Waiting-hall TV shows people waiting, minutes per patient and the wait for the last token.
- Phone bookings reserve their token number at booking. A booked patient who comes within the grace time (Settings › Hospital, default 30 min) keeps the earlier number and is called before walk-ins who came first. After the grace time they get a new token. The queue shows "Booked, not arrived yet".
- Patients' door: a second port (8091) that opens only the token page. No staff screens, no logins, and a limit on how often one phone can ask. Patients never touch the staff portal.
- QR codes use the laptop's Wi-Fi address, not a VPN address.
- The whole-hospital map is only for the founder doctors. Reception, nurses, doctors and consultants see only the bed list they work from.
- Waiting-hall TV can show chosen departments: /display?d=PED,DER,ORT.

## 0.11.0 – 11 Nov 2026

- Log out and every "are you sure" now use on-screen dialogs (some windows silently blocked the browser's pop-ups, so Log out did nothing).
- Demo login page: "Try each role" buttons (demo copy only).
- Who can see what: choose a role, then switch screens on or off, grouped by area, with the home screen shown.
- Each role sees its own job: role-specific hospital map (nurses: inpatient wing only; doctors: own OP room and inpatients); visiting doctors see only their own operations; inpatient advance amounts only for billing; pharmacy sees prescriptions read-only; insurance desk sees only scheme and insurance admissions; reception no longer has ward duty or inpatient charts.
- The building animation plays once per session.

## 0.10.1 – 11 Nov 2026

- Doctors no longer get the OP queue controls by default: reception calls tokens; doctors see their own list in My day. Tick "OP queue" for doctors in Settings › Who can see what if they should call their own patients.

## 0.10.0 – 11 Nov 2026

- People on the map look like people: doctors in white aprons with stethoscopes, nurses in blue scrubs and caps, staff and patients in everyday clothes, standing or seated.
- Every OP room has a nameplate (doctor, department, in/out). Hovering over any room, bed or desk shows who and what it is without clicking. Zoom centres on the selected place.
- Insurance desk on the map, with claims to follow up.
- Insurance follow-up: "Send to insurance desk" from the inpatient bill; claim timeline (sent, documents, file, status, follow-ups); follow-up note with next date; "New from inpatients", "Follow-up due", "No update 7+ days" lists; the desk's work today per person; amount pending with insurers; alerts on the doctors' dashboard.
- Insurance desk opens on Claims.

## 0.9.0 – 11 Nov 2026

- Realistic hospital map: rooms with walls and windows, doctors at their desks, patients on waiting-hall benches, beds with pillows, blankets, curtains and drip stands, ICU monitors, nurses' station, OT table and lamp, pharmacy shelves, lab benches, entrance with the hospital name, ambulance, cars, road and trees.
- Motion: the building rises in, people move, status lights pulse, the ambulance light flashes; clicking zooms to the place and shows a large callout with its numbers; numbers count up; cards lift on hover; screens fade in. Still for anyone whose device asks for less motion.
- Greeting and live indicator on the Hospital overview.

## 0.8.0 – 11 Nov 2026

- New blue and white look.
- Interactive hospital map (3D-style): OP rooms with doctor status and people waiting, wards with every bed by status, reception, OT, pharmacy and lab. Click anything for live details; zoom and drag. On the Hospital overview and as "Hospital map" on the Beds screen.
- Settings: print token slips or not; waiting-hall TV shows token and name, name only, or token only.
- "Fresh demo.command" starts the demo with new made-up patients dated today.

## 0.7.0 – 10 Nov 2026

- Nurses send the daily charge slip to IP billing inside the system; it shows on the doctors' dashboard until checked. No WhatsApp, no paper.
- IP billing is with the full-access doctors by default (not reception).
- "Your job here" card on each role's home screen, and a Help button.
- Inpatient billing locked to the full-access doctors (cannot be given to anyone else); in-house and visiting doctors no longer enter charges.
- The person logged in and their role are always shown at the top; Log out asks to confirm.

## 0.6.0 – 10 Nov 2026

- Pharmacy counter quick sale: pick patient (with prescription photo), medicines from stock with batch/expiry/MRP, expired batches blocked, cash/UPI/card, slip; inpatient sales go to the hospital bill; "To enter in Pharmasoft" copy list with Pharmasoft bill number.
- Stock import reads MRP.
- Hospital overview rebuilt as one dashboard: Needs attention list, then OP, inpatients and beds, pharmacy, money today, doctors, staff/claims/lab.

## 0.5.0 – 10 Nov 2026

- Inpatient billing in this system (Essel is OP only): advances, payments and refunds with numbered receipts; pharmacy and outside lab bills on the IP bill; final bill with number and scheme share; discounts and reopening only by full-access doctors; cancel with reason, never delete.
- "Enter in Essel" is now only for OP registrations.
- Accounts check: inpatient money by mode, cash handover by person, refunds, discounts, cancelled receipts, dues after discharge.

## 0.4.0 – 10 Nov 2026

- Price list set only by full-access doctors; nurses and reception record items and days/times, amounts come from the list; cancel with reason; printable charge slip; billing desk ticks lines entered in Essel; bed shift.
- Prescription photos are a reception job: phone camera, preview, retake, extra pages, next patient; saving marks the patient seen. Doctors only view.
- Returning patients: tag and Past records in queue and My day; one timeline of old prescriptions, reports and admissions.
- Queue buttons renamed: Call to doctor, Seen by doctor, Not here, Came back; how-to note on the queue.

## 0.3.0 – 10 Nov 2026

- Personal username and password for every person; no list of names on the login page; one-time password and forced change at first login; reset by a full-access doctor or at the laptop; lockout after 5 wrong tries; sessions survive a laptop restart; "keep me logged in" only on your own phone.
- Who can see what: screens per role and per person, checked by the server on every request. Owners are shown as doctors with full access.
- Separate home screens: My day (doctors), Ward duty (nurses), Hospital overview (full access).
- Doctors in / out: arrival and leaving saved from the status buttons; expected days for visiting doctors; payment per day attended.
- Claims: photos per document, automatic lab reports and summary, one-file claim download/share, portal copy sheet.
- Admission history and Accounts check screens.

## 0.2.0 – 10 Nov 2026

- Follow-ups and vaccines, lab reports, inpatient chart, OT, discharge tracker and summary, claims, pharmacy alerts and dose check, attendance, roster, salary, consultant payouts. Names on the waiting-hall display.

## 0.1.0 – 10 Nov 2026

First version (Phase 1).

- Staff logins with 4-digit PIN and roles.
- OP Desk: find or add a patient, give a department token, print the slip.
- Queue with Call / Done, doctor status, and a waiting-hall display that speaks the token.
- Phone bookings with a separate fee.
- Bed board with admit and discharge.
- Prescription photos (paper prescriptions stay handwritten).
- "Enter in Essel" copy screen.
- Owner "Today" screen.
- Telegram updates: daily summary, admissions/discharges, doctor status.
- Activity record that cannot be edited, daily backup, Telugu/English switch, demo data.
