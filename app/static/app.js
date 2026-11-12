'use strict';
// Sunrise Hospital - all staff screens. Plain JavaScript, no build step.

const S = { me: null, depts: [], doctors: [], hospital: 'Sunrise Hospital', address: '', areas: [], lang: 'en', poll: null, timer: null, pendingAppt: null };
try { S.lang = localStorage.getItem('lang') || 'en'; } catch (e) { /* private mode */ }

const VIEWS = {};  // more.js adds the later-phase screens here
const DESK = ['owner', 'reception'];
const DOCS = ['doctor', 'consultant'];
const ROLE_NAMES = { owner: 'Doctor (full access)', doctor: 'In-house doctor', consultant: 'Visiting consultant', reception: 'Reception', nurse: 'Nursing', pharmacy: 'Pharmacy / accounts', insurance: 'Insurance desk', lab: 'Lab', support: 'Support staff (no login)' };
const DOC_STATUS = { in: 'In', delayed: 'Delayed', surgery: 'In surgery', out: 'Not in' };
const VISIT_STATUS = { waiting: 'Waiting', called: 'Called in to doctor', done: 'Seen', skipped: 'Not here when called' };
const BED_STATUS = { vacant: 'Vacant', occupied: 'Occupied', cleaning: 'Cleaning', reserved: 'Reserved' };
const PAYERS = ['Cash', 'Dr NTR Vaidya Seva', 'PM-JAY', 'Insurance / TPA'];
// [address, tab name, screen permission]. Each person sees only the tabs their login allows; the first one is their home.
const NAV = [
  ['today', 'Hospital overview', 'today'],
  ['myday', 'My day', 'myday'],
  ['desk', 'OP Desk', 'desk'],
  ['ward', 'Ward duty', 'ward'],
  ['queue', 'Queue', 'queue'],
  ['appointments', 'Phone bookings', 'appointments'],
  ['doctors', 'Doctors in / out', 'doctors'],
  ['followups', 'Follow-ups', 'followups'],
  ['beds', 'Beds', 'beds'],
  ['ot', 'OT', 'ot'],
  ['lab', 'Lab', 'lab'],
  ['claims', 'Claims', 'claims'],
  ['iphistory', 'Admissions', 'iphistory'],
  ['pharmsale', 'Medicine sale', 'pharmsale'],
  ['pharmacy', 'Stock alerts', 'pharmacy'],
  ['rx', 'Prescriptions', 'rx'],
  ['ipbill', 'IP billing', 'ipbill'],
  ['essel', 'Enter in Essel', 'essel'],
  ['accounts', 'Accounts check', 'accounts'],
  ['staff', 'Staff', 'staff'],
  ['settings', 'Settings', 'settings'],
];
const PAGES = { patient: ['records'], ip: ['chart', 'iphistory', 'claims'], bill: ['ipbill', 'claims', 'accounts'] };  // pages opened from inside other screens

// ---------- small helpers ----------
const t = (s) => (S.lang === 'te' && window.TE[s]) || s;
const dept = (id) => S.depts.find((d) => d.id === id) || {};
const doctor = (id) => S.doctors.find((d) => d.id === id) || {};
const deptName = (d) => (S.lang === 'te' && d.name_te) || d.name || '';
const can = (roles) => roles.includes(S.me.role);  // only for clinical rules tied to being a doctor
const has = (...keys) => keys.some((k) => (S.me.screens || []).includes(k));
const sexWord = (s) => ({ M: 'Male', F: 'Female', O: 'Other' }[s] || '');

// Let append() and replaceChildren() accept lists and skip empty values, so screens can be written as plain nested lists.
for (const m of ['append', 'replaceChildren']) {
  const orig = Element.prototype[m];
  Element.prototype[m] = function (...kids) { return orig.apply(this, kids.flat(Infinity).filter((k) => k != null && k !== false)); };
}

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const k of kids.flat(Infinity)) if (k != null && k !== false) e.append(k.nodeType ? k : String(k));
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'class') e.className = v;
    else if (k === 'value') e.value = v;
    else if (k === 'checked') e.checked = !!v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  return e;
}

async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body instanceof Blob) { opt.body = body; opt.headers['Content-Type'] = body.type; }
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
  let r;
  try { r = await fetch(path, opt); } catch (e) { throw new Error('Cannot reach the hospital laptop. Check that it is on and on the same Wi-Fi.'); }
  const d = await r.json().catch(() => ({}));
  if (r.status === 401 && S.me) { S.me = null; render(); }
  if (!r.ok) throw new Error(d.error || 'Something went wrong');
  return d;
}

let toastTimer;
function toast(msg, bad) {
  const el = document.getElementById('toast');
  // An open pop-up covers the page, so the message must sit inside it to be seen.
  const open = [...document.querySelectorAll('dialog[open]')].pop();
  (open || document.body).append(el);
  el.textContent = msg;
  el.className = 'show' + (bad ? ' bad' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = ''; }, bad ? 5000 : 2500);
}
const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };

function clock(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' });
}
function dayText(iso) {
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}
function waited(iso) {
  const m = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
  return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h ' + (m % 60) + ' min';
}
const isoToday = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };

function field(label, input, hint) {
  return h('label', { class: 'field' }, h('span', { class: 'label' }, label), input, hint && h('span', { class: 'hint' }, hint));
}

// A row of big choice buttons; returns element with .value
function choice(options, value, onchange) {
  const box = h('div', { class: 'choice' });
  box.value = value;
  const draw = () => {
    box.replaceChildren(...options.map(([v, label, sub]) => h('button', {
      type: 'button', class: 'opt' + (box.value === v ? ' on' : ''),
      onclick: () => { box.value = v; draw(); if (onchange) onchange(v); },
    }, label, sub && h('small', {}, sub))));
  };
  draw();
  return box;
}

function modal(title, body, onclose) {
  const d = h('dialog', {}, h('div', { class: 'modal-head' }, h('h2', {}, title),
    h('button', { class: 'btn quiet', type: 'button', 'aria-label': 'Close', onclick: () => d.close() }, 'Close')), body);
  d.addEventListener('close', () => { document.body.append(document.getElementById('toast')); d.remove(); if (onclose) onclose(); });
  document.body.append(d);
  d.showModal();
  return d;
}

// Simple form in a pop-up. fields: {key, label, type: text|number|select|check|multi|time, options, hint}
function formModal(title, fields, init, save) {
  const inputs = {};
  const form = h('form', { class: 'form' });
  for (const f of fields) {
    let el;
    if (f.type === 'select') el = h('select', { value: init[f.key] == null ? '' : String(init[f.key]) }, f.options.map(([v, l]) => h('option', { value: v }, l)));
    else if (f.type === 'check') el = h('input', { type: 'checkbox', checked: init[f.key] });
    else if (f.type === 'multi') el = h('div', { class: 'checks' }, f.options.map(([v, l]) => h('label', {}, h('input', { type: 'checkbox', value: v, checked: (init[f.key] || []).map(String).includes(String(v)) }), ' ' + l)));
    else el = h('input', { type: f.type === 'number' ? 'text' : (f.type || 'text'), inputmode: f.type === 'number' ? 'numeric' : null, value: init[f.key] == null ? '' : init[f.key], placeholder: f.placeholder, autocomplete: 'off' });
    inputs[f.key] = [f, el];
    form.append(f.type === 'check' ? h('label', { class: 'field inline' }, el, ' ' + f.label) : f.type === 'multi' ? h('div', { class: 'field' }, h('span', { class: 'label' }, f.label), el, f.hint && h('span', { class: 'hint' }, f.hint)) : field(f.label, el, f.hint));
  }
  form.append(h('div', { class: 'actions' }, h('button', { class: 'btn primary', type: 'submit' }, t('Save'))));
  const d = modal(title, form);
  const first = form.querySelector('input:not([type=checkbox]), select, textarea');
  if (first) first.focus();
  form.addEventListener('submit', guard(async (ev) => {
    ev.preventDefault();
    const out = {};
    for (const [k, [f, el]] of Object.entries(inputs)) {
      if (f.type === 'check') out[k] = el.checked ? 1 : 0;
      else if (f.type === 'multi') out[k] = [...el.querySelectorAll('input:checked')].map((c) => c.value);
      else if (f.optional && el.value === '') continue;
      else out[k] = el.value.trim();
    }
    await save(out);
    d.close();
    toast('Saved');
  }));
}

async function shrink(file) {
  try {
    const img = await createImageBitmap(file);
    const s = Math.min(1, 1800 / Math.max(img.width, img.height));
    const c = h('canvas', { width: Math.round(img.width * s), height: Math.round(img.height * s) });
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    return await new Promise((res) => c.toBlob(res, 'image/jpeg', 0.85));
  } catch (e) { return file; }
}
function addPhoto(visitId, after) {
  const inp = h('input', { type: 'file', accept: 'image/*', capture: 'environment' });
  inp.onchange = guard(async () => {
    if (!inp.files[0]) return;
    toast('Saving photo...');
    await api('POST', '/api/visits/' + visitId + '/prescription', await shrink(inp.files[0]));
    toast('Prescription photo saved');
    if (after) after();
  });
  inp.click();
}
function showPhotos(ids) {
  modal('Prescription', h('div', { class: 'photos' }, ids.map((id) => h('a', { href: '/files/rx/' + id, target: '_blank', rel: 'noopener' }, h('img', { src: '/files/rx/' + id, alt: 'Prescription photo' })))));
}

// ---------- shell ----------
function go(hash) { if (location.hash === '#' + hash) render(); else location.hash = hash; }

async function render() {
  clearInterval(S.timer); S.poll = null;
  document.body.append(document.getElementById('toast'));
  document.querySelectorAll('dialog').forEach((d) => d.remove());
  document.documentElement.lang = S.lang === 'te' ? 'te' : 'en';
  const app = document.getElementById('app');
  // Asked again on every screen change, so a change to someone's access applies at once
  // and a different person logging in on the same phone never sees the previous person's screens.
  try {
    const b = await api('GET', '/api/bootstrap');
    Object.assign(S, { me: b.me, depts: b.departments, doctors: b.doctors, hospital: b.hospital, address: b.address, areas: b.areas, tokenPrint: b.token_print, tokenBase: b.token_base });
  } catch (e) { S.me = null; app.replaceChildren(); return viewLogin(app); }
  if (S.me.must_change) { app.replaceChildren(); return viewPassword(app, true); }
  const allowed = NAV.filter((n) => has(n[2]));
  let [name, arg] = location.hash.slice(1).split('/');
  const pageOk = PAGES[name] && has(...PAGES[name]);
  if (!pageOk && !allowed.some((n) => n[0] === name)) name = allowed.length ? allowed[0][0] : 'none';
  const root = h('main', {});
  app.replaceChildren(
    h('header', { class: 'top' },
      h('div', { class: 'brand' }, h('div', { class: 'brand-row' }, logoMark(), S.hospital), h('div', { class: 'whoami' }, h('span', { class: 'dot' }), 'Logged in: ', h('strong', {}, S.me.name), ' · ' + (S.me.role_name || ''))),
      h('div', { class: 'who' }, window.dutyButton && !['owner', 'consultant', 'lab'].includes(S.me.role) && window.dutyButton(),
        h('button', { class: 'btn quiet', onclick: () => { location.hash = ''; window.showHelp(); } }, 'Help'),
        h('button', { class: 'btn quiet', onclick: () => { const box = h('div', {}); modal('Change my password', box); viewPassword(box, false); } }, 'Password'),
        h('button', { class: 'btn quiet', onclick: () => { S.lang = S.lang === 'te' ? 'en' : 'te'; try { localStorage.setItem('lang', S.lang); } catch (e) { /* ignore */ } render(); } }, S.lang === 'te' ? 'English' : 'తెలుగు'),
        h('button', { class: 'btn quiet logout', onclick: guard(async () => { if (!(await ask('Log out ' + S.me.name + '?', 'Log out'))) return; await api('POST', '/api/logout', {}); S.me = null; location.hash = ''; render(); }) }, t('Log out')))),
    allowed.length > 1 && h('nav', { class: 'tabs' }, allowed.map(([k, label]) => h('a', { href: '#' + k, class: k === name ? 'on' : '' }, t(label)))),
    root);
  const views = Object.assign({ today: viewToday, desk: viewDesk, queue: viewQueue, appointments: viewAppointments, beds: viewBeds, essel: viewEssel, rx: viewQueue, settings: viewSettings, patient: viewPatient }, VIEWS);
  if (!views[name]) { root.append(h('p', { class: 'empty' }, 'Your login has no screens yet.')); return; }
  if (allowed.length && name === allowed[0][0]) root.append(roleHelp());
  try { await views[name](root, arg, name); } catch (e) { root.append(h('p', { class: 'empty' }, e.message)); }
  window.animateNumbers(root);
  if (S.poll) S.timer = setInterval(() => { if (!document.querySelector('dialog[open]') && !document.hidden) S.poll().then(() => window.animateNumbers(root)).catch(() => {}); }, 6000);
}
window.addEventListener('hashchange', render);
fetch('/api/display').then((r) => r.json()).then((d) => { S.displayMode = d.mode; }).catch(() => {});

