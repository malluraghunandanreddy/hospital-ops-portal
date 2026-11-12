'use strict';
// Later-phase screens: follow-ups, lab, IP chart, OT, claims, pharmacy, staff. Uses the helpers in app.js.


const SERVICES = ['Dressing', 'Nebulisation', 'Injection', 'IV fluids', 'Catheterisation', 'Suture removal', 'ECG', 'Oxygen', 'Blood transfusion', 'Physiotherapy'];
const EVENT_NAMES = { vitals: 'Vitals', medicine: 'Medicine given', service: 'Service done', io: 'Intake / output', note: 'Nursing note', round: 'Doctor round' };
const CLAIM_NAMES = { preparing: 'Preparing', submitted: 'Submitted', queried: 'Query from insurer', approved: 'Approved', settled: 'Settled', rejected: 'Rejected' };
const OT_CHECKS = [['consent', 'Consent signed'], ['fasting', 'Fasting confirmed'], ['tests', 'Investigations ready'], ['fitness', 'Anesthesia fitness'], ['site', 'Site marked'], ['blood', 'Blood arranged (if needed)']];
const FU_KINDS = [['surgery', 'Surgery (sutures, dressing)'], ['ortho', 'Orthopedics (plaster, physio)'], ['skin', 'Skin session'], ['antenatal', 'Antenatal'], ['vaccine', 'Vaccine'], ['other', 'Other']];
const since = (iso) => waited(iso);
const tag = (text, cls) => h('span', { class: 'tag ' + (cls || '') }, text);
const tbl2 = (heads, rows) => h('table', { class: 'plain' }, h('thead', {}, h('tr', {}, heads.map((x) => h('th', {}, x)))), h('tbody', {}, rows));
const area = (value, rows) => h('textarea', { rows: rows || 3 }, value || '');

function printDoc(el) {
  document.getElementById('print-slip').replaceChildren(el);
  window.print();
}
function docHead(title) {
  return [h('div', { class: 'doc-h' }, S.hospital), h('div', { class: 'doc-s' }, S.address), h('h1', {}, title)];
}
function wordFile(el, name) {
  const html = '<html><head><meta charset="utf-8"><style>body{font-family:Arial;font-size:11pt}table{border-collapse:collapse;width:100%}td,th{border:1px solid #999;padding:4px;text-align:left}h1{font-size:15pt}h2{font-size:12pt}</style></head><body>' + el.innerHTML + '</body></html>';
  const a = h('a', { href: URL.createObjectURL(new Blob([html], { type: 'application/msword' })), download: name + '.doc' });
  document.body.append(a); a.click(); a.remove();
}
function pickFile(accept, then) {
  const inp = h('input', { type: 'file', accept });
  inp.onchange = () => { if (inp.files[0]) then(inp.files[0]); };
  inp.click();
}

// ---------- header: mark duty in / out ----------
window.dutyButton = () => {
  const b = h('button', { class: 'btn quiet' }, 'Duty');
  const draw = (d) => { b.textContent = !d.today || !d.today.in_at ? 'Mark duty in' : d.today.out_at ? 'Duty over ' + clock(d.today.out_at) : 'On duty since ' + clock(d.today.in_at) + ' — mark out'; b.disabled = !!(d.today && d.today.out_at); };
  api('GET', '/api/duty').then(draw).catch(() => {});
  b.onclick = guard(async () => { draw(await api('POST', '/api/duty', {})); toast('Marked'); });
  return b;
};

// ---------- follow-ups and vaccines ----------
VIEWS.followups = async (root) => {
  const box = h('div', {});
  root.append(box);
  const act = (f, body) => guard(async () => { await api('POST', '/api/followups/' + f.id, body); await load(); });
  const row = (f) => h('div', { class: 'qrow' + (f.late_days > 0 ? ' late' : '') },
    h('div', { class: 'tok small' }, dayText(f.due_date).replace(/ \d{4}$/, ''), f.late_days > 0 && h('div', { class: 'muted' }, f.late_days + ' days late')),
    h('div', { class: 'qinfo' }, h('a', { class: 'pname', href: '#patient/' + f.patient_id }, f.name), ' ', tag(f.title),
      h('div', { class: 'muted' }, [f.age, f.phone ? 'Phone ' + f.phone : 'No phone', f.guardian && 'Guardian ' + f.guardian, f.area, f.calls ? 'Called ' + f.calls + ' time' + (f.calls > 1 ? 's' : '') + ', last ' + dayText(f.last_call) : null, f.note].filter(Boolean).join(' · '))),
    h('div', { class: 'qact' },
      h('button', { class: 'btn primary', onclick: () => formModal(f.title + ' — done', f.kind === 'vaccine' ? [{ key: 'batch', label: 'Vaccine batch number(s)' }, { key: 'note', label: 'Note' }] : [{ key: 'note', label: 'Note (optional)' }], {}, async (v) => { await api('POST', '/api/followups/' + f.id, Object.assign(v, { action: 'done' })); await load(); }) }, 'Done'),
      h('button', { class: 'btn', onclick: () => formModal('Phone call to ' + f.name, [{ key: 'note', label: 'What did they say?' }], {}, async (v) => { await api('POST', '/api/followups/' + f.id, Object.assign(v, { action: 'called' })); await load(); }) }, 'Called them'),
      h('button', { class: 'btn', onclick: () => formModal('New date', [{ key: 'due_date', label: 'Coming on', type: 'date' }], { due_date: f.due_date }, async (v) => { await api('POST', '/api/followups/' + f.id, Object.assign(v, { action: 'move' })); await load(); }) }, 'Change date'),
      h('button', { class: 'btn quiet', onclick: guard(async () => { if (await ask('Remove this follow-up?', 'Remove')) await act(f, { action: 'cancel' })(); }) }, 'Remove')));
  const group = (title, list, empty) => h('section', {}, h('h2', {}, title + ' (' + list.length + ')'), list.length ? h('div', { class: 'qlist' }, list.map(row)) : h('p', { class: 'empty' }, empty));
  const load = async () => {
    const d = await api('GET', '/api/followups');
    box.replaceChildren(
      !d.confirmed.vaccine && h('div', { class: 'note' }, 'The vaccine schedule is a draft. The pediatrician must check it and press Confirm in Settings before it is used for real patients.'),
      h('p', { class: 'muted' }, 'Call the people in the first list. To add a follow-up or start a child\'s vaccine schedule, open the patient from OP Desk or Queue.'),
      group('Missed — call today', d.missed, 'Nobody has missed a follow-up.'), group('Due today', d.today, 'Nothing due today.'), group('Next 7 days', d.upcoming, 'Nothing in the next 7 days.'));
  };
  S.poll = load;
  await load();
};

// Added to the patient page by app.js
window.patientExtras = (d, id) => {
  const p = d.patient;
  const again = () => render();
  const fuRow = (f) => h('div', { class: 'qrow ' + (f.status === 'done' ? 'done' : '') }, h('div', { class: 'tok small' }, dayText(f.due_date)),
    h('div', { class: 'qinfo' }, h('span', { class: 'pname' }, f.title), h('div', { class: 'muted' }, f.status === 'done' ? 'Done ' + dayText(f.done_at) + (f.batch ? ' · batch ' + f.batch : '') : (f.due_date < isoToday() ? 'Missed' : 'Due'), f.note ? ' · ' + f.note : '')),
    h('div', { class: 'qact' }, f.status !== 'done'
      ? h('button', { class: 'btn', onclick: () => formModal(f.title + ' — done', [{ key: 'batch', label: 'Batch number (vaccines)' }, { key: 'note', label: 'Note' }], {}, async (v) => { await api('POST', '/api/followups/' + f.id, Object.assign(v, { action: 'done' })); again(); }) }, 'Done')
      : h('button', { class: 'btn quiet', onclick: guard(async () => { await api('POST', '/api/followups/' + f.id, { action: 'reopen' }); again(); }) }, 'Undo')));
  return [
    h('div', { class: 'headrow' }, h('h3', {}, 'Follow-ups and vaccines'), h('div', { class: 'qact' },
      h('button', { class: 'btn', onclick: () => formModal('Add follow-up', [{ key: 'kind', label: 'For', type: 'select', options: FU_KINDS }, { key: 'title', label: 'What is due', placeholder: 'Suture removal' }, { key: 'due_date', label: 'Date', type: 'date' }, { key: 'note', label: 'Note' }], { kind: 'surgery' }, async (v) => { await api('POST', '/api/followups', Object.assign(v, { patient_id: +id })); again(); }) }, 'Add follow-up'),
      h('button', { class: 'btn', onclick: () => formModal('Vaccine schedule', [{ key: 'date', label: 'Child\'s date of birth', type: 'date' }], { date: p.dob || '' }, async (v) => { await api('POST', '/api/patients/' + id + '/plan', Object.assign(v, { plan: 'vaccine' })); again(); }) }, 'Start vaccine schedule'),
      p.sex === 'F' && h('button', { class: 'btn', onclick: () => formModal('Antenatal schedule', [{ key: 'date', label: 'LMP date (first day of last period)', type: 'date' }], {}, async (v) => { await api('POST', '/api/patients/' + id + '/plan', Object.assign(v, { plan: 'antenatal' })); again(); }) }, 'Start antenatal schedule'))),
    d.followups.length ? h('div', { class: 'qlist' }, d.followups.map(fuRow)) : h('p', { class: 'empty' }, 'None.'),
    h('div', { class: 'headrow' }, h('h3', {}, 'Lab and scan reports'),
      h('button', { class: 'btn', onclick: () => formModal('Order test', [{ key: 'test', label: 'Test or scan', placeholder: 'CBC' }, { key: 'outsourced', label: 'Sample goes to an outside lab', type: 'check' }], {}, async (v) => { await api('POST', '/api/lab', Object.assign(v, { patient_id: +id })); again(); }) }, 'Order test')),
    d.labs.length ? h('div', { class: 'qlist' }, d.labs.map((l) => h('div', { class: 'qrow' }, h('div', { class: 'qinfo' }, h('span', { class: 'pname' }, l.test), ' ', l.critical ? tag('CRITICAL', 'bad') : null,
      h('div', { class: 'muted' }, 'Ordered ' + dayText(l.ordered_at) + ' · ' + (l.status === 'reported' ? 'Report ready ' + dayText(l.reported_at) : l.status === 'collected' ? 'Sample collected, report awaited' : 'Sample not collected yet'))),
      h('div', { class: 'qact' }, l.has_file ? h('a', { class: 'btn', href: '/files/lab/' + l.id, target: '_blank', rel: 'noopener' }, 'Open report') : null)))) : h('p', { class: 'empty' }, 'None.'),
  ];
};

// ---------- lab ----------
VIEWS.lab = async (root) => {
  const box = h('div', {});
  root.append(box);
  const upload = (o) => pickFile('image/*,application/pdf', (file) => {
    const crit = h('input', { type: 'checkbox' });
    const m = modal('Report for ' + o.name + ' — ' + o.test, h('div', {}, h('p', {}, file.name), h('label', { class: 'field inline' }, crit, ' A value is critical — alert the doctor now'),
      h('div', { class: 'actions' }, h('button', { class: 'btn primary', onclick: guard(async () => {
        const blob = file.type === 'application/pdf' ? file : await shrink(file);
        await api('POST', '/api/lab/' + o.id + '/report' + (crit.checked ? '?critical=1' : ''), blob); m.close(); toast('Report saved'); await load();
      }) }, 'Save report'))));
  });
  const load = async () => {
    const d = await api('GET', '/api/lab');
    box.replaceChildren(h('p', { class: 'muted' }, 'Tests ordered by the doctors. Mark when the sample is taken, then attach the report as a photo or PDF. The doctor sees it at once.'),
      d.orders.length ? h('div', { class: 'qlist' }, d.orders.map((o) => h('div', { class: 'qrow ' + (o.status === 'reported' ? 'done' : '') },
        h('div', { class: 'qinfo' }, h('span', { class: 'pname' }, o.name), ' ', tag(o.test), o.outsourced ? tag('Outside lab') : null, o.critical ? tag('CRITICAL', 'bad') : null,
          h('div', { class: 'muted' }, [o.age, sexWord(o.sex), o.uhid, o.doctor, o.status === 'ordered' ? 'ordered ' + since(o.ordered_at) + ' ago' : o.status === 'collected' ? 'sample taken ' + since(o.collected_at) + ' ago' : 'reported ' + dayText(o.reported_at)].filter(Boolean).join(' · '))),
        h('div', { class: 'qact' },
          o.status === 'ordered' && h('button', { class: 'btn', onclick: guard(async () => { await api('POST', '/api/lab/' + o.id + '/collected', {}); await load(); }) }, 'Sample collected'),
          o.status !== 'reported' && h('button', { class: 'btn primary', onclick: () => upload(o) }, 'Attach report'),
          o.status === 'reported' && h('a', { class: 'btn', href: '/files/lab/' + o.id, target: '_blank', rel: 'noopener' }, 'Open report')))))
        : h('p', { class: 'empty' }, 'No tests waiting.'));
  };
  S.poll = load;
  await load();
};

