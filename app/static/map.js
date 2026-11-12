'use strict';
// Hospital map: a cutaway 3D-style (isometric) drawing of the hospital in plain SVG, so it works offline
// on the hospital laptop and older PCs. Rooms have walls and windows, beds have patients, the waiting hall
// has people, and everything is clickable. Motion: the building rises in, people move gently, lights pulse,
// and clicking zooms to the place and shows its numbers. People who ask their device for less motion get a still map.

(function () {
  const U = 15, C30 = 0.866, S30 = 0.5;
  const P = (x, y, z) => [(x - y) * C30 * U, (x + y) * S30 * U - (z || 0) * U];
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const shade = (hex, f) => {
    const n = parseInt(hex.slice(1), 16);
    const c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.max(0, Math.min(255, Math.round(f < 0 ? v * (1 + f) : v + (255 - v) * f))));
    return '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('');
  };
  const f1 = (n) => n.toFixed(1);
  const pts = (arr) => arr.map((p) => f1(p[0]) + ',' + f1(p[1])).join(' ');
  const COL = {
    blue: '#2f63e0', deep: '#1f4fc4', wall: '#e6ecf7', wallTop: '#ffffff', floor: '#f3f6fc', ward: '#eef3fb', tile: '#e4ebf7',
    vacant: '#3fae7a', occupied: '#2f63e0', cleaning: '#e3a32b', reserved: '#8fb0ef', discharge: '#e3a32b',
    in: '#29a36a', delayed: '#e3a32b', surgery: '#2f63e0', out: '#a7b1c2', skin: '#d9a07a', hair: '#2b2622',
    wood: '#c99a6b', grass: '#dcefe2', grass2: '#cfe8d7', road: '#d9dee8', line: '#ffffff', tree: '#67b88a', tree2: '#4fa275',
  };
  const CLOTHES = ['#e05d5d', '#f0a33a', '#5b8def', '#8e6bd6', '#3fae7a', '#d6739f', '#4a5975', '#e08a3c'];

  // ---- shapes ----
  function box(x, y, z, w, d, hgt, color, o) {
    o = o || {};
    const top = o.top || shade(color, 0.35), left = o.left || shade(color, -0.1), right = o.right || shade(color, -0.26);
    const t = [P(x, y, z + hgt), P(x + w, y, z + hgt), P(x + w, y + d, z + hgt), P(x, y + d, z + hgt)];
    const l = [P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + hgt), P(x, y + d, z + hgt)];
    const r = [P(x + w, y, z), P(x + w, y + d, z), P(x + w, y + d, z + hgt), P(x + w, y, z + hgt)];
    const st = ' stroke="' + (o.stroke || 'rgba(23,32,54,.10)') + '" stroke-width="' + (o.sw || 0.6) + '" stroke-linejoin="round"' + (o.op ? ' fill-opacity="' + o.op + '"' : '');
    return '<polygon points="' + pts(l) + '" fill="' + left + '"' + st + '/><polygon points="' + pts(r) + '" fill="' + right + '"' + st + '/><polygon points="' + pts(t) + '" fill="' + top + '"' + st + '/>';
  }
  const flat = (x, y, z, w, d, fill, extra) => '<polygon points="' + pts([P(x, y, z), P(x + w, y, z), P(x + w, y + d, z), P(x, y + d, z)]) + '" fill="' + fill + '"' + (extra || '') + '/>';
  const text = (x, y, z, s, cls, dy) => { const p = P(x, y, z); return '<text x="' + f1(p[0]) + '" y="' + f1(p[1] + (dy || 0)) + '" class="' + cls + '" text-anchor="middle">' + esc(s) + '</text>'; };
  const pill = (x, y, z, s, color, cls) => {
    const p = P(x, y, z), w = 14 + String(s).length * 6.6;
    return '<g class="m-pill ' + (cls || '') + '"><rect x="' + f1(p[0] - w / 2) + '" y="' + f1(p[1] - 26) + '" width="' + f1(w) + '" height="20" rx="10" fill="' + color + '"/>' +
      '<text x="' + f1(p[0]) + '" y="' + f1(p[1] - 12) + '" text-anchor="middle" class="m-pilltext">' + esc(s) + '</text></g>';
  };
  const shortName = (n) => String(n || '').replace(/\b[A-Z]\.\s*/g, '').replace(/^Dr\s*/, 'Dr ').trim();
  const plate = (x, y, z, name, code, color) => {
    const p = P(x, y, z), w = Math.max(60, 16 + String(name).length * 6.2);
    return '<g class="m-plate"><rect x="' + f1(p[0] - w / 2) + '" y="' + f1(p[1] - 30) + '" width="' + f1(w) + '" height="28" rx="6" fill="#ffffff" stroke="#c7d6fb"/>' +
      '<rect x="' + f1(p[0] - w / 2) + '" y="' + f1(p[1] - 30) + '" width="4" height="28" rx="2" fill="' + color + '"/>' +
      '<text x="' + f1(p[0] + 2) + '" y="' + f1(p[1] - 18) + '" text-anchor="middle" class="m-plate1">' + esc(name) + '</text>' +
      '<text x="' + f1(p[0] + 2) + '" y="' + f1(p[1] - 7) + '" text-anchor="middle" class="m-plate2">' + esc(code) + '</text></g>';
  };
  let seed = 1;
  const rnd = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
  // A person, drawn at their feet. o.role: 'doctor' (white apron, stethoscope), 'coat' (white coat, no stethoscope),
  // 'nurse' (blue scrubs and cap), otherwise everyday clothes in `shirt`. o.sit draws them seated, o.female longer hair.
  function person(x, y, z, shirt, o) {
    o = o || {};
    if (o.coat && !o.role) o.role = 'doctor';
    if (o.cap && !o.role) o.role = 'nurse';
    const p = P(x, y, z || 0), fx = p[0], fy = p[1], sit = !!o.sit;
    const role = o.role, female = o.female != null ? o.female : rnd() < 0.5;
    const pants = role === 'nurse' ? '#7fa6e6' : role ? '#3b4660' : ['#34405a', '#5a4a3a', '#2f3b55', '#6b5b8a'][Math.floor(rnd() * 4)];
    const top = role === 'nurse' ? '#8fb6f0' : role ? (shirt && shirt !== '#ffffff' ? shirt : '#5b8def') : shirt;
    const lift = sit ? 6 : 0, by = fy - lift;        // body baseline (hips) moves down when seated
    const r = (x1, y1, w, hgt, fill, rx) => '<rect x="' + f1(x1) + '" y="' + f1(y1) + '" width="' + f1(w) + '" height="' + f1(hgt) + '" rx="' + (rx == null ? 1.2 : rx) + '" fill="' + fill + '"/>';
    let g = '<g class="m-bob" style="animation-delay:-' + f1(rnd() * 3) + 's"><ellipse cx="' + f1(fx) + '" cy="' + f1(fy) + '" rx="5.5" ry="2.2" fill="rgba(23,32,54,.14)"/>';
    if (sit) g += r(fx - 3.6, by - 3, 7.2, 3.2, pants, 1.5) + r(fx - 3.4, by - 0.5, 2.6, 6, pants) + r(fx + 0.8, by - 0.5, 2.6, 6, pants);
    else g += r(fx - 3.3, fy - 11, 2.8, 11, pants) + r(fx + 0.5, fy - 11, 2.8, 11, pants) + '<ellipse cx="' + f1(fx - 1.9) + '" cy="' + f1(fy - 0.4) + '" rx="2" ry="1" fill="#1f2433"/><ellipse cx="' + f1(fx + 1.9) + '" cy="' + f1(fy - 0.4) + '" rx="2" ry="1" fill="#1f2433"/>';
    const ty = by - (sit ? 13 : 20);                  // top of torso
    g += r(fx - 4.6, ty, 9.2, 10.5, top, 2.4);
    if (role === 'doctor' || role === 'coat') {
      // white apron / coat open at the front, showing the shirt
      g += '<path d="M' + f1(fx - 5) + ' ' + f1(ty + 0.5) + 'h3.6l1.4 6v' + (sit ? 5 : 9) + 'h-5z M' + f1(fx + 5) + ' ' + f1(ty + 0.5) + 'h-3.6l-1.4 6v' + (sit ? 5 : 9) + 'h5z" fill="#ffffff" stroke="#c9d4e8" stroke-width=".6"/>';
      g += '<path d="M' + f1(fx + 2.2) + ' ' + f1(ty + 7) + 'h2" stroke="#c9d4e8" stroke-width=".8"/>';
      if (role === 'doctor') g += '<path d="M' + f1(fx - 2.6) + ' ' + f1(ty + 0.4) + 'q-0.4 5 2.6 6.5q3-1.5 2.6-6.5" fill="none" stroke="#2b3548" stroke-width=".9"/><circle cx="' + f1(fx) + '" cy="' + f1(ty + 7.2) + '" r="1.1" fill="#9aa6bd"/>';
    }
    const arm = role === 'doctor' || role === 'coat' ? '#ffffff' : top;
    g += r(fx - 6.6, ty + 0.8, 2.4, 9, arm, 1.2) + r(fx + 4.2, ty + 0.8, 2.4, 9, arm, 1.2);
    g += '<circle cx="' + f1(fx - 5.4) + '" cy="' + f1(ty + 10.3) + '" r="1.3" fill="' + COL.skin + '"/><circle cx="' + f1(fx + 5.4) + '" cy="' + f1(ty + 10.3) + '" r="1.3" fill="' + COL.skin + '"/>';
    g += r(fx - 1.3, ty - 2.2, 2.6, 2.8, COL.skin, 0.6);
    const hy = ty - 6;
    if (female && role !== 'nurse') g += '<path d="M' + f1(fx - 4.6) + ' ' + f1(hy) + 'q0 8 2 9h5.2q2-1 2-9z" fill="' + COL.hair + '"/>';
    g += '<circle cx="' + f1(fx) + '" cy="' + f1(hy) + '" r="4.3" fill="' + COL.skin + '"/>';
    g += '<path d="M' + f1(fx - 4.4) + ' ' + f1(hy - 0.4) + 'a4.4 4.4 0 0 1 8.8 0q-1.5-2.2-4.4-2.2t-4.4 2.2z" fill="' + COL.hair + '"/>';
    g += '<circle cx="' + f1(fx - 1.5) + '" cy="' + f1(hy + 0.6) + '" r=".55" fill="#3a2a20"/><circle cx="' + f1(fx + 1.5) + '" cy="' + f1(hy + 0.6) + '" r=".55" fill="#3a2a20"/>';
    if (role === 'nurse') g += r(fx - 3.6, hy - 6, 7.2, 2.6, '#ffffff', 1) + '<path d="M' + f1(fx - 0.9) + ' ' + f1(hy - 4.7) + 'h1.8M' + f1(fx) + ' ' + f1(hy - 5.6) + 'v1.8" stroke="#e05d5d" stroke-width=".7"/>';
    return g + '</g>';
  }
  const chair = (x, y) => box(x, y, 0, 0.7, 0.7, 0.45, '#4a5975') + box(x, y, 0.45, 0.7, 0.15, 0.6, '#4a5975');
  const desk = (x, y, w) => box(x, y, 0, w || 2, 0.9, 0.78, COL.wood, { top: '#e2c39c' }) + box(x + 0.3, y + 0.15, 0.78, 0.7, 0.12, 0.45, '#2b3548', { top: '#3d4a63' });
  const bench = (x, y, len) => box(x, y, 0, len, 0.7, 0.42, '#7d8fb8', { top: '#9fb0d6' }) + box(x, y, 0.42, len, 0.15, 0.5, '#7d8fb8');
  const plant = (x, y) => box(x, y, 0, 0.5, 0.5, 0.45, '#c9b59a') + (() => { const p = P(x + 0.25, y + 0.25, 0.9); return '<circle cx="' + f1(p[0]) + '" cy="' + f1(p[1]) + '" r="6" fill="' + COL.tree + '"/><circle cx="' + f1(p[0] + 3) + '" cy="' + f1(p[1] - 3) + '" r="4" fill="' + COL.tree2 + '"/>'; })();
  function shelf(x, y, len) {
    let s = box(x, y, 0, len, 0.55, 2, '#d7c3a0', { top: '#e8d7b8' });
    for (let lv = 0; lv < 3; lv++) for (let i = 0; i < Math.floor(len / 0.55); i++) {
      const c = CLOTHES[(i + lv * 3) % CLOTHES.length];
      s += box(x + 0.1 + i * 0.55, y + 0.55, 0.25 + lv * 0.6, 0.38, 0.02, 0.35, c, { left: c, right: shade(c, -0.2), top: shade(c, 0.3) });
    }
    return s;
  }
  function bed(x, y, st, occupied, icu) {
    const c = COL[st] || COL.vacant;
    let s = box(x, y, 0, 1.6, 3, 0.5, '#c7d0e0', { top: '#dfe5ef' });
    s += box(x + 0.05, y + 0.05, 0.5, 1.5, 2.9, 0.15, '#ffffff', { top: '#ffffff' });
    s += box(x + 0.25, y + 0.15, 0.65, 1.1, 0.6, 0.2, '#ffffff', { top: '#f7f9fc' });
    s += box(x, y + 2.95, 0, 1.6, 0.08, 0.95, shade(c, -0.1));          // foot board in the status colour
    if (occupied) {
      s += box(x + 0.1, y + 0.9, 0.65, 1.4, 2, 0.22, c, { top: shade(c, 0.25) });
      const hp = P(x + 0.8, y + 0.45, 0.95);
      s += '<circle cx="' + f1(hp[0]) + '" cy="' + f1(hp[1]) + '" r="3.6" fill="' + COL.skin + '"/><path d="M' + f1(hp[0] - 3.6) + ' ' + f1(hp[1] - 0.6) + 'a3.6 3.6 0 0 1 7.2 0z" fill="' + COL.hair + '"/>';
      // drip stand
      const a = P(x + 1.9, y + 0.4, 0), b = P(x + 1.9, y + 0.4, 2.3);
      s += '<line x1="' + f1(a[0]) + '" y1="' + f1(a[1]) + '" x2="' + f1(b[0]) + '" y2="' + f1(b[1]) + '" stroke="#8a96ad" stroke-width="1.3"/><rect x="' + f1(b[0] - 2.5) + '" y="' + f1(b[1]) + '" width="5" height="7" rx="1.5" fill="#cfe3ff" stroke="#8fb0ef" stroke-width=".6"/>';
    }
    if (icu) {
      s += box(x - 0.6, y + 0.2, 0, 0.35, 0.35, 1.1, '#4b5a75') + box(x - 0.7, y + 0.15, 1.1, 0.5, 0.5, 0.4, '#2b3548');
      const m = P(x - 0.2, y + 0.4, 1.3);
      s += '<rect class="m-blink" x="' + f1(m[0] - 3) + '" y="' + f1(m[1] - 3) + '" width="6" height="4" rx="1" fill="#5df0a1"/>';
    }
    return s;
  }
  function tree(x, y, big) {
    const b = P(x, y, 0), r = big ? 13 : 10;
    return '<g class="m-sway" style="animation-delay:-' + f1(rnd() * 4) + 's"><ellipse cx="' + f1(b[0]) + '" cy="' + f1(b[1]) + '" rx="' + (r * 0.8) + '" ry="' + (r * 0.35) + '" fill="rgba(23,32,54,.10)"/><rect x="' + f1(b[0] - 1.6) + '" y="' + f1(b[1] - 16) + '" width="3.2" height="16" rx="1" fill="#a98261"/>' +
      '<circle cx="' + f1(b[0]) + '" cy="' + f1(b[1] - 22) + '" r="' + r + '" fill="' + COL.tree + '"/><circle cx="' + f1(b[0] + r * 0.45) + '" cy="' + f1(b[1] - 26) + '" r="' + (r * 0.6) + '" fill="' + COL.tree2 + '"/><circle cx="' + f1(b[0] - r * 0.4) + '" cy="' + f1(b[1] - 28) + '" r="' + (r * 0.45) + '" fill="#86cba2"/></g>';
  }
  function car(x, y, color) {
    return box(x, y, 0.15, 1.7, 3.2, 0.6, color) + box(x + 0.15, y + 0.9, 0.75, 1.4, 1.5, 0.5, '#cfe0fb', { top: shade(color, 0.3), left: '#bcd3f5', right: '#a9c3ee' });
  }
  function ambulance(x, y) {
    let s = box(x, y, 0.2, 2, 4, 1.5, '#ffffff', { left: '#f3f6fc', right: '#e3e9f4', top: '#ffffff' });
    s += box(x + 0.1, y + 3, 0.2, 1.8, 1, 1.0, '#ffffff', { top: '#dfe8f8' });
    const a = P(x, y + 4, 0.8), b = P(x + 2, y + 4, 0.8), c = P(x + 2, y + 4, 1.05), d = P(x, y + 4, 1.05);
    s += '<polygon points="' + pts([a, b, c, d]) + '" fill="#e05d5d"/>';
    const cr = P(x + 1, y + 4, 1.45);
    s += '<path d="M' + f1(cr[0] - 1.5) + ' ' + f1(cr[1] - 4.5) + 'h3v3h3v3h-3v3h-3v-3h-3v-3h3z" fill="#e05d5d"/>';
    const lt = P(x + 1, y + 1, 1.75);
    s += '<rect class="m-siren" x="' + f1(lt[0] - 5) + '" y="' + f1(lt[1] - 3) + '" width="10" height="4" rx="2" fill="#4d8bff"/>';
    return s;
  }
  // A room: floor, two back walls with windows (front walls left open, like a cutaway model)
  function room(x, y, w, d, o) {
    o = o || {};
    const hgt = o.h || 2.3, wc = o.wall || COL.wall;
    let s = flat(x, y, 0.01, w, d, o.floor || COL.floor, ' stroke="rgba(23,32,54,.07)"');
    if (o.tiles) for (let i = 1; i < w; i += 1.5) s += '<line x1="' + f1(P(x + i, y, 0.02)[0]) + '" y1="' + f1(P(x + i, y, 0.02)[1]) + '" x2="' + f1(P(x + i, y + d, 0.02)[0]) + '" y2="' + f1(P(x + i, y + d, 0.02)[1]) + '" stroke="rgba(23,32,54,.05)"/>';
    s += box(x, y, 0, 0.22, d, hgt, wc, { top: COL.wallTop, left: shade(wc, -0.04), right: shade(wc, -0.12) });
    s += box(x, y, 0, w, 0.22, hgt, wc, { top: COL.wallTop, left: shade(wc, -0.06), right: shade(wc, -0.14) });
    for (let i = 1.2; i < w - 1; i += 2.4) s += '<polygon points="' + pts([P(x + i, y + 0.22, 1), P(x + i + 1.2, y + 0.22, 1), P(x + i + 1.2, y + 0.22, 1.8), P(x + i, y + 0.22, 1.8)]) + '" fill="#bfd6ff" stroke="#ffffff" stroke-width="1"/>';
    for (let i = 1.2; i < d - 1; i += 2.6) s += '<polygon points="' + pts([P(x + 0.22, y + i, 1), P(x + 0.22, y + i + 1.2, 1), P(x + 0.22, y + i + 1.2, 1.8), P(x + 0.22, y + i, 1.8)]) + '" fill="#cadfff" stroke="#ffffff" stroke-width="1"/>';
    return s;
  }

  // ---- the hospital ----
  function layout(data) {
    seed = 7;
    const zones = [], labels = [], anchors = {}, items = [];
    let order = 0;
    const zone = (key, id, svg, cls) => zones.push({ key, svg: id ? '<g class="m-hit ' + (cls || '') + '" data-id="' + esc(id) + '">' + svg + '</g>' : svg });
    // What this login's map shows: 'full' (whole hospital), 'doctor' (own OP room + inpatient wing), 'ward' (inpatient wing only)
    const sc = data.scope || 'full';
    const depts = sc === 'full' ? data.depts : sc === 'doctor' ? data.depts.filter((d) => d.doctors.some((x) => x.id === S.me.doctor_id)) : [];
    const showHall = sc === 'full';
    const opCols = depts.length > 1 ? 2 : 1, roomW = 8, roomD = 6.2;
    const opRows = depts.length ? Math.ceil(depts.length / opCols) : 0;
    const opEnd = opRows * (roomD + 0.4);
    // OP rooms
    depts.forEach((d, i) => {
      const x = (i % opCols) * (roomW + 0.5), y = Math.floor(i / opCols) * (roomD + 0.4), id = 'dept-' + d.id;
      items.push({ id, kind: 'dept', ref: d });
      const doc = d.doctors.find((x) => x.status === 'in') || d.doctors.find((x) => x.status !== 'out') || d.doctors[0], st = doc ? doc.status : 'out';
      let s = room(x, y, roomW, roomD, { tiles: true });
      s += plant(x + 0.5, y + 0.5) + desk(x + 3, y + 2.2, 2.2) + chair(x + 3.7, y + 1.2) + chair(x + 3.7, y + 3.4);
      s += box(x + 6, y + 0.6, 0, 1.4, 3, 0.7, '#dfe7f6', { top: '#ffffff' });          // examination couch
      if (st === 'in') s += person(x + 4.05, y + 1.55, 0, '#5b8def', { role: 'doctor', sit: true, female: /meera|kavya|nisha|anita|grace|salma/i.test(doc.name) });
      if (st === 'in' && d.waiting) s += person(x + 4.05, y + 3.75, 0, CLOTHES[d.id % CLOTHES.length], { sit: true });
      const lp = P(x + 0.22, y + roomD / 2, 2.6);
      s += '<circle class="' + (st === 'in' ? 'm-pulse' : '') + '" cx="' + f1(lp[0]) + '" cy="' + f1(lp[1]) + '" r="5.5" fill="' + COL[st] + '" stroke="#fff" stroke-width="2"/>';
      zone(x + y, id, s);
      labels.push(plate(x + roomW / 2, y + 0.3, 2.45, doc ? shortName(doc.name) : d.name, d.name + ' · ' + (doc ? DOC_STATUS[st] : 'No doctor'), COL[st]));
      if (d.waiting) labels.push(pill(x + roomW / 2, y + roomD / 2 - 1.2, 2.6, d.waiting + ' waiting', '#172036'));
      anchors[id] = [x + roomW / 2, y + roomD / 2, 2];
    });
    // Waiting hall with benches and people
    const hy = opEnd + 0.2, hallW = depts.length ? opCols * (roomW + 0.5) - 0.5 : 0;
    if (showHall) {
    items.push({ id: 'reception', kind: 'reception' });
    let hall = room(0, hy, hallW, 4.6, { floor: '#f6f8fd', h: 0.6 });
    const benches = Math.floor(hallW / 4);
    for (let b = 0; b < benches; b++) hall += bench(0.8 + b * 4, hy + 1.4, 3) + bench(0.8 + b * 4, hy + 3.2, 3);
    zone(hy, 'reception', hall);
    for (let k = 0; k < Math.min(data.waitingTotal, benches * 8); k++) {
      const b = Math.floor(k / 8) % benches, seat = k % 4, row = Math.floor(k / 4) % 2;
      zone(hy + 2 + row * 2 + k * 0.01, null, person(1.2 + b * 4 + seat * 0.75, hy + 1.85 + row * 1.8, 0.42, CLOTHES[k % CLOTHES.length], { sit: true }));
    }
    // Reception desk and entrance
    const ry = hy + 4.8;
    let rec = room(0, ry, hallW, 4.2, { floor: '#f3f6fc', h: 0.6, tiles: true });
    rec += box(2, ry + 1.2, 0, 6, 1, 1.05, COL.blue, { top: '#ffffff' }) + person(4, ry + 0.8, 0, '#2f63e0', { female: true }) + person(6.5, ry + 0.8, 0, '#2f63e0', { female: false });
    rec += plant(hallW - 1.2, ry + 0.6);
    zone(ry, 'reception', rec);
    labels.push(text(hallW / 2, hy + 2.3, 0.6, 'Waiting hall', 'm-name'), text(5, ry + 2.6, 1.1, 'Reception', 'm-name'));
    anchors.reception = [hallW / 2, hy + 2.3, 1];
    }
    const frontY = showHall ? hy + 9 : opEnd;
    // Wards
    const wx = hallW ? hallW + 1.6 : 0, per = 6;
    let wy = 0, wardMaxW = 0;
    data.wards.forEach((ward) => {
      const n = Math.max(ward.beds.length, 1), cols = Math.min(per, Math.max(2, n)), rows = Math.ceil(n / per);
      const ww = 1.4 + cols * 2.9, wd = 1.2 + rows * 4.6, icu = /icu/i.test(ward.name), id = 'ward-' + ward.name;
      wardMaxW = Math.max(wardMaxW, ww);
      items.push({ id, kind: 'ward', ref: ward });
      zone(wx + wy - 0.5, id, room(wx, wy, ww, wd, { floor: icu ? '#f2f5fb' : COL.ward, tiles: true }));
      labels.push(text(wx + ww / 2, wy + wd, 0, ward.name, 'm-name', 16));
      anchors[id] = [wx + ww / 2, wy + wd / 2, 1];
      ward.beds.forEach((b, i) => {
        const bx = wx + 1.1 + (i % per) * 2.9, by = wy + 0.9 + Math.floor(i / per) * 4.6;
        const st = b.status === 'occupied' && b.discharge_ordered_at ? 'discharge' : b.status;
        const bid = 'bed-' + b.id;
        items.push({ id: bid, kind: 'bed', ref: b });
        let s = bed(bx, by, st, b.status === 'occupied', icu);
        if (i % per !== per - 1 && i < ward.beds.length - 1) s += box(bx + 2.2, by, 0, 0.06, 2.8, 1.7, '#9fc0f0', { op: 0.35, top: '#d8e6fc', stroke: 'rgba(47,99,224,.12)' });
        zone(bx + by + 0.3, bid, s);
        labels.push(text(bx + 0.8, by + 3.3, 0, b.label, 'm-bed', 10));
        anchors[bid] = [bx + 0.8, by + 1.5, 1];
      });
      wy += wd + 0.5;
    });
    // Nurses' station between the wards and the services
    const ns = Math.max(wy, 4) + 0.2;
    let nurse = room(wx, ns, Math.max(wardMaxW, 16), 3.4, { floor: '#f6f8fd', h: 0.6 });
    nurse += box(wx + 1, ns + 1, 0, 4, 0.9, 1, '#ffffff', { top: '#eaf0fe', left: '#eef3fb', right: '#dfe7f6' }) + person(wx + 3, ns + 0.6, 0, '#8fb0ef', { cap: true });
    nurse += '<g class="m-walk" style="--dx:70px;--dy:40px">' + person(wx + 7, ns + 1.6, 0, '#8fb0ef', { cap: true }) + '</g>';
    zone(wx + ns, null, nurse);
    labels.push(text(wx + 3, ns + 2.6, 1, 'Nurses\' station', 'm-name'));
    // Services row: lab, pharmacy, OT
    const sy = Math.max(frontY, ns + 3.6) + 0.4;
    const colW = Math.max(wardMaxW, 16), otW = Math.round(colW * 0.55);
    const services = showHall ? [['lab', 'Lab', 0, 7.4], ['pharmacy', 'Pharmacy', 7.9, hallW - 7.9], ['ot', 'Operation theatre', wx, otW], ['insurance', 'Insurance desk', wx + otW + 0.5, colW - otW - 0.5]]
      : [['ot', 'Operation theatre', wx, Math.min(colW, 12)]];
    services.forEach(([key, name, x, w]) => {
      items.push({ id: key, kind: key });
      let s = room(x, sy, w, 5.2, { tiles: true, floor: key === 'ot' ? '#eef6f3' : COL.floor });
      if (key === 'lab') { s += box(x + 0.8, sy + 0.6, 0, 5, 1, 0.95, '#ffffff', { top: '#eaf0fe' }); for (let i = 0; i < 3; i++) s += box(x + 1.2 + i * 1.5, sy + 0.8, 0.95, 0.35, 0.35, 0.5, '#2b3548'); s += person(x + 2.5, sy + 2.3, 0, '#3fae7a', { role: 'coat' }); }
      if (key === 'pharmacy') { s += shelf(x + 0.6, sy + 0.4, Math.min(w - 1.2, 5)) + box(x + 0.8, sy + 2.6, 0, Math.min(w - 1.6, 5), 0.9, 1.05, COL.blue, { top: '#ffffff' }) + person(x + 2.5, sy + 1.9, 0, '#3fae7a', { role: 'coat', female: false }); }
      if (key === 'insurance') {
        s += desk(x + 1, sy + 1.4, 2.4) + chair(x + 1.8, sy + 0.5) + person(x + 2.15, sy + 0.85, 0, '#8e6bd6', { sit: true, female: false });
        s += box(x + w - 1.4, sy + 0.5, 0, 0.9, 0.7, 1.6, '#9aa6bd', { top: '#c5cddc' }) + box(x + 1.2, sy + 1.55, 0.78, 0.8, 0.5, 0.12, '#ffffff', { top: '#ffffff' }) + chair(x + 1.8, sy + 2.6);
      }
      if (key === 'ot') {
        const busy = data.ot && data.ot.bookings.some((b) => b.status !== 'done');
        s += box(x + w / 2 - 1, sy + 1.2, 0, 2, 3.2, 0.85, '#9db0cf', { top: '#e7f3ee' });
        const lp = P(x + w / 2, sy + 2.8, 2.6);
        s += '<ellipse class="' + (busy ? 'm-glow' : '') + '" cx="' + f1(lp[0]) + '" cy="' + f1(lp[1]) + '" rx="13" ry="6" fill="#fff6c8" stroke="#e3c35a" stroke-width="1.2"/>';
        if (busy) s += person(x + w / 2 - 1.6, sy + 2.2, 0, '#3fae7a', { cap: true }) + person(x + w / 2 + 1.5, sy + 3.2, 0, '#3fae7a', { cap: true });
      }
      zone(x + sy, key, s);
      labels.push(text(x + w / 2, sy + 4.8, 0.2, name, 'm-name', 14));
      const c = data.counts[key];
      if (c) labels.push(pill(x + w / 2, sy + 2.6, 2.5, c.text, c.color));
      anchors[key] = [x + w / 2, sy + 2.6, 1];
    });
    const bEnd = sy + 5.4, bW = wx + colW;
    // Building floor slab and outer (blue) back walls
    zones.unshift({ key: -100, svg: box(-0.6, -0.6, -0.35, bW + 1.2, bEnd + 1.2, 0.35, '#c9d6ee', { top: '#e9eef8' }) +
      box(-0.6, -0.6, 0, 0.35, bEnd + 1.2, 2.9, COL.blue, { top: '#5b85ea' }) + box(-0.6, -0.6, 0, bW + 1.2, 0.35, 2.9, COL.blue, { top: '#5b85ea' }) });
    // Outside: lawn, road, entrance canopy, ambulance, cars, trees
    const ground = flat(-7, -7, -0.36, bW + 18, bEnd + 20, COL.grass) + flat(-7, bEnd + 4.5, -0.35, bW + 18, 4.2, COL.road) +
      (() => { let s = ''; for (let i = -6; i < bW + 10; i += 3) s += flat(i, bEnd + 6.45, -0.34, 1.6, 0.25, COL.line); return s; })() +
      flat(2, bEnd + 0.6, -0.34, 5, 3.9, '#e6eaf2');
    zones.unshift({ key: -200, svg: ground });
    zone(bEnd + 3, null, box(1.8, bEnd + 0.6, 1.9, 5.4, 2, 0.25, COL.blue, { top: '#5b85ea' }) + box(1.9, bEnd + 2.4, 0, 0.2, 0.2, 1.9, '#c7d0e0') + box(6.9, bEnd + 2.4, 0, 0.2, 0.2, 1.9, '#c7d0e0'));
    labels.push(text(4.5, bEnd + 1.6, 2.6, S.hospital || 'Hospital', 'm-sign'));
    zone(bEnd + 8, null, ambulance(8.5, bEnd + 0.8));
    ['#e05d5d', '#5b8def', '#e8eef7', '#4a5975', '#f0a33a'].forEach((c, i) => zone(bEnd + 10 + i, null, car(wx + 1 + i * 2.4, bEnd + 0.9, c)));
    zone(bEnd + 12, null, '<g class="m-walk slow" style="--dx:-120px;--dy:69px">' + person(bW - 2, bEnd + 3.2, 0, '#d6739f') + '</g>' +
      '<g class="m-walk" style="--dx:90px;--dy:-52px">' + person(10, bEnd + 3.8, 0, '#4a5975') + '</g>');
    [[-3.5, -2], [-3.5, 6], [-3.5, 14], [-3.5, 22], [6, -3.5], [16, -3.5], [26, -3.5], [bW - 2, -3.5], [bW + 3, 4], [bW + 3, 14], [-3, bEnd + 2]].forEach(([x, y], i) => zone(x + y + (y < 0 ? -50 : 0), null, tree(x, y, i % 3 === 0)));
    zones.sort((a, b) => a.key - b.key);
    const svg = zones.map((z) => '<g class="m-rise" style="--d:' + Math.min(900, (order++) * 18) + 'ms">' + z.svg + '</g>').join('') + '<g class="m-labels">' + labels.join('') + '</g>';
    return { items, svg, anchors, bounds: [P(-4.5, bEnd + 9, 0), P(bW + 4, -4.5, 0), P(-4.5, -4.5, 3), P(bW + 4, bEnd + 9, 0)] };
  }

  async function gather() {
    const tryApi = (path) => api('GET', path).catch(() => null);
    const [beds, dash, ot] = await Promise.all([tryApi('/api/beds'), has('today') ? tryApi('/api/dashboard') : null, has('ot') ? tryApi('/api/ot') : null]);
    const byWard = {};
    (beds ? beds.beds : []).forEach((b) => { (byWard[b.ward] = byWard[b.ward] || []).push(b); });
    const wards = Object.entries(byWard).map(([name, list]) => ({ name, beds: list }));
    const op = dash ? Object.fromEntries(dash.op.map((r) => [r.id, r])) : {};
    const depts = S.depts.map((d) => ({ id: d.id, code: d.code, name: d.name, doctors: S.doctors.filter((x) => x.dept_id === d.id),
      waiting: op[d.id] ? op[d.id].waiting + op[d.id].called : 0, seen: op[d.id] ? op[d.id].done : 0, total: op[d.id] ? op[d.id].total : 0 }));
    const m = dash ? dash.more : null;
    const counts = {};
    if (ot) { const n = ot.bookings.filter((b) => b.status !== 'done').length; if (n) counts.ot = { text: n + ' today', color: '#1f4fc4' }; }
    if (m && m.pharm.count) counts.pharmacy = { text: m.pharm.count + ' sales', color: '#172036' };
    const cf = m ? m.claimflow : (has('claims') ? await tryApi('/api/claims/summary') : null);
    if (cf) { const n = cf.due.length + cf.new.length; counts.insurance = { text: n ? n + ' to follow up' : (cf.statuses.submitted + cf.statuses.queried) + ' with insurers', color: n ? '#c0392b' : '#172036' }; }
    if (m && m.labs_open) counts.lab = { text: m.labs_open + ' awaited', color: m.critical_labs.length ? '#c0392b' : '#172036' };
    return { wards, depts, dash, m, ot, counts, cf, waitingTotal: depts.reduce((a, d) => a + d.waiting, 0), bedsTotal: beds ? beds.beds.length : 0 };
  }

  // Short facts for the big callout on the map
  function callout(item, data) {
    if (!item) return null;
    if (item.kind === 'bed') {
      const b = item.ref;
      if (b.status !== 'occupied') return { title: 'Bed ' + b.label, big: BED_STATUS[b.status], sub: b.ward };
      const stay = Math.floor((Date.now() - new Date(b.admitted_at)) / 86400000) + 1;
      return { title: 'Bed ' + b.label + (b.patient ? ' · ' + b.patient : ''), big: 'Day ' + stay, sub: [b.diagnosis, b.doctor].filter(Boolean).join(' · ') };
    }
    if (item.kind === 'dept') {
      const d = item.ref, doc = d.doctors.find((x) => x.status === 'in') || d.doctors[0];
      return { title: (doc ? shortName(doc.name) + ' · ' : '') + d.name, big: d.waiting + ' waiting', sub: (doc ? DOC_STATUS[doc.status] + ' · ' : '') + d.seen + ' seen · ' + d.total + ' today' };
    }
    if (item.kind === 'insurance') {
      const c = data.cf; if (!c) return { title: 'Insurance desk', big: '', sub: '' };
      return { title: 'Insurance desk', big: (c.due.length + c.new.length) + ' to follow up', sub: c.today.submitted + ' submitted · ' + c.today.followups + ' follow-ups today' };
    }
    if (item.kind === 'ward') { const w = item.ref, o = w.beds.filter((b) => b.status === 'occupied').length; return { title: w.name, big: o + ' / ' + w.beds.length, sub: 'beds occupied' }; }
    if (item.kind === 'reception') return { title: 'Waiting hall', big: data.waitingTotal + ' waiting', sub: data.dash ? data.dash.appointments.pending + ' phone bookings to come' : '' };
    if (item.kind === 'ot') { const l = data.ot ? data.ot.bookings : []; return { title: 'Operation theatre', big: l.length + ' today', sub: l.filter((b) => b.status === 'done').length + ' done' }; }
    if (item.kind === 'pharmacy') return { title: 'Pharmacy', big: data.m ? '₹' + Math.round(data.m.pharm.counter).toLocaleString('en-IN') : '', sub: data.m ? data.m.pharm.count + ' sales today' : '' };
    if (item.kind === 'lab') return { title: 'Lab', big: data.m ? data.m.labs_open + ' awaited' : '', sub: data.m && data.m.critical_labs.length ? data.m.critical_labs.length + ' critical' : 'reports' };
    return null;
  }

  // Right-hand details for whatever was clicked
  function details(item, data, opts) {
    const money = (n) => '₹' + Math.round(n || 0).toLocaleString('en-IN');
    const row = (k, v) => v || v === 0 ? h('div', { class: 'md-row' }, h('span', {}, k), h('strong', {}, v)) : null;
    const link = (href, text2, screen) => (!screen || has(screen)) && h('a', { class: 'btn primary', href }, text2);
    if (!item) {
      const d = data.dash, occ = data.wards.reduce((a, w) => a + w.beds.filter((b) => b.status === 'occupied').length, 0);
      return [h('div', { class: 'md-kicker' }, h('span', { class: 'live-dot' }), 'Hospital · live'), h('h3', {}, S.hospital), h('div', { class: 'md-sub' }, S.address),
        h('div', { class: 'md-bar' }, h('span', { style: 'width:' + (data.bedsTotal ? Math.round(occ / data.bedsTotal * 100) : 0) + '%' })),
        row('Beds occupied', occ + ' / ' + data.bedsTotal), d && row('OP patients today', d.op.reduce((a, r) => a + r.total, 0)), d && row('Waiting now', data.waitingTotal),
        data.m && row('Inpatient money today', money(data.m.ip_money.collected)), data.m && row('Pharmacy counter', money(data.m.pharm.counter)),
        h('p', { class: 'muted' }, (data.scope === 'ward' ? 'Tap a bed or ward' : 'Tap a bed, a room or a desk') + ' to zoom in and see it live.')];
    }
    if (item.kind === 'bed') {
      const b = item.ref, stay = b.admitted_at ? Math.floor((Date.now() - new Date(b.admitted_at)) / 86400000) + 1 : null;
      return [h('div', { class: 'md-kicker' }, b.ward + ' · bed ' + b.label), h('h3', {}, b.status === 'occupied' ? (b.patient || 'Occupied') : BED_STATUS[b.status]),
        b.status === 'occupied' ? [row('Age', b.age), row('Doctor', b.doctor), row('Day of stay', stay), row('Diagnosis', b.diagnosis), row('Scheme / cash', b.payer),
          b.discharge_ordered_at && h('div', { class: 'tag warn' }, 'Discharge ordered')] : b.note ? h('p', {}, b.note) : null,
        h('div', { class: 'actions' }, b.admission_id && link('#ip/' + b.admission_id, 'Open chart', 'chart'), b.admission_id && link('#bill/' + b.admission_id, 'Bill', 'ipbill'),
          opts.onBed ? h('button', { class: 'btn', onclick: () => opts.onBed(b) }, b.status === 'occupied' ? 'Bed options' : 'Admit or change bed') : b.status !== 'occupied' && link('#beds', 'Admit or change', 'admit'))];
    }
    if (item.kind === 'dept') {
      const d = item.ref;
      return [h('div', { class: 'md-kicker' }, 'OP · ' + d.code), h('h3', {}, d.name), row('Waiting', d.waiting), row('Seen today', d.seen), row('Total today', d.total),
        d.doctors.map((x) => h('div', { class: 'md-row' }, h('span', {}, x.name), h('strong', { class: 'state ' + x.status }, DOC_STATUS[x.status]))),
        h('div', { class: 'actions' }, link('#queue', 'Open queue', 'queue'))];
    }
    if (item.kind === 'ward') {
      const w = item.ref, c = (s) => w.beds.filter((b) => b.status === s).length;
      return [h('div', { class: 'md-kicker' }, 'Ward'), h('h3', {}, w.name), row('Beds', w.beds.length), row('Occupied', c('occupied')), row('Vacant', c('vacant')), row('Being cleaned', c('cleaning')), row('Reserved', c('reserved')),
        h('div', { class: 'actions' }, link('#ward', 'Ward duty', 'ward'), link('#beds', 'Bed list', 'beds'))];
    }
    if (item.kind === 'reception') {
      const d = data.dash;
      return [h('div', { class: 'md-kicker' }, 'Front desk'), h('h3', {}, 'Reception and waiting hall'), row('Waiting in the hall', data.waitingTotal),
        d && row('Phone bookings still to come', d.appointments.pending), d && row('Not yet entered in Essel', d.essel_pending),
        h('div', { class: 'actions' }, link('#desk', 'OP Desk', 'desk'), link('#appointments', 'Phone bookings', 'appointments'))];
    }
    if (item.kind === 'ot') {
      const list = data.ot ? data.ot.bookings : [];
      return [h('div', { class: 'md-kicker' }, 'Today'), h('h3', {}, 'Operation theatre'),
        list.length ? list.map((o) => h('div', { class: 'md-row' }, h('span', {}, o.start_time + ' ' + o.patient_name), h('strong', {}, o.status === 'done' ? 'Done' : o.checklist.length + '/6 ready'))) : h('p', { class: 'muted' }, 'No operations today.'),
        h('div', { class: 'actions' }, link('#ot', 'Open OT', 'ot'))];
    }
    if (item.kind === 'pharmacy') {
      const m = data.m;
      return [h('div', { class: 'md-kicker' }, 'Today'), h('h3', {}, 'Pharmacy'), m && row('Counter sales', m.pharm.count), m && row('Received', money(m.pharm.counter)),
        m && row('To inpatient bills', money(m.pharm.to_ip_bills)), m && row('Not in Pharmasoft yet', m.pharm.pending),
        m && row('Stock', m.pharmacy.expired + ' expired · ' + m.pharmacy.low + ' low'), h('div', { class: 'actions' }, link('#pharmsale', 'Counter', 'pharmsale'), link('#pharmacy', 'Stock alerts', 'pharmacy'))];
    }
    if (item.kind === 'insurance') {
      const c = data.cf;
      return [h('div', { class: 'md-kicker' }, 'Today'), h('h3', {}, 'Insurance desk'),
        c ? [row('Claims submitted to insurers', c.today.submitted), row('Documents attached', c.today.docs), row('Follow-ups done', c.today.followups),
          row('New from inpatients', c.new.length), row('Follow-ups due', c.due.length), row('No update 7+ days', c.stale.length), row('Pending with insurers', money(c.pending_amount))] : h('p', { class: 'muted' }, 'No access to claims.'),
        h('div', { class: 'actions' }, link('#claims', 'Open claims', 'claims'))];
    }
    if (item.kind === 'lab') {
      const m = data.m;
      return [h('div', { class: 'md-kicker' }, 'Today'), h('h3', {}, 'Lab'), m && row('Reports awaited', m.labs_open),
        m && m.critical_labs.map((x) => h('div', { class: 'tag bad' }, 'CRITICAL: ' + x.name + ' — ' + x.test)), h('div', { class: 'actions' }, link('#lab', 'Open lab', 'lab'))];
    }
    return null;
  }

  const ICONS = {
    bed: '<path d="M2 14V6m0 5h16v3M5 10a2 2 0 1 1 0-.1M8 9h8a2 2 0 0 1 2 2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    op: '<circle cx="10" cy="6" r="3" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M4 17c0-3.3 2.7-6 6-6s6 2.7 6 6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    wait: '<circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M10 6v4l3 2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
  };
  const reduced = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  window.HospitalMap = function (host, opts) {
    opts = opts || {};
    let introDone = false;
    try { introDone = sessionStorage.getItem('hm_intro_done') === '1'; } catch (e) { /* ignore */ }
    const state = { sel: null, k: 1, tx: 0, ty: 0, data: null, items: [], anchors: {}, first: !introDone };
    // Whole hospital only for logins with the Hospital overview (the founder doctors); anyone else a small part, never all.
    const scope = opts.scope || ((S.me.screens || []).includes('today') ? 'full' : DOCS.includes(S.me.role) ? 'doctor' : 'ward');
    const svgWrap = h('div', { class: 'hm-canvas', tabindex: '0', 'aria-label': 'Hospital map. The panel beside it lists the same information as text.' });
    const panel = h('aside', { class: 'hm-panel', 'aria-live': 'polite' });
    const kpis = h('div', { class: 'hm-kpis' });
    const bubble = h('div', { class: 'hm-callout', hidden: true });
    let g = null, anim = null;
    const apply = () => { if (g) g.setAttribute('transform', 'translate(' + f1(state.tx) + ' ' + f1(state.ty) + ') scale(' + state.k.toFixed(3) + ')'); placeBubble(); };
    const animateTo = (k, tx, ty) => {
      if (anim) cancelAnimationFrame(anim);
      if (reduced()) { state.k = k; state.tx = tx; state.ty = ty; apply(); return; }
      const s0 = { k: state.k, tx: state.tx, ty: state.ty }, t0 = performance.now(), dur = 520;
      const step = (now) => {
        const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
        state.k = s0.k + (k - s0.k) * e; state.tx = s0.tx + (tx - s0.tx) * e; state.ty = s0.ty + (ty - s0.ty) * e; apply();
        if (p < 1) anim = requestAnimationFrame(step);
      };
      anim = requestAnimationFrame(step);
    };
    const zoom = (f) => {
      const svg = svgWrap.querySelector('svg'); if (!svg) return;
      const vb = svg.viewBox.baseVal, a = state.sel && state.anchors[state.sel];
      let cx = vb.x + vb.width / 2, cy = vb.y + vb.height / 2;
      if (a) { const p = P(a[0], a[1], a[2]); cx = p[0] * state.k + state.tx; cy = p[1] * state.k + state.ty; }   // zoom around the selected place
      const k = Math.min(3.2, Math.max(0.6, state.k * f));
      animateTo(k, cx - (cx - state.tx) * k / state.k, cy - (cy - state.ty) * k / state.k);
    };
    const focusOn = (id) => {
      const a = state.anchors[id], svg = svgWrap.querySelector('svg');
      if (!a || !svg) return;
      const p = P(a[0], a[1], a[2]), vb = svg.viewBox.baseVal, k = id.startsWith('bed-') ? 2.2 : 1.7;
      animateTo(k, vb.x + vb.width * 0.5 - p[0] * k, vb.y + vb.height * 0.64 - p[1] * k);
    };
    function placeBubble() {
      const item = state.items.find((i) => i.id === state.sel), info = callout(item, state.data), a = state.anchors[state.sel], svg = svgWrap.querySelector('svg');
      if (!info || !a || !svg) { bubble.hidden = true; return; }
      const p = P(a[0], a[1], a[2]), pt = svg.createSVGPoint();
      pt.x = p[0] * state.k + state.tx; pt.y = p[1] * state.k + state.ty;
      const m = svg.getScreenCTM(), sp = pt.matrixTransform(m), box2 = svgWrap.getBoundingClientRect();
      bubble.hidden = false;
      bubble.replaceChildren(h('div', { class: 'hc-title' }, info.title), h('div', { class: 'hc-big' }, info.big), info.sub && h('div', { class: 'hc-sub' }, info.sub));
      bubble.style.left = Math.max(8, Math.min(box2.width - 230, sp.x - box2.left - 110)) + 'px';
      bubble.style.top = Math.max(8, sp.y - box2.top - 118) + 'px';
    }
    const controls = h('div', { class: 'hm-ctrl' }, h('button', { type: 'button', 'aria-label': 'Zoom in', onclick: () => zoom(1.25) }, '+'),
      h('button', { type: 'button', 'aria-label': 'Zoom out', onclick: () => zoom(1 / 1.25) }, '−'),
      h('button', { type: 'button', 'aria-label': 'Show whole hospital', onclick: () => { state.sel = null; paint(); animateTo(1, 0, 0); } }, '⟲'));
    const legend = h('div', { class: 'hm-legend' }, [['vacant', 'Vacant'], ['occupied', 'Occupied'], ['discharge', 'Discharge / cleaning'], ['reserved', 'Reserved']].map(([k, l]) =>
      h('span', {}, h('i', { style: 'background:' + COL[k] }), l)), h('span', {}, h('i', { style: 'background:' + COL.in + ';border-radius:50%' }), 'Doctor in'));
    const tip = h('div', { class: 'hm-tip', hidden: true });
    host.replaceChildren(h('div', { class: 'hm' }, h('div', { class: 'hm-stage' }, svgWrap, kpis, bubble, tip, controls, legend), panel));
    svgWrap.addEventListener('pointermove', (e) => {
      if (drag && moved) { tip.hidden = true; return; }
      const hit = e.target.closest && e.target.closest('[data-id]');
      const id = hit && hit.getAttribute('data-id');
      const item = id && id !== state.sel ? state.items.find((i) => i.id === id) : null, info = item && callout(item, state.data);
      if (!info) { tip.hidden = true; return; }
      const r0 = svgWrap.getBoundingClientRect();
      tip.replaceChildren(h('strong', {}, info.title), h('span', {}, [info.big, info.sub].filter(Boolean).join(' · ')));
      tip.hidden = false;
      tip.style.left = Math.min(r0.width - 250, e.clientX - r0.left + 14) + 'px';
      tip.style.top = Math.max(6, e.clientY - r0.top - 52) + 'px';
    });
    svgWrap.addEventListener('pointerleave', () => { tip.hidden = true; });
    const paint = () => {
      const built = layout(state.data);
      state.items = built.items; state.anchors = built.anchors;
      const b = built.bounds, xs = b.map((p) => p[0]), ys = b.map((p) => p[1]);
      const vb = [Math.min(...xs) - 10, Math.min(...ys) - 80, Math.max(...xs) - Math.min(...xs) + 20, Math.max(...ys) - Math.min(...ys) + 100];
      svgWrap.innerHTML = '<svg viewBox="' + vb.map(f1).join(' ') + '" role="img" aria-label="Hospital map" class="' + (state.first && !reduced() ? 'hm-intro' : '') + '"><g class="hm-g">' + built.svg + '</g></svg>';
      g = svgWrap.querySelector('.hm-g');
      if (state.sel) svgWrap.querySelectorAll('[data-id="' + CSS.escape(state.sel) + '"]').forEach((el) => el.classList.add('sel'));
      if (state.first) { state.first = false; try { sessionStorage.setItem('hm_intro_done', '1'); } catch (e) { /* ignore */ } setTimeout(() => { const s = svgWrap.querySelector('svg'); if (s) s.classList.remove('hm-intro'); }, 2200); }
      apply();
      const d = state.data.dash, occ = state.data.wards.reduce((a, w) => a + w.beds.filter((x) => x.status === 'occupied').length, 0);
      const kpi = (icon, value, labelText) => {
        const ic = h('span', { class: 'hm-ic' });
        ic.innerHTML = '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">' + ICONS[icon] + '</svg>';
        return h('div', { class: 'hm-kpi' }, ic, h('div', {}, h('strong', {}, value), h('small', {}, labelText)));
      };
      kpis.replaceChildren(kpi('bed', occ + ' / ' + state.data.bedsTotal, 'beds occupied'), d && kpi('op', d.op.reduce((a, r) => a + r.total, 0), 'OP patients today'),
        d && kpi('wait', state.data.waitingTotal, 'waiting now'));
      const item = state.items.find((i) => i.id === state.sel) || null;
      panel.replaceChildren(item && h('button', { class: 'btn quiet hm-back', onclick: () => { state.sel = null; paint(); animateTo(1, 0, 0); } }, '← Whole hospital'), details(item, state.data, opts));
      if (window.animateNumbers) window.animateNumbers(host);
    };
    // Click to select (zooms in), drag to move, ctrl/cmd + wheel to zoom
    let drag = null, moved = false;
    svgWrap.addEventListener('pointerdown', (e) => { drag = { x: e.clientX, y: e.clientY, tx: state.tx, ty: state.ty }; moved = false; });
    svgWrap.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) { moved = true; const svg = svgWrap.querySelector('svg'); const r = svg.viewBox.baseVal.width / svg.clientWidth; state.tx = drag.tx + dx * r; state.ty = drag.ty + dy * r; apply(); }
    });
    const end = () => { drag = null; };
    svgWrap.addEventListener('pointerup', end); svgWrap.addEventListener('pointerleave', end);
    svgWrap.addEventListener('click', (e) => {
      if (moved) return;
      const hit = e.target.closest('[data-id]');
      state.sel = hit ? hit.getAttribute('data-id') : null;
      paint();
      if (state.sel) focusOn(state.sel); else animateTo(1, 0, 0);
      if (hit && window.innerWidth < 900) setTimeout(() => panel.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'nearest' }), 550);
    });
    svgWrap.addEventListener('wheel', (e) => { if (!e.ctrlKey && !e.metaKey) return; e.preventDefault(); zoom(e.deltaY < 0 ? 1.12 : 1 / 1.12); }, { passive: false });
    window.addEventListener('resize', placeBubble);
    return { async load() { state.data = await gather(); state.data.scope = scope; paint(); } };
  };
})();