// ---------- login ----------
// Every person has their own username and password. Nothing about the staff is shown before login.
function viewLogin(app) {
  const user = h('input', { autocomplete: 'username', autocapitalize: 'none', spellcheck: 'false', required: true });
  const pass = h('input', { type: 'password', autocomplete: 'current-password', required: true });
  const remember = h('input', { type: 'checkbox' });
  const show = h('input', { type: 'checkbox', onchange: () => { pass.type = show.checked ? 'text' : 'password'; } });
  const msg = h('p', { class: 'error', role: 'alert' });
  const btn = h('button', { class: 'btn primary big wide', type: 'submit' }, 'Log in');
  const form = h('form', { class: 'login-card' },
    h('h1', {}, S.hospital), h('p', { class: 'muted' }, 'Log in with your own username and password'),
    field('Username', user), field('Password', pass),
    h('label', { class: 'field inline' }, show, ' Show password'),
    h('label', { class: 'field inline' }, remember, ' Keep me logged in on this phone (only on your own phone)'),
    msg, btn,
    h('p', { class: 'muted small' }, h('a', { href: '/display', target: '_blank' }, 'Open waiting-hall display')));
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    msg.textContent = ''; btn.disabled = true;
    try { await api('POST', '/api/login', { username: user.value.trim(), password: pass.value, remember: remember.checked }); pass.value = ''; location.hash = ''; render(); }
    catch (e) { msg.textContent = e.message; pass.value = ''; pass.focus(); }
    btn.disabled = false;
  });
  const demoBox = h('div', {});
  app.append(h('div', { class: 'login' }, form, demoBox));
  setTimeout(() => user.focus(), 0);
  api('GET', '/api/demo-logins').then((d) => {
    if (!d.demo || !d.people.length) return;
    demoBox.replaceChildren(h('section', { class: 'login-card demo-card' }, h('h2', {}, 'Demo: try each role'),
      h('p', { class: 'muted' }, 'This copy has made-up patients. Tap a person to log in as them, then use Log out to try the next one. A real hospital copy does not show this.'),
      h('div', { class: 'demo-people' }, d.people.map((p) => h('button', { class: 'demo-person', type: 'button', onclick: guard(async () => {
        await api('POST', '/api/login', { username: p.username, password: d.password }); location.hash = ''; render();
      }) }, h('strong', {}, p.name), h('small', {}, p.role_name))))));
  }).catch(() => {});
}

// First login (forced) or changing your own password later.
function viewPassword(box, forced) {
  const old = h('input', { type: 'password', autocomplete: 'current-password' });
  const nw = h('input', { type: 'password', autocomplete: 'new-password' });
  const again = h('input', { type: 'password', autocomplete: 'new-password' });
  const msg = h('p', { class: 'error', role: 'alert' });
  const form = h('form', { class: forced ? 'login-card' : 'form' },
    forced && h('h1', {}, 'Welcome, ' + S.me.name),
    forced && h('p', {}, 'Choose your own password. Do not share it with anyone. Everything you do in the system is recorded under your name.'),
    field(forced ? 'One-time password you were given' : 'Current password', old),
    field('New password', nw, 'At least 8 characters, with letters and numbers. Not your name.'),
    field('New password again', again), msg,
    h('div', { class: 'actions' }, h('button', { class: 'btn primary big', type: 'submit' }, 'Save my password'),
      forced && h('button', { class: 'btn', type: 'button', onclick: guard(async () => { await api('POST', '/api/logout', {}); S.me = null; render(); }) }, t('Log out'))));
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    msg.textContent = '';
    if (nw.value !== again.value) { msg.textContent = 'The two new passwords are not the same'; return; }
    try {
      await api('POST', '/api/password', { old: old.value, new: nw.value });
      toast('Password saved. Other phones and computers have been logged out.');
      S.me = null; render();
    } catch (e) { msg.textContent = e.message; }
  });
  box.append(forced ? h('div', { class: 'login' }, form) : form);
  setTimeout(() => old.focus(), 0);
}

// ---------- patient form (new and edit) ----------
function patientForm(init, onSave, onCancel) {
  const f = {
    name: h('input', { value: init.name || '', autocomplete: 'off', required: true }),
    age_y: h('input', { value: init.age_y == null ? '' : init.age_y, inputmode: 'numeric', class: 'narrow', autocomplete: 'off' }),
    age_m: h('input', { value: init.age_m == null ? '' : init.age_m, inputmode: 'numeric', class: 'narrow', autocomplete: 'off' }),
    dob: h('input', { type: 'date', value: init.dob || '', max: isoToday() }),
    phone: h('input', { value: init.phone || '', inputmode: 'numeric', maxlength: 10, autocomplete: 'off' }),
    guardian: h('input', { value: init.guardian || '', autocomplete: 'off' }),
    area: h('input', { value: init.area || '', list: 'areas', autocomplete: 'off' }),
    referral: h('input', { value: init.referral || '', autocomplete: 'off' }),
  };
  const sex = choice([['M', t('Male')], ['F', t('Female')], ['O', t('Other')]], init.sex || null);
  const form = h('form', { class: 'form' },
    field(t('Name'), f.name),
    h('div', { class: 'field' }, h('span', { class: 'label' }, t('Age')),
      h('div', { class: 'agerow' }, f.age_y, h('span', {}, t('years')), f.age_m, h('span', {}, t('months')), h('span', { class: 'muted' }, t('or date of birth')), f.dob)),
    h('div', { class: 'field' }, h('span', { class: 'label' }, t('Sex')), sex),
    field(t('Phone'), f.phone, 'Own number, or the guardian\'s. Leave empty if there is no phone.'),
    field(t('Village / area'), f.area),
    field(t('Guardian (for children)'), f.guardian),
    field(t('Referred by'), f.referral),
    h('datalist', { id: 'areas' }, S.areas.map((a) => h('option', { value: a }))),
    h('div', { class: 'actions' }, h('button', { class: 'btn primary big', type: 'submit' }, t('Save')),
      onCancel && h('button', { class: 'btn', type: 'button', onclick: onCancel }, t('Cancel'))));
  form.addEventListener('submit', guard(async (ev) => {
    ev.preventDefault();
    const body = { sex: sex.value };
    for (const k of Object.keys(f)) body[k] = f[k].value.trim();
    await onSave(body);
  }));
  setTimeout(() => f.name.focus(), 0);
  return form;
}
const patientLine = (p) => [p.age, sexWord(p.sex), p.phone, p.area, p.uhid].filter(Boolean).join(' · ');

function patientSearch(onPick, extra, startText) {
  const input = h('input', { type: 'search', class: 'search', placeholder: t('Phone number, name or UHID'), autocomplete: 'off', value: startText || '' });
  const results = h('div', { class: 'results' });
  let timer, seq = 0;
  const run = guard(async () => {
    const q = input.value.trim(), my = ++seq;
    if (q.length < 2) { results.replaceChildren(); return; }
    const d = await api('GET', '/api/patients?q=' + encodeURIComponent(q));
    if (my !== seq) return;
    results.replaceChildren(d.patients.length
      ? d.patients.map((p) => h('button', { class: 'result', type: 'button', onclick: () => onPick(p) }, h('strong', {}, p.name), h('span', {}, patientLine(p)), p.last_visit && h('span', { class: 'ret' }, 'Came before · last ' + dayText(p.last_visit) + (p.last_doctor ? ' · ' + p.last_doctor : ''))))
      : h('p', { class: 'empty' }, t('No patient found')));
  });
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 200); });
  if (startText) run();
  setTimeout(() => input.focus(), 0);
  return h('div', {}, h('div', { class: 'searchrow' }, input, extra && extra(input)), results);
}

// ---------- OP desk ----------
async function viewDesk(root) {
  const main = h('section', { class: 'panel' }), side = h('aside', { class: 'panel' });
  root.append(h('div', { class: 'cols' }, main, side));
  let appt = S.pendingAppt; S.pendingAppt = null;

  const drawSide = async () => {
    const d = await api('GET', '/api/queue');
    const rows = S.depts.map((dp) => {
      const v = d.visits.filter((x) => x.dept_id === dp.id);
      return [dp, v.filter((x) => x.status === 'waiting' || x.status === 'called').length, v.length];
    }).filter((r) => r[2]);
    side.replaceChildren(h('h2', {}, t('Today')),
      rows.length ? h('table', { class: 'plain' }, h('thead', {}, h('tr', {}, h('th', {}, t('Department')), h('th', { class: 'num' }, t('Waiting')), h('th', { class: 'num' }, t('Total')))),
        h('tbody', {}, rows.map(([dp, w, n]) => h('tr', {}, h('td', {}, deptName(dp)), h('td', { class: 'num' }, w), h('td', { class: 'num' }, n)))),
        h('tfoot', {}, h('tr', {}, h('td', {}, t('Total')), h('td', { class: 'num' }, rows.reduce((a, r) => a + r[1], 0)), h('td', { class: 'num' }, d.visits.length))))
        : h('p', { class: 'empty' }, 'No tokens given yet today.'));
  };
  S.poll = drawSide;
  drawSide().catch(() => {});

  const find = () => {
    const banner = appt && h('div', { class: 'note' }, 'Phone booking: ', h('strong', {}, appt.name), ' · ' + appt.phone + ' · ' + deptName(dept(appt.dept_id)),
      ' ', h('button', { class: 'btn quiet', onclick: () => { appt = null; find(); } }, t('Cancel')));
    main.replaceChildren(h('h2', {}, t('Find patient')), banner,
      patientSearch(token, (input) => h('button', { class: 'btn', type: 'button', onclick: () => add(input.value.trim()) }, t('New patient')), appt ? appt.phone : ''));
  };
  const add = (text) => {
    const init = appt ? { name: appt.name, phone: appt.phone } : (/^\d+$/.test(text) ? { phone: text } : { name: text });
    main.replaceChildren(h('h2', {}, t('New patient')),
      patientForm(init, async (body) => { const d = await api('POST', '/api/patients', body); token(d.patient); }, find));
  };
  const token = (p) => {
    let deptId = appt ? appt.dept_id : null, doctorId = appt ? appt.doctor_id : null;
    const source = choice([['walkin', t('Walk-in')], ['phone', t('Phone booked')]], appt ? 'phone' : 'walkin', () => draw());
    const body = h('div', {});
    const draw = () => {
      const docs = S.doctors.filter((d) => d.dept_id === deptId);
      if (deptId && !docs.some((d) => d.id === doctorId)) doctorId = docs.length ? docs[0].id : null;
      const dp = dept(deptId);
      body.replaceChildren(
        h('h3', {}, t('Department')),
        h('div', { class: 'choice grid' }, S.depts.map((d) => h('button', { type: 'button', class: 'opt' + (d.id === deptId ? ' on' : ''), onclick: () => { deptId = d.id; draw(); } }, deptName(d)))),
        docs.length > 1 && h('div', {}, h('h3', {}, t('Doctor')), h('div', { class: 'choice' }, docs.map((d) => h('button', { type: 'button', class: 'opt' + (d.id === doctorId ? ' on' : ''), onclick: () => { doctorId = d.id; draw(); } }, d.name)))),
        docs.length === 1 && h('p', { class: 'muted' }, docs[0].name + ' · ' + t(DOC_STATUS[docs[0].status]) + (docs[0].status_note ? ' (' + docs[0].status_note + ')' : '')),
        h('h3', {}, 'How did they come?'), source,
        deptId && h('p', { class: 'fee' }, 'Consultation fee: ', h('strong', {}, '₹' + (source.value === 'phone' ? dp.fee_phone : dp.fee_walkin)), h('span', { class: 'muted' }, ' — collect and bill in Essel as usual')),
        h('div', { class: 'actions' }, h('button', { class: 'btn primary big', disabled: !deptId, onclick: guard(async () => {
          const d = await api('POST', '/api/visits', { patient_id: p.id, dept_id: deptId, doctor_id: doctorId, source: source.value, appointment_id: appt ? appt.id : null });
          appt = null; drawSide().catch(() => {}); slip(d.visit, find);
          if (d.late_booking) toast('Came after the booked time and grace period, so a new token was given instead of ' + d.late_booking + '.', true);
        }) }, t('Give token'))));
    };
    main.replaceChildren(
      h('div', { class: 'picked' }, h('div', {}, h('strong', {}, p.name), h('div', { class: 'muted' }, patientLine(p)),
        p.last_visit && h('div', { class: 'ret' }, 'Returning patient — ' + p.visit_count + ' earlier visit' + (p.visit_count > 1 ? 's' : '') + ', last ' + dayText(p.last_visit) + (p.last_doctor ? ' with ' + p.last_doctor : '') + '. Their old prescriptions and reports are shown to the doctor.')),
        h('button', { class: 'btn quiet', onclick: find }, t('Change'))), body);
    draw();
  };
  find();
}