// ---------- inpatient chart ----------
VIEWS.ip = async (root, id) => {
  const box = h('div', {});
  root.append(box);
  const post = (path, body) => guard(async () => { await api('POST', '/api/admissions/' + id + path, body); await load(); });
  const addEvent = (kind, fields) => formModal(EVENT_NAMES[kind], fields, {}, async (v) => { await api('POST', '/api/admissions/' + id + '/event', { kind, data: v }); await load(); });
  const load = async () => {
    const [d, ch] = await Promise.all([api('GET', '/api/admissions/' + id), api('GET', '/api/admissions/' + id + '/charges')]);
    const a = d.admission, live = a.status === 'admitted', doc = can(['owner'].concat(DOCS));
    const sum = d.summary, f = {};
    const sumLabels = { diagnosis: 'Final diagnosis', procedure: 'Procedure done', course: 'Course in hospital', condition: 'Condition at discharge', medicines: 'Medicines on discharge', advice: 'Advice', followup: 'Follow-up' };
    const summaryDoc = () => h('div', { class: 'doc' }, docHead('Discharge Summary'),
      tbl2([], [['Patient', a.patient + ' · ' + [a.age, sexWord(a.sex)].join(' · ')], ['UHID', a.uhid], ['Address', a.area], ['Doctor', a.doctor], ['Admitted', dayText(a.admitted_at)], ['Discharged', a.discharged_at ? dayText(a.discharged_at) : dayText(new Date().toISOString())], ['Scheme / cash', a.payer]].map(([k, v]) => h('tr', {}, h('th', {}, k), h('td', {}, v || '')))),
      Object.keys(sumLabels).filter((k) => sum.data[k]).map((k) => [h('h2', {}, sumLabels[k]), h('p', { class: 'pre' }, sum.data[k])]),
      h('p', { class: 'sign' }, sum.final ? 'Signed: ' + sum.signed_by + ', ' + dayText(sum.signed_at) : 'DRAFT — not signed'));
    const stepRow = (s) => h('label', { class: 'step' + (s.done_at ? ' ok' : '') }, h('input', { type: 'checkbox', checked: !!s.done_at, disabled: s.step === 'summary', onchange: (ev) => post('/step', { step: s.step, done: ev.target.checked })() }),
      h('span', {}, s.label, h('small', {}, s.done_at ? 'Done by ' + s.done_by + ' at ' + clock(s.done_at) : s.step === 'summary' ? 'Waiting for the doctor to sign' : 'Waiting')));
    box.replaceChildren(
      h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('div', {}, h('h2', {}, a.patient + ' — bed ' + a.bed), h('div', { class: 'muted' }, [a.age, sexWord(a.sex), a.uhid, a.doctor, a.diagnosis, a.procedure, a.payer].filter(Boolean).join(' · ')),
        h('div', { class: 'muted' }, 'Admitted ' + dayText(a.admitted_at) + (a.discharged_at ? ' · left ' + dayText(a.discharged_at) : '') + (a.attendant_name ? ' · Attendant ' + a.attendant_name + ' ' + (a.attendant_phone || '') : ''))),
        h('a', { class: 'btn', href: '#beds' }, 'All beds')),
        live && !a.discharge_ordered_at && doc && has('chart') && h('div', { class: 'actions' }, h('button', { class: 'btn', onclick: guard(async () => { if (await ask('Order discharge for ' + a.patient + '?', 'Order discharge')) await post('/order-discharge', {})(); }) }, 'Doctor: order discharge')),
        live && a.discharge_ordered_at && h('div', { class: 'discharge' }, h('h3', {}, 'Discharge ordered ' + since(a.discharge_ordered_at) + ' ago — still pending:'), d.steps.map(stepRow),
          h('div', { class: 'actions' }, has('ward') && h('button', { class: 'btn primary', onclick: guard(async () => {
            const left = d.steps.filter((s) => !s.done_at).map((s) => s.label);
            if (!(await ask((left.length ? 'Still pending: ' + left.join(', ') + '.\n\n' : '') + 'Has the patient left? The bed will go for cleaning.', 'Yes, patient has left'))) return;
            await api('POST', '/api/admissions/' + id + '/discharge', {}); go('beds');
          }) }, 'Patient has left'), doc && h('button', { class: 'btn quiet', onclick: post('/order-discharge', { cancel: true }) }, 'Cancel discharge order')))),
      live && has('chart') && h('div', { class: 'actions bar' },
        [
          h('button', { class: 'btn', onclick: () => addEvent('vitals', [{ key: 'Temp', label: 'Temperature (°F)' }, { key: 'Pulse', label: 'Pulse (/min)' }, { key: 'BP', label: 'BP (mmHg)', placeholder: '120/80' }, { key: 'SpO2', label: 'SpO2 (%)' }, { key: 'RR', label: 'Breathing rate (/min)' }, { key: 'Weight', label: 'Weight (kg)' }]) }, 'Vitals'),
          h('button', { class: 'btn', onclick: () => addEvent('medicine', [{ key: 'Medicine', label: 'Medicine and dose given (as written by the doctor)' }, { key: 'Route', label: 'Route', type: 'select', options: [['', '—'], ['Oral', 'Oral'], ['IV', 'IV'], ['IM', 'IM'], ['Other', 'Other']] }]) }, 'Medicine given'),
          !can(DOCS) && h('button', { class: 'btn primary', onclick: () => chargeForm(id, a, ch, null, load) }, 'Service / charge given'),
          !can(DOCS) && h('button', { class: 'btn', onclick: () => chargeForm(id, a, ch, 'days', load) }, 'Room and nursing days'),
          h('button', { class: 'btn', onclick: () => addEvent('io', [{ key: 'Intake', label: 'Intake (ml)' }, { key: 'Output', label: 'Output (ml)' }, { key: 'Note', label: 'Note' }]) }, 'Intake / output'),
          h('button', { class: 'btn', onclick: () => addEvent('note', [{ key: 'Note', label: 'Note for the next shift' }]) }, 'Note / handover'),
          has('ward', 'admit') && h('button', { class: 'btn', onclick: () => shiftBed(id, a, load) }, 'Shift bed')],
        doc && h('button', { class: 'btn', onclick: () => addEvent('round', [{ key: 'Notes', label: 'Round notes' }, { key: 'Orders', label: 'Orders for nurses' }]) }, 'Doctor round')),
      chargePanel(id, a, ch, load),
      h('div', { class: 'cols even' },
        h('section', { class: 'panel' }, h('h2', {}, 'Chart'), d.events.length ? h('div', { class: 'timeline' }, d.events.map((e) => h('div', { class: 'ev ' + e.kind }, h('div', { class: 'muted' }, dayText(e.at).replace(/ \d{4}$/, '') + ', ' + clock(e.at) + ' · ' + e.staff_name),
          h('strong', {}, EVENT_NAMES[e.kind]), ' ', Object.entries(e.data).map(([k, v]) => k + ': ' + v).join(' · '),
          ))) : h('p', { class: 'empty' }, 'Nothing recorded yet.'),
          d.labs.length > 0 && [h('h2', {}, 'Lab reports'), d.labs.map((l) => h('p', {}, l.test + ' — ', l.has_file ? h('a', { href: '/files/lab/' + l.id, target: '_blank', rel: 'noopener' }, 'open report') : l.status, l.critical ? tag('CRITICAL', 'bad') : null))]),
        h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('h2', {}, 'Discharge summary'), sum.final ? tag('Signed by ' + sum.signed_by, 'ok') : tag('Draft', 'warn')),
          h('p', { class: 'muted' }, 'Started from the admission details. The doctor completes and signs it.'),
          Object.entries(sumLabels).map(([k, label]) => { f[k] = area(sum.data[k], k === 'course' || k === 'medicines' ? 4 : 2); f[k].disabled = !doc || !!sum.final; return field(label, f[k]); }),
          h('div', { class: 'actions' },
            doc && !sum.final && h('button', { class: 'btn', onclick: guard(async () => { const data = {}; for (const k in f) data[k] = f[k].value; await api('POST', '/api/admissions/' + id + '/summary', { data }); toast('Saved'); await load(); }) }, 'Save draft'),
            doc && !sum.final && h('button', { class: 'btn primary', onclick: guard(async () => { if (!(await ask('Sign this summary? It will be locked.', 'Sign'))) return; const data = {}; for (const k in f) data[k] = f[k].value; await api('POST', '/api/admissions/' + id + '/summary', { data, final: true }); await load(); }) }, 'Sign'),
            doc && !!sum.final && h('button', { class: 'btn quiet', onclick: guard(async () => { await api('POST', '/api/admissions/' + id + '/summary', { data: sum.data }); await load(); }) }, 'Re-open to change'),
            h('button', { class: 'btn', onclick: () => printDoc(summaryDoc()) }, 'Print / save as PDF')))));
  };
  await load();
};

// ---------- charge slip (replaces the nurse's handwritten slip) ----------
const rupees = (n) => '₹' + Math.round(n || 0).toLocaleString('en-IN');
const unitWord = (u, q) => ({ day: q === 1 ? 'day' : 'days', hour: q === 1 ? 'hour' : 'hours', each: q === 1 ? 'time' : 'times' }[u] || '');

async function chargeForm(id, a, ch, mode, reload) {
  const pr = await api('GET', '/api/prices');
  const items = pr.items.filter((x) => (mode === 'days' ? ['room', 'nursing'].includes(x.category) : !['room'].includes(x.category)));
  if (!items.length) return toast('The price list is empty. Prices are set in Settings > Price list.', true);
  let pick = mode === 'days' ? (ch.room_item || items[0]) : null;
  const qty = h('input', { inputmode: 'decimal', class: 'narrow' });
  const date = h('input', { type: 'date', value: isoToday(), min: a.admitted_at.slice(0, 10), max: isoToday() });
  const note = h('input', { autocomplete: 'off' });
  const search = h('input', { type: 'search', placeholder: 'Search, e.g. dressing', autocomplete: 'off' });
  const list = h('div', { class: 'choice grid' }), info = h('p', { class: 'fee' });
  const draw = () => {
    const q = search.value.trim().toLowerCase();
    list.replaceChildren(Object.entries(pr.categories).map(([cat, label]) => {
      const its = items.filter((x) => x.category === cat && (!q || x.name.toLowerCase().includes(q)));
      return its.length ? [h('h3', { class: 'span' }, label), its.map((x) => h('button', { type: 'button', class: 'opt' + (pick && pick.id === x.id ? ' on' : ''), onclick: () => { pick = x; qty.value = ''; suggest(); draw(); } },
        x.name, h('small', {}, rupees(x.price) + ' ' + pr.units[x.unit])))] : null;
    }));
    const n = parseFloat(qty.value);
    info.replaceChildren(pick ? [pick.name + ': ', h('strong', {}, (n > 0 ? n : '?') + ' ' + unitWord(pick.unit, n)), ' × ' + rupees(pick.price) + ' = ', h('strong', {}, n > 0 ? rupees(n * pick.price) : '—')] : 'Choose what was given.');
  };
  const suggest = () => {
    if (!pick || qty.value) return;
    if (pick.category === 'room') qty.value = Math.max(ch.stay_days - ch.room_days, 1);
    else if (pick.category === 'nursing') qty.value = Math.max(ch.stay_days - ch.nursing_days, 1);
    else qty.value = 1;
  };
  qty.addEventListener('input', draw);
  search.addEventListener('input', draw);
  const save = h('button', { class: 'btn primary big', type: 'submit' }, 'Save');
  const form = h('form', { class: 'form' },
    mode === 'days' && h('p', { class: 'note' }, 'Stay so far: ' + ch.stay_days + ' day' + (ch.stay_days > 1 ? 's' : '') + ' (each 24 hours or part). Already recorded: room ' + ch.room_days + ', nursing ' + ch.nursing_days + '. Enter only the days not yet recorded.'),
    mode !== 'days' && search, list, h('div', { class: 'agerow' }, h('span', {}, 'How many'), qty, h('span', {}, 'on'), date), field('Note (optional)', note), info,
    h('p', { class: 'muted' }, 'Prices come from the hospital price list and cannot be changed here.'),
    h('div', { class: 'actions' }, save));
  const m = modal(mode === 'days' ? 'Room and nursing days' : 'Service / charge given', form);
  form.addEventListener('submit', guard(async (ev) => {
    ev.preventDefault();
    if (!pick) throw new Error('Choose what was given');
    save.disabled = true;
    try { await api('POST', '/api/admissions/' + id + '/charges', { item_id: pick.id, qty: qty.value, for_date: date.value, note: note.value }); }
    finally { save.disabled = false; }
    toast('Saved: ' + pick.name); m.close(); await reload();
  }));
  suggest(); draw();
}

function chargePanel(id, a, ch, reload) {
  const slip = () => h('div', { class: 'doc' }, docHead('Inpatient Charge Slip'),
    tbl2([], [['Patient', a.patient + ' · ' + a.uhid], ['Bed', a.bed + ' (' + a.ward + ')'], ['Doctor', a.doctor], ['Admitted', dayText(a.admitted_at)], ['Scheme / cash', a.payer]].map(([k, v]) => h('tr', {}, h('th', {}, k), h('td', {}, v || '')))),
    h('h2', {}, 'Charges'), tbl2(['Date', 'Item', 'Qty', 'Rate', 'Amount', 'Entered by'], ch.lines.filter((x) => !x.cancelled).map((x) => h('tr', {}, h('td', {}, dayText(x.for_date || x.entered_at)), h('td', {}, x.name + (x.note ? ' (' + x.note + ')' : '')), h('td', {}, x.qty + ' ' + unitWord(x.unit, x.qty)), h('td', {}, rupees(x.rate)), h('td', {}, rupees(x.amount)), h('td', {}, x.entered_by)))),
    h('p', { class: 'sign' }, 'Total: ' + rupees(ch.total) + ' · Paid so far: ' + rupees(ch.paid) + ' · ' + (ch.balance >= 0 ? 'Balance: ' + rupees(ch.balance) : 'Advance remaining: ' + rupees(-ch.balance))),
    h('p', {}, ch.final ? 'Final bill.' : 'Running total. The final bill is made at discharge.'));
  const row = (x) => h('tr', { class: x.cancelled ? 'off cancelled' : '' },
    h('td', {}, dayText(x.for_date || x.entered_at).replace(/ \d{4}$/, '')), h('td', {}, x.name, x.note ? h('div', { class: 'muted' }, x.note) : null, x.cancelled ? h('div', { class: 'muted' }, 'Cancelled by ' + x.cancelled_by + ': ' + x.cancel_reason) : null),
    h('td', {}, x.qty + ' ' + unitWord(x.unit, x.qty)), h('td', { class: 'num' }, rupees(x.rate)), h('td', { class: 'num' }, rupees(x.amount)), h('td', { class: 'muted' }, x.entered_by),
    h('td', {}, !x.cancelled && !can(DOCS) && (['pharmacy', 'outside'].includes(x.category) ? has('ipbill', 'pharmacy') : has('chart', 'ipbill')) && h('button', { class: 'btn quiet', onclick: () => formModal('Cancel: ' + x.name, [{ key: 'reason', label: 'Why is this entry wrong?' }], {}, async (v) => { await api('POST', '/api/charges/' + x.id + '/cancel', v); await reload(); }) }, 'Cancel')));
  return h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('h2', {}, 'Charges'), h('div', { class: 'qact' },
      has('ipbill') && h('a', { class: 'btn', href: '#bill/' + id }, 'Open bill'),
      has('chart') && !can(DOCS) && ch.lines.length > 0 && !ch.final && h('button', { class: 'btn primary', onclick: guard(async () => { await api('POST', '/api/admissions/' + id + '/slip', {}); toast('Charge slip sent. It shows on the IP billing dashboard.'); await reload(); }) }, 'Send charge slip'),
      h('button', { class: 'btn', onclick: () => printDoc(slip()) }, 'Print charge slip'))),
    ch.slips.length > 0 && h('p', { class: ch.slips[0].checked_at ? 'ok-line' : 'muted' }, 'Last charge slip sent ' + dayText(ch.slips[0].sent_at) + ', ' + clock(ch.slips[0].sent_at) + ' by ' + ch.slips[0].sent_by + ' (' + rupees(ch.slips[0].total) + ') — ' +
      (ch.slips[0].checked_at ? 'checked by ' + ch.slips[0].checked_by : 'waiting to be checked')),
    h('p', { class: 'muted' }, 'Staff record what was given and how many days or times; the amount comes from the price list set by the hospital. Wrong entries are cancelled with a reason, never deleted.'),
    ch.lines.length ? h('div', { class: 'scroll' }, tbl2(['Date', 'Item', 'Quantity', 'Rate', 'Amount', 'By', ''], ch.lines.map(row))) : h('p', { class: 'empty' }, 'No charges recorded yet.'),
    h('div', { class: 'totals' }, Object.entries(ch.by_category).map(([c, v]) => h('span', {}, (ch.categories[c] || c) + ': ' + rupees(v))), h('strong', {}, 'Total ' + rupees(ch.total))));
}

async function shiftBed(id, a, reload) {
  const b = await api('GET', '/api/beds');
  const free = b.beds.filter((x) => x.status !== 'occupied');
  if (!free.length) return toast('No free bed', true);
  formModal('Shift ' + a.patient + ' from ' + a.bed, [{ key: 'bed_id', label: 'New bed', type: 'select', options: free.map((x) => [x.id, x.label + ' — ' + x.ward + (x.status !== 'vacant' ? ' (' + BED_STATUS[x.status].toLowerCase() + ')' : '')]) }], {},
    async (v) => { await api('POST', '/api/admissions/' + id + '/transfer', v); toast('Shifted. Old bed marked for cleaning. Record room days for the new ward from today.'); await reload(); });
}

// ---------- operation theatre ----------
VIEWS.ot = async (root) => {
  let day = isoToday();
  const list = h('div', {});
  const fields = () => [{ key: 'patient_name', label: 'Patient' }, { key: 'procedure', label: 'Procedure' }, { key: 'surgeon_id', label: 'Surgeon', type: 'select', options: S.doctors.map((x) => [x.id, x.name]) },
    { key: 'anesthetist', label: 'Anesthetist' }, { key: 'ot_date', label: 'Date', type: 'date' }, { key: 'start_time', label: 'Start', type: 'time' }, { key: 'end_time', label: 'End (expected)', type: 'time' }];
  const save = (extra) => async (v) => {
    const r = await api('POST', '/api/ot', Object.assign(v, extra));
    if (r.clash && r.clash.length) setTimeout(() => tell('Saved, but the theatre is already booked at that time:\n' + r.clash.map((c) => c.start_time + '–' + c.end_time + ' ' + c.patient_name).join('\n'), 'Time clash'), 100);
    day = v.ot_date; dateInput.value = day; await load();
  };
  const dateInput = h('input', { type: 'date', value: day, onchange: (e) => { day = e.target.value || isoToday(); load(); } });
  const load = async () => {
    const d = await api('GET', '/api/ot?date=' + day), edit = has('ot');
    list.replaceChildren(d.bookings.length ? h('div', { class: 'qlist' }, d.bookings.map((o) => h('div', { class: 'qrow ' + (o.status === 'done' ? 'done' : '') },
      h('div', { class: 'tok small' }, o.start_time + '–' + o.end_time),
      h('div', { class: 'qinfo' }, h('span', { class: 'pname' }, o.patient_name), ' ', o.clash ? tag('Time clash', 'bad') : null, o.status === 'done' ? tag('Done', 'ok') : null,
        h('div', { class: 'muted' }, [o.procedure, o.surgeon, o.anesthetist ? 'Anesthetist: ' + o.anesthetist : 'Anesthetist not fixed'].filter(Boolean).join(' · ')),
        h('div', { class: 'checks' }, OT_CHECKS.map(([k, label]) => h('label', {}, h('input', { type: 'checkbox', checked: o.checklist.includes(k), disabled: o.status === 'done', onchange: guard(async (ev) => {
          const set = new Set(o.checklist); if (ev.target.checked) set.add(k); else set.delete(k);
          await api('POST', '/api/ot', { id: o.id, checklist: [...set] }); await load();
        }) }), ' ' + label)))),
      edit && o.status !== 'done' && h('div', { class: 'qact' },
        h('button', { class: 'btn primary', onclick: guard(async () => { await api('POST', '/api/ot', { id: o.id, status: 'done' }); await load(); }) }, 'Done'),
        h('button', { class: 'btn', onclick: () => formModal('Change booking', fields(), o, save({ id: o.id })) }, 'Change'),
        h('button', { class: 'btn quiet', onclick: guard(async () => { if (await ask('Cancel this operation booking?', 'Cancel booking')) { await api('POST', '/api/ot', { id: o.id, status: 'cancelled' }); await load(); } }) }, 'Cancel')))))
      : h('p', { class: 'empty' }, 'No operations booked for this day.'));
  };
  root.append(h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('h2', {}, 'Operation theatre'), h('div', { class: 'qact' }, dateInput,
    has('ot') && h('button', { class: 'btn primary', onclick: () => formModal('Book operation', fields(), { ot_date: day, surgeon_id: S.doctors[0] && S.doctors[0].id }, save({})) }, 'Book operation'))), list));
  S.poll = load;
  await load();
};

