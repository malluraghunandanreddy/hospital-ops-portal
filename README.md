# Hospital operations portal

> **Demo copy.** "Sunrise Hospital", its place, doctors, staff and patients are all made up. There is no real patient data in this repository; the database (`data/`) is never committed.
>
> Python standard library + SQLite + plain JavaScript. No install, no build step. Run `python3 app/server.py` and open http://localhost:8080 (demo logins in `DEMO_LOGINS.txt`).

This runs next to Essel (the hospital's OP software, by the current software vendor) and Pharmasoft (the pharmacy counter software). It does not change either of them. OP fees stay in Essel. Inpatients are not handled by either program, so inpatient billing is done here.

## Logins and who sees what

- **Everyone has their own username and password.** The login page shows nothing about the staff.
- **Adding a person** (Settings > Staff and logins > Add person): the system gives a one-time password. Hand it over in person. At first login they must choose their own (at least 8 characters, letters and numbers, not their name).
- **Forgotten password:** Dr Arjun Rao or Dr Meera press "Reset password" next to the name. If one of them forgets their own, the other resets it; if both are locked out, double-click **Reset a password.bat** on the laptop.
- **Someone leaves:** untick "Working here". Their login stops at once on every phone.
- **"Keep me logged in on this phone"** is only for a person's own phone. On the reception computer leave it unticked: closing the browser logs them out.
- Five wrong passwords lock that username for 5 minutes.

| Login | Home screen | Also sees |
|---|---|---|
| Dr Arjun Rao, Dr Meera (full access) | Hospital overview | Everything, including Accounts check, Staff and salary, Settings |
| In-house doctor | My day (own patients in order, no queue buttons) | Beds, OT, Admission history, patient records |
| Visiting doctor | My day (own patients only, no queue buttons) | Beds, OT |
| Reception | OP Desk | Ward duty, Queue, Phone bookings, Doctors in/out, Follow-ups, Beds, OT, Lab, Admissions, Prescriptions (photos), Enter in Essel |
| Nursing | Ward duty | Beds, OT, inpatient charts |
| Pharmacy | Medicine sale | Stock alerts, Prescriptions |
| Insurance desk | Admissions | Claims |
| Outside lab | Lab | nothing else |

Change any of this in **Settings > Who can see what** (for a whole role) or the **Screens** button next to a person (just for them). A screen that is not ticked disappears and cannot be opened by typing its address. Some rules never change: full-access doctors see everything, only they open Settings, only doctors order discharge or sign summaries, and a visiting doctor only sees their own patients.

## Insurance claims: hand-off and follow-up

1. When a scheme or insurance patient's bill is ready, the doctor presses **Send to insurance desk** on the IP bill.
2. The claim appears on the insurance desk under **New from inpatients**.
3. After every call to the insurer or TPA, the desk presses **Follow-up**, writes what was said and the next date to check. On that date it appears under **Follow-up due** for the desk and under Needs attention for the doctors.
4. **Timeline** shows every step with name and date. The top of Claims shows the desk's work today (submitted, documents, follow-ups) and the amount pending with insurers.

## Hospital map

The Hospital overview (and Beds → Hospital map) shows the hospital as a 3D-style map: OP rooms with each doctor's status light and the people waiting, every ward with each bed coloured by status (green vacant, blue occupied, amber discharge or cleaning, light blue reserved), reception and the waiting hall, OT, pharmacy and lab. Click anything to see it live on the right, with buttons to the right screen. Use + and − to zoom and drag to move.

## Tokens without a printer

Settings → Tokens and waiting-hall TV: choose **No printing** and OP Desk shows the token big instead of printing, so reception says it, writes it on the OP sheet or gives a numbered card. The TV can show token and name, name only, or token only.

## How the OP queue works

1. Reception gives a token at **OP Desk** (a printed slip).
2. **Call to doctor**: the token shows on the waiting-hall TV and is read out. The patient goes in. Reception or the doctor can press it.
3. **Seen by doctor**: press when the patient comes out.
4. **Not here**: the token was called but the patient was not in the hall. They are kept aside, not deleted. **Came back** puts them back in line.
5. The big green button **Seen — call next token** does steps 3 and 2 together.

## Prescriptions (doctors only write on paper)

Reception opens **Prescriptions** on their phone. It lists today's patients by doctor, with "Photo needed" first. **Take photo** opens the phone camera; check the preview, Save (or Retake, or add another page). The photo is saved under that patient and that doctor's visit, and the next patient comes up. If the doctor forgot to mark the patient seen, saving the photo does it.

## Returning patients

When a patient has come before, reception sees "Returning patient — last visit …" while giving the token, and the doctor sees a **Returning** tag and a **Past records** button in the queue and My day. Past records shows every old prescription photo, lab report and admission (with the discharge summary), newest first.

## How the departments connect (one patient record, separate screens)

Each department works on its own screens with its own logins and does not wait for any other. They are joined by the patient's UHID:

- Reception registers the patient once → the doctor's queue, the waiting-hall TV and the prescription photo list all use it.
- Reception photographs the prescription → the doctor sees it next visit, and the pharmacy counter sees it when the patient comes to buy.
- Pharmacy sells to an inpatient → it goes onto the hospital bill by itself.
- Nurses record room days and services → they make the inpatient bill.
- Lab reports → reach the doctor's My day, the patient's past records and the claim file.
- The full-access doctors' **Hospital overview** shows all of it on one screen: a "Needs attention" list, then OP, inpatients and beds, pharmacy, money today, doctors, and staff/claims/lab.

## Pharmacy counter (Medicine sale)

The counter is too busy to make each bill in Pharmasoft while the patient waits. Now:

1. Tap the patient (today's OP patient — their prescription photo is right there — or an inpatient, or walk-in).
2. Type a few letters of each medicine and tap it. Batch, expiry and MRP come from the stock list loaded from Pharmasoft. Expired batches cannot be sold. Change quantity with − and +.
3. Choose Cash / UPI / Card and save. Print a slip if they want one. Inpatient sales take no money; they go on the hospital bill.
4. When it is quiet, open **To enter in Pharmasoft**: each sale's fields are ready to copy into Pharmasoft's Counter Sales screen. Type the Pharmasoft bill number and press Entered.

The stock list needs an MRP column to fill prices; if it has none, the pharmacist types the rate. A sale is cancelled (for example a return) with a reason, never deleted.

## Inpatient billing (Essel and Pharmasoft are not used for inpatients)

- **IP billing** tab — by default only Dr Arjun Rao and Dr Meera have it (give it to someone else in Settings > Who can see what if needed): every inpatient with charges, paid and balance.
- **Charge slips**: nurses press **Send charge slip** on the chart (daily and before discharge). It appears on the doctors' dashboard under Needs attention and in IP billing; open the bill, compare, press **Checked**.
- **Advance**: taken in IP billing (or in the admission form by whoever has IP billing); a numbered receipt (R/2026-27/0001) is made and can be printed.
- **Take advance / Take payment / Return extra**: each gives a numbered receipt. UPI, card and cheque need the reference number.
- **Pharmacy** adds medicines issued to the ward from the Pharmacy screen, with the pharmacy bill number. The billing desk adds **outside lab / scan bills** the same way.
- **Make final bill**: for scheme or insurance patients, enter the amount the scheme pays; the rest is the patient's. The bill gets a number (IP/2026-27/0001) and the charges are locked. The discharge step "Final bill made and paid" ticks itself when nothing is left to pay.
- **Discounts** and **reopening a final bill**: only full-access doctors, always with a reason.
- A wrong receipt is **cancelled with a reason**, never deleted. The person who took it can cancel it the same day; after that only a full-access doctor.
- **Accounts check** shows inpatient money received by cash / UPI / card, cash to hand over by each person, refunds, discounts, cancelled receipts and discharged patients who still owe.

## Attendance

- Staff with a login press **Mark duty in** at the top after logging in, and again for duty out.
- Visiting doctors: arrival and leaving are saved when they are set to "In" / "Not in".
- Support staff without a login are marked on **Staff > Attendance** (P, A, L, H, O).
- Salary uses this attendance; days not marked are shown before paying.

## Inpatient charges (replaces the handwritten charge slip)

- **Prices**: only the full-access doctors set them, in **Settings > Price list** (room per day for each ward, nursing per day, doctor visits, OT, dressings, nebulisation, oxygen per hour, and so on). The prices there now are placeholders.
- **Nurses and reception** open the patient's chart and press **Service / charge given** or **Room and nursing days**, choose the item and enter how many times or days. They cannot type a price. The system shows the stay so far and what is already recorded, so days are not missed or doubled.
- **Shift bed** moves a patient (for example ICU to a room); the old bed goes for cleaning.
- A wrong entry is **cancelled with a reason**; it stays visible, struck through.
- **Send charge slip** sends the day's slip to IP billing inside the system (no paper). **Print charge slip** prints it if needed. These charges make the inpatient bill. The claim file includes the charge statement.

## What each screen replaces

| Screen | Replaces |
|---|---|
| OP Desk | The OP register book, with printed tokens |
| Queue + waiting-hall TV | Calling patients by voice |
| Doctors in / out | Asking whether a visiting doctor came. Setting a doctor to "In" saves the arrival time by itself; "Not in" saves the leaving time. Visiting doctors' payments use these days |
| Ward duty, Beds, inpatient chart | Ward registers, vitals sheets, handover book, discharge running around |
| Claims | Rewriting the IP file into Word. Photograph each paper into the claim; lab reports and the signed summary are added by themselves. "Download claim file" gives one ZIP with everything; "Portal details" lets the desk copy each field into the insurer's website |
| IP billing | Handwritten inpatient bills and receipts |
| Accounts check | OP: comparing expected fees with Essel's day report. IP: money received here, cash handover, dues |
| Prescriptions | Nothing is typed. Paper prescriptions are photographed |

## Starting and stopping

1. Double-click **Start Sunrise.bat** (Windows) or **start.command** (Mac).
2. A black window opens and shows two addresses. Keep it open.
3. The browser opens by itself. Log in with your username and password.

To stop: close the black window, or just shut the laptop. Everything stops, exactly like Essel.

**Patients' phones** use the patients' door (port 8091), which opens only the "My token" page. Do not give patients the staff Wi-Fi password. Keep two networks: a **staff Wi-Fi** (laptop, reception PCs, TV, staff phones) and a separate **patients' Wi-Fi** used only to show the token page. Patients without a smartphone follow the TV and their slip.

**Phones and the waiting-hall TV** must be on the same Wi-Fi as the laptop. Type the "On phones" address shown in the black window into the phone's browser. For the TV, use the address ending in `/display`.

First time only: install Python 3 from python.org (tick "Add Python to PATH"). Nothing else is needed and no internet is needed to run.

## Before real use

- Demo logins are in `DEMO_LOGINS.txt`. This copy has made-up patients.
- For a clean copy: stop the program, delete the `data` folder, and start with demo off (Windows: run `set HOSPITAL_DEMO=0` before the .bat; Mac: `HOSPITAL_DEMO=0 ./start.command`). The black window shows one-time passwords for `arjun` and `meera`. Log in, choose your own passwords, then add doctors, staff, fees and beds in Settings.
- Turn on disk encryption on the laptop (BitLocker on Windows, FileVault on Mac). Patient data and prescription photos are in the `data` folder.

## Backups

A copy of the database is saved in `data/backups` each day the laptop is on (last 30 days kept). These are on the same laptop, so **once a week copy the whole `data` folder to a USB drive** kept in a different place. To restore: stop the program and put that `data` folder back.

## Telegram updates

Settings > Updates on Telegram has four numbered steps. It takes about five minutes and is free. Messages go out only while the laptop is on and has internet; if the internet is down they wait and go later.

## Moving to the cloud later

Copy this folder (with `data`) to the server and run `python3 app/server.py` behind HTTPS with `HOSPITAL_HTTPS=1`. Nothing else changes; staff then use one web address from anywhere. Until then, the screens open only on the hospital Wi-Fi.

## For the developer

- `app/core.py` rules and database, `app/server.py` web server, `app/seed.py` first-run data, `app/static/` screens.
- Python standard library only; SQLite file in `data/sunrise.db`.
- Tests: `python3 -m unittest discover tests`
- Plan, assumptions and what is not built yet: `PLAN.md`.