// QR code for the patient's own "My token" page. Empty when there is no address patients can reach.
function tokenQR(v, cell) {
  if (!v.public_code || !S.tokenBase || !window.qrcode) return null;
  const q = window.qrcode(0, 'M');
  q.addData(S.tokenBase + '/t?c=' + v.public_code);
  q.make();
  const span = h('span', { class: 'qr' });
  span.innerHTML = q.createSvgTag({ cellSize: cell || 3, margin: 1, scalable: true });
  return span;
}

function slip(v, after) {
  const build = () => h('div', { class: 'slip' },
    h('div', { class: 'slip-h' }, S.hospital), h('div', { class: 'slip-s' }, S.address),
    h('div', { class: 'slip-l' }, 'TOKEN / టోకెన్'), h('div', { class: 'slip-t' }, v.token_code),
    h('div', { class: 'slip-d' }, v.dept), v.dept_te && h('div', { class: 'slip-d' }, v.dept_te),
    v.doctor && h('div', {}, v.doctor),
    h('div', { class: 'slip-p' }, v.name + ' · ' + v.uhid), h('div', {}, dayText(v.created_at) + ', ' + clock(v.created_at)),
    h('div', { class: 'slip-w' }, 'Please wait until your token number is called.'), h('div', { class: 'slip-w' }, window.TE['Please wait until your token number is called.']),
    tokenQR(v) && h('div', { class: 'slip-qr' }, tokenQR(v), h('div', { class: 'slip-w' }, 'Scan with your phone to see how many are ahead of you.'), h('div', { class: 'slip-w' }, 'మీ ముందు ఎంత మంది ఉన్నారో ఫోన్‌లో చూడండి.')));
  document.getElementById('print-slip').replaceChildren(build());
  if (S.tokenPrint === false) {
    // No printer: show the number big so reception can say it, write it on the OP sheet, or hand over the numbered card.
    const go = h('button', { class: 'btn primary big', onclick: () => d.close() }, t('Next patient'));
    const d = modal(t('Token') + ' ' + v.token_code, h('div', { class: 'noprint' },
      h('div', { class: 'np-token' }, v.token_code), h('div', { class: 'np-who' }, v.name + ' · ' + v.dept + (v.doctor ? ' · ' + v.doctor : '')),
      tokenQR(v, 5) && h('div', { class: 'np-qr' }, tokenQR(v, 5), h('small', {}, 'Patients with a smartphone can scan this to follow their turn.')),
      h('ul', {}, h('li', {}, 'Tell the patient: token ', h('strong', {}, v.token_no), ' for ' + v.dept + '.'),
        h('li', {}, 'Write ', h('strong', {}, v.token_code), ' on their OP sheet, or give numbered card ', h('strong', {}, v.token_no), '.'),
        h('li', {}, 'They will be called by ' + (S.displayMode === 'token' ? 'number' : 'name') + ' on the waiting-hall TV.')),
      h('div', { class: 'actions center' }, go)), after);
    go.focus();
    return;
  }
  const next = h('button', { class: 'btn big', onclick: () => d.close() }, t('Next patient'));
  const d = modal(t('Token') + ' ' + v.token_code, h('div', {}, build(),
    h('div', { class: 'actions center' }, h('button', { class: 'btn primary big', onclick: () => window.print() }, t('Print')), next)), after);
  next.focus();
}

// ---------- queue (also the pharmacy's prescription list) ----------
async function viewQueue(root, arg, name) {
  let filter = 'all';
  const pharmacy = name === 'rx';
  const box = h('div', {});
  root.append(box);
  const setStatus = async (id, status) => { await api('POST', '/api/visits/' + id + '/status', { status }); };
  const load = async () => {
    const [q, b] = await Promise.all([api('GET', '/api/queue'), pharmacy ? null : api('GET', '/api/bootstrap')]);
    if (b) S.doctors = b.doctors;
    const mine = can(DOCS) ? S.doctors.filter((d) => d.id === S.me.doctor_id) : S.doctors;
    const used = S.depts.filter((d) => q.visits.some((v) => v.dept_id === d.id));
    if (filter !== 'all' && !used.some((d) => d.id === filter)) filter = 'all';
    const list = q.visits.filter((v) => filter === 'all' || v.dept_id === filter);
    const order = { called: 0, waiting: 1, skipped: 2, done: 3 };
    list.sort((a, b2) => order[a.status] - order[b2.status] || a.dept_id - b2.dept_id || a.token_no - b2.token_no);
    const active = list.filter((v) => v.status === 'waiting' || v.status === 'called');
    const oneQueue = filter !== 'all' || can(DOCS);
    const called = active.filter((v) => v.status === 'called'), nextUp = active.find((v) => v.status === 'waiting');

    const row = (v) => h('div', { class: 'qrow ' + v.status },
      h('div', { class: 'tok' }, v.token_code),
      h('div', { class: 'qinfo' },
        has('records') ? h('a', { href: '#patient/' + v.patient_id, class: 'pname' }, v.name) : h('span', { class: 'pname' }, v.name),
        v.source === 'phone' && [' ', tag('Booked')],
        v.last_visit && [' ', tag('Returning · last ' + dayText(v.last_visit).replace(/ \d{4}$/, ''), 'ok')],
        h('div', { class: 'muted' }, [v.age, sexWord(v.sex), doctor(v.doctor_id).name || deptName(dept(v.dept_id)), v.status === 'waiting' ? 'waiting ' + waited(v.created_at) : t(VISIT_STATUS[v.status])].filter(Boolean).join(' · '))),
      h('div', { class: 'qact' },
        !pharmacy && v.status === 'waiting' && h('button', { class: 'btn primary', onclick: guard(async () => { await setStatus(v.id, 'called'); await load(); }) }, t('Call to doctor')),
        !pharmacy && v.status === 'called' && h('button', { class: 'btn primary', onclick: guard(async () => { await setStatus(v.id, 'done'); await load(); }) }, t('Seen by doctor')),
        !pharmacy && v.status === 'called' && h('button', { class: 'btn', onclick: guard(async () => { await setStatus(v.id, 'skipped'); await load(); }) }, t('Not here')),
        !pharmacy && (v.status === 'skipped' || v.status === 'done') && h('button', { class: 'btn quiet', onclick: guard(async () => { await setStatus(v.id, 'waiting'); await load(); }) }, v.status === 'skipped' ? t('Came back') : t('Undo')),
        v.last_visit && has('records') && h('a', { class: 'btn', href: '#patient/' + v.patient_id }, 'Past records'),
        v.rx.length > 0 && h('button', { class: 'btn', onclick: () => showPhotos(v.rx) }, 'View prescription' + (v.rx.length > 1 ? ' (' + v.rx.length + ')' : '')),
        !can(DOCS) && has('rx') && h('button', { class: 'btn', onclick: () => addPhoto(v.id, load) }, v.rx.length ? '+ ' + t('Photo') : 'Prescription ' + t('Photo').toLowerCase()),
        pharmacy && window.rxExtras && window.rxExtras(v, load)));

    box.replaceChildren(
      !pharmacy && h('div', { class: 'docs' }, mine.map((d) => h('label', { class: 'doc ' + d.status }, h('span', {}, d.name, h('small', {}, deptName(dept(d.dept_id)))),
        h('select', { value: d.status, onchange: guard(async (ev) => {
          const status = ev.target.value;
          const note = status === 'delayed' ? ((await askText('Doctor delayed', 'Expected at what time? (optional)')) || '') : '';
          await api('POST', '/api/doctors/' + d.id + '/status', { status, note }); await load();
        }) }, Object.entries(DOC_STATUS).map(([k, l]) => h('option', { value: k }, t(l)))))),
      ),
      !pharmacy && q.booked_not_arrived && q.booked_not_arrived.filter((a) => filter === 'all' || a.dept_id === filter).length > 0 && h('div', { class: 'booked-strip' },
        h('strong', {}, 'Booked, not arrived yet: '), q.booked_not_arrived.filter((a) => filter === 'all' || a.dept_id === filter).map((a) => h('span', { class: 'tag' }, a.token_code + (a.appt_time ? ' · ' + a.appt_time : ''))),
        h('span', { class: 'muted' }, ' — call the next patient who is here; booked patients get their number when they come.')),
      !pharmacy && h('details', { class: 'howto', open: !!S.howto, ontoggle: (e) => { S.howto = e.target.open; } }, h('summary', {}, 'How the queue works'), h('ol', {},
        h('li', {}, h('strong', {}, t('Call to doctor')), ': the token number shows on the waiting-hall TV and is read out. The patient goes in.'),
        h('li', {}, h('strong', {}, t('Seen by doctor')), ': press when the patient comes out. The next token can be called.'),
        h('li', {}, h('strong', {}, t('Not here')), ': the token was called but the patient was not in the hall. They are kept aside, not deleted. Press ', h('strong', {}, t('Came back')), ' when they return and they join the line again.'),
        h('li', {}, 'The big green button does both at once: marks the patient inside as seen and calls the next token.'))),
      !can(DOCS) && used.length > 1 && h('div', { class: 'pills' }, [['all', t('All'), q.visits]].concat(used.map((d) => [d.id, d.code, q.visits.filter((v) => v.dept_id === d.id)])).map(([k, label, vs]) =>
        h('button', { class: 'pill' + (filter === k ? ' on' : ''), onclick: () => { filter = k; load(); } }, label, h('small', {}, vs.filter((v) => v.status === 'waiting' || v.status === 'called').length)))),
      !pharmacy && oneQueue && nextUp && h('div', { class: 'actions' }, h('button', { class: 'btn primary big', onclick: guard(async () => {
        for (const c of called) await setStatus(c.id, 'done');
        await setStatus(nextUp.id, 'called'); await load();
      }) }, (called.length ? t('Seen — call next token') : t('Call next token')) + ' ' + nextUp.token_code)),
      list.length ? h('div', { class: 'qlist' }, list.map(row)) : h('p', { class: 'empty' }, t('Nobody is waiting')));
  };
  S.poll = load;
  await load();
}