// ---------- claims ----------
VIEWS.claims = async (root) => {
  const box = h('div', {});
  root.append(box);
  const packet = async (c, how) => {
    const d = await api('GET', '/api/claims/' + c.id + '/packet');
    const a = d.admission, s = d.summary.data;
    const el = h('div', { class: 'doc' }, docHead('Claim file — ' + c.scheme),
      tbl2([], [['Patient', a.patient + ' · ' + [a.age, sexWord(a.sex)].join(' · ')], ['UHID', a.uhid], ['Address', a.area], ['Phone', a.phone], ['Claim / pre-auth no.', c.claim_no], ['Treating doctor', a.doctor],
        ['Admitted', dayText(a.admitted_at)], ['Discharged', a.discharged_at ? dayText(a.discharged_at) : 'Still admitted'], ['Diagnosis', s.diagnosis || a.diagnosis], ['Procedure', s.procedure || a.procedure]].map(([k, v]) => h('tr', {}, h('th', {}, k), h('td', {}, v || '')))),
      h('h2', {}, 'Course in hospital'), h('p', { class: 'pre' }, s.course || '—'), h('h2', {}, 'Condition at discharge'), h('p', { class: 'pre' }, s.condition || '—'),
      h('h2', {}, 'Investigations'), d.labs.length ? tbl2(['Test', 'Status'], d.labs.map((l) => h('tr', {}, h('td', {}, l.test), h('td', {}, l.status === 'reported' ? 'Report dated ' + dayText(l.reported_at) : l.status)))) : h('p', {}, '—'),
      h('h2', {}, 'Services and doctor rounds'), d.events.length ? tbl2(['Date', 'Entry', 'By'], d.events.map((e) => h('tr', {}, h('td', {}, dayText(e.at)), h('td', {}, Object.values(e.data).join(' · ')), h('td', {}, e.staff_name)))) : h('p', {}, '—'),
      h('h2', {}, 'Documents'), tbl2(['Document', 'Attached'], d.claim.items.map((i) => h('tr', {}, h('td', {}, i), h('td', {}, d.claim.checked.includes(i) ? 'Yes' : 'NO')))),
      d.claim.missing.length > 0 && h('p', {}, h('strong', {}, 'Missing: '), d.claim.missing.join('; ')),
      h('p', { class: 'sign' }, d.summary.final ? 'Discharge summary signed by ' + d.summary.signed_by : 'Discharge summary NOT signed'));
    if (how === 'word') wordFile(el, 'Claim-' + a.uhid); else printDoc(el);
  };
  // Documents: photograph or attach each paper; things the system already has are included automatically.
  const documents = (c) => {
    const body = h('div', {});
    const m = modal('Documents — ' + c.patient, body, load);
    const draw = (cl) => {
      body.replaceChildren(
        h('p', { class: 'muted' }, 'Take a photo of each paper with the phone, or attach a PDF. Lab reports, round notes and the signed discharge summary are added from the system by themselves.'),
        cl.items.map((item) => {
          const files = cl.docs.filter((x) => x.item === item);
          const auto = cl.auto.includes(item), ticked = cl.checked.includes(item);
          return h('div', { class: 'step' + (files.length || auto || ticked ? ' ok' : '') },
            h('span', {}, item, h('small', {}, auto ? 'Added from the system' : files.length ? files.length + ' file' + (files.length > 1 ? 's' : '') + ' attached' : ticked ? 'Marked as given on paper' : 'Not attached yet'),
              files.map((f) => h('small', {}, h('a', { href: '/files/claimdoc/' + f.id, target: '_blank', rel: 'noopener' }, 'Open'), ' · ', f.uploaded_by, ' · ',
                h('a', { href: '#', onclick: guard(async (ev) => { ev.preventDefault(); if (!(await ask('Remove this file?', 'Remove'))) return; await api('POST', '/api/claim-docs/' + f.id + '/remove', {}); await refresh(); }) }, 'remove')))),
            !auto && h('div', { class: 'qact' },
              h('button', { class: 'btn', onclick: () => pickFile('image/*,application/pdf', guard(async (file) => {
                toast('Saving...');
                await api('POST', '/api/claims/' + c.id + '/doc?item=' + encodeURIComponent(item), file.type === 'application/pdf' ? file : await shrink(file));
                toast('Attached'); await refresh();
              })) }, files.length ? 'Add another' : 'Photo / file'),
              !files.length && h('button', { class: 'btn quiet', onclick: guard(async () => {
                const set = new Set(cl.checked); if (ticked) set.delete(item); else set.add(item);
                await api('POST', '/api/claims/' + c.id, { checked: [...set] }); await refresh();
              }) }, ticked ? 'Undo' : 'Given on paper')));
        }));
    };
    const refresh = async () => { const d = await api('GET', '/api/claims'); draw(d.claims.find((x) => x.id === c.id)); };
    draw(c);
  };
  // Every field the insurer's portal asks for, in one list with copy buttons: no retyping from paper or Word.
  const portal = async (c) => {
    const d = await api('GET', '/api/claims/' + c.id + '/portal');
    const copy = (v) => (navigator.clipboard ? navigator.clipboard.writeText(v) : Promise.reject()).then(() => toast('Copied — paste it in the portal'), () => toast('Select and copy by hand', true));
    modal('Details for the portal — ' + c.patient, h('div', {},
      h('p', { class: 'muted' }, 'Open the insurer\'s portal in another tab. Tap a value here to copy it, then paste it into the same box on the portal.'),
      h('div', { class: 'portal' }, d.fields.map((f) => h('button', { class: 'ef wide', disabled: !f.value, onclick: () => copy(f.value) }, h('small', {}, f.label), f.value || '— not filled —'))),
      h('p', { class: 'muted' }, 'Card / member ID and pre-auth number are filled in with "Status".')));
  };
  // The whole claim as one file: claim details and discharge summary as Word, portal details, lab reports and every attached photo.
  const zipFile = async (c) => {
    const r = await fetch('/api/claims/' + c.id + '/zip');
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || 'Could not make the file');
    const name = (r.headers.get('Content-Disposition') || '').split('filename="')[1].replace('"', '');
    return new File([await r.blob()], name, { type: 'application/zip' });
  };
  const download = async (c) => {
    const f = await zipFile(c);
    const a = h('a', { href: URL.createObjectURL(f), download: f.name }); document.body.append(a); a.click(); a.remove();
    toast('Saved to Downloads: ' + f.name);
  };
  const share = async (c) => {
    const f = await zipFile(c);
    if (navigator.canShare && navigator.canShare({ files: [f] })) await navigator.share({ files: [f], title: 'Claim ' + c.patient });
    else { const a = h('a', { href: URL.createObjectURL(f), download: f.name }); document.body.append(a); a.click(); a.remove(); toast('This browser cannot share directly, so the file was saved to Downloads.'); }
  };
  let filter = 'open';
  const timeline = async (c) => {
    const d = await api('GET', '/api/claims/' + c.id + '/events');
    modal('Timeline — ' + c.patient, h('div', { class: 'tl' }, d.events.length ? d.events.map((e) => h('div', { class: 'tl-row ' + e.kind },
      h('div', { class: 'tl-dot' }), h('div', {}, h('strong', {}, e.label), e.detail ? h('div', {}, e.detail) : null, h('div', { class: 'muted' }, dayText(e.at) + ', ' + clock(e.at) + ' · ' + (e.staff_name || ''))))) : h('p', { class: 'empty' }, 'Nothing recorded yet.')));
  };
  const follow = (c) => {
    const nxt = new Date(); nxt.setDate(nxt.getDate() + 2);
    formModal('Follow-up — ' + c.patient, [{ key: 'note', label: 'What happened? (who you spoke to, what they said)' }, { key: 'next_followup', label: 'Next follow-up on', type: 'date' }],
      { next_followup: nxt.toISOString().slice(0, 10) }, async (v) => { await api('POST', '/api/claims/' + c.id + '/followup', v); await load(); });
  };
  const load = async () => {
    const [d, sm] = await Promise.all([api('GET', '/api/claims'), api('GET', '/api/claims/summary')]);
    const td = isoToday();
    const isOpen = (c) => !['settled', 'rejected'].includes(c.status);
    const groups = {
      new: ['New from inpatients', (c) => c.sent_at && !c.picked_at && isOpen(c)],
      due: ['Follow-up due', (c) => c.next_followup && c.next_followup <= td && isOpen(c)],
      stale: ['No update 7+ days', (c) => ['submitted', 'queried'].includes(c.status) && c.idle_days >= 7],
      open: ['All open', isOpen],
      closed: ['Settled / rejected', (c) => !isOpen(c)],
    };
    const list = d.claims.filter(groups[filter][1]);
    const me = sm.today.by_person[S.me.name] || { submitted: 0, docs: 0, followups: 0, files: 0 };
    const stat = (n, label, cls) => h('div', { class: 'stat' + (cls ? ' ' + cls : '') }, h('strong', {}, n), h('span', {}, label));
    box.replaceChildren(
      h('div', { class: 'cl-head' },
        h('section', { class: 'panel' }, h('h3', {}, S.me.role === 'insurance' ? 'Your work today' : 'Insurance desk today'),
          h('div', { class: 'stats three' }, stat(S.me.role === 'insurance' ? me.submitted : sm.today.submitted, 'claims submitted to insurers'),
            stat(S.me.role === 'insurance' ? me.docs : sm.today.docs, 'documents attached'), stat(S.me.role === 'insurance' ? me.followups : sm.today.followups, 'follow-ups done')),
          S.me.role !== 'insurance' && Object.keys(sm.today.by_person).length > 0 && h('p', { class: 'muted' }, Object.entries(sm.today.by_person).map(([k, v]) => k + ': ' + v.submitted + ' submitted, ' + v.docs + ' documents, ' + v.followups + ' follow-ups').join(' · '))),
        h('section', { class: 'panel' }, h('h3', {}, 'Waiting'),
          h('div', { class: 'stats three' }, stat(sm.new.length, 'new from inpatients', sm.new.length ? 'hot' : ''), stat(sm.due.length, 'follow-ups due', sm.due.length ? 'hot' : ''),
            stat('₹' + Math.round(sm.pending_amount).toLocaleString('en-IN'), 'pending with insurers')),
          sm.stale.length > 0 && h('p', { class: 'missing' }, sm.stale.length + ' submitted or queried claim(s) with no update for 7 days or more.'))),
      h('div', { class: 'pills' }, Object.entries(groups).map(([k, [label, fn]]) => h('button', { class: 'pill' + (filter === k ? ' on' : ''), onclick: () => { filter = k; load(); } }, label, h('small', {}, d.claims.filter(fn).length)))),
      list.length ? h('div', { class: 'qlist claims-list' }, list.map((c) => h('div', { class: 'qrow' + (c.next_followup && c.next_followup <= td && isOpen(c) ? ' late' : '') },
        h('div', { class: 'qinfo' }, h('a', { class: 'pname', href: '#ip/' + c.admission_id }, c.patient), ' ', tag(c.scheme), tag(CLAIM_NAMES[c.status] + ' · ' + c.days + ' days', c.status === 'rejected' || c.status === 'queried' ? 'bad' : c.status === 'settled' ? 'ok' : 'warn'),
          c.sent_at && !c.picked_at ? tag('New', 'bad') : null,
          h('div', { class: 'muted' }, [c.uhid, 'Bed ' + c.bed, c.doctor, c.procedure || c.diagnosis, c.member_id && 'Card ' + c.member_id, c.claim_no && 'No. ' + c.claim_no, c.bill && c.bill.scheme_amount ? 'Claim ₹' + c.bill.scheme_amount.toLocaleString('en-IN') : null, c.reason && 'Reason: ' + c.reason].filter(Boolean).join(' · ')),
          h('div', { class: 'muted' }, c.sent_at ? 'Sent to the desk ' + dayText(c.sent_at) + ' by ' + c.sent_by : 'Not sent from inpatient billing yet', c.next_followup ? ' · next follow-up ' + dayText(c.next_followup) : '', ' · last update ' + (c.idle_days ? c.idle_days + ' days ago' : 'today')),
          c.missing.length ? h('div', { class: 'missing' }, 'Missing (' + c.missing.length + '): ' + c.missing.join('; ')) : h('div', { class: 'ok-line' }, 'All documents ready')),
        h('div', { class: 'qact' }, h('button', { class: 'btn primary', onclick: () => follow(c) }, 'Follow-up'), h('button', { class: 'btn', onclick: guard(() => timeline(c)) }, 'Timeline'),
          h('button', { class: 'btn', onclick: () => documents(c) }, 'Documents'),
          h('button', { class: 'btn', onclick: guard(() => portal(c)) }, 'Portal details'),
          h('button', { class: 'btn', onclick: () => formModal('Claim status — ' + c.patient, [{ key: 'status', label: 'Status', type: 'select', options: Object.entries(CLAIM_NAMES) }, { key: 'member_id', label: 'Card / member ID' }, { key: 'claim_no', label: 'Pre-auth / claim number' }, { key: 'reason', label: 'Reason (for query or rejection)' }], c, async (v) => { await api('POST', '/api/claims/' + c.id, v); await load(); }) }, 'Status'),
          h('button', { class: 'btn', onclick: guard(() => download(c)) }, 'Download claim file'),
          h('button', { class: 'btn quiet', onclick: guard(() => share(c)) }, 'Share'),
          h('button', { class: 'btn quiet', onclick: guard(() => packet(c, 'print')) }, 'Print')))))
        : h('p', { class: 'empty' }, filter === 'open' ? 'No open claims.' : 'Nothing here.'));
  };
  S.poll = load;
  await load();
};

