# Plan – Sunrise Hospital operations layer

## Decisions that differ from the original build prompt

| Build prompt said | Decided | Why |
|---|---|---|
| Postgres, cloud hosting, bridge machine | One program on one hospital laptop, SQLite file, no installs beyond Python | Hospital does not want to maintain a server; wants it to stop when the laptop closes, like Essel |
| Fixed cloud | Same program runs unchanged on a cloud server later | They may move to cloud; not fixed |
| WhatsApp Business API + SMS + voice | Telegram first, behind a small `notify()` function | Free, no approval, set up in 5 minutes. WhatsApp/SMS can be added behind the same function |
| Typed prescriptions optional | Not built. Photo of the paper prescription only | Doctors write by hand; firm constraint |
| Phase 0 report before code | Phase 1 built with manual entry; integration questions still open | Everything must work with manual entry anyway (section 4) |

## How the double entry is removed (Phase 1)

Route (b) from the prompt: capture once at OP Desk, then the **Enter in Essel** screen lists the same fields ready to copy, and the paper register is retired. Nothing is written into Essel's database. If the current software vendor later offers an import utility, only that screen changes.

## Logins and access (added after Phase 1)

Personal usernames and strong passwords replace shared 4-digit PINs. Screens are given per role and can be changed per person in Settings; the server enforces it. The two founders are full-access doctors (never called "owners" on screen).

## Built (Phase 1)

Logins with PIN and roles · OP registration · tokens per department · printable slip · waiting-hall display with spoken call-out · phone bookings with separate fee · doctor in/delayed/surgery · bed board with admit/discharge · prescription photos · owner Today screen · Telegram updates (daily summary, admissions/discharges, doctor status; per-person topic and department choice) · tamper-proof activity record · daily backup · Telugu/English switch · demo data · 24 tests.

## Assumptions to confirm (all changeable in Settings)

1. Dr Arjun Rao sits in Pediatrics and Dr Meera in Dermatology.
2. Fees (₹300–600) are placeholders.
3. Wards and bed numbers (16 beds) are placeholders.
4. Field order on **Enter in Essel** is a guess; needs a look at Essel's OP Registration screen.
5. In-house doctor sees the full history of patients she has seen; a visiting consultant sees only their own visits.
6. Telegram messages carry no patient names (bed numbers and counts only), because Telegram is a third party.
7. Telugu wording needs a read-through by staff (`app/static/i18n.js`).

## Known limits

- Phones outside the hospital Wi-Fi cannot open the screens until it is moved to the cloud. Telegram updates still reach them.
- On the hospital Wi-Fi the connection is plain HTTP. Use a password-protected Wi-Fi that patients do not share.
- Updates and the daily summary go only while the laptop is on.
- Laptop loss = data loss unless the weekly USB copy is done. Disk encryption must be switched on by the hospital.
- Token slip prints through the browser's print dialog on any printer; an 80 mm thermal printer needs to be set as default with "no margins". Not tested on real hardware.
- Spoken call-out uses the TV browser's built-in voice; Telugu is spoken only if that device has a Telugu voice, otherwise English.

## Not built yet

- Phase 2: vaccine and follow-up tracker, lab report flow, patient SMS/WhatsApp/voice reminders.
- Phase 3: nursing tasks, OT schedule, discharge step tracker and summary, insurance claim packets.
- Phase 4: pharmacy stock import, expiry/reorder alerts, dose check.
- Phase 5: roster, attendance, payroll, consultant payouts.
- Insurance desk and lab logins exist as roles but have no screens yet.

## Still needed from the hospital / the current software vendor

The nine open questions in section 11 of the build prompt are all still open; most urgent for the next phases: sample exports from Essel and Pharmasoft, the pediatrician's vaccine schedule, scheme checklists, and reception printer model.