// ---------- phone bookings ----------
async function viewAppointments(root) {
  let day = isoToday();
  const list = h('div', {});
  const f = {
    name: h('input', { autocomplete: 'off' }), phone: h('input', { inputmode: 'numeric', maxlength: 10, autocomplete: 'off' }),
    dept_id: h('select', {}, S.depts.map((d) => h('option', { value: d.id }, deptName(d)))),
    appt_date: h('input', { type: 'date', value: day, min: day }), appt_time: h('input', { type: 'time' }), note: h('input', { autocomplete: 'off' }),
  };
  const dateInput = h('input', { type: 'date', value: day, onchange: (e) => { day = e.target.value || isoToday(); load(); } });
  const load = async () => {
    const d = await api('GET', '/api/appointments?date=' + day);
    const words = { booked: 'Booked', arrived: 'Arrived', cancelled: 'Cancelled', noshow: 'Did not come' };
    const set = (a, status) => guard(async () => { await api('POST', '/api/appointments/' + a.id + '/status', { status }); await load(); });
    list.replaceChildren(d.appointments.length ? h('div', { class: 'qlist' }, d.appointments.map((a) => h('div', { class: 'qrow ' + (a.status === 'booked' ? 'waiting' : 'done') },
      h('div', { class: 'tok small' }, a.token_code || '—', h('div', { class: 'muted' }, a.appt_time || '')),
      h('div', { class: 'qinfo' }, h('span', { class: 'pname' }, a.name), h('div', { class: 'muted' }, [a.phone, deptName(dept(a.dept_id)), doctor(a.doctor_id).name, a.note, a.status === 'booked' ? 'Token kept for them until they arrive' : words[a.status]].filter(Boolean).join(' · '))),
      h('div', { class: 'qact' },
        a.status === 'booked' && day === isoToday() && h('button', { class: 'btn primary', onclick: () => { S.pendingAppt = a; go('desk'); } }, 'Arrived — give token'),
        a.status === 'booked' && h('button', { class: 'btn', onclick: set(a, 'noshow') }, 'Did not come'),
        a.status === 'booked' && h('button', { class: 'btn', onclick: set(a, 'cancelled') }, t('Cancel')),
        (a.status === 'noshow' || a.status === 'cancelled') && h('button', { class: 'btn', onclick: set(a, 'booked') }, 'Undo')))))
      : h('p', { class: 'empty' }, 'No phone bookings for this day.'));
  };
  const form = h('form', { class: 'form grid2' }, field(t('Name'), f.name), field(t('Phone'), f.phone), field(t('Department'), f.dept_id),
    field('Date', f.appt_date), field('Time', f.appt_time), field('Note', f.note),
    h('div', { class: 'actions' }, h('button', { class: 'btn primary', type: 'submit' }, 'Save booking')));
  form.addEventListener('submit', guard(async (ev) => {
    ev.preventDefault();
    const body = {}; for (const k of Object.keys(f)) body[k] = f[k].value.trim();
    const docs = S.doctors.filter((d) => d.dept_id === +body.dept_id);
    body.doctor_id = docs.length ? docs[0].id : null;
    const r = await api('POST', '/api/appointments', body);
    tell('Tell the caller:\n\nYour token is ' + r.token_code + (body.appt_time ? '. Please come by ' + body.appt_time : '') + ' on ' + dayText(body.appt_date) + '.\n\nBooked patients are called before walk-ins who come later.', 'Booked: ' + r.token_code);
    f.name.value = f.phone.value = f.note.value = f.appt_time.value = '';
    day = body.appt_date; dateInput.value = day; await load();
  }));
  root.append(h('div', { class: 'cols' },
    h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('h2', {}, t('Phone bookings')), dateInput), list),
    h('aside', { class: 'panel' }, h('h2', {}, 'New phone booking'), form)));
  S.poll = load;
  await load();
}

// ---------- beds ----------
async function viewBeds(root) {
  let mode = 'map';
  try { mode = localStorage.getItem('beds_view') || (window.innerWidth < 700 ? 'list' : 'map'); } catch (e) { /* ignore */ }
  // The whole-hospital map is only for the founder doctors (Hospital overview). Everyone else gets the bed list they work from.
  const mapAllowed = has('today');
  if (!mapAllowed) mode = 'list';
  const box = h('div', {}), mapHost = h('div', {});
  const toggle = h('div', { class: 'pills' });
  root.append(toggle, mapHost, box);
  let map = null;
  const drawToggle = () => mapAllowed && toggle.replaceChildren([['map', 'Hospital map'], ['list', 'Bed list']].map(([k, l]) => h('button', { class: 'pill' + (mode === k ? ' on' : ''), onclick: () => {
    mode = k; try { localStorage.setItem('beds_view', k); } catch (e) { /* ignore */ } drawToggle(); load(); } }, l)));
  const stayDay = (iso) => Math.floor((Date.now() - new Date(iso)) / 86400000) + 1;
  const open = (b) => {
    const body = h('div', {});
    const d = modal(b.label + ' · ' + b.ward, body, load);
    const setBed = (status) => guard(async () => {
      const note = status === 'reserved' ? ((await askText('Reserve bed', 'Reserved for? (optional)')) || '') : '';
      await api('POST', '/api/beds/' + b.id + '/status', { status, note }); d.close();
    });
    if (b.status === 'occupied') {
      const rows = b.patient ? [['Patient', b.patient + ' · ' + [b.age, sexWord(b.sex)].filter(Boolean).join(' · ')], ['UHID', b.uhid], ['Doctor', b.doctor],
        ['Admitted', dayText(b.admitted_at) + ', ' + clock(b.admitted_at) + ' (day ' + stayDay(b.admitted_at) + ')'], ['Diagnosis', b.diagnosis], ['Procedure', b.procedure], ['Scheme / cash', b.payer],
        ['Expected stay', b.expected_days ? b.expected_days + ' days' : ''], ['Attendant', [b.attendant_name, b.attendant_phone].filter(Boolean).join(' · ')],
        ['Advance at admission', b.deposit_noted ? '₹' + b.deposit_noted : '']] : [['Doctor', b.doctor], ['Patient', 'Another doctor\'s patient']];
      body.append(h('table', { class: 'plain kv' }, h('tbody', {}, rows.filter((r) => r[1]).map(([k, v]) => h('tr', {}, h('th', {}, k), h('td', {}, v))))),
        b.discharge_ordered_at && h('p', { class: 'note' }, 'Doctor ordered discharge ' + waited(b.discharge_ordered_at) + ' ago.'),
        b.admission_id && h('div', { class: 'actions' }, has('chart') && h('button', { class: 'btn primary', onclick: () => { d.close(); go('ip/' + b.admission_id); } }, 'Open chart (vitals, notes, discharge)'),
          has('ward') && h('button', { class: 'btn', onclick: guard(async () => {
          if (!(await ask('Has ' + b.patient + ' left ' + b.label + '? The bed will be marked for cleaning.', 'Yes, patient has left'))) return;
          await api('POST', '/api/admissions/' + b.admission_id + '/discharge', {}); d.close();
        }) }, 'Patient has left')));
      return;
    }
    body.append(h('p', {}, 'This bed is ', h('strong', {}, t(BED_STATUS[b.status]).toLowerCase()), b.note ? ' — ' + b.note : '', '.'));
    if (!has('ward', 'admit')) return;
    body.append(h('div', { class: 'actions' },
      has('admit') && h('button', { class: 'btn primary', onclick: () => admitForm(b, body, d) }, t('Admit patient')),
      has('ward') && b.status !== 'vacant' && h('button', { class: 'btn', onclick: setBed('vacant') }, 'Mark vacant'),
      has('ward') && b.status !== 'cleaning' && h('button', { class: 'btn', onclick: setBed('cleaning') }, 'Mark cleaning'),
      has('ward') && b.status !== 'reserved' && h('button', { class: 'btn', onclick: setBed('reserved') }, 'Reserve')));
  };
  const admitForm = (b, body, d) => {
    let patient = null;
    const pbox = h('div', {});
    const pickPatient = () => pbox.replaceChildren(patientSearch((p) => { patient = p; pbox.replaceChildren(h('div', { class: 'picked' }, h('div', {}, h('strong', {}, p.name), h('div', { class: 'muted' }, patientLine(p))), h('button', { class: 'btn quiet', type: 'button', onclick: pickPatient }, t('Change')))); }),
      h('p', { class: 'hint' }, 'New patient? Register at OP Desk first, then admit here.'));
    pickPatient();
    const f = {
      doctor_id: h('select', {}, S.doctors.map((x) => h('option', { value: x.id }, x.name))),
      diagnosis: h('input', { autocomplete: 'off' }), procedure: h('input', { autocomplete: 'off' }),
      payer: h('select', {}, PAYERS.map((x) => h('option', {}, x))),
      expected_days: h('input', { inputmode: 'numeric', class: 'narrow' }),
      attendant_name: h('input', { autocomplete: 'off' }), attendant_phone: h('input', { inputmode: 'numeric', maxlength: 10 }),
      deposit_noted: h('input', { inputmode: 'numeric' }),
      deposit_mode: h('select', {}, ['Cash', 'UPI', 'Card', 'Cheque', 'Bank transfer'].map((x) => h('option', {}, x))),
      deposit_ref: h('input', { autocomplete: 'off', placeholder: 'UPI / card / cheque number' }),
    };
    const form = h('form', { class: 'form' }, h('div', { class: 'field' }, h('span', { class: 'label' }, 'Patient'), pbox),
      field('Admitting doctor', f.doctor_id), field('Diagnosis', f.diagnosis), field('Planned procedure', f.procedure), field('Scheme / cash', f.payer),
      field('Expected stay (days)', f.expected_days), field('Attendant name', f.attendant_name), field('Attendant phone', f.attendant_phone),
      has('ipbill') && [field('Advance received now (₹)', f.deposit_noted, 'Leave empty if no advance is taken now. A numbered receipt is made.'),
        h('div', { class: 'agerow' }, f.deposit_mode, f.deposit_ref)],
      h('div', { class: 'actions' }, h('button', { class: 'btn primary big', type: 'submit' }, 'Admit to ' + b.label)));
    form.addEventListener('submit', guard(async (ev) => {
      ev.preventDefault();
      if (!patient) throw new Error('Choose the patient');
      const out = { patient_id: patient.id, bed_id: b.id }; for (const k of Object.keys(f)) out[k] = f[k].value.trim();
      const r = await api('POST', '/api/admissions', out); d.close(); toast('Admitted to ' + b.label + (r.receipt_no ? ' · receipt ' + r.receipt_no : ''));
      if (r.receipt_no && window.printReceipt) window.printReceipt(r.id, r.receipt_no);
    }));
    body.replaceChildren(form);
  };
  const load = async () => {
    drawToggle();
    mapHost.hidden = mode !== 'map'; box.hidden = mode === 'map';
    if (mode === 'map') { if (!map) map = window.HospitalMap(mapHost, { onBed: (b) => open(b) }); await map.load(); return; }
    const d = await api('GET', '/api/beds');
    const count = (s) => d.beds.filter((b) => b.status === s).length;
    const wards = [...new Set(d.beds.map((b) => b.ward))];
    box.replaceChildren(
      h('div', { class: 'legend' }, Object.keys(BED_STATUS).map((s) => h('span', { class: 'lg ' + s }, t(BED_STATUS[s]) + ' ' + count(s)))),
      wards.map((w) => h('section', {}, h('h3', {}, w), h('div', { class: 'beds' }, d.beds.filter((b) => b.ward === w).map((b) => h('button', { class: 'bed ' + b.status, onclick: () => open(b) },
        h('span', { class: 'bedno' }, b.label),
        b.status === 'occupied' ? [h('strong', {}, b.patient || t('Occupied')), h('span', { class: 'muted' }, [b.patient && b.age, b.doctor].filter(Boolean).join(' · ')), h('span', { class: 'muted' }, 'Day ' + stayDay(b.admitted_at) + (b.payer && b.payer !== 'Cash' ? ' · ' + b.payer : '')), b.discharge_ordered_at && h('span', { class: 'tag warn' }, 'Discharge ordered')]
          : [h('strong', {}, t(BED_STATUS[b.status])), b.note && h('span', { class: 'muted' }, b.note)]))))));
  };
  S.poll = load;
  await load();
}