// ---------- pharmacy ----------
VIEWS.pharmacy = async (root) => {
  const box = h('div', {});
  root.append(box);
  const copy = (text) => (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(() => toast('Copied. Paste it in WhatsApp to the distributor.'), () => toast('Could not copy', true));
  const load = async () => {
    const [d, r] = await Promise.all([api('GET', '/api/pharmacy'), api('GET', '/api/dose-refs')]);
    const stockRows = (list) => tbl2(['Item', 'Batch', 'Expiry', 'Qty', 'Supplier'], list.map((x) => h('tr', {}, h('td', {}, x.item), h('td', {}, x.batch), h('td', {}, dayText(x.expiry), ' ', tag(x.days < 0 ? 'expired' : x.days + ' days', x.days <= 30 ? 'bad' : 'warn')), h('td', { class: 'num' }, x.qty), h('td', {}, x.supplier))));
    const bySupplier = {};
    d.low.forEach((x) => { (bySupplier[x.supplier || 'Supplier not known'] = bySupplier[x.supplier || 'Supplier not known'] || []).push(x); });
    const drug = h('select', {}, r.refs.map((x) => h('option', { value: x.id }, x.drug))), kg = h('input', { inputmode: 'decimal', class: 'narrow' }), result = h('div', {});
    box.replaceChildren(
      h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('h2', {}, 'Stock alerts'), h('button', { class: 'btn primary', onclick: () => pickFile('.csv,text/csv,text/plain', guard(async (file) => {
        const res = await api('POST', '/api/pharmacy/import', new Blob([await file.arrayBuffer()], { type: 'text/csv' }));
        await tell(res.rows + ' stock lines read.' + (res.errors.length ? '\n\nCould not read:\n' + res.errors.join('\n') : ''), 'Stock loaded'); await load();
      })) }, 'Load stock file from Pharmasoft')),
        h('p', { class: 'muted' }, d.last_import ? 'Last loaded ' + dayText(d.last_import.at) + ', ' + clock(d.last_import.at) + ' by ' + d.last_import.staff_name + ' · ' + d.items + ' lines. ' : 'No stock loaded yet. ', 'In Pharmasoft, export the stock list (with batch and expiry) as CSV and load it here, once a day or once a week. Pharmasoft itself is not touched.'),
        d.expired.length > 0 && [h('h3', {}, 'Already expired (' + d.expired.length + ') — remove from the shelf'), h('div', { class: 'scroll' }, stockRows(d.expired))],
        h('h3', {}, 'Expiring in the next ' + d.window + ' days (' + d.expiring.length + ')'), d.expiring.length ? h('div', { class: 'scroll' }, stockRows(d.expiring)) : h('p', { class: 'empty' }, 'Nothing.'),
        h('h3', {}, 'Low stock — ' + d.low_qty + ' or fewer left (' + d.low.length + ')'),
        d.low.length ? Object.entries(bySupplier).map(([sup, items]) => h('div', { class: 'order' }, h('div', { class: 'headrow' }, h('strong', {}, sup),
          h('button', { class: 'btn', onclick: () => copy('Order from ' + S.hospital + ' pharmacy:\n' + items.map((x) => '- ' + x.item + ' : ____').join('\n')) }, 'Copy order draft')),
          h('ul', {}, items.map((x) => h('li', {}, x.item + ' — ' + x.qty + ' left'))))) : h('p', { class: 'empty' }, 'Nothing.'),
        h('p', { class: 'muted' }, 'Order drafts leave the quantity blank for the pharmacist to fill. Nothing is ordered automatically.')),
      h('section', { class: 'panel' }, h('h2', {}, 'Child dose check'),
        h('p', { class: 'muted' }, 'A cross-check only. It shows the range the hospital\'s doctors entered for the child\'s weight. It does not replace the prescription; if the prescribed dose is outside the range, ask the doctor.'),
        r.refs.length ? [h('div', { class: 'agerow' }, drug, h('span', {}, 'Weight'), kg, h('span', {}, 'kg'), h('button', { class: 'btn primary', onclick: guard(async () => {
          const x = await api('POST', '/api/dose-check', { ref_id: drug.value, weight_kg: kg.value });
          result.replaceChildren(h('div', { class: 'dose' }, h('div', {}, x.drug + ' for ' + x.weight_kg + ' kg'), h('strong', {}, x.low_mg + ' to ' + x.high_mg + ' mg per ' + x.per), x.capped && h('div', {}, 'Limited by the maximum dose.'), x.note && h('div', {}, x.note), h('div', { class: 'muted' }, 'Reference entered by ' + x.confirmed_by + '. Confirm with the doctor if in doubt.')));
        }) }, 'Check')), result] : h('p', { class: 'empty' }, 'No dose reference has been entered yet. Drugs are added in Settings > Child dose reference.')));
  };
  await load();
};

// "Bought / not bought" on the pharmacy's prescription list
window.rxExtras = (v, reload) => [
  v.bought === 1 ? tag('Bought', 'ok') : v.bought === 0 ? tag('Not bought' + (v.not_bought_reason ? ': ' + v.not_bought_reason : ''), 'warn') : null,
  h('button', { class: 'btn', onclick: guard(async () => { await api('POST', '/api/visits/' + v.id + '/bought', { bought: true }); await reload(); }) }, 'Bought here'),
  h('button', { class: 'btn', onclick: () => formModal('Not bought — why?', [{ key: 'reason', label: 'Reason', type: 'select', options: ['Not in stock', 'Too costly', 'Bought outside', 'Already has it', 'Did not come to pharmacy', 'Other'].map((x) => [x, x]) }], { reason: 'Not in stock' }, async (x) => { await api('POST', '/api/visits/' + v.id + '/bought', { bought: false, reason: x.reason }); await reload(); }) }, 'Not bought'),
];

// ---------- staff: attendance, roster, salary, payouts ----------
VIEWS.staff = async (root) => {
  let tab = 'attendance', month = isoToday().slice(0, 7), week = isoToday();
  const box = h('div', {});
  const tabs = h('div', { class: 'pills' });
  root.append(tabs, box);
  const money = (n) => '₹' + Math.round(n).toLocaleString('en-IN');
  const monthInput = () => h('input', { type: 'month', value: month, onchange: (e) => { month = e.target.value || month; load(); } });
  const MARKS = ['', 'P', 'A', 'L', 'H', 'O'];
  const views = {
    attendance: async () => {
      const d = await api('GET', '/api/attendance?month=' + month);
      box.replaceChildren(h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('h2', {}, 'Attendance'), monthInput()),
        h('p', { class: 'muted' }, 'Staff mark themselves in from their own login (top of the screen). Tap a box to correct it: P present · A absent · L paid leave · H half day · O weekly off.'),
        h('div', { class: 'scroll' }, h('table', { class: 'plain att' }, h('thead', {}, h('tr', {}, h('th', {}, 'Name'), Array.from({ length: d.days }, (_, i) => h('th', {}, i + 1)))),
          h('tbody', {}, d.staff.map((s) => h('tr', {}, h('td', {}, s.name), s.days.map((m, i) => h('td', {}, h('button', { class: 'mark m' + m, onclick: guard(async (ev) => {
            const next = MARKS[(MARKS.indexOf(ev.target.textContent) + 1) % MARKS.length];
            await api('POST', '/api/attendance', { staff_id: s.id, day: d.month + '-' + String(i + 1).padStart(2, '0'), status: next });
            ev.target.textContent = next; ev.target.className = 'mark m' + next;
          }) }, m))))))))));
    },
    roster: async () => {
      const d = await api('GET', '/api/roster?week=' + week);
      const shifts = ['', 'Morning', 'Evening', 'Night', 'Full day', 'Off'];
      box.replaceChildren(h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('h2', {}, 'Duty roster'), h('input', { type: 'date', value: week, onchange: (e) => { week = e.target.value || week; load(); } })),
        d.gaps.length > 0 && h('div', { class: 'note' }, h('strong', {}, 'Gaps: '), d.gaps.map((g) => dayText(g.slice(0, 10)).replace(/ \d{4}$/, '') + g.slice(10)).join(' · ')),
        h('div', { class: 'scroll' }, tbl2(['Name'].concat(d.days.map((x) => new Date(x).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric' }))), d.staff.map((s) => h('tr', {}, h('td', {}, s.name, h('div', { class: 'muted' }, ROLE_NAMES[s.role])),
          s.shifts.map((sh, i) => h('td', {}, h('select', { class: 'shift', value: sh, onchange: guard(async (ev) => { await api('POST', '/api/roster', { staff_id: s.id, day: d.days[i], shift: ev.target.value }); await load(); }) }, shifts.map((x) => h('option', { value: x }, x || '—'))))))))),
        h('p', { class: 'muted' }, 'A day marked Off counts as a paid weekly off in salary.')));
    },
    salary: async () => {
      const d = await api('GET', '/api/payroll?month=' + month);
      const slip = (r) => h('div', { class: 'doc' }, docHead('Payslip — ' + d.month), tbl2([], [['Name', r.name], ['Role', ROLE_NAMES[r.role]], ['Monthly salary', money(r.salary)], ['Days in month', r.days], ['Paid days', r.paid_days + ' (present ' + r.present + ', leave ' + r.leave + ', weekly off ' + r.off + ', half days ' + r.half + ')'], ['Absent / not marked', r.absent + ' / ' + r.unmarked], ['Earned', money(r.earned)]]
        .concat(r.deductions.map((x) => ['Less: ' + x.name, money(x.amount)]), [['Net pay', money(r.net)]]).map(([k, v]) => h('tr', {}, h('th', {}, k), h('td', {}, v)))));
      const csv = () => { const rows = [['Name', 'Role', 'Salary', 'Paid days', 'Earned'].concat((d.rows[0] ? d.rows[0].deductions : []).map((x) => x.name), ['Net'])].concat(d.rows.map((r) => [r.name, r.role, r.salary, r.paid_days, r.earned].concat(r.deductions.map((x) => x.amount), [r.net])));
        const a = h('a', { href: URL.createObjectURL(new Blob([rows.map((x) => x.join(',')).join('\n')], { type: 'text/csv' })), download: 'salary-' + d.month + '.csv' }); document.body.append(a); a.click(); a.remove(); };
      box.replaceChildren(h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('h2', {}, 'Salary'), h('div', { class: 'qact' }, monthInput(), h('button', { class: 'btn', onclick: csv }, 'Export for accountant'))),
        h('p', { class: 'muted' }, 'Worked out from attendance: salary × paid days ÷ days in the month. Days not marked are not paid, so complete the attendance first. Set salaries in Settings > Staff logins and deductions (PF, ESI, professional tax) in Settings > Salary deductions. Have the accountant check the rules before paying from this.'),
        d.rows.length ? h('div', { class: 'scroll' }, tbl2(['Name', 'Salary', 'Paid days', 'Not marked', 'Earned', 'Deductions', 'Net', ''], d.rows.map((r) => h('tr', {}, h('td', {}, r.name, h('div', { class: 'muted' }, ROLE_NAMES[r.role])), h('td', {}, money(r.salary)), h('td', {}, r.paid_days + ' / ' + r.days), h('td', {}, r.unmarked ? tag(r.unmarked, 'warn') : '0'),
          h('td', {}, money(r.earned)), h('td', {}, money(r.deductions.reduce((a, x) => a + x.amount, 0))), h('td', {}, h('strong', {}, money(r.net))), h('td', {}, h('button', { class: 'btn quiet', onclick: () => printDoc(slip(r)) }, 'Payslip'))))))
          : h('p', { class: 'empty' }, 'No salaries entered yet. Add each person\'s monthly salary in Settings > Staff logins.')));
    },
    payouts: async () => {
      const d = await api('GET', '/api/payouts?month=' + month);
      const kinds = { visit: 'per OP visit', case: 'per case (OP + IP)', fixed: 'fixed per month', '': 'not set' };
      box.replaceChildren(h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('h2', {}, 'Visiting consultant statement'), h('div', { class: 'qact' }, monthInput(),
        h('button', { class: 'btn', onclick: () => printDoc(h('div', { class: 'doc' }, docHead('Consultant statement — ' + d.month), tbl2(['Doctor', 'OP patients seen', 'Admissions', 'Rate', 'Amount'], d.rows.map((r) => h('tr', {}, h('td', {}, r.name), h('td', {}, r.visits), h('td', {}, r.admissions), h('td', {}, money(r.payout_rate) + ' ' + kinds[r.payout_kind || '']), h('td', {}, money(r.amount))))))) }, 'Print'))),
        h('p', { class: 'muted' }, 'Counted from OP patients marked Done and admissions recorded here. Set each doctor\'s rate in Settings > Doctors.'),
        h('div', { class: 'scroll' }, tbl2(['Doctor', 'OP patients seen', 'Admissions', 'Rate', 'Amount'], d.rows.map((r) => h('tr', {}, h('td', {}, r.name, h('div', { class: 'muted' }, r.dept)), h('td', {}, r.visits), h('td', {}, r.admissions), h('td', {}, r.payout_kind ? money(r.payout_rate) + ' ' + kinds[r.payout_kind] : tag('not set', 'warn')), h('td', {}, h('strong', {}, money(r.amount)))))))));
    },
  };
  const load = async () => {
    tabs.replaceChildren([['attendance', 'Attendance'], ['roster', 'Duty roster'], ['salary', 'Salary'], ['payouts', 'Consultants']].map(([k, label]) => h('button', { class: 'pill' + (tab === k ? ' on' : ''), onclick: () => { tab = k; load(); } }, label)));
    await views[tab]();
  };
  await load();
};

// ---------- extra lines on the Hospital overview ----------
window.todayExtras = (m) => [
  m.consultants_not_in.length > 0 && h('li', {}, h('a', { href: '#doctors' }, 'Visiting doctors expected today, not arrived yet'), ': ' + m.consultants_not_in.join(', ')),
  m.followups.missed > 0 && h('li', {}, h('a', { href: '#followups' }, m.followups.missed + ' missed follow-ups'), ' to call'),
  m.followups.today > 0 && h('li', {}, h('a', { href: '#followups' }, m.followups.today + ' follow-ups'), ' due today'),
  m.discharges.map((x) => h('li', {}, h('a', { href: '#ip/' + x.admission_id }, 'Bed ' + x.bed + ' discharge'), ' ordered ' + since(x.ordered_at) + ' ago' + (x.waiting.length ? ', waiting for: ' + x.waiting.join(', ').toLowerCase() : ', ready to leave'))),
  h('li', {}, 'Pharmacy counter today: ' + rupees(m.pharm.counter) + ' from ' + m.pharm.count + ' sales', m.pharm.pending ? ' · ' + m.pharm.pending + ' not yet in Pharmasoft' : ''),
  h('li', {}, h('a', { href: '#accounts' }, 'Inpatient money received today: ' + rupees(m.ip_money.collected)), m.ip_money.refunds ? ' (refunds ' + rupees(m.ip_money.refunds) + ')' : ''),
  m.ip_money.due_after_discharge.length > 0 && h('li', {}, h('a', { href: '#ipbill' }, m.ip_money.due_after_discharge.length + ' discharged patients'), ' with bill not settled: ' + m.ip_money.due_after_discharge.map((x) => x.name + (x.final ? ' ' + rupees(x.balance) : ' (no final bill)')).join(', ')),
  m.labs_open > 0 && h('li', {}, h('a', { href: '#lab' }, m.labs_open + ' lab reports'), ' awaited'),
  m.claimflow && m.claimflow.due.length > 0 && h('li', {}, h('a', { href: '#claims' }, m.claimflow.due.length + ' insurance follow-ups due')),
  (m.claims.preparing + m.claims.queried) > 0 && h('li', {}, h('a', { href: '#claims' }, (m.claims.preparing + m.claims.queried) + ' claims'), ' need work (' + m.claims.submitted + ' submitted, ' + m.claims.approved + ' approved)'),
  (m.pharmacy.expired + m.pharmacy.expiring + m.pharmacy.low) > 0 && h('li', {}, h('a', { href: '#pharmacy' }, 'Pharmacy'), ': ' + m.pharmacy.expired + ' expired, ' + m.pharmacy.expiring + ' expiring in ' + m.pharmacy.window + ' days, ' + m.pharmacy.low + ' low stock'),
  h('li', {}, 'On duty now: ' + (m.on_duty.length ? m.on_duty.join(', ') : 'nobody has marked in')),
];

// ---------- extra sections in Settings ----------
window.settingsExtras = (d, reload, section, tbl, editBtn) => {
  const post = (path) => async (body) => { await api('POST', path, body); await reload(); };
  const m = d.more, off = (r) => (r.active ? '' : 'off');
  const schedF = [{ key: 'plan', label: 'Schedule', type: 'select', options: [['vaccine', 'Child vaccines (days after birth)'], ['antenatal', 'Antenatal (days after LMP)']] }, { key: 'title', label: 'What is due' }, { key: 'offset_days', label: 'Days after birth / LMP', type: 'number' }, { key: 'active', label: 'In use', type: 'check' }];
  const docF = [{ key: 'scheme', label: 'Scheme', type: 'select', options: PAYERS.filter((x) => x !== 'Cash').map((x) => [x, x]) }, { key: 'item', label: 'Document' }, { key: 'active', label: 'In use', type: 'check' }];
  const doseF = [{ key: 'drug', label: 'Drug and form', placeholder: 'as the doctors want it shown' }, { key: 'min_mg_kg', label: 'Lowest mg per kg' }, { key: 'max_mg_kg', label: 'Highest mg per kg' }, { key: 'per', label: 'Per', type: 'select', options: [['dose', 'dose'], ['day', 'day']] }, { key: 'max_mg', label: 'Maximum mg (optional)' }, { key: 'note', label: 'Note shown to the pharmacist' }, { key: 'active', label: 'In use', type: 'check' }];
  const dedF = [{ key: 'name', label: 'Name', placeholder: 'PF' }, { key: 'kind', label: 'Type', type: 'select', options: [['percent', '% of earned salary'], ['fixed', 'Fixed amount (₹)']] }, { key: 'value', label: 'Value' }, { key: 'active', label: 'In use', type: 'check' }];
  const confirmBtn = (plan, label) => m.confirmed[plan] ? h('span', { class: 'muted' }, label + ' confirmed by ' + m.confirmed[plan] + '. ') : h('button', { class: 'btn primary', onclick: guard(async () => { if (await ask('Confirm that a doctor has checked every line of the ' + label.toLowerCase() + ' schedule?', 'Confirm')) { await api('POST', '/api/admin/confirm-schedule', { plan }); await reload(); } }) }, 'Doctor: confirm ' + label.toLowerCase() + ' schedule');
  const priceF = [{ key: 'category', label: 'Type', type: 'select', options: [['room', 'Room / bed (per day)'], ['nursing', 'Nursing care'], ['visit', 'Doctor visits'], ['procedure', 'Procedures and OT'], ['service', 'Ward services'], ['investigation', 'Investigations done in the hospital'], ['other', 'Other']] },
    { key: 'name', label: 'Name (as staff will see it)' }, { key: 'unit', label: 'Charged', type: 'select', options: [['day', 'per day'], ['each', 'each time'], ['hour', 'per hour']] },
    { key: 'price', label: 'Price (₹)', type: 'number' }, { key: 'ward', label: 'Ward (only for room charges)', type: 'select', options: [['', '—']].concat([...new Set(d.beds.map((b) => b.ward))].map((w) => [w, w])) },
    { key: 'active', label: 'In use', type: 'check' }];
  const cats = { room: 'Room / bed', nursing: 'Nursing care', visit: 'Doctor visits', procedure: 'Procedures and OT', service: 'Ward services', investigation: 'Investigations', other: 'Other' };
  const units = { day: 'per day', each: 'each time', hour: 'per hour' };
  return [
    section('Price list', 'Only doctors with full access can set or change prices. Nurses and reception only choose what was given and how many days or times; the amount is worked out from here. A price change applies to new entries only. The prices below are placeholders until you set your own.', 'Add charge', () => formModal('Add charge', priceF, { active: 1, category: 'service', unit: 'each' }, post('/api/admin/price')),
      tbl(['Type', 'Charge', 'Price', ''], m.prices.map((r) => h('tr', { class: off(r) }, h('td', {}, cats[r.category]), h('td', {}, r.name, r.ward ? h('div', { class: 'muted' }, 'Ward: ' + r.ward) : null),
        h('td', { class: 'num' }, '₹' + r.price.toLocaleString('en-IN') + ' ' + units[r.unit]), h('td', {}, editBtn(() => formModal(r.name, priceF, r, (v) => post('/api/admin/price')(Object.assign(v, { id: r.id }))))))))),
    section('Tokens and waiting-hall TV', 'Choose what suits the hospital. Changes apply at once on every desk and on the TV.', null, null, h('div', { class: 'opts' },
      h('h3', {}, 'Token slip at OP Desk'),
      choice([['1', 'Print a token slip', 'Needs a printer at reception'], ['0', 'No printing', 'Say the number, write it on the OP sheet, or give a numbered card']], d.settings.token_print,
        guard(async (v) => { await api('POST', '/api/admin/settings', { token_print: v }); toast('Saved'); await reload(); })),
      h('h3', {}, 'Waiting-hall TV shows'),
      choice([['both', 'Token and name', 'PED-07 · Ravi Kumar'], ['name', 'Name only', 'Calls the patient by name'], ['token', 'Token only', 'For privacy: no names on screen']], d.settings.display_mode,
        guard(async (v) => { await api('POST', '/api/admin/settings', { display_mode: v }); toast('Saved'); await reload(); })))),
    section('Vaccine and antenatal schedules', 'These are DRAFTS taken from the national schedule. A doctor must check every line, correct it here, and confirm. Any change needs a fresh confirmation.', 'Add line', () => formModal('Add line', schedF, { active: 1, plan: 'vaccine' }, post('/api/admin/schedule-item')),
      [tbl(['Schedule', 'Due', 'Days', ''], m.schedule.map((r) => h('tr', { class: off(r) }, h('td', {}, r.plan === 'vaccine' ? 'Vaccine' : 'Antenatal'), h('td', {}, r.title), h('td', {}, r.offset_days), h('td', {}, editBtn(() => formModal(r.title, schedF, r, (v) => post('/api/admin/schedule-item')(Object.assign(v, { id: r.id }))))))),
      ), h('div', { class: 'actions' }, confirmBtn('vaccine', 'Vaccine'), confirmBtn('antenatal', 'Antenatal'))]),
    section('Claim document checklists', 'Draft lists. Correct them to match what each scheme really asks for.', 'Add document', () => formModal('Add document', docF, { active: 1, scheme: 'Dr NTR Vaidya Seva' }, post('/api/admin/scheme-doc')),
      tbl(['Scheme', 'Document', ''], m.scheme_docs.map((r) => h('tr', { class: off(r) }, h('td', {}, r.scheme), h('td', {}, r.item), h('td', {}, editBtn(() => formModal(r.item, docF, r, (v) => post('/api/admin/scheme-doc')(Object.assign(v, { id: r.id }))))))))),
    section('Child dose reference', 'Empty on purpose. Only the hospital\'s doctors add drugs and ranges here, from the reference they trust. The pharmacy screen then shows the range for a child\'s weight.', 'Add drug', () => formModal('Add drug', doseF, { active: 1, per: 'dose' }, post('/api/admin/dose-ref')),
      m.dose_refs.length ? tbl(['Drug', 'mg per kg', 'Max', 'Entered by', ''], m.dose_refs.map((r) => h('tr', { class: off(r) }, h('td', {}, r.drug), h('td', {}, r.min_mg_kg + ' – ' + r.max_mg_kg + ' per ' + r.per), h('td', {}, r.max_mg || '—'), h('td', {}, r.confirmed_by), h('td', {}, editBtn(() => formModal(r.drug, doseF, r, (v) => post('/api/admin/dose-ref')(Object.assign(v, { id: r.id })))))))) : h('p', { class: 'empty' }, 'No drugs entered.')),
    section('Pharmacy alerts', null, 'Change', () => formModal('Pharmacy alerts', [{ key: 'expiry_days', label: 'Warn when expiry is within (days)', type: 'number' }, { key: 'low_qty', label: 'Low stock when quantity is at or below', type: 'number' }], d.settings, post('/api/admin/settings')),
      h('p', {}, 'Expiry warning ' + d.settings.expiry_days + ' days ahead · low stock at ' + d.settings.low_qty + ' or fewer.')),
    section('Salary deductions', 'For example PF, ESI, professional tax. Ask the accountant for the correct values.', 'Add deduction', () => formModal('Add deduction', dedF, { active: 1, kind: 'percent' }, post('/api/admin/deduction')),
      m.deductions.length ? tbl(['Name', 'Value', ''], m.deductions.map((r) => h('tr', { class: off(r) }, h('td', {}, r.name), h('td', {}, r.kind === 'percent' ? r.value + '% of earned' : '₹' + r.value), h('td', {}, editBtn(() => formModal(r.name, dedF, r, (v) => post('/api/admin/deduction')(Object.assign(v, { id: r.id })))))))) : h('p', { class: 'empty' }, 'None set.')),
  ];
};

// ---------- My day (in-house and visiting doctors) ----------
VIEWS.myday = async (root) => {
  const box = h('div', {});
  root.append(box);
  const load = async () => {
    const d = await api('GET', '/api/myday');
    const me = d.doctor, waiting = d.visits.filter((v) => v.status === 'waiting' || v.status === 'called');
    const setStatus = (status) => guard(async () => { await api('POST', '/api/doctors/' + me.id + '/status', { status }); await load(); });
    box.replaceChildren(
      h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('div', {}, h('h2', {}, me.name), h('div', { class: 'muted' }, me.dept + (d.today && d.today.arrived_at ? ' · arrived ' + d.today.arrived_at + (d.today.left_at ? ', left ' + d.today.left_at : '') : ''))),
        h('div', { class: 'choice' }, Object.entries(DOC_STATUS).map(([k, l]) => h('button', { class: 'opt' + (me.status === k ? ' on' : ''), onclick: setStatus(k) }, t(l)))))),
      h('div', { class: 'stats' }, h('a', { class: 'stat', href: '#queue' }, h('strong', {}, waiting.length), h('span', {}, 'waiting for me')), h('div', { class: 'stat' }, h('strong', {}, d.visits.filter((v) => v.status === 'done').length), h('span', {}, 'seen today')),
        h('div', { class: 'stat' }, h('strong', {}, d.inpatients.length), h('span', {}, 'my inpatients')), h('div', { class: 'stat' }, h('strong', {}, d.month.seen), h('span', {}, 'seen this month' + (me.kind === 'consultant' ? ' · ' + d.month.days + ' days here' : '')))),
      h('div', { class: 'cols even' },
        h('section', { class: 'panel' }, h('h2', {}, 'My OP patients today'), d.visits.length ? h('div', { class: 'qlist' }, d.visits.map((v) => h('div', { class: 'qrow ' + v.status }, h('div', { class: 'tok small' }, v.token_code),
          h('div', { class: 'qinfo' }, has('records') ? h('a', { class: 'pname', href: '#patient/' + v.patient_id }, v.name) : h('span', { class: 'pname' }, v.name),
            v.last_visit && [' ', tag('Returning · last ' + dayText(v.last_visit).replace(/ \d{4}$/, ''), 'ok')], v.reports ? [' ', tag(v.reports + ' report' + (v.reports > 1 ? 's' : ''))] : null,
            h('div', { class: 'muted' }, [v.age, sexWord(v.sex), t(VISIT_STATUS[v.status]), v.rx ? 'prescription photo saved' : ''].filter(Boolean).join(' · '))),
          v.last_visit && has('records') && h('a', { class: 'btn', href: '#patient/' + v.patient_id }, 'Past records')))) : h('p', { class: 'empty' }, 'No OP patients for you today.'),
          has('queue') && h('div', { class: 'actions' }, h('a', { class: 'btn', href: '#queue' }, 'Open queue to call patients'))),
        h('section', { class: 'panel' }, h('h2', {}, 'My inpatients'), d.inpatients.length ? h('div', { class: 'qlist' }, d.inpatients.map((a) => h('div', { class: 'qrow' }, h('div', { class: 'tok small' }, a.bed),
          h('div', { class: 'qinfo' }, has('chart') ? h('a', { class: 'pname', href: '#ip/' + a.id }, a.name) : h('span', { class: 'pname' }, a.name), ' ', a.discharge_ordered_at ? tag('Discharge ordered', 'warn') : null,
            h('div', { class: 'muted' }, [a.age, a.diagnosis, 'Day ' + (Math.floor((Date.now() - new Date(a.admitted_at)) / 86400000) + 1), a.payer !== 'Cash' && a.payer].filter(Boolean).join(' · ')),
            h('div', { class: 'muted' }, a.last_round ? 'Last round ' + since(a.last_round) + ' ago' : 'No round note yet', a.last_vitals ? ' · vitals ' + since(a.last_vitals) + ' ago' : ''))))) : h('p', { class: 'empty' }, 'None.'),
          h('h2', {}, 'Reports for my patients'), d.labs.length ? h('div', { class: 'qlist' }, d.labs.map((l) => h('div', { class: 'qrow' }, h('div', { class: 'qinfo' }, h('span', { class: 'pname' }, l.name), ' ', tag(l.test), l.critical ? tag('CRITICAL', 'bad') : null,
            h('div', { class: 'muted' }, l.status === 'reported' ? 'Ready ' + dayText(l.reported_at) : l.status === 'collected' ? 'Sample taken, report awaited' : 'Sample not taken yet')),
            l.has_file ? h('a', { class: 'btn', href: '/files/lab/' + l.id, target: '_blank', rel: 'noopener' }, 'Open') : null))) : h('p', { class: 'empty' }, 'None in the last 3 days.'),
          h('h2', {}, 'My operations (next 7 days)'), d.ot.length ? h('ul', { class: 'todo' }, d.ot.map((o) => h('li', {}, dayText(o.ot_date).replace(/ \d{4}$/, '') + ' ' + o.start_time + ' — ' + o.patient_name + (o.procedure ? ', ' + o.procedure : '') + ' · checklist ' + o.checklist.length + '/' + OT_CHECKS.length + (o.anesthetist ? '' : ' · anesthetist not fixed')))) : h('p', { class: 'empty' }, 'None.'))));
  };
  S.poll = load;
  await load();
};

// ---------- Ward duty (nurses) ----------
VIEWS.ward = async (root) => {
  const box = h('div', {});
  root.append(box);
  const load = async () => {
    const d = await api('GET', '/api/ward');
    const old = (iso, hours) => !iso || (Date.now() - new Date(iso)) / 3600000 > hours;
    box.replaceChildren(
      h('section', { class: 'panel' }, h('h2', {}, 'Inpatients (' + d.inpatients.length + ')'),
        h('p', { class: 'muted' }, 'Vitals older than 6 hours are marked. Tap a name to open the chart and record vitals, medicines, services and handover notes.'),
        d.inpatients.length ? h('div', { class: 'qlist' }, d.inpatients.map((a) => h('div', { class: 'qrow' + (a.discharge_ordered_at ? ' late' : '') }, h('div', { class: 'tok small' }, a.bed),
          h('div', { class: 'qinfo' }, has('chart') ? h('a', { class: 'pname', href: '#ip/' + a.id }, a.name) : h('span', { class: 'pname' }, a.name), ' ', old(a.vitals && a.vitals.at, 6) ? tag(a.vitals ? 'Vitals due' : 'No vitals yet', 'warn') : null,
            h('div', { class: 'muted' }, [a.age, sexWord(a.sex), a.doctor, a.diagnosis, 'Day ' + (Math.floor((Date.now() - new Date(a.admitted_at)) / 86400000) + 1)].filter(Boolean).join(' · ')),
            a.vitals && h('div', { class: 'muted' }, 'Vitals ' + clock(a.vitals.at) + ': ' + Object.entries(a.vitals.data).map(([k, v]) => k + ' ' + v).join(', ')),
            a.round && h('div', { class: 'muted' }, 'Doctor\'s orders (' + clock(a.round.at) + '): ' + (a.round.data.Orders || a.round.data.Notes || '')),
            a.discharge_ordered_at && h('div', { class: 'missing' }, 'Discharge ordered ' + since(a.discharge_ordered_at) + ' ago' + (a.waiting.length ? ' — waiting for: ' + a.waiting.join(', ').toLowerCase() : ' — ready to leave'))),
          has('chart') && h('div', { class: 'qact' }, h('a', { class: 'btn', href: '#ip/' + a.id }, 'Open chart'))))) : h('p', { class: 'empty' }, 'No inpatients.')),
      h('div', { class: 'cols even' },
        h('section', { class: 'panel' }, h('h2', {}, 'Beds to clean or keep ready'), d.cleaning.length ? h('div', { class: 'qlist' }, d.cleaning.map((b) => h('div', { class: 'qrow' }, h('div', { class: 'tok small' }, b.label),
          h('div', { class: 'qinfo' }, t(BED_STATUS[b.status]) + (b.note ? ' — ' + b.note : '')),
          b.status === 'cleaning' && h('button', { class: 'btn primary', onclick: guard(async () => { await api('POST', '/api/beds/' + b.id + '/status', { status: 'vacant' }); await load(); }) }, 'Cleaned, ready')))) : h('p', { class: 'empty' }, 'Nothing.')),
        h('section', { class: 'panel' }, h('h2', {}, 'Operations today'), d.ot.length ? h('ul', { class: 'todo' }, d.ot.map((o) => h('li', {}, o.start_time + ' ' + o.patient_name + (o.procedure ? ', ' + o.procedure : '') + ' · ' + (o.surgeon || '') + ' · checklist ' + JSON.parse(o.checklist || '[]').length + '/' + OT_CHECKS.length))) : h('p', { class: 'empty' }, 'None.'))));
  };
  S.poll = load;
  await load();
};

// ---------- Doctors in / out (reception keeps this; most of it fills itself from the status buttons) ----------
VIEWS.doctors = async (root) => {
  let day = isoToday();
  const box = h('div', {});
  const dateInput = h('input', { type: 'date', value: day, max: isoToday(), onchange: (e) => { day = e.target.value || isoToday(); load(); } });
  root.append(h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('h2', {}, 'Doctors in / out'), dateInput),
    h('p', { class: 'muted' }, 'When reception or the doctor sets a doctor to "In", the arrival time is saved by itself; "Not in" saves the leaving time. Correct a time here if it was marked late. Visiting doctors\' payments use these days.'), box));
  const load = async () => {
    const d = await api('GET', '/api/doctor-days?date=' + day), isToday = day === isoToday();
    box.replaceChildren(h('div', { class: 'qlist' }, d.doctors.map((x) => h('div', { class: 'qrow' + (x.expected && !x.arrived_at && x.kind === 'consultant' ? ' late' : '') },
      h('div', { class: 'qinfo' }, h('span', { class: 'pname' }, x.name), ' ', x.kind === 'consultant' ? tag('Visiting') : null,
        x.expected && !x.arrived_at ? tag(x.kind === 'consultant' ? 'Expected' + (x.visit_time ? ' ' + x.visit_time : '') + ', not come' : 'Not marked', 'warn') : null,
        h('div', { class: 'muted' }, [x.dept, x.arrived_at ? 'Came ' + x.arrived_at : null, x.left_at ? 'left ' + x.left_at : x.arrived_at ? 'still here' : null, x.marked_by && 'marked by ' + x.marked_by, x.kind === 'consultant' && x.visit_days ? 'usually ' + x.visit_days : null].filter(Boolean).join(' · '))),
      h('div', { class: 'qact' },
        isToday && !x.arrived_at && h('button', { class: 'btn primary', onclick: guard(async () => { await api('POST', '/api/doctors/' + x.id + '/status', { status: 'in' }); await load(); }) }, 'Arrived now'),
        isToday && x.arrived_at && !x.left_at && h('button', { class: 'btn', onclick: guard(async () => { await api('POST', '/api/doctors/' + x.id + '/status', { status: 'out' }); await load(); }) }, 'Left now'),
        h('button', { class: 'btn quiet', onclick: () => formModal('Times for ' + x.name, [{ key: 'arrived_at', label: 'Came at', type: 'time' }, { key: 'left_at', label: 'Left at', type: 'time' }], x, async (v) => { await api('POST', '/api/doctor-days', Object.assign(v, { doctor_id: x.id, date: day })); await load(); }) }, 'Correct times'))))),
      d.month.length > 0 && [h('h3', {}, 'Visiting doctors this month'), h('div', { class: 'scroll' }, tbl2(['Doctor', 'Days came', 'Dates'], d.month.map((m) => h('tr', {}, h('td', {}, m.name), h('td', {}, m.days), h('td', { class: 'muted' }, m.dates ? m.dates.split(',').map(Number).sort((a, b) => a - b).join(', ') : '—')))))]);
  };
  S.poll = load;
  await load();
};