// ---------- copy step into Essel ----------
async function viewEssel(root) {
  const box = h('div', {});
  root.append(h('p', { class: 'muted' }, 'Patients registered here today that are not yet typed into Essel. Fields are in the same order as Essel\'s OP Registration screen. Tap a value to copy it.'), box);
  const copy = (text) => { (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(() => toast('Copied'), () => toast('Select and copy by hand', true)); };
  const load = async () => {
    const d = await api('GET', '/api/queue');
    const todo = d.visits.filter((v) => !v.essel_done), done = d.visits.length - todo.length;
    box.replaceChildren(h('h2', {}, 'OP registrations'), h('p', {}, h('strong', {}, todo.length), ' to enter · ' + done + ' already entered'),
      todo.length ? todo.map((v) => {
        const fields = [['Name', v.name], ['Age', v.age], ['Sex', sexWord(v.sex)], ['Phone', v.phone], ['Area', v.area], ['Guardian', v.guardian],
          ['Department', dept(v.dept_id).name], ['Doctor', doctor(v.doctor_id).name], ['Referred by', v.referral], ['Fee', v.fee_shown != null ? String(v.fee_shown) : '']];
        return h('div', { class: 'essel' }, h('div', { class: 'tok' }, v.token_code),
          h('div', { class: 'efields' }, fields.map(([k, val]) => h('button', { class: 'ef', disabled: !val, onclick: () => copy(val) }, h('small', {}, k), val || '—'))),
          h('button', { class: 'btn primary', onclick: guard(async () => { await api('POST', '/api/visits/' + v.id + '/essel', { done: true }); await load(); }) }, 'Entered in Essel'));
      }) : h('p', { class: 'empty' }, 'Everything is entered.'));
  };
  S.poll = load;
  await load();
}

// ---------- patient record ----------
async function viewPatient(root, id) {
  const d = await api('GET', '/api/patients/' + id);
  const p = d.patient;
  const edit = () => { const m = modal('Edit patient', patientForm(p, async (body) => { await api('PUT', '/api/patients/' + id, body); m.close(); toast('Saved'); render(); })); };
  root.append(h('section', { class: 'panel' },
    h('div', { class: 'headrow' }, h('div', {}, h('h2', {}, p.name), h('div', { class: 'muted' }, patientLine(p)),
      (p.guardian || p.referral) && h('div', { class: 'muted' }, [p.guardian && 'Guardian: ' + p.guardian, p.referral && 'Referred by: ' + p.referral].filter(Boolean).join(' · '))),
      has('desk') && h('button', { class: 'btn', onclick: edit }, 'Edit')),
    pastRecords(d),
    d.admissions.length > 0 && [h('h3', {}, 'Admissions'), h('div', { class: 'qlist' }, d.admissions.map((a) => h('div', { class: 'qrow' }, h('div', { class: 'tok small' }, a.bed),
      h('div', { class: 'qinfo' }, has('chart', 'iphistory') ? h('a', { class: 'pname', href: '#ip/' + a.id }, a.diagnosis || 'Admission') : h('span', { class: 'pname' }, a.diagnosis || 'Admission'), h('div', { class: 'muted' }, [dayText(a.admitted_at) + (a.discharged_at ? ' to ' + dayText(a.discharged_at) : ' — still admitted'), a.doctor, a.procedure, a.payer].filter(Boolean).join(' · '))))))],
    h('h3', {}, 'OP visits'),
    d.visits.length ? h('div', { class: 'qlist' }, d.visits.map((v) => {
      const rx = d.prescriptions.filter((r) => r.visit_id === v.id).map((r) => r.id);
      return h('div', { class: 'qrow' }, h('div', { class: 'tok small' }, v.token_code),
        h('div', { class: 'qinfo' }, h('span', { class: 'pname' }, dayText(v.visit_date)), h('div', { class: 'muted' }, [v.dept, v.doctor, t(VISIT_STATUS[v.status])].filter(Boolean).join(' · ')),
          rx.length > 0 && h('div', { class: 'thumbs' }, rx.map((r) => h('button', { class: 'thumb', onclick: () => showPhotos(rx) }, h('img', { src: '/files/rx/' + r, alt: 'Prescription', loading: 'lazy' }))))),
        h('div', { class: 'qact' }, !can(DOCS) && has('rx') && h('button', { class: 'btn', onclick: () => addPhoto(v.id, render) }, 'Add prescription photo')));
    })) : h('p', { class: 'empty' }, 'No visits yet.'),
    window.patientExtras && window.patientExtras(d, id)));
}

// ---------- hospital overview (full-access doctors) ----------
async function viewToday(root) {
  const mapHost = h('div', {}), box = h('div', {});
  const hr = new Date().getHours(), hello = hr < 12 ? 'Good morning' : hr < 17 ? 'Good afternoon' : 'Good evening';
  root.append(h('div', { class: 'hello' }, h('div', {}, h('h1', {}, hello + ', ' + S.me.name.replace(/^Dr\.? /, 'Dr ')),
    h('p', {}, new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' }) + ' · ' + S.hospital)),
    h('span', { class: 'live-pill' }, h('span', { class: 'live-dot' }), 'Live')), mapHost, box);
  const map = window.HospitalMap(mapHost);
  const load = async () => {
    map.load().catch(() => {});
    const [d, b] = await Promise.all([api('GET', '/api/dashboard'), api('GET', '/api/bootstrap')]);
    S.doctors = b.doctors;
    const m = d.more, money = (n) => '₹' + Math.round(n || 0).toLocaleString('en-IN');
    const op = d.op.filter((r) => r.total), total = d.op.reduce((a, r) => a + r.total, 0), waiting = d.op.reduce((a, r) => a + r.waiting + r.called, 0);
    const card = (title, href, linkText, ...body) => h('section', { class: 'panel card' }, h('div', { class: 'headrow' }, h('h2', {}, title), href && h('a', { class: 'btn quiet', href }, linkText || 'Open')), body);
    const big = (n, label, cls) => h('div', { class: 'mini' + (cls ? ' ' + cls : '') }, h('strong', {}, n), h('span', {}, label));
    const days = Object.fromEntries(m.doctor_days.map((x) => [x.id, x]));
    // Things that need someone to act, most urgent first
    const alerts = [
      m.critical_labs.length && ['bad', m.critical_labs.length + ' CRITICAL lab value' + (m.critical_labs.length > 1 ? 's' : '') + ' today: ' + m.critical_labs.map((x) => x.name + ' (' + x.test + ', ' + (x.doctor || '') + ')').join('; '), '#lab'],
      m.discharges.length && ['warn', m.discharges.length + ' discharge' + (m.discharges.length > 1 ? 's' : '') + ' in progress: ' + m.discharges.map((x) => 'bed ' + x.bed + ' ' + waited(x.ordered_at) + (x.waiting.length ? ' (waiting: ' + x.waiting.join(', ').toLowerCase() + ')' : ' (ready)')).join('; '), '#ward'],
      m.consultants_not_in.length && ['warn', 'Visiting doctors expected, not arrived: ' + m.consultants_not_in.join(', '), '#doctors'],
      m.ip_money.due_after_discharge.length && ['bad', m.ip_money.due_after_discharge.length + ' discharged patient' + (m.ip_money.due_after_discharge.length > 1 ? 's' : '') + ' with bill not settled', '#ipbill'],
      m.pharmacy.expired && ['bad', m.pharmacy.expired + ' expired medicine batch' + (m.pharmacy.expired > 1 ? 'es' : '') + ' still in stock', '#pharmacy'],
      m.followups.missed && ['warn', m.followups.missed + ' missed follow-ups and vaccines to call', '#followups'],
      m.unsigned && ['warn', m.unsigned + ' discharged patient' + (m.unsigned > 1 ? 's' : '') + ' without a signed discharge summary', '#iphistory'],
      m.claimflow.due.length && ['warn', m.claimflow.due.length + ' insurance claim follow-up' + (m.claimflow.due.length > 1 ? 's' : '') + ' due today (' + m.claimflow.due.map((x) => x.patient).join(', ') + ')', '#claims'],
      m.claimflow.new.length && ['warn', m.claimflow.new.length + ' claim' + (m.claimflow.new.length > 1 ? 's' : '') + ' sent to the insurance desk, not yet picked up', '#claims'],
      m.claimflow.stale.length && ['bad', m.claimflow.stale.length + ' insurance claim' + (m.claimflow.stale.length > 1 ? 's' : '') + ' with no update for 7+ days', '#claims'],
      m.claimflow.not_sent.length && ['warn', m.claimflow.not_sent.length + ' discharged scheme / insurance patient' + (m.claimflow.not_sent.length > 1 ? 's' : '') + ' not yet sent to the insurance desk', '#ipbill'],
      m.slips.waiting.length && ['warn', m.slips.waiting.length + ' charge slip' + (m.slips.waiting.length > 1 ? 's' : '') + ' from the wards waiting for your check (bed ' + m.slips.waiting.map((x) => x.bed).join(', ') + ')', '#ipbill'],
      m.slips.not_sent_today.length && new Date().getHours() >= 18 && ['warn', 'No charge slip sent today for bed ' + m.slips.not_sent_today.map((x) => x.bed).join(', '), '#ward'],
      m.rx_missing && ['warn', m.rx_missing + ' patients seen today without a prescription photo', '#rx'],
      d.essel_pending && ['warn', d.essel_pending + ' OP registrations not yet entered in Essel', '#essel'],
      m.pharm.pending && ['warn', m.pharm.pending + ' pharmacy sales not yet entered in Pharmasoft', '#pharmsale'],
      d.unsent && ['warn', d.unsent + ' Telegram updates waiting (internet may be down)', '#settings'],
    ].filter(Boolean);
    box.replaceChildren(
      h('div', { class: 'headrow' }, h('p', { class: 'muted' }, dayText(d.date) + ' · updates every few seconds'), null),
      h('section', { class: 'panel attention' }, h('h2', {}, alerts.length ? 'Needs attention (' + alerts.length + ')' : 'Nothing needs attention'),
        alerts.length ? h('ul', { class: 'alerts' }, alerts.map(([cls, text, href]) => h('li', { class: cls }, h('a', { href }, text)))) : h('p', { class: 'ok-line' }, 'All departments are up to date.')),
      h('div', { class: 'cards' },
        card('OP today', '#queue', 'Queue',
          h('div', { class: 'minis' }, big(total, 'patients'), big(waiting, 'waiting now'), big(d.appointments.pending, 'phone bookings to come')),
          op.length ? h('table', { class: 'plain' }, h('thead', {}, h('tr', {}, h('th', {}, t('Department')), h('th', { class: 'num' }, t('Waiting')), h('th', { class: 'num' }, 'Seen'), h('th', { class: 'num' }, t('Total')))),
            h('tbody', {}, op.map((r) => h('tr', {}, h('td', {}, r.name), h('td', { class: 'num' }, r.waiting + r.called), h('td', { class: 'num' }, r.done), h('td', { class: 'num' }, r.total))))) : h('p', { class: 'empty' }, 'No OP patients yet.')),
        card('Inpatients and beds', '#beds', 'Beds',
          h('div', { class: 'minis' }, big(d.beds.occupied + ' / ' + d.beds.total, 'beds occupied'), big(d.beds.vacant, 'vacant'), big(d.beds.cleaning, 'being cleaned')),
          d.inpatients.length ? h('table', { class: 'plain' }, h('tbody', {}, d.inpatients.map((r) => h('tr', {}, h('td', { class: 'bedcell' }, r.label),
            h('td', {}, has('chart') ? h('a', { href: '#ip/' + r.admission_id }, r.patient) : r.patient, h('div', { class: 'muted' }, [r.diagnosis, r.doctor, r.payer !== 'Cash' && r.payer].filter(Boolean).join(' · '))),
            h('td', { class: 'num' }, 'Day ' + (Math.floor((Date.now() - new Date(r.admitted_at)) / 86400000) + 1), r.discharge_ordered_at ? h('div', {}, tag('Discharge', 'warn')) : null))))) : h('p', { class: 'empty' }, 'No inpatients.')),
        card('Pharmacy', '#pharmsale', 'Counter',
          h('div', { class: 'minis' }, big(money(m.pharm.counter), m.pharm.count + ' counter sales'), big(money(m.pharm.to_ip_bills), 'to inpatient bills'), big(m.pharm.pending, 'not in Pharmasoft yet', m.pharm.pending ? 'warnc' : '')),
          h('p', {}, h('a', { href: '#pharmacy' }, 'Stock: '), m.pharmacy.expired + ' expired · ' + m.pharmacy.expiring + ' expiring in ' + m.pharmacy.window + ' days · ' + m.pharmacy.low + ' low')),
        card('Money today', '#accounts', 'Accounts check',
          h('table', { class: 'plain kv' }, h('tbody', {},
            h('tr', {}, h('th', {}, 'OP fees expected (collected in Essel)'), h('td', { class: 'num' }, money(m.op_fees))),
            h('tr', {}, h('th', {}, 'Inpatient money received'), h('td', { class: 'num' }, money(m.ip_money.collected))),
            h('tr', {}, h('th', {}, 'Pharmacy counter'), h('td', { class: 'num' }, money(m.pharm.counter))),
            h('tr', {}, h('th', {}, 'Refunds / discounts given'), h('td', { class: 'num' }, money(m.ip_money.refunds) + ' / ' + money(m.ip_money.discounts)))))),
        card('Doctors', '#doctors', 'In / out',
          h('table', { class: 'plain' }, h('tbody', {}, S.doctors.map((x) => h('tr', {}, h('td', {}, x.name, h('div', { class: 'muted' }, dept(x.dept_id).name)),
            h('td', {}, h('span', { class: 'state ' + x.status }, DOC_STATUS[x.status]), h('div', { class: 'muted' }, [days[x.id] && days[x.id].arrived_at && 'came ' + days[x.id].arrived_at, days[x.id] && days[x.id].left_at && 'left ' + days[x.id].left_at, x.status_note].filter(Boolean).join(' · ')))))))),
        card('Staff, claims and lab', null, null,
          h('p', {}, h('strong', {}, 'On duty now: '), m.on_duty.length ? m.on_duty.join(', ') : 'nobody has marked in', ' ', h('a', { href: '#staff' }, 'attendance')),
          h('p', {}, h('a', { href: '#claims' }, 'Claims'), ': ' + m.claims.preparing + ' preparing · ' + m.claims.submitted + ' submitted · ' + m.claims.queried + ' queried · ' + m.claims.approved + ' approved · ' + m.claims.settled + ' settled'),
          h('p', {}, 'Insurance desk today: ' + m.claimflow.today.submitted + ' submitted, ' + m.claimflow.today.docs + ' documents, ' + m.claimflow.today.followups + ' follow-ups · ₹' + Math.round(m.claimflow.pending_amount).toLocaleString('en-IN') + ' pending with insurers'),
          h('p', {}, h('a', { href: '#lab' }, 'Lab'), ': ' + m.labs_open + ' reports awaited'),
          h('p', {}, h('a', { href: '#followups' }, 'Follow-ups'), ': ' + m.followups.today + ' due today, ' + m.followups.missed + ' missed'))));
  };
  S.poll = load;
  await load();
}

// ---------- settings (full-access doctors only) ----------
async function viewSettings(root) {
  const box = h('div', { class: 'settings' });
  root.append(box);
  const post = (path) => async (body) => { await api('POST', path, body); await load(); };
  const section = (title, intro, addLabel, onAdd, table) => h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('h2', {}, title), addLabel && h('button', { class: 'btn', onclick: onAdd }, addLabel)), intro && h('p', { class: 'muted' }, intro), h('div', { class: 'scroll' }, table));
  const tbl = (heads, rows) => h('table', { class: 'plain' }, h('thead', {}, h('tr', {}, heads.map((x) => h('th', {}, x)))), h('tbody', {}, rows));
  const editBtn = (fn) => h('button', { class: 'btn quiet', onclick: fn }, 'Edit');
  const off = (r) => (r.active ? '' : ' off');

  const load = async () => {
    const [d, b] = await Promise.all([api('GET', '/api/admin/all'), api('GET', '/api/bootstrap')]);
    Object.assign(S, { depts: b.departments, doctors: b.doctors, hospital: b.hospital, address: b.address });
    const deptOpts = d.departments.map((x) => [x.id, x.name]);
    const deptF = [{ key: 'name', label: 'Name' }, { key: 'name_te', label: 'Name in Telugu' }, { key: 'code', label: 'Token code', hint: '2 to 4 letters, printed on tokens. Example: PED' },
      { key: 'fee_walkin', label: 'Walk-in fee (₹)', type: 'number' }, { key: 'fee_phone', label: 'Phone-booking fee (₹)', type: 'number' }, { key: 'active', label: 'In use', type: 'check' }];
    const docF = [{ key: 'name', label: 'Name' }, { key: 'dept_id', label: 'Department', type: 'select', options: deptOpts },
      { key: 'kind', label: 'Type', type: 'select', options: Object.entries(DOC_KINDS) },
      { key: 'visit_days', label: 'Days a visiting doctor is expected', type: 'multi', options: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((x) => [x, x]) },
      { key: 'visit_time', label: 'Usual time of arrival', type: 'time' },
      { key: 'payout_kind', label: 'Visiting doctor payment', type: 'select', options: [['', 'Not set'], ['visit', 'Per OP patient seen'], ['case', 'Per case (OP + IP)'], ['day', 'Per day attended'], ['fixed', 'Fixed per month']] }, { key: 'payout_rate', label: 'Rate (₹)', type: 'number' }, { key: 'active', label: 'In use', type: 'check' }];
    const staffF = (isNew) => [{ key: 'name', label: 'Name' }, { key: 'role', label: 'Role', type: 'select', options: Object.entries(ROLE_NAMES) },
      { key: 'doctor_id', label: 'Which doctor (for doctor logins: their own patients and My day)', type: 'select', options: [['', '—']].concat(d.doctors.map((x) => [x.id, x.name])) },
      { key: 'username', label: 'Username', placeholder: isNew ? 'leave empty to make one from the name' : '', optional: isNew },
      { key: 'salary', label: 'Monthly salary (₹), 0 if not on payroll', type: 'number' }, { key: 'active', label: 'Working here (untick when someone leaves: their login stops at once)', type: 'check' }];
    const saveStaff = (extra) => async (v) => {
      const r = await api('POST', '/api/admin/staff', Object.assign(v, extra));
      await load();
      if (r.temp_password) showTemp(v.name, r.username, r.temp_password);
    };
    const bedF = [{ key: 'ward', label: 'Ward' }, { key: 'label', label: 'Bed number' }, { key: 'active', label: 'In use', type: 'check' }];
    const tgF = (chats) => [{ key: 'label', label: 'Person or group' },
      chats && chats.length ? { key: 'chat_id', label: 'Telegram chat', type: 'select', options: chats.map((c) => [c.chat_id, c.name + ' (' + c.chat_id + ')']) } : { key: 'chat_id', label: 'Telegram chat ID' },
      { key: 'topics', label: 'Which updates', type: 'multi', options: [['summary', 'Daily summary'], ['ip', 'Admissions and discharges'], ['doctor', 'Doctor in / delayed / in surgery'], ['lab', 'Critical lab values'], ['pharmacy', 'Pharmacy expiry and low stock']] },
      { key: 'dept_ids', label: 'Which departments', type: 'multi', options: deptOpts, hint: 'Tick none to get all departments.' }, { key: 'active', label: 'Switched on', type: 'check' }];
    const s = d.settings;

    box.replaceChildren(
      s.demo && h('div', { class: 'note' }, 'This copy contains made-up demo patients and staff, and every demo login has the same password. Before real use, start a clean copy (see README).'),
      section('Hospital', null, 'Edit', () => formModal('Hospital', [{ key: 'hospital_name', label: 'Name' }, { key: 'hospital_addr', label: 'Address (printed on tokens)' }, { key: 'casualty_phone', label: 'Casualty phone (shown on waiting-hall display)' },
        { key: 'consult_minutes', label: 'Usual minutes per OP patient (used for waiting times until enough patients are seen today)', type: 'number' },
        { key: 'booking_grace', label: 'Phone bookings keep their token until this many minutes after the booked time', type: 'number' },
        { key: 'public_url', label: 'Address patients\' phones use for "My token" (leave empty for the patients\' door on the guest Wi-Fi' + (s.public_base ? ', now ' + s.public_base : '') + ')', placeholder: 'e.g. https://token.yourhospital.in' }], s, post('/api/admin/settings')),
        h('p', {}, s.hospital_name + ' · ' + s.hospital_addr + (s.casualty_phone ? ' · Casualty ' + s.casualty_phone : '')),
        h('p', { class: 'muted' }, 'Patients\' token page: ' + (s.public_url || s.public_base || 'not available (no network address)') + ' · about ' + s.consult_minutes + ' min per OP patient until today\'s real times are known.'),
        h('p', { class: 'muted' }, 'This address is the patients\' door: it opens only the token page (no logins, no names). Patients can use it on a guest Wi-Fi or, with an internet address, on their own mobile data. Keep the staff portal on the staff Wi-Fi.')),
      section('Departments and fees', 'Fees are shown to reception when giving a token. Money is still collected and billed in Essel.', 'Add department', () => formModal('Add department', deptF, { active: 1 }, post('/api/admin/department')),
        tbl(['Department', 'Code', 'Walk-in', 'Phone booking', ''], d.departments.map((r) => h('tr', { class: off(r) }, h('td', {}, r.name, h('div', { class: 'muted' }, r.name_te)), h('td', {}, r.code), h('td', {}, '₹' + r.fee_walkin), h('td', {}, '₹' + r.fee_phone),
          h('td', {}, editBtn(() => formModal(r.name, deptF, r, (v) => post('/api/admin/department')(Object.assign(v, { id: r.id })))))))),
      ),
      section('Doctors', null, 'Add doctor', () => formModal('Add doctor', docF, { active: 1, kind: 'consultant', dept_id: deptOpts[0][0] }, post('/api/admin/doctor')),
        tbl(['Doctor', 'Department', 'Type', ''], d.doctors.map((r) => h('tr', { class: off(r) }, h('td', {}, r.name), h('td', {}, (d.departments.find((x) => x.id === r.dept_id) || {}).name), h('td', {}, DOC_KINDS[r.kind], r.kind === 'consultant' && r.visit_days ? h('div', { class: 'muted' }, r.visit_days + (r.visit_time ? ' · ' + r.visit_time : '')) : null),
          h('td', {}, editBtn(() => formModal(r.name, docF, Object.assign({}, r, { visit_days: (r.visit_days || '').split(',') }), (v) => post('/api/admin/doctor')(Object.assign(v, { id: r.id }))))))))),
      section('Staff and logins', 'Each person has their own username and password. When you add someone, the system gives a one-time password; they choose their own at first login. Everything they do is recorded under their name.', 'Add person', () => formModal('Add person', staffF(true), { active: 1, role: 'reception' }, saveStaff({})),
        tbl(['Name', 'Username', 'Role', 'Screens', 'Last login', ''], d.staff.map((r) => h('tr', { class: off(r) }, h('td', {}, r.name),
          h('td', {}, r.username || '—', r.must_change && r.role !== 'support' ? h('div', { class: 'muted' }, 'not logged in yet') : null),
          h('td', {}, ROLE_NAMES[r.role] + (r.active ? '' : ' (switched off)')),
          h('td', {}, r.role === 'owner' ? 'Everything' : r.role === 'support' ? '—' : r.screens == null ? 'Same as role' : h('span', { class: 'tag warn' }, 'Custom: ' + (r.screens ? r.screens.split(',').length : 0))),
          h('td', { class: 'muted' }, r.last_login ? dayText(r.last_login) : '—'),
          h('td', {}, editBtn(() => formModal(r.name, staffF(false), r, saveStaff({ id: r.id }))),
            r.role !== 'support' && r.role !== 'owner' && h('button', { class: 'btn quiet', onclick: () => personScreens(r, d.access, load) }, 'Screens'),
            r.role !== 'support' && h('button', { class: 'btn quiet', onclick: guard(async () => {
              if (!(await ask('Give ' + r.name + ' a new one-time password? Their current password stops working and they are logged out everywhere.', 'Reset password'))) return;
              const x = await api('POST', '/api/admin/staff/' + r.id + '/reset-password', {}); await load(); showTemp(r.name, x.username, x.temp_password);
            }) }, 'Reset password')))))),
      accessMatrix(d.access, load),
      section('Beds', null, 'Add bed', () => formModal('Add bed', bedF, { active: 1 }, post('/api/admin/bed')),
        tbl(['Ward', 'Bed', ''], d.beds.map((r) => h('tr', { class: off(r) }, h('td', {}, r.ward), h('td', {}, r.label + (r.active ? '' : ' (not in use)')),
          h('td', {}, editBtn(() => formModal(r.label, bedF, r, (v) => post('/api/admin/bed')(Object.assign(v, { id: r.id }))))))))),
      window.settingsExtras && window.settingsExtras(d, load, section, tbl, editBtn),
      h('section', { class: 'panel' }, h('h2', {}, 'Updates on Telegram'),
        h('p', { class: 'muted' }, 'Messages never contain patient names. They are sent only while this laptop is on and has internet; if the internet is down they are sent when it comes back.'),
        h('ol', { class: 'steps' },
          h('li', {}, 'In Telegram, open ', h('strong', {}, '@BotFather'), ', send ', h('code', {}, '/newbot'), ' and follow the steps. It gives a long token.'),
          h('li', {}, 'Paste the token here: ', h('button', { class: 'btn', onclick: () => formModal('Telegram bot token', [{ key: 'tg_token', label: 'Token from BotFather', type: 'password' }], {}, post('/api/admin/settings')) }, s.telegram_set ? 'Token saved — change' : 'Enter token')),
          h('li', {}, 'Each person opens the new bot in Telegram and presses Start. For a department group, add the bot to the group and send any message there.'),
          h('li', {}, 'Then press ', h('button', { class: 'btn', disabled: !s.telegram_set, onclick: guard(async () => {
            const c = await api('POST', '/api/admin/telegram-chats', {});
            if (!c.chats.length) throw new Error('Nobody has written to the bot yet. Do step 3, then try again.');
            formModal('Add person or group', tgF(c.chats), { active: 1, topics: ['summary'], label: c.chats[0].name }, post('/api/admin/target'));
          }) }, 'Add person or group'))),
        d.targets.length > 0 && h('div', { class: 'scroll' }, tbl(['Who', 'Gets', 'Departments', ''], d.targets.map((r) => h('tr', { class: off(r) }, h('td', {}, r.label), h('td', {}, (r.topics || '').split(',').filter(Boolean).map((x) => ({ summary: 'Daily summary', ip: 'Admissions', doctor: 'Doctor status', lab: 'Critical lab', pharmacy: 'Pharmacy' }[x])).join(', ') || '—'),
          h('td', {}, (r.dept_ids || '').split(',').filter(Boolean).map((x) => (d.departments.find((y) => y.id === +x) || {}).code).join(', ') || 'All'),
          h('td', {}, editBtn(() => formModal(r.label, tgF(null), Object.assign({}, r, { topics: (r.topics || '').split(','), dept_ids: (r.dept_ids || '').split(',') }), (v) => post('/api/admin/target')(Object.assign(v, { id: r.id })))),
            h('button', { class: 'btn quiet', onclick: guard(async () => { await api('POST', '/api/admin/telegram-test', { id: r.id }); toast('Test message sent'); }) }, 'Send test')))))),
        h('div', { class: 'actions' },
          h('button', { class: 'btn', onclick: () => formModal('Daily summary time', [{ key: 'summary_time', label: 'Send the daily summary at', type: 'time' }], s, post('/api/admin/settings')) }, 'Daily summary at ' + s.summary_time),
          h('button', { class: 'btn', disabled: !d.targets.length, onclick: guard(async () => { await api('POST', '/api/admin/summary-now', {}); toast('Summary will be sent in a few seconds'); }) }, 'Send summary now')),
        d.outbox.some((m) => m.error && !m.sent_at) && h('p', { class: 'error' }, 'Last message could not be sent: ' + d.outbox.find((m) => m.error && !m.sent_at).error)),
      h('section', { class: 'panel' }, h('div', { class: 'headrow' }, h('h2', {}, 'Activity record'), h('button', { class: 'btn', onclick: guard(async () => {
        const a = await api('GET', '/api/audit?limit=300');
        modal('Activity record', h('div', { class: 'scroll tall' }, tbl(['When', 'Who', 'What', 'Details'], a.rows.map((r) => h('tr', {}, h('td', {}, dayText(r.at) + ' ' + clock(r.at)), h('td', {}, r.staff_name), h('td', {}, r.action + (r.entity_id ? ' #' + r.entity_id : '')), h('td', { class: 'muted' }, r.detail || ''))))));
      }) }, 'Show')), h('p', { class: 'muted' }, 'Every registration, token, bed change, login and setting change is recorded with the person\'s name and time. It cannot be edited or deleted.')));
  };
  await load();
}

const DOC_KINDS = { owner: 'Doctor (full access)', inhouse: 'In-house doctor', consultant: 'Visiting consultant' };

function showTemp(name, username, pw) {
  modal('Login for ' + name, h('div', {},
    h('p', {}, 'Give these to ', h('strong', {}, name), ' in person (not on WhatsApp):'),
    h('table', { class: 'plain kv temp' }, h('tbody', {}, h('tr', {}, h('th', {}, 'Username'), h('td', {}, username)), h('tr', {}, h('th', {}, 'One-time password'), h('td', {}, pw)))),
    h('p', { class: 'muted' }, 'It works once. At first login they must choose their own password. This one-time password is not shown again.')));
}

// Settings: which screens each role has. Ticks save at once.
// Screens grouped by area, with a plain name and one line on what the screen is for.
const SCREEN_GROUPS = [
  ['Front desk and OP', [['desk', 'OP Desk', 'Register patients, give tokens'], ['queue', 'Queue', 'Call tokens in, mark seen'], ['appointments', 'Phone bookings', 'Book patients by phone'],
    ['doctors', 'Doctors in / out', 'Mark visiting doctors came / left'], ['followups', 'Follow-ups', 'Vaccine and follow-up call lists'], ['rx', 'Prescriptions', 'Photograph paper prescriptions'], ['essel', 'Enter in Essel', 'Copy OP registrations into Essel']]],
  ['Doctors', [['myday', 'My day', 'Own patients, inpatients, reports, OT'], ['records', 'Patient records', 'Open a patient\'s history and past records']]],
  ['Inpatients', [['beds', 'Beds', 'See the bed board and hospital map'], ['admit', 'Admit patients', 'Put a patient in a bed'], ['ward', 'Ward duty', 'Inpatient list, bed cleaning, patient left'],
    ['chart', 'Inpatient chart', 'Vitals, medicines, charges, rounds, discharge steps'], ['iphistory', 'Admissions', 'Past and current admissions'], ['ot', 'OT', 'Operation bookings and checklist']]],
  ['Lab, pharmacy and insurance', [['lab', 'Lab', 'Samples and reports'], ['pharmsale', 'Medicine sale', 'Pharmacy counter sales'], ['pharmacy', 'Stock alerts', 'Expiry, low stock, dose check'], ['claims', 'Claims', 'Insurance claims and follow-ups']]],
  ['Hospital and money', [['today', 'Hospital overview', 'The whole hospital on one screen'], ['accounts', 'Accounts check', 'Fees, cash handover, compare with Essel'], ['staff', 'Staff', 'Attendance, roster, salary'],
    ['ipbill', 'IP billing', 'Only full-access doctors'], ['settings', 'Settings', 'Only full-access doctors']]],
];
const homeOf = (keys) => { const n = NAV.find((x) => keys.includes(x[2])); return n ? n[1] : 'nothing yet'; };

// One switch per screen, grouped. `onToggle(key, on)` saves; locked screens are shown but cannot be switched.
function screenSwitches(keys, locked, onToggle, disabled) {
  return h('div', { class: 'sw-groups' }, SCREEN_GROUPS.map(([title, list]) => h('section', { class: 'sw-group' }, h('h3', {}, title),
    list.map(([k, name, what]) => {
      const lock = locked.includes(k);
      const box = h('input', { type: 'checkbox', role: 'switch', checked: !lock && keys.includes(k), disabled: lock || disabled, onchange: (ev) => onToggle(k, ev.target.checked) });
      return h('label', { class: 'sw' + (lock ? ' locked' : '') }, h('span', { class: 'sw-text' }, h('strong', {}, name), h('small', {}, what)), box, h('span', { class: 'sw-track', 'aria-hidden': 'true' }));
    }))));
}

function accessMatrix(acc, reload) {
  const roles = acc.roles.filter((r) => r.key !== 'owner');
  let pick = roles[0].key;
  try { pick = localStorage.getItem('access_role') || pick; } catch (e) { /* ignore */ }
  const body = h('div', {});
  const draw = () => {
    const r = roles.find((x) => x.key === pick) || roles[0];
    body.replaceChildren(
      h('div', { class: 'pills' }, roles.map((x) => h('button', { class: 'pill' + (x.key === r.key ? ' on' : ''), type: 'button', onclick: () => { pick = x.key; try { localStorage.setItem('access_role', pick); } catch (e) { /* ignore */ } draw(); } }, x.name, h('small', {}, x.screens.length)))),
      h('div', { class: 'sw-head' }, h('div', {}, h('strong', {}, r.name), ' opens on ', h('strong', {}, homeOf(r.screens)), ' and has ', h('strong', {}, r.screens.length), ' screen' + (r.screens.length === 1 ? '' : 's') + '.'),
        h('span', { class: 'muted' }, 'Changes save at once.')),
      screenSwitches(r.screens, acc.locked, guard(async (k, on) => {
        const set = new Set(r.screens); if (on) set.add(k); else set.delete(k);
        await api('POST', '/api/admin/role-screens', { role: r.key, screens: [...set] }); r.screens = [...set]; toast((on ? 'Turned on' : 'Turned off') + ' for ' + r.name); draw();
      })));
  };
  draw();
  return h('section', { class: 'panel' }, h('h2', {}, 'Who can see what'),
    h('p', { class: 'muted' }, 'Choose a role, then switch screens on or off for everyone in it. A screen that is off disappears from their tabs and cannot be opened by typing the address. To change one person only, use "Screens" next to their name above.'),
    body,
    h('p', { class: 'muted' }, 'Always, whatever is switched: doctors with full access see everything; Settings, logins and IP billing are only for them; only doctor logins can order discharge or sign summaries; a visiting doctor only sees their own patients.'));
}

function personScreens(r, acc, reload) {
  const roleSet = (acc.roles.find((x) => x.key === r.role) || { screens: [] }).screens;
  let custom = r.screens != null;
  let keys = custom ? (r.screens || '').split(',').filter(Boolean) : roleSet.slice();
  const body = h('div', {});
  const draw = () => body.replaceChildren(
    choice([['same', 'Same as ' + ROLE_NAMES[r.role], 'Follows the role'], ['own', 'Only for ' + r.name.split(' ')[0], 'Choose below']], custom ? 'own' : 'same', (v) => { custom = v === 'own'; if (!custom) keys = roleSet.slice(); draw(); }),
    h('p', { class: 'muted' }, 'Opens on ' + homeOf(keys) + ' · ' + keys.length + ' screens'),
    screenSwitches(keys, acc.locked, (k, on) => { const set = new Set(keys); if (on) set.add(k); else set.delete(k); keys = [...set]; draw(); }, !custom));
  draw();
  const m = modal('Screens for ' + r.name, h('div', {}, body, h('div', { class: 'actions' }, h('button', { class: 'btn primary', onclick: guard(async () => {
    await api('POST', '/api/admin/staff', { id: r.id, screens: custom ? keys : null });
    m.close(); toast('Saved'); await reload();
  }) }, 'Save'))));
}

// Everything from earlier visits in one place, newest first: what the doctor looks at for a returning patient.
function pastRecords(d) {
  const items = [];
  const vById = Object.fromEntries(d.visits.map((v) => [v.id, v]));
  const byVisit = {};
  d.prescriptions.forEach((r) => { (byVisit[r.visit_id] = byVisit[r.visit_id] || []).push(r.id); });
  Object.entries(byVisit).forEach(([vid, ids]) => { const v = vById[vid] || {}; items.push({ date: v.visit_date || '', kind: 'Prescription', who: v.doctor, rx: ids, label: v.dept }); });
  (d.labs || []).filter((l) => l.has_file).forEach((l) => items.push({ date: (l.reported_at || l.ordered_at).slice(0, 10), kind: 'Lab report', who: l.doctor, label: l.test, lab: l.id, critical: l.critical }));
  d.admissions.forEach((a) => items.push({ date: a.admitted_at.slice(0, 10), kind: 'Admission', who: a.doctor, label: [a.diagnosis, a.procedure].filter(Boolean).join(' · ') + (a.discharged_at ? ' — discharged ' + dayText(a.discharged_at) : ' — in hospital now'), ip: a.id, signed: a.signed }));
  items.sort((x, y) => (y.date > x.date ? 1 : y.date < x.date ? -1 : 0));
  return h('section', { class: 'records' }, h('h3', {}, 'Past records (' + items.length + ')'),
    items.length ? h('div', { class: 'record-list' }, items.map((it) => h('div', { class: 'record' },
      h('div', { class: 'rec-date' }, dayText(it.date)), h('div', { class: 'rec-body' }, h('strong', {}, it.kind), it.critical ? [' ', tag('CRITICAL', 'bad')] : null,
        h('div', { class: 'muted' }, [it.label, it.who].filter(Boolean).join(' · ')),
        it.rx && h('div', { class: 'thumbs big' }, it.rx.map((r) => h('button', { class: 'thumb', onclick: () => showPhotos(it.rx) }, h('img', { src: '/files/rx/' + r, alt: 'Prescription', loading: 'lazy' })))),
        it.lab && h('a', { class: 'btn', href: '/files/lab/' + it.lab, target: '_blank', rel: 'noopener' }, 'Open report'),
        it.ip && has('chart', 'iphistory') && h('a', { class: 'btn', href: '#ip/' + it.ip }, it.signed ? 'Discharge summary and chart' : 'Chart'))))) : h('p', { class: 'empty' }, 'No earlier prescriptions or reports yet.'));
}

// A short "your job here" card on each person's home screen. Closed once, it stays closed on that phone.
const ROLE_HELP = {
  owner: ['"Needs attention" at the top lists what is waiting in any department. Tap a line to go there.',
    'The cards below show OP, inpatients, pharmacy, money, doctors and staff as they happen.',
    'IP billing: nurses\' charge slips arrive here. Check them, take advances and payments, and make the final bill.',
    'Prices, staff logins and who can see what are in Settings. Discounts and reopening a final bill are only for you.',
    'Once a day open Accounts check: OP against Essel, inpatient and pharmacy cash handover.'],
  doctor: ['Set your status at the top of My day: In, Delayed, In surgery or Not in. The waiting hall and reception see it.',
    'My day lists your patients for today in order. Reception calls each token in; you do not need to press anything for the queue.',
    'Returning patients have a green tag. "Past records" shows old prescriptions, reports and discharge summaries.',
    'Inpatients: open the chart for round notes, "order discharge" and signing the summary. Prescriptions stay on paper; reception photographs them.'],
  consultant: ['Set your status at the top of My day so reception and the waiting hall know you are here.',
    'My day lists only your patients: today\'s OP in order (reception calls them in), your inpatients, their reports and your operations.',
    'Returning patients have a green tag; "Past records" shows what was done before.',
    'Prescriptions stay on paper; reception photographs them for you.'],
  reception: ['OP Desk: type the phone number, pick the patient (or New patient), choose department, Give token and print.',
    'Phone bookings: when the patient arrives press "Arrived — give token".',
    'Prescriptions: after the doctor, photograph each paper prescription with the phone. The next patient comes up by itself.',
    'Doctors in / out: tap "Arrived now" / "Left now" for visiting doctors.',
    'Enter in Essel: OP registrations, when it is quiet.'],
  nurse: ['Ward duty lists every inpatient. Yellow "Vitals due" means more than 6 hours since the last vitals.',
    'Open chart → Vitals, Medicine given, "Service / charge given", "Room and nursing days". Choose the item and how many; the price is fixed by the hospital.',
    'Once a day (and before discharge) press "Send charge slip" on the chart. It reaches the IP billing dashboard at once — no paper slip.',
    'Discharge: tick the steps as they are done, then "Patient has left". Mark beds "Cleaned, ready".'],
  pharmacy: ['Medicine sale: tap the patient (their prescription photo is there), tap each medicine, Cash / UPI / Card, Save. Next customer.',
    'Inpatients: no money is taken; the sale goes on their hospital bill.',
    'When the counter is quiet: "To enter in Pharmasoft" — copy each sale into Pharmasoft and type its bill number.',
    'Each morning load the stock file from Pharmasoft in Stock alerts, so prices, batches and expiry are up to date.'],
  insurance: ['Start with "New from inpatients" and "Follow-up due" at the top of Claims. The numbers show your work today.',
    'After every call to the insurer or TPA press "Follow-up": write what they said and the next date to check.',
    'Documents: photograph each paper with the phone. Lab reports and the signed summary are added by themselves.',
    'Portal details: tap each value to copy it into the insurer\'s website.',
    'Download claim file or Share sends everything in one file. Update Status when the insurer replies.'],
  lab: ['Press "Sample collected" when you take the sample.',
    'Press "Attach report" and take a photo or choose the PDF. Tick "critical" if a value is dangerous; the doctor is alerted.'],
};
function roleHelp() {
  const steps = ROLE_HELP[S.me.role];
  const key = 'help_closed_' + S.me.id;
  let closed = false;
  try { closed = localStorage.getItem(key) === '1'; } catch (e) { /* ignore */ }
  if (!steps || closed) return null;
  const box = h('section', { class: 'helpcard' }, h('div', { class: 'headrow' }, h('h2', {}, 'Your job here'),
    h('button', { class: 'btn quiet', onclick: () => { try { localStorage.setItem(key, '1'); } catch (e) { /* ignore */ } box.remove(); } }, 'Got it, hide this')),
    h('ol', {}, steps.map((x) => h('li', {}, x))));
  return box;
}
window.showHelp = () => { try { localStorage.removeItem('help_closed_' + S.me.id); } catch (e) { /* ignore */ } render(); };

// Numbers count up to their new value when they change (skipped for people who prefer less motion).
const lastNumbers = new Map();
window.animateNumbers = (scope) => {
  const still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  (scope || document).querySelectorAll('.hm-kpi strong, .mini strong, .stat strong, .md-row strong, .hc-big').forEach((el) => {
    const box = el.closest('.hm-kpi, .mini, .stat, .md-row, .hm-callout');
    const key = (box ? box.textContent.replace(el.textContent, '') : '') + '|' + (location.hash || '');
    const m = el.textContent.match(/^(₹?)([\d,]+)(.*)$/);
    if (!m) return;
    const to = parseInt(m[2].replace(/,/g, ''), 10), from = lastNumbers.has(key) ? lastNumbers.get(key) : 0;
    lastNumbers.set(key, to);
    if (still || from === to) return;
    const fmt = (n) => m[1] + (m[1] ? Math.round(n).toLocaleString('en-IN') : String(Math.round(n))) + m[3];
    const t0 = performance.now(), dur = 700;
    const step = (now) => { const p = Math.min(1, (now - t0) / dur); el.textContent = fmt(from + (to - from) * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(step); };
    el.textContent = fmt(from);
    requestAnimationFrame(step);
  });
};

function logoMark() {
  const span = h('span', { class: 'logo', 'aria-hidden': 'true' });
  span.innerHTML = '<svg viewBox="0 0 20 20"><path d="M7 2h6v5h5v6h-5v5H7v-5H2V7h5z" fill="#fff"/></svg>';
  return span;
}

// On-screen replacements for the browser's confirm / prompt / alert, which some app windows silently block.
window.ask = (message, okLabel) => new Promise((resolve) => {
  let answered = false;
  const yes = h('button', { class: 'btn primary', type: 'button', onclick: () => { answered = true; d.close(); resolve(true); } }, okLabel || 'Yes');
  const d = modal('Please confirm', h('div', {}, h('p', { class: 'pre' }, message),
    h('div', { class: 'actions' }, yes, h('button', { class: 'btn', type: 'button', onclick: () => d.close() }, t('Cancel')))), () => { if (!answered) resolve(false); });
  yes.focus();
});
window.askText = (title, label) => new Promise((resolve) => {
  let answered = false;
  const inp = h('input', { autocomplete: 'off' });
  const form = h('form', { class: 'form' }, field(label, inp), h('div', { class: 'actions' }, h('button', { class: 'btn primary', type: 'submit' }, 'OK')));
  const d = modal(title, form, () => { if (!answered) resolve(null); });
  form.addEventListener('submit', (ev) => { ev.preventDefault(); answered = true; d.close(); resolve(inp.value.trim()); });
  inp.focus();
});
window.tell = (message, title) => new Promise((resolve) => {
  const ok = h('button', { class: 'btn primary', type: 'button', onclick: () => d.close() }, 'OK');
  const d = modal(title || 'Done', h('div', {}, h('p', { class: 'pre' }, message), h('div', { class: 'actions' }, ok)), () => resolve());
  ok.focus();
});

// render() is called at the end of more.js, after all screens are registered.