// ---------- Admission history ----------
VIEWS.iphistory = async (root) => {
  const f = { q: h('input', { type: 'search', placeholder: 'Name, UHID, phone or diagnosis' }), from: h('input', { type: 'date' }), to: h('input', { type: 'date' }),
    status: h('select', {}, [['', 'All'], ['admitted', 'Still admitted'], ['discharged', 'Discharged']].map(([v, l]) => h('option', { value: v }, l))) };
  const list = h('div', {});
  const load = async () => {
    const qs = Object.entries(f).filter(([, el]) => el.value).map(([k, el]) => k + '=' + encodeURIComponent(el.value)).join('&');
    const d = await api('GET', '/api/admissions?' + qs);
    list.replaceChildren(d.admissions.length ? h('div', { class: 'scroll' }, tbl2(['Patient', 'Admitted', 'Discharged', 'Doctor', 'Diagnosis / procedure', 'Scheme', 'Summary'], d.admissions.map((a) => h('tr', {},
      h('td', {}, has('chart', 'iphistory') ? h('a', { href: '#ip/' + a.id }, a.name) : a.name, h('div', { class: 'muted' }, a.uhid + ' · bed ' + a.bed)),
      h('td', {}, dayText(a.admitted_at)), h('td', {}, a.discharged_at ? dayText(a.discharged_at) : tag('In hospital', 'ok')), h('td', {}, a.doctor),
      h('td', {}, [a.diagnosis, a.procedure].filter(Boolean).join(' · ')), h('td', {}, a.payer, a.claim_status ? h('div', { class: 'muted' }, 'Claim: ' + CLAIM_NAMES[a.claim_status]) : null),
      h('td', {}, a.signed ? tag('Signed', 'ok') : a.discharged_at ? tag('Not signed', 'warn') : '—'))))) : h('p', { class: 'empty' }, 'No admissions match.'));
  };
  const form = h('form', { class: 'filters' }, f.q, f.from, f.to, f.status, h('button', { class: 'btn primary', type: 'submit' }, 'Search'));
  form.addEventListener('submit', guard(async (ev) => { ev.preventDefault(); await load(); }));
  root.append(h('section', { class: 'panel' }, h('h2', {}, 'Admission history'), h('p', { class: 'muted' }, 'Every admission, past and present. Open one to see the full chart, reports and discharge summary.'), form, list));
  await load();
};

// ---------- Accounts check (full-access doctors) ----------
VIEWS.accounts = async (root) => {
  let day = isoToday();
  const box = h('div', {});
  const money = (n) => '₹' + Math.round(n || 0).toLocaleString('en-IN');
  const dateInput = h('input', { type: 'date', value: day, max: isoToday(), onchange: (e) => { day = e.target.value || isoToday(); load(); } });
  root.append(h('div', { class: 'note' }, 'OP fees are collected in Essel: compare the OP figures with Essel\'s day report. Inpatient money is taken and recorded in this system (IP billing).'), box);
  const load = async () => {
    const d = await api('GET', '/api/accounts?date=' + day);
    const total = d.op.reduce((a, r) => a + r.expected, 0), pts = d.op.reduce((a, r) => a + r.patients, 0);
    box.replaceChildren(
      h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('h2', {}, 'Day check'), dateInput),
        h('div', { class: 'stats' }, h('div', { class: 'stat' }, h('strong', {}, money(total)), h('span', {}, 'consultation fees expected (' + pts + ' OP patients)')),
          h('a', { class: 'stat', href: '#ipbill' }, h('strong', {}, money(d.ip.collected)), h('span', {}, 'inpatient money received (after refunds)')),
          h('a', { class: 'stat', href: '#essel' }, h('strong', {}, d.essel_pending), h('span', {}, 'registrations not entered in Essel'))),
        d.op.length ? h('div', { class: 'scroll' }, tbl2(['Department', 'Patients', 'Walk-in', 'Phone booked', 'Did not come', 'Fees expected'], d.op.map((r) => h('tr', {}, h('td', {}, r.dept), h('td', {}, r.patients), h('td', {}, r.walkin), h('td', {}, r.phone), h('td', {}, r.skipped), h('td', {}, money(r.expected)))))) : h('p', { class: 'empty' }, 'No OP patients on this day.'),
        h('h3', {}, 'OP compared with Essel'),
        d.check ? h('p', {}, d.check.result === 'matched' ? tag('Matched', 'ok') : tag('Difference', 'bad'), ' by ' + d.check.checked_by + ', ' + clock(d.check.at) + (d.check.note ? ' — ' + d.check.note : '')) : h('p', { class: 'muted' }, 'Not checked yet.'),
        h('div', { class: 'actions' }, h('button', { class: 'btn primary', onclick: guard(async () => { await api('POST', '/api/accounts/check', { date: day, result: 'matched' }); await load(); }) }, 'Matches Essel'),
          h('button', { class: 'btn', onclick: () => formModal('Difference with Essel', [{ key: 'note', label: 'What is different?' }], {}, async (v) => { await api('POST', '/api/accounts/check', { date: day, result: 'difference', note: v.note }); await load(); }) }, 'There is a difference'))),
      h('section', { class: 'panel' }, h('h2', {}, 'Inpatient money on this day'),
        tbl2(['How paid', 'Amount'], Object.entries(d.ip.by_mode).map(([k, v]) => h('tr', {}, h('td', {}, k), h('td', { class: 'num' }, money(v))))
          .concat([h('tr', {}, h('th', {}, 'Total'), h('th', { class: 'num' }, money(d.ip.collected)))])),
        Object.keys(d.ip.cash_by_person).length > 0 && [h('h3', {}, 'Cash to hand over, by person'), tbl2(['Received by', 'Cash'], Object.entries(d.ip.cash_by_person).map(([k, v]) => h('tr', {}, h('td', {}, k), h('td', { class: 'num' }, money(v)))))],
        h('p', {}, 'Refunds ' + money(d.ip.refunds) + ' · discounts given ' + money(d.ip.discounts) + ' · final bills made ' + d.ip.bills),
        d.ip.cancelled.length > 0 && [h('h3', {}, 'Cancelled receipts'), h('ul', { class: 'todo' }, d.ip.cancelled.map((c) => h('li', {}, c.receipt_no + ' ' + money(c.amount) + ' — ' + c.cancelled_by + ': ' + c.cancel_reason)))],
        d.ip.due_after_discharge.length > 0 && [h('h3', {}, 'Discharged, bill not settled'), tbl2(['Bed', 'Patient', 'Left on', 'Balance'], d.ip.due_after_discharge.map((x) => h('tr', {}, h('td', {}, x.bed), h('td', {}, h('a', { href: '#bill/' + x.id }, x.name)), h('td', {}, dayText(x.discharged_at)), h('td', {}, x.final ? money(x.balance) : tag('No final bill', 'warn')))))]),
      h('section', { class: 'panel' }, h('h2', {}, 'Pharmacy counter on this day'),
        h('p', {}, 'Received at the counter: ', h('strong', {}, money(d.pharm.counter)), ' (' + (Object.entries(d.pharm.by_mode).map(([k, v]) => k + ' ' + money(v)).join(', ') || 'none') + ') · added to inpatient bills ' + money(d.pharm.to_ip_bills)),
        Object.keys(d.pharm.cash_by_person).length > 0 && h('p', {}, 'Cash to hand over: ' + Object.entries(d.pharm.cash_by_person).map(([k, v]) => k + ' ' + money(v)).join(', ')),
        h('p', { class: d.pharm.pending ? 'missing' : 'ok-line' }, d.pharm.pending ? d.pharm.pending + ' sales not yet entered in Pharmasoft' : 'All sales entered in Pharmasoft')),
      h('section', { class: 'panel' }, h('h2', {}, 'This month so far'),
        tbl2([], [['Inpatient charges recorded on this day', money(d.services.amount) + ' (' + d.services.n + ' lines)'], ['OP consultation fees expected', money(d.month.fees) + ' (' + d.month.visits + ' patients)'], ['Visiting doctors\' payments due', money(d.month.payouts)], ['Salaries (from attendance, after deductions)', money(d.month.salary_net) + ' for ' + d.month.salary_people + ' people']].map(([k, v]) => h('tr', {}, h('th', {}, k), h('td', {}, v)))),
        h('div', { class: 'actions' }, has('staff') && h('a', { class: 'btn', href: '#staff' }, 'Salary and payment details')),
        d.recent.length > 0 && [h('h3', {}, 'Recent day checks'), h('ul', { class: 'todo' }, d.recent.map((c) => h('li', {}, dayText(c.day) + ': ' + (c.result === 'matched' ? 'matched' : 'difference — ' + c.note) + ' (' + c.checked_by + ')')))]));
  };
  await load();
};

// ---------- Prescription photos (reception's phone; the doctor does nothing) ----------
VIEWS.rx = async (root) => {
  let day = isoToday(), docFilter = 'all', search = '';
  const takesPhotos = has('desk', 'records');
  const box = h('div', {});
  const dateInput = h('input', { type: 'date', value: day, max: isoToday(), onchange: (e) => { day = e.target.value || isoToday(); load(); } });
  const find = h('input', { type: 'search', placeholder: 'Token number or name', autocomplete: 'off' });
  find.addEventListener('input', () => { search = find.value.trim().toLowerCase(); draw(); });
  root.append(h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('h2', {}, 'Prescription photos'), dateInput),
    takesPhotos && h('p', { class: 'muted' }, 'After the doctor sees a patient, take a photo of the paper prescription here. It is saved under that patient and the doctor who saw them, and the doctor can see it next time. Use the phone: "Take photo" opens the camera.'),
    find), box);
  let visits = [];
  const needsPhoto = (v) => !v.rx.length && v.status !== 'skipped';
  const nextAfter = (v) => visits.filter(needsPhoto).filter((x) => x.id !== v.id && (docFilter === 'all' || x.doctor_id === docFilter)).sort((a, b) => (a.status === 'done' ? 0 : 1) - (b.status === 'done' ? 0 : 1) || a.token_no - b.token_no)[0];

  // Camera -> preview -> save (or retake, or add another page) -> next patient
  const capture = (v, pages) => {
    const inp = h('input', { type: 'file', accept: 'image/*', capture: 'environment' });
    inp.onchange = () => { if (inp.files[0]) preview(v, inp.files[0], pages || 0); };
    inp.click();
  };
  const preview = (v, file, pages) => {
    const url = URL.createObjectURL(file);
    const saving = h('span', { class: 'muted' });
    const doSave = async (more) => {
      saving.textContent = 'Saving...';
      await api('POST', '/api/visits/' + v.id + '/prescription', await shrink(file));
      m.close(); URL.revokeObjectURL(url);
      v.rx = v.rx.concat([0]);
      if (more) return capture(v, pages + 1);
      const nx = nextAfter(v);
      await load();
      if (nx) {
        const n = modal('Saved for ' + v.name, h('div', {}, h('p', {}, 'Next patient without a prescription photo:'),
          h('div', { class: 'picked' }, h('div', {}, h('strong', {}, nx.token_code + '  ' + nx.name), h('div', { class: 'muted' }, doctor(nx.doctor_id).name || ''))),
          h('div', { class: 'actions' }, h('button', { class: 'btn primary big', onclick: () => { n.close(); capture(nx); } }, 'Take photo'), h('button', { class: 'btn', onclick: () => n.close() }, 'Stop for now'))));
      } else toast('Saved. All prescriptions are photographed.');
    };
    const m = modal(v.token_code + ' · ' + v.name, h('div', {},
      h('p', { class: 'muted' }, (doctor(v.doctor_id).name || '') + (pages ? ' · page ' + (pages + 1) : '') + ' — check that the writing is clear.'),
      h('img', { src: url, class: 'rx-preview', alt: 'Prescription photo' }),
      h('div', { class: 'actions' }, h('button', { class: 'btn primary big', onclick: guard(() => doSave(false)) }, 'Save'),
        h('button', { class: 'btn', onclick: () => { m.close(); capture(v, pages); } }, 'Retake'),
        h('button', { class: 'btn', onclick: guard(() => doSave(true)) }, 'Save, add another page'), saving)));
  };

  const draw = () => {
    const docs = S.doctors.filter((d) => visits.some((v) => v.doctor_id === d.id));
    const shown = visits.filter((v) => (docFilter === 'all' || v.doctor_id === docFilter) && (!search || v.token_code.toLowerCase().includes(search) || v.name.toLowerCase().includes(search)));
    const todo = shown.filter((v) => needsPhoto(v) && v.status === 'done');
    const withDoctor = shown.filter((v) => needsPhoto(v) && v.status !== 'done');
    const doneList = shown.filter((v) => v.rx.length);
    const row = (v) => h('div', { class: 'qrow ' + (v.rx.length ? 'done' : '') }, h('div', { class: 'tok' }, v.token_code),
      h('div', { class: 'qinfo' }, h('span', { class: 'pname' }, v.name), h('div', {}, h('strong', {}, doctor(v.doctor_id).name || deptName(dept(v.dept_id)))),
        h('div', { class: 'muted' }, [v.age, sexWord(v.sex), v.rx.length ? v.rx.length + ' photo' + (v.rx.length > 1 ? 's' : '') + ' saved' : t(VISIT_STATUS[v.status])].filter(Boolean).join(' · '))),
      h('div', { class: 'qact' },
        takesPhotos && h('button', { class: 'btn ' + (v.rx.length ? '' : 'primary'), onclick: () => capture(v) }, v.rx.length ? 'Add page' : 'Take photo'),
        v.rx.length > 0 && h('button', { class: 'btn', onclick: () => showPhotos(v.rx) }, 'View'),
        has('pharmacy') && window.rxExtras && window.rxExtras(v, load)));
    if (!takesPhotos) {   // pharmacy: look at prescriptions and mark bought; reception takes the photos
      box.replaceChildren(h('p', { class: 'muted' }, 'Prescriptions photographed by reception today. Tap View to read one at the counter.'),
        docs.length > 1 && h('div', { class: 'pills' }, [['all', 'All doctors']].concat(docs.map((d) => [d.id, d.name])).map(([k, label]) => h('button', { class: 'pill' + (docFilter === k ? ' on' : ''), onclick: () => { docFilter = k; draw(); } }, label))),
        doneList.length ? h('div', { class: 'qlist' }, doneList.map(row)) : h('p', { class: 'empty' }, 'No prescription photos yet today.'));
      return;
    }
    box.replaceChildren(
      h('div', { class: 'stats' }, h('div', { class: 'stat' }, h('strong', {}, visits.filter((v) => needsPhoto(v) && v.status === 'done').length), h('span', {}, 'seen by the doctor, photo not taken')),
        h('div', { class: 'stat' }, h('strong', {}, visits.filter((v) => v.rx.length).length), h('span', {}, 'photos saved'))),
      docs.length > 1 && h('div', { class: 'pills' }, [['all', 'All doctors', visits]].concat(docs.map((d) => [d.id, d.name, visits.filter((v) => v.doctor_id === d.id)])).map(([k, label, vs]) =>
        h('button', { class: 'pill' + (docFilter === k ? ' on' : ''), onclick: () => { docFilter = k; draw(); } }, label, h('small', {}, vs.filter((v) => needsPhoto(v) && v.status === 'done').length)))),
      h('h3', {}, 'Photo needed (' + todo.length + ')'), todo.length ? h('div', { class: 'qlist' }, todo.map(row)) : h('p', { class: 'empty' }, 'Nothing pending.'),
      withDoctor.length > 0 && [h('h3', {}, 'Not marked seen yet (' + withDoctor.length + ')'), h('p', { class: 'muted' }, 'If the patient comes out with a prescription, take the photo here; they will be marked seen.'), h('div', { class: 'qlist' }, withDoctor.map(row))],
      doneList.length > 0 && [h('h3', {}, 'Photo saved (' + doneList.length + ')'), h('div', { class: 'qlist' }, doneList.map(row))]);
  };
  const load = async () => {
    const [q, b] = await Promise.all([api('GET', '/api/queue?date=' + day), api('GET', '/api/bootstrap')]);
    S.doctors = b.doctors; visits = q.visits; draw();
  };
  S.poll = load;
  await load();
};


// ---------- Inpatient billing (Essel is not used for inpatients) ----------
const KIND_NAMES = { advance: 'Advance', payment: 'Payment', refund: 'Refund' };
window.printReceipt = async (aid, receiptNo) => {
  const d = await api('GET', '/api/admissions/' + aid + '/bill');
  const p = d.payments.find((x) => x.receipt_no === receiptNo);
  if (!p) return;
  printDoc(h('div', { class: 'doc' }, docHead(KIND_NAMES[p.kind] + ' Receipt'),
    tbl2([], [['Receipt no.', p.receipt_no], ['Date', dayText(p.at) + ', ' + clock(p.at)], ['Patient', d.admission.patient + ' · ' + d.admission.uhid], ['Bed', d.admission.bed],
      [p.kind === 'refund' ? 'Amount returned' : 'Amount received', rupees(p.amount)], ['Paid by', p.mode + (p.ref ? ' · ' + p.ref : '')], ['Received by', p.received_by]].map(([k, v]) => h('tr', {}, h('th', {}, k), h('td', {}, v)))),
    p.cancelled ? h('p', {}, h('strong', {}, 'CANCELLED: ' + p.cancel_reason)) : null, h('p', { class: 'sign' }, 'Signature')));
};

VIEWS.ipbill = async (root) => {
  const box = h('div', {});
  root.append(h('section', { class: 'panel' }, h('h2', {}, 'Inpatient billing'),
    h('p', { class: 'muted' }, 'Everyone in hospital, and discharged patients whose bill is not settled. Charges come from what nurses record and the price list. Take advances and payments here; each gets a numbered receipt. Make the final bill before the patient leaves.'), box));
  const load = async () => {
    const d = await api('GET', '/api/ipbilling');
    box.replaceChildren(d.patients.length ? h('div', { class: 'qlist' }, d.patients.map((x) => h('div', { class: 'qrow' + (x.status !== 'admitted' ? ' late' : '') },
      h('div', { class: 'tok small' }, x.bed),
      h('div', { class: 'qinfo' }, h('a', { class: 'pname', href: '#bill/' + x.id }, x.name), ' ', x.payer !== 'Cash' ? tag(x.payer) : null,
        x.status !== 'admitted' ? tag('Discharged ' + dayText(x.discharged_at), 'bad') : x.discharge_ordered_at ? tag('Discharge ordered', 'warn') : null, x.final ? tag('Final bill ' + x.bill_no, 'ok') : null,
        h('div', { class: 'muted' }, 'Charges ' + rupees(x.total) + (x.discount ? ' · discount ' + rupees(x.discount) : '') + (x.scheme_amount ? ' · scheme ' + rupees(x.scheme_amount) : '') + ' · paid ' + rupees(x.paid)),
        x.slip && h('div', {}, tag('Slip from ward ' + clock(x.slip.sent_at) + ' — to check', 'warn')),
        h('div', { class: x.balance > 0 ? 'missing' : 'ok-line' }, x.balance > 0 ? 'To pay: ' + rupees(x.balance) : x.balance < 0 ? (x.final ? 'To return: ' : 'Advance left: ') + rupees(-x.balance) : 'Settled')),
      h('div', { class: 'qact' }, h('a', { class: 'btn primary', href: '#bill/' + x.id }, 'Open bill'))))) : h('p', { class: 'empty' }, 'No inpatients.'));
  };
  S.poll = load;
  await load();
};

VIEWS.bill = async (root, id) => {
  const box = h('div', {});
  root.append(box);
  const load = async () => {
    const d = await api('GET', '/api/admissions/' + id + '/bill');
    const a = d.admission, st = d.state, final = st.final;
    const ch = Object.assign({}, d.charges, { slips: (await api('GET', '/api/admissions/' + id + '/charges')).slips });
    const live = ch.lines.filter((x) => !x.cancelled);
    const take = (kind) => formModal(KIND_NAMES[kind] + ' — ' + a.patient, [{ key: 'amount', label: 'Amount (₹)', type: 'number' },
      { key: 'mode', label: kind === 'refund' ? 'Returned as' : 'Paid by', type: 'select', options: d.modes.map((m) => [m, m]) }, { key: 'ref', label: 'UPI / card / cheque reference (not needed for cash)', optional: true }],
      { mode: 'Cash', amount: kind !== 'advance' && st.balance ? Math.abs(st.balance) : '' }, async (v) => {
        const r = await api('POST', '/api/admissions/' + id + '/payments', Object.assign(v, { kind }));
        await load(); if (await ask('Receipt ' + r.receipt_no + ' saved. Print it now?', 'Print receipt')) window.printReceipt(id, r.receipt_no);
      });
    const finalBill = () => h('div', { class: 'doc' }, docHead('Inpatient Final Bill'),
      tbl2([], [['Bill no.', st.bill ? st.bill.bill_no : 'DRAFT'], ['Patient', a.patient + ' · ' + [a.age, sexWord(a.sex)].filter(Boolean).join(' · ')], ['UHID', a.uhid], ['Address', a.area], ['Doctor', a.doctor],
        ['Admitted', dayText(a.admitted_at) + ', ' + clock(a.admitted_at)], ['Discharged', a.discharged_at ? dayText(a.discharged_at) + ', ' + clock(a.discharged_at) : '—'], ['Bed', a.bed + ' (' + a.ward + ')'], ['Scheme / cash', a.payer]].map(([k, v]) => h('tr', {}, h('th', {}, k), h('td', {}, v || '')))),
      h('h2', {}, 'Charges'),
      Object.entries(d.categories).filter(([c]) => live.some((x) => x.category === c)).map(([c, label]) => [h('h3', {}, label), tbl2(['Date', 'Item', 'Qty', 'Rate', 'Amount'],
        live.filter((x) => x.category === c).map((x) => h('tr', {}, h('td', {}, dayText(x.for_date || x.entered_at)), h('td', {}, x.name), h('td', {}, x.qty + ' ' + unitWord(x.unit, x.qty)), h('td', {}, rupees(x.rate)), h('td', {}, rupees(x.amount)))))]),
      h('h2', {}, 'Summary'), tbl2([], [['Total charges', rupees(st.total)], ['Less discount', rupees(st.discount)], ['Payable by scheme / insurer', rupees(st.scheme_amount)], ['Payable by patient', rupees(st.payable)],
        ['Paid (advances and payments, less refunds)', rupees(st.paid)], [st.balance >= 0 ? 'Balance to pay' : 'To be returned', rupees(Math.abs(st.balance))]].map(([k, v]) => h('tr', {}, h('th', {}, k), h('td', {}, v)))),
      h('h3', {}, 'Receipts'), tbl2(['Receipt', 'Date', 'Type', 'How', 'Amount'], d.payments.filter((p) => !p.cancelled).map((p) => h('tr', {}, h('td', {}, p.receipt_no), h('td', {}, dayText(p.at)), h('td', {}, KIND_NAMES[p.kind]), h('td', {}, p.mode), h('td', {}, rupees(p.amount))))),
      h('p', { class: 'sign' }, 'Authorised signature'));
    box.replaceChildren(
      h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('div', {}, h('h2', {}, a.patient + ' — bed ' + a.bed), h('div', { class: 'muted' }, [a.uhid, a.doctor, a.payer, 'admitted ' + dayText(a.admitted_at), a.discharged_at && 'left ' + dayText(a.discharged_at)].filter(Boolean).join(' · ')),
          final ? h('div', { class: 'ok-line' }, 'Final bill ' + st.bill.bill_no + ' made by ' + st.bill.finalised_by + ', ' + dayText(st.bill.finalised_at) + '. Charges are locked.') : st.bill && st.bill.reopened ? h('div', { class: 'missing' }, 'Final bill ' + st.bill.bill_no + ' reopened by ' + st.bill.reopened_by + ': ' + st.bill.reopen_reason) : null),
          h('div', { class: 'qact' }, has('chart') && h('a', { class: 'btn', href: '#ip/' + id }, 'Chart'), h('a', { class: 'btn', href: '#ipbill' }, 'All bills'))),
        h('div', { class: 'stats' }, h('div', { class: 'stat' }, h('strong', {}, rupees(st.total)), h('span', {}, 'charges')), h('div', { class: 'stat' }, h('strong', {}, rupees(st.discount + st.scheme_amount)), h('span', {}, 'discount + scheme')),
          h('div', { class: 'stat' }, h('strong', {}, rupees(st.paid)), h('span', {}, 'paid')), h('div', { class: 'stat' + (st.balance > 0 ? ' due' : '') }, h('strong', {}, rupees(Math.abs(st.balance))), h('span', {}, st.balance > 0 ? 'to pay' : st.balance < 0 ? (final ? 'to return' : 'advance left') : 'settled'))),
        has('ipbill') && h('div', { class: 'actions' },
          h('button', { class: 'btn primary', onclick: () => take(final ? 'payment' : 'advance') }, final ? 'Take payment' : 'Take advance'),
          !final && h('button', { class: 'btn', onclick: () => take('payment') }, 'Take payment'),
          final && st.balance < 0 && h('button', { class: 'btn', onclick: () => take('refund') }, 'Return extra'),
          !final && h('button', { class: 'btn', onclick: () => formModal('Outside lab / scan bill', [{ key: 'amount', label: 'Bill amount (₹)', type: 'number' }, { key: 'ref', label: 'Their bill number' }, { key: 'note', label: 'Note' }], {}, async (v) => { await api('POST', '/api/admissions/' + id + '/external-bill', Object.assign(v, { kind: 'outside' })); await load(); }) }, 'Add outside lab / scan bill'),
          !final && d.can_discount && h('button', { class: 'btn', onclick: () => formModal('Discount', [{ key: 'amount', label: 'Discount (₹)', type: 'number' }, { key: 'reason', label: 'Reason' }], {}, async (v) => { await api('POST', '/api/admissions/' + id + '/discount', v); await load(); }) }, 'Give discount'),
          !final && h('button', { class: 'btn primary', onclick: () => {
            const fields = a.payer !== 'Cash' ? [{ key: 'scheme_amount', label: 'Amount payable by ' + a.payer + ' (₹)', type: 'number', hint: 'The rest is payable by the patient.' }] : [];
            formModal('Make final bill', fields.concat([{ key: 'ok', label: 'All charges are entered (room days, services, pharmacy and outside bills). Charges will be locked.', type: 'check' }]), { ok: 0 }, async (v) => {
              if (!v.ok) throw new Error('Tick the box to confirm all charges are entered');
              const r = await api('POST', '/api/admissions/' + id + '/finalise', v); await load(); toast('Final bill ' + r.bill_no + ' made');
            });
          } }, 'Make final bill'),
          final && d.can_discount && h('button', { class: 'btn quiet', onclick: () => formModal('Reopen final bill', [{ key: 'reason', label: 'Why?' }], {}, async (v) => { await api('POST', '/api/admissions/' + id + '/reopen-bill', v); await load(); }) }, 'Reopen bill'),
          h('button', { class: 'btn', onclick: () => printDoc(finalBill()) }, final ? 'Print final bill' : 'Print draft bill'),
          a.payer !== 'Cash' && !d.claim_sent && h('button', { class: 'btn primary', onclick: () => formModal('Send to insurance desk', [{ key: 'note', label: 'Note for the insurance desk (optional)' }], {}, async (v) => { await api('POST', '/api/admissions/' + id + '/send-to-insurance', v); toast('Sent to the insurance desk'); await load(); }) }, 'Send to insurance desk'))),
      d.claim_sent && h('div', { class: 'note ok-note' }, 'Sent to the insurance desk ' + dayText(d.claim_sent.sent_at) + ' by ' + d.claim_sent.sent_by + ' · claim status: ' + CLAIM_NAMES[d.claim_sent.status] + (d.claim_sent.next_followup ? ' · next follow-up ' + dayText(d.claim_sent.next_followup) : ''),
        h('button', { class: 'btn quiet', onclick: guard(async () => { const e = await api('GET', '/api/claims/' + d.claim_sent.id + '/events'); modal('Claim timeline', h('div', { class: 'tl' }, e.events.map((x) => h('div', { class: 'tl-row' }, h('div', { class: 'tl-dot' }), h('div', {}, h('strong', {}, x.label), x.detail ? h('div', {}, x.detail) : null, h('div', { class: 'muted' }, dayText(x.at) + ' · ' + (x.staff_name || ''))))))); }) }, 'Timeline')),
      ch.slips.filter((x) => !x.checked_at).map((x) => h('div', { class: 'note' }, 'Charge slip from the ward: sent ' + dayText(x.sent_at) + ', ' + clock(x.sent_at) + ' by ' + x.sent_by + ', total ' + rupees(x.total) + ' (' + x.lines + ' lines). Check it against the charges below. ',
        has('ipbill') && h('button', { class: 'btn primary', onclick: guard(async () => { await api('POST', '/api/charge-slips/' + x.id + '/checked', {}); await load(); }) }, 'Checked'))),
      h('div', { class: 'cols even' },
        h('section', { class: 'panel' }, h('h2', {}, 'Receipts'), d.payments.length ? h('div', { class: 'qlist' }, d.payments.map((p) => h('div', { class: 'qrow' + (p.cancelled ? ' done' : '') },
          h('div', { class: 'qinfo' }, h('span', { class: 'pname' }, p.receipt_no), ' ', tag(KIND_NAMES[p.kind]), p.cancelled ? tag('Cancelled', 'bad') : null,
            h('div', { class: 'muted' }, [dayText(p.at) + ' ' + clock(p.at), p.mode + (p.ref ? ' ' + p.ref : ''), p.received_by].join(' · ')), p.cancelled ? h('div', { class: 'muted' }, p.cancelled_by + ': ' + p.cancel_reason) : null),
          h('strong', {}, rupees(p.amount)),
          h('div', { class: 'qact' }, h('button', { class: 'btn quiet', onclick: guard(() => window.printReceipt(id, p.receipt_no)) }, 'Print'),
            !p.cancelled && has('ipbill') && h('button', { class: 'btn quiet', onclick: () => formModal('Cancel receipt ' + p.receipt_no, [{ key: 'reason', label: 'Why is this receipt wrong?' }], {}, async (v) => { await api('POST', '/api/ip-payments/' + p.id + '/cancel', v); await load(); }) }, 'Cancel'))))) : h('p', { class: 'empty' }, 'No money taken yet.'),
          d.discounts.length > 0 && [h('h3', {}, 'Discounts'), h('ul', { class: 'todo' }, d.discounts.map((x) => h('li', { class: x.cancelled ? 'muted' : '' }, rupees(x.amount) + ' — ' + x.reason + ' (' + x.given_by + ')' + (x.cancelled ? ' — removed by ' + x.cancelled_by : ''),
            !x.cancelled && !final && d.can_discount && h('button', { class: 'btn quiet', onclick: guard(async () => { await api('POST', '/api/ip-discounts/' + x.id + '/cancel', { reason: 'removed' }); await load(); }) }, 'Remove'))))]),
        h('section', { class: 'panel' }, h('h2', {}, 'Charges (' + live.length + ')'),
          live.length ? h('div', { class: 'scroll' }, tbl2(['Item', 'Qty', 'Amount'], Object.entries(d.categories).filter(([c]) => live.some((x) => x.category === c)).map(([c, label]) => [
            h('tr', { class: 'cat' }, h('td', { colspan: 2 }, label), h('td', { class: 'num' }, rupees(ch.by_category[c]))),
            live.filter((x) => x.category === c).map((x) => h('tr', {}, h('td', {}, x.name, h('div', { class: 'muted' }, dayText(x.for_date || x.entered_at) + ' · ' + x.entered_by)), h('td', {}, x.qty + ' ' + unitWord(x.unit, x.qty)), h('td', { class: 'num' }, rupees(x.amount))))]))) : h('p', { class: 'empty' }, 'No charges yet.'),
          h('p', { class: 'muted' }, 'Nurses add room days and services from the chart. Pharmacy adds medicine bills from the Pharmacy screen.'))));
  };
  await load();
};

// Pharmacy: medicines issued to inpatients go onto their bill with the pharmacy bill number.
window.pharmacyIP = async () => {
  const d = await api('GET', '/api/ipbilling');
  return h('section', { class: 'panel' }, h('h2', {}, 'Medicines issued to inpatients'),
    h('p', { class: 'muted' }, 'When medicines go to the ward, add the pharmacy bill to the patient\'s hospital bill here, with its bill number.'),
    d.patients.length ? h('div', { class: 'qlist' }, d.patients.map((x) => h('div', { class: 'qrow' }, h('div', { class: 'tok small' }, x.bed), h('div', { class: 'qinfo' }, h('span', { class: 'pname' }, x.name), h('div', { class: 'muted' }, x.uhid)),
      h('button', { class: 'btn', onclick: () => formModal('Pharmacy bill for ' + x.name, [{ key: 'amount', label: 'Bill amount (₹)', type: 'number' }, { key: 'ref', label: 'Pharmacy bill number' }, { key: 'note', label: 'Note' }], {}, async (v) => {
        await api('POST', '/api/admissions/' + x.id + '/external-bill', Object.assign(v, { kind: 'pharmacy' })); toast('Added to ' + x.name + '\'s bill');
      }) }, 'Add pharmacy bill')))) : h('p', { class: 'empty' }, 'No inpatients.'));
};

// ---------- Pharmacy counter: quick sale now, Pharmasoft later ----------
VIEWS.pharmsale = async (root) => {
  let tab = 'sale', who = null, pickTab = 'op', lines = [], mode = 'Cash';
  const tabs = h('div', { class: 'pills' }), box = h('div', {});
  root.append(tabs, box);
  const money = (n) => '₹' + (Math.round(n * 100) / 100).toLocaleString('en-IN');
  const copy = (text) => (navigator.clipboard ? navigator.clipboard.writeText(String(text)) : Promise.reject()).then(() => toast('Copied'), () => toast('Select and copy by hand', true));
  const drawTabs = (pending) => tabs.replaceChildren([['sale', 'New sale'], ['pending', 'To enter in Pharmasoft' + (pending ? ' (' + pending + ')' : '')], ['today', 'Today\'s sales']].map(([k, l]) =>
    h('button', { class: 'pill' + (tab === k ? ' on' : ''), onclick: () => { tab = k; show(); } }, l)));

  const slipFor = (sale) => h('div', { class: 'slip' }, h('div', { class: 'slip-h' }, S.hospital + ' — Pharmacy'), h('div', { class: 'slip-s' }, S.address),
    h('div', {}, sale.sale_no + ' · ' + dayText(sale.at) + ' ' + clock(sale.at)), h('div', { class: 'slip-p' }, sale.name || 'Customer', sale.doctor ? ' · ' + sale.doctor : ''),
    h('table', { class: 'slip-t2' }, sale.items.map((x) => h('tr', {}, h('td', {}, x.item, h('div', {}, 'B: ' + (x.batch || '-') + (x.expiry ? ' Exp ' + x.expiry.slice(5, 7) + '/' + x.expiry.slice(2, 4) : ''))), h('td', {}, x.qty + ' × ' + x.rate), h('td', {}, money(x.amount))))),
    h('div', { class: 'slip-d' }, 'Total ' + money(sale.total) + (sale.mode ? ' · ' + sale.mode : ' · added to hospital bill')),
    h('div', { class: 'slip-w' }, 'Medicine slip. The GST bill is made in Pharmasoft.'));
  const printSlip = (sale) => { document.getElementById('print-slip').replaceChildren(slipFor(sale)); window.print(); };

  const saleScreen = async () => {
    const c = await api('GET', '/api/pharmacy/customers');
    const total = lines.reduce((a, x) => a + x.qty * x.rate, 0);
    const pickBox = h('div', {});
    if (!who) {
      const walkName = h('input', { autocomplete: 'off', placeholder: 'Name (optional)' }), walkPhone = h('input', { inputmode: 'numeric', maxlength: 10, placeholder: 'Phone (optional)' });
      pickBox.append(h('div', { class: 'pills' }, [['op', 'Today\'s OP patients'], ['ip', 'Inpatients'], ['walkin', 'Walk-in']].map(([k, l]) => h('button', { class: 'pill' + (pickTab === k ? ' on' : ''), onclick: () => { pickTab = k; show(); } }, l))),
        pickTab === 'op' && (c.op.length ? h('div', { class: 'qlist' }, c.op.map((x) => h('button', { class: 'qrow pick' + (x.sales ? ' done' : ''), onclick: () => { who = Object.assign({ kind: 'op' }, x); show(); } },
          h('div', { class: 'tok small' }, x.token_code), h('div', { class: 'qinfo' }, h('span', { class: 'pname' }, x.name), ' ', x.rx.length ? tag('Prescription photo', 'ok') : null, x.sales ? tag('Already sold') : null,
            h('div', { class: 'muted' }, [x.doctor, t(VISIT_STATUS[x.status])].filter(Boolean).join(' · ')))))) : h('p', { class: 'empty' }, 'No OP patients today.')),
        pickTab === 'ip' && (c.ip.length ? h('div', { class: 'qlist' }, c.ip.map((x) => h('button', { class: 'qrow pick', onclick: () => { who = Object.assign({ kind: 'ip' }, x); show(); } },
          h('div', { class: 'tok small' }, x.bed), h('div', { class: 'qinfo' }, h('span', { class: 'pname' }, x.name), h('div', { class: 'muted' }, (x.doctor || '') + ' · goes on the hospital bill, no money taken now'))))) : h('p', { class: 'empty' }, 'No inpatients.')),
        pickTab === 'walkin' && h('div', { class: 'form' }, walkName, walkPhone, h('div', { class: 'actions' }, h('button', { class: 'btn primary', onclick: () => { who = { kind: 'walkin', name: walkName.value.trim(), phone: walkPhone.value.trim() }; show(); } }, 'Continue'))));
      return box.replaceChildren(h('section', { class: 'panel' }, h('h2', {}, 'Who is buying?'), pickBox));
    }
    const search = h('input', { type: 'search', class: 'search', placeholder: 'Type medicine name', autocomplete: 'off' });
    const results = h('div', { class: 'results' });
    let timer, seq = 0;
    const addLine = (x) => {
      const same = lines.find((l) => l.item === x.item && l.batch === x.batch);
      if (same) same.qty += 1; else lines.push({ item: x.item, batch: x.batch || '', expiry: x.expiry || '', qty: 1, rate: x.mrp || 0, stock: x.qty });
      show();
    };
    search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(guard(async () => {
      const q = search.value.trim(), my = ++seq;
      if (q.length < 2) { results.replaceChildren(); return; }
      const d = await api('GET', '/api/pharmacy/items?q=' + encodeURIComponent(q));
      if (my !== seq) return;
      results.replaceChildren(d.items.length ? d.items.map((x) => h('button', { class: 'result', type: 'button', disabled: x.expired, onclick: () => addLine(x) },
        h('strong', {}, x.item), h('span', {}, ['Batch ' + (x.batch || '-'), x.expiry ? (x.expired ? 'EXPIRED ' : 'Exp ') + dayText(x.expiry) : '', x.mrp != null ? 'MRP ₹' + x.mrp : 'MRP not in stock file', x.qty != null ? x.qty + ' in stock' : ''].filter(Boolean).join(' · ')))) : h('p', { class: 'empty' }, 'Not in the stock list. Use "Add by hand".'));
    }), 200); });
    const lineRow = (l, i) => h('tr', {}, h('td', {}, l.item, h('div', { class: 'muted' }, 'Batch ' + (l.batch || '-') + (l.expiry ? ' · Exp ' + dayText(l.expiry) : ''))),
      h('td', { class: 'qtycell' }, h('button', { class: 'btn quiet', onclick: () => { l.qty = Math.max(1, l.qty - 1); show(); } }, '−'), h('strong', {}, l.qty), h('button', { class: 'btn quiet', onclick: () => { l.qty += 1; show(); } }, '+')),
      h('td', {}, h('input', { class: 'narrow', inputmode: 'decimal', value: l.rate, onchange: (e) => { l.rate = parseFloat(e.target.value) || 0; show(); } })),
      h('td', { class: 'num' }, money(l.qty * l.rate)), h('td', {}, h('button', { class: 'btn quiet', 'aria-label': 'Remove', onclick: () => { lines.splice(i, 1); show(); } }, '✕')));
    const ref = h('input', { autocomplete: 'off', placeholder: 'UPI / card reference' });
    const save = h('button', { class: 'btn primary big', disabled: !lines.length }, who.kind === 'ip' ? 'Add to hospital bill ' + money(total) : 'Save sale ' + money(total));
    save.onclick = guard(async () => {
      save.disabled = true;
      try {
        const r = await api('POST', '/api/pharmacy/sales', { kind: who.kind, visit_id: who.visit_id, admission_id: who.admission_id, name: who.name, phone: who.phone, items: lines, mode, ref: ref.value });
        const sale = { sale_no: r.sale_no, at: new Date().toISOString(), name: who.name, doctor: who.doctor, items: lines.map((l) => Object.assign({ amount: l.qty * l.rate }, l)), total: r.total, mode: who.kind === 'ip' ? null : mode };
        who = null; lines = []; mode = 'Cash';
        const m = modal('Saved ' + r.sale_no, h('div', {}, h('p', { class: 'fee' }, h('strong', {}, money(r.total)), sale.mode ? ' received by ' + sale.mode : ' added to the hospital bill'),
          h('div', { class: 'actions' }, h('button', { class: 'btn primary big', onclick: () => m.close() }, 'Next customer'), h('button', { class: 'btn', onclick: () => printSlip(sale) }, 'Print slip'))), show);
      } finally { save.disabled = false; }
    });
    box.replaceChildren(h('div', { class: 'cols' },
      h('section', { class: 'panel' },
        h('div', { class: 'picked' }, h('div', {}, h('strong', {}, who.name || 'Walk-in customer'), h('div', { class: 'muted' }, [who.token_code, who.bed && 'Bed ' + who.bed, who.doctor, who.phone].filter(Boolean).join(' · '))),
          h('div', { class: 'qact' }, who.rx && who.rx.length > 0 && h('button', { class: 'btn', onclick: () => showPhotos(who.rx) }, 'Prescription'), h('button', { class: 'btn quiet', onclick: () => { who = null; lines = []; show(); } }, t('Change')))),
        h('h3', {}, 'Medicines'), h('div', { class: 'searchrow' }, search, h('button', { class: 'btn', onclick: () => formModal('Add by hand', [{ key: 'item', label: 'Medicine' }, { key: 'batch', label: 'Batch' }, { key: 'expiry', label: 'Expiry', type: 'date' }, { key: 'qty', label: 'Quantity', type: 'number' }, { key: 'rate', label: 'Rate / MRP (₹)', type: 'number' }], { qty: 1 },
          async (v) => { if (!v.item) throw new Error('Enter the medicine'); lines.push({ item: v.item, batch: v.batch, expiry: v.expiry, qty: parseFloat(v.qty) || 1, rate: parseFloat(v.rate) || 0 }); show(); }) }, 'Add by hand')), results),
      h('aside', { class: 'panel' }, h('h2', {}, 'Bill'),
        lines.length ? h('div', { class: 'scroll' }, tbl2(['Medicine', 'Qty', 'Rate', 'Amount', ''], lines.map(lineRow))) : h('p', { class: 'empty' }, 'Search and tap medicines to add them.'),
        h('p', { class: 'fee' }, 'Total ', h('strong', {}, money(total))),
        who.kind !== 'ip' ? [choice(c.modes.map((x) => [x, x]), mode, (v) => { mode = v; ref.style.display = v === 'Cash' ? 'none' : ''; }), ref] : h('p', { class: 'muted' }, 'Inpatient: no money now. This goes on their hospital bill.'),
        h('div', { class: 'actions' }, save))));
    if (mode === 'Cash') ref.style.display = 'none';
    setTimeout(() => search.focus(), 0);
  };

  const pendingScreen = async () => {
    const d = await api('GET', '/api/pharmacy/sales?pending=1');
    drawTabs(d.pending);
    box.replaceChildren(h('p', { class: 'muted' }, 'When the counter is quiet, enter each sale in Pharmasoft\'s Counter Sales screen. Tap a value to copy it. Then type the bill number Pharmasoft gives and press Entered.'),
      d.sales.length ? d.sales.map((s) => {
        const no = h('input', { class: 'narrow wide2', placeholder: 'Pharmasoft bill no.', autocomplete: 'off' });
        return h('div', { class: 'essel col' }, h('div', { class: 'headrow' }, h('div', {}, h('strong', {}, s.sale_no), ' ', s.kind === 'ip' ? tag('Inpatient — on hospital bill') : tag(s.mode), h('div', { class: 'muted' }, dayText(s.at) + ' ' + clock(s.at) + ' · ' + s.sold_by)), h('strong', {}, money(s.total))),
          h('div', { class: 'efields' }, [['Customer', s.name], ['Cell no.', s.phone], ['Doctor', s.doctor], ['Payment', s.mode || 'Credit (hospital bill)']].map(([k, v]) => h('button', { class: 'ef', disabled: !v, onclick: () => copy(v) }, h('small', {}, k), v || '—'))),
          h('div', { class: 'scroll' }, tbl2(['Medicine', 'Batch', 'Qty', 'Rate'], s.items.map((x) => h('tr', {}, h('td', {}, h('button', { class: 'ef', onclick: () => copy(x.item) }, x.item)), h('td', {}, h('button', { class: 'ef', onclick: () => copy(x.batch) }, x.batch || '—')),
            h('td', {}, h('button', { class: 'ef', onclick: () => copy(x.qty) }, x.qty)), h('td', {}, h('button', { class: 'ef', onclick: () => copy(x.rate) }, x.rate)))))),
          h('div', { class: 'actions' }, no, h('button', { class: 'btn primary', onclick: guard(async () => { await api('POST', '/api/pharmacy/sales/' + s.id + '/entered', { pharmasoft_no: no.value }); await show(); }) }, 'Entered in Pharmasoft')));
      }) : h('p', { class: 'empty' }, 'Everything is entered in Pharmasoft.'));
  };

  const todayScreen = async () => {
    const d = await api('GET', '/api/pharmacy/sales');
    drawTabs(d.day.pending);
    box.replaceChildren(h('div', { class: 'stats' }, h('div', { class: 'stat' }, h('strong', {}, money(d.day.counter)), h('span', {}, 'received at the counter (' + Object.entries(d.day.by_mode).map(([k, v]) => k + ' ' + money(v)).join(', ') + ')')),
        h('div', { class: 'stat' }, h('strong', {}, money(d.day.to_ip_bills)), h('span', {}, 'added to inpatient bills'))),
      Object.keys(d.day.cash_by_person).length > 0 && h('p', {}, 'Cash to hand over: ' + Object.entries(d.day.cash_by_person).map(([k, v]) => k + ' ' + money(v)).join(', ')),
      d.sales.length ? h('div', { class: 'qlist' }, d.sales.map((s) => h('div', { class: 'qrow' + (s.cancelled ? ' done' : '') },
        h('div', { class: 'qinfo' }, h('span', { class: 'pname' }, s.name || 'Walk-in'), ' ', tag(s.sale_no), s.cancelled ? tag('Cancelled', 'bad') : s.pharmasoft_no ? tag('Pharmasoft ' + s.pharmasoft_no, 'ok') : tag('Not in Pharmasoft yet', 'warn'),
          h('div', { class: 'muted' }, clock(s.at) + ' · ' + s.items.map((x) => x.item + ' ×' + x.qty).join(', ') + ' · ' + (s.mode || 'hospital bill') + ' · ' + s.sold_by), s.cancelled ? h('div', { class: 'muted' }, s.cancelled_by + ': ' + s.cancel_reason) : null),
        h('strong', {}, money(s.total)),
        h('div', { class: 'qact' }, h('button', { class: 'btn quiet', onclick: () => printSlip(s) }, 'Slip'),
          !s.cancelled && h('button', { class: 'btn quiet', onclick: () => formModal('Cancel ' + s.sale_no, [{ key: 'reason', label: 'Why? (for example: medicine returned)' }], {}, async (v) => { await api('POST', '/api/pharmacy/sales/' + s.id + '/cancel', v); await show(); }) }, 'Cancel'))))) : h('p', { class: 'empty' }, 'No sales yet today.'));
  };

  const show = async () => {
    if (tab === 'sale') { drawTabs((await api('GET', '/api/pharmacy/sales?pending=1')).pending); await saleScreen(); }
    else if (tab === 'pending') await pendingScreen(); else await todayScreen();
  };
  await show();
};

render();
