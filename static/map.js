/* Tube Sim map UI. Vanilla JS, no build step. */

const svg = document.getElementById("map");
const viewport = document.getElementById("viewport");
const tooltip = document.getElementById("tooltip");

let STATE = null; // {stations: [...], lines: [...]}
const byId = new Map();

const layerVisible = { tube: true, overground: false, dlr: false, "elizabeth-line": false, rail: true };
const LINE_MODE = new Map();

// ---- projection ----------------------------------------------------------

let PROJ = null; // {minLon, maxLat, cosLat0, k}

function project(lat, lon) {
  return {
    x: (lon - PROJ.minLon) * PROJ.cosLat0 * PROJ.k,
    y: (PROJ.maxLat - lat) * PROJ.k,
  };
}

function projectAll() {
  const lats = STATE.stations.map(s => s.lat);
  const lons = STATE.stations.map(s => s.lon);
  const lat0 = (Math.min(...lats) + Math.max(...lats)) / 2;
  PROJ = {
    minLon: Math.min(...lons),
    maxLat: Math.max(...lats),
    cosLat0: Math.cos(lat0 * Math.PI / 180),
    k: 100000,
  };
  for (const s of STATE.stations) {
    const p = project(s.lat, s.lon);
    s.x = p.x;
    s.y = p.y;
  }
  // frame Greater London (zones 1-6); the far-out Elizabeth/Metropolitan stations stay reachable by panning
  const core = STATE.stations.filter(s => { const z = parseInt(s.zone, 10); return z >= 1 && z <= 6; });
  const framed = core.length > 50 ? core : STATE.stations;
  const xs = framed.map(s => s.x);
  const ys = framed.map(s => s.y);
  const pad = 1500;
  return {
    x: Math.min(...xs) - pad,
    y: Math.min(...ys) - pad,
    w: Math.max(...xs) - Math.min(...xs) + 2 * pad,
    h: Math.max(...ys) - Math.min(...ys) + 2 * pad + 4500, // extra room at the bottom for the time bar
  };
}

let vb; // current viewBox {x, y, w, h}

const LOD_FULL_WIDTH = 55000; // hide minor stations when showing more than this

function applyViewBox() {
  svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
  updateLod();
  updateMarkerSizes();
}

// keep markers a constant size on screen: radius in viewBox units must
// shrink as you zoom in, so clustered stations stay delineated dots
function updateMarkerSizes() {
  if (!STATE) return;
  const scale = vb.w / svgWidth(); // viewBox units per CSS px
  // Fixed viewBox radius: on screen dots shrink at the same rate as the
  // lines when zooming out. Once zoomed in past rFixed/rPx, the screen-size
  // floor takes over so dense clusters stay delineated. Fixed radii are
  // 0.5-0.7x the line width, so the 1.2x cap is never reached (and the
  // river, not being a line, plays no part here).
  for (const s of STATE.stations) {
    if (!s.dotEl) continue;
    const r = Math.max(s.rFixed, s.rPx * scale);
    s.dotEl.setAttribute("r", r);
    s.haloEl.setAttribute("r", r + 9 * scale);
  }
  if (RAIL) for (const s of RAIL.list) s.dotEl.setAttribute("r", Math.max(32, 1.7 * scale));
}

function updateLod() {
  const showMinor = vb.w <= LOD_FULL_WIDTH;
  for (const s of STATE.stations) {
    if (s.interchange || !s.el) continue;
    s.el.style.opacity = showMinor ? "1" : "0";
    s.el.style.pointerEvents = showMinor ? "" : "none";
  }
}

function svgPoint(evt) {
  const pt = svg.createSVGPoint();
  pt.x = evt.clientX;
  pt.y = evt.clientY;
  return pt.matrixTransform(svg.getScreenCTM().inverse());
}

// ---- rendering -----------------------------------------------------------

const SVGNS = "http://www.w3.org/2000/svg";

// on-screen width of the map in CSS px (clientWidth is unreliable on an outer <svg>)
const svgWidth = () => svg.getBoundingClientRect().width || 1;

function el(tag, attrs = {}) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

function renderMap() {
  const gEdges = document.getElementById("edges");
  const gStations = document.getElementById("stations");

  for (const line of STATE.lines) {
    const g = el("g", { "data-line": line.id, "data-mode": line.mode });
    for (const [a, b] of line.edges) {
      const sa = byId.get(a), sb = byId.get(b);
      g.appendChild(el("line", {
        class: "edge",
        x1: sa.x, y1: sa.y, x2: sb.x, y2: sb.y,
        stroke: line.color,
        "stroke-width": line.mode === "tube" ? 150 : 130,
      }));
    }
    gEdges.appendChild(g);
  }

  for (const s of STATE.stations) {
    const g = el("g", { class: "station" + (s.interchange ? " interchange" : ""), "data-id": s.id });
    const halo = el("circle", { class: "halo", cx: s.x, cy: s.y, r: 500 });
    const dot = el("circle", { class: "dot", cx: s.x, cy: s.y, r: 300 });
    g.appendChild(halo);
    g.appendChild(dot);
    g.addEventListener("click", ev => { ev.stopPropagation(); onStationClick(s.id); });
    g.addEventListener("mousemove", ev => showTooltip(s, ev));
    g.addEventListener("mouseleave", hideTooltip);
    gStations.appendChild(g);
    s.el = g;
    s.haloEl = halo;
    s.dotEl = dot;
    s.rPx = s.interchange ? 4.2 : 2.6;   // screen-size floor when zoomed in
    s.rFixed = s.interchange ? 75 : 55;  // viewBox size: shrinks with zoom like lines
  }
  applyLayers();
  updateMarkerSizes();
}

function applyLayers() {
  document.querySelectorAll("#edges g[data-line]").forEach(g => {
    g.style.display = layerVisible[g.dataset.mode] ? "" : "none";
  });
  document.getElementById("river").style.display = riverVisible ? "" : "none";
  for (const id of ["rail-edges", "rail-stations"]) document.getElementById(id).style.display = layerVisible.rail ? "" : "none";
  for (const s of STATE.stations) {
    // with history loaded, only the lines serving the station at the chosen date count
    const lines = s.activeLines ? [...s.activeLines] : s.lines;
    const vis = lines.some(lid => layerVisible[LINE_MODE.get(lid)]);
    s.el.style.display = vis ? "" : "none";
  }
}

let riverVisible = true;

function renderRiver(parts) {
  const g = document.getElementById("river");
  for (const part of parts) {
    const pts = part.map(([lat, lon]) => {
      const p = project(lat, lon);
      return `${p.x},${p.y}`;
    }).join(" ");
    g.appendChild(el("polyline", { class: "river-bank", points: pts }));
  }
  for (const part of parts) {
    const pts = part.map(([lat, lon]) => {
      const p = project(lat, lon);
      return `${p.x},${p.y}`;
    }).join(" ");
    g.appendChild(el("polyline", { class: "river-fill", points: pts }));
  }
}

function showTooltip(s, ev) {
  tooltip.hidden = false;
  tooltip.textContent = s.name + (s.interchange ? " (interchange)" : "");
  tooltip.style.left = ev.clientX + 12 + "px";
  tooltip.style.top = ev.clientY - 8 + "px";
}
function hideTooltip() { tooltip.hidden = true; }

// ---- route drawing -------------------------------------------------------

function clearRoutes() {
  document.getElementById("routes").replaceChildren();
  document.getElementById("markers").replaceChildren();
}

// Flatten legs into one ordered station list (legs share endpoints).
function flattenPath(legs) {
  const out = [];
  for (const leg of legs) {
    for (const id of leg.path) {
      if (out.length && out[out.length - 1] === id) continue;
      out.push(id);
    }
  }
  return out;
}

function drawLegs(legs, opts = {}) {
  clearRoutes();
  const g = document.getElementById("routes");
  const gMark = document.getElementById("markers");

  // casing + coloured leg segments
  for (const leg of legs) {
    const pts = leg.path.map(id => { const s = byId.get(id); return `${s.x},${s.y}`; }).join(" ");
    g.appendChild(el("polyline", {
      class: "route-line", points: pts, stroke: "#0a0e12", "stroke-width": 680,
    }));
  }
  for (const leg of legs) {
    const pts = leg.path.map(id => { const s = byId.get(id); return `${s.x},${s.y}`; }).join(" ");
    g.appendChild(el("polyline", {
      class: "route-line", points: pts, stroke: leg.color, "stroke-width": 400,
    }));
  }

  // animated flow overlay along the whole run (shows direction & continuity)
  const flat = flattenPath(legs);
  const flowPts = flat.map(id => { const s = byId.get(id); return `${s.x},${s.y}`; }).join(" ");
  g.appendChild(el("polyline", { class: "route-flow", points: flowPts }));

  // station name labels: everything on short routes, key stops on long ones
  const labelAll = flat.length <= 26;
  const labelled = new Set();
  flat.forEach((id, i) => {
    const isLegEnd = legs.some(l => l.path[l.path.length - 1] === id);
    if (!labelAll && !(i === 0 || i === flat.length - 1 || isLegEnd)) return;
    if (labelled.has(id)) return;
    labelled.add(id);
    const s = byId.get(id);
    const t = el("text", { class: "route-label", x: s.x, y: s.y - 330 });
    t.textContent = s.name;
    gMark.appendChild(t);
  });

  // numbered badges at each leg's alighting station
  legs.forEach((leg, i) => {
    const end = byId.get(leg.path[leg.path.length - 1]);
    const badge = el("g", { class: "leg-badge" });
    badge.appendChild(el("circle", { cx: end.x, cy: end.y, r: 300 }));
    const t = el("text", { x: end.x, y: end.y + 85 });
    t.textContent = i + 1;
    badge.appendChild(t);
    gMark.appendChild(badge);
  });

  // A/B endpoints (journey mode)
  if (opts.endpoints) {
    const a = byId.get(flat[0]), b = byId.get(flat[flat.length - 1]);
    const mk = (s, txt, fill) => {
      const g2 = el("g", { class: "endpoint-badge" });
      g2.appendChild(el("circle", { cx: s.x, cy: s.y, r: 360, fill, stroke: "#11151a", "stroke-width": 60 }));
      const t = el("text", { x: s.x, y: s.y + 105, fill: "#11151a" });
      t.textContent = txt;
      g2.appendChild(t);
      gMark.appendChild(g2);
    };
    mk(a, "A", "#2ecc71");
    mk(b, "B", "#e74c3c");
  }
}

// ---- journey mode --------------------------------------------------------

let selA = null, selB = null;

function onStationClick(id) {
  if (currentMode !== "journey") return;
  if (selA && selB) { selA = null; selB = null; }
  if (!selA) selA = id; else selB = id;
  updateSelection();
}

function updateSelection() {
  for (const s of STATE.stations) {
    s.el.classList.toggle("selected-a", s.id === selA);
    s.el.classList.toggle("selected-b", s.id === selB);
  }
  const box = document.getElementById("journey-selection");
  box.replaceChildren();
  const res = document.getElementById("journey-result");
  res.replaceChildren();
  const name = id => byId.get(id).name;
  if (selA) box.appendChild(node("div", "sel", [node("b", "", "A: "), document.createTextNode(name(selA))]));
  if (selB) box.appendChild(node("div", "sel", [node("b", "", "B: "), document.createTextNode(name(selB))]));
  if (selA && selB) {
    fetch(`/api/route?from=${encodeURIComponent(selA)}&to=${encodeURIComponent(selB)}${dateParam()}`)
      .then(r => r.json())
      .then(data => {
        if (data.error) { clearRoutes(); res.textContent = data.error; return; }
        drawLegs(data.legs, { endpoints: true });
        res.appendChild(renderTotals(data.totals));
        res.appendChild(renderLegList(data.legs));
      });
  } else {
    clearRoutes();
  }
}

// ---- challenge mode ------------------------------------------------------

function runChallenge() {
  const btn = document.getElementById("ch-solve");
  const status = document.getElementById("challenge-status");
  const res = document.getElementById("challenge-result");
  const objective = document.getElementById("ch-objective").value;
  const rule = document.getElementById("ch-rule").value;
  const budget = Number(document.getElementById("ch-budget").value);
  const includeModes = [...document.querySelectorAll("#ch-modes input:checked")].map(i => i.value);
  btn.disabled = true;
  res.replaceChildren();
  status.textContent = `Solving (up to ${budget}s)…`;
  fetch("/api/challenge/solve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ objective, rule, budget_seconds: budget, include_modes: includeModes, date: dateOrNull() }),
  })
    .then(r => r.json())
    .then(data => {
      btn.disabled = false;
      if (data.error) { status.textContent = data.error; return; }
      if (!data.solved) { status.textContent = "No complete run found — try a longer think time."; return; }
      status.textContent =
        `Solved in ${data.seconds}s — covering ${data.lines_to_cover} lines (${data.objective}, ${data.rule}).`;
      drawLegs(data.legs);
      res.appendChild(renderTotals(data.totals));
      res.appendChild(renderCoverage(data.lines_covered));
      res.appendChild(renderLegList(data.legs));
    })
    .catch(err => { btn.disabled = false; status.textContent = "Request failed: " + err; });
}

function renderCoverage(covered) {
  const wrap = node("div", "coverage", []);
  const linesById = new Map(STATE.lines.map(l => [l.id, l]));
  for (const lid of covered) {
    const l = linesById.get(lid);
    const chip = node("span", "line-chip", [document.createTextNode(l.name)]);
    chip.style.background = l.color;
    if (["northern", "piccadilly", "weaver", "elizabeth", "mildmay", "suffragette", "dlr"].includes(lid)) {
      chip.style.color = "#e8edf2";
    }
    wrap.appendChild(chip);
  }
  return wrap;
}

// the date the slider is on, or null for "today" (so the server uses today's network)
function dateOrNull() { return HIST && curISO < "2025-12-31" ? curISO : null; }
function dateParam() { const d = dateOrNull(); return d ? `&date=${d}` : ""; }

function updateCoverCount() {
  const ids = ACTIVE_LINE_IDS || new Set(STATE.lines.map(l => l.id)); // lines running on the chosen date
  const modeOf = id => LINE_MODE.get(id);
  const wanted = new Set(["tube", ...[...document.querySelectorAll("#ch-modes input:checked")].map(i => i.value)]);
  const n = [...ids].filter(id => wanted.has(modeOf(id))).length;
  document.getElementById("ch-cover-count").textContent = n ? `Covering ${n} line${n === 1 ? "" : "s"}` : "No lines to cover on this date";
}

// ---- shared little builders ----------------------------------------------

function node(tag, cls, children) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  // children is a list of nodes and/or strings; a bare string is one text child (the old code looped over its characters and threw)
  for (const c of [].concat(children)) e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  return e;
}

function renderTotals(t) {
  const parts = [];
  const add = (label, v) => parts.push(document.createTextNode(`${label} ${v} `));
  if (t.minutes != null) add("⏱", fmtMinutes(t.minutes));
  if (t.km != null) add("📏", t.km + " km");
  if (t.stops != null) add("stops", t.stops);
  if (t.hops != null) add("hops", t.hops);
  if (t.stops_made != null) add("stops made", t.stops_made);
  if (t.transfers != null) add("changes", t.transfers);
  return node("div", "totals", parts);
}

function fmtMinutes(m) {
  const h = Math.floor(m / 60), mm = Math.round(m % 60);
  return h ? `${h}h ${mm}m` : `${mm} min`;
}

function renderLegList(legs) {
  const wrap = node("div", "legs", []);
  legs.forEach((leg, i) => {
    const row = node("div", "leg", []);
    const chip = node("span", "chip", []);
    chip.style.background = leg.color;
    row.appendChild(node("span", "n", [document.createTextNode(`${i + 1}.`)]));
    row.appendChild(chip);
    row.appendChild(document.createTextNode(
      `${leg.line_name}: ${leg.from_name} → ${leg.to_name} (${leg.stops})`
    ));
    wrap.appendChild(row);
  });
  return wrap;
}

// ---- mode tabs, layers, search, pan/zoom ----------------------------------

let currentMode = "journey";

document.querySelectorAll("#mode-tabs .tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#mode-tabs .tab").forEach(b => b.classList.toggle("active", b === btn));
    currentMode = btn.dataset.mode;
    document.getElementById("journey-ui").hidden = currentMode !== "journey";
    document.getElementById("challenge-ui").hidden = currentMode !== "challenge";
    if (currentMode === "challenge") clearRoutes();
  });
});

document.getElementById("ch-solve").addEventListener("click", runChallenge);
document.getElementById("ch-budget").addEventListener("input", e => {
  document.getElementById("budget-label").textContent = e.target.value + "s";
});
document.querySelectorAll("#ch-modes input").forEach(i =>
  i.addEventListener("change", updateCoverCount));

document.querySelectorAll("[data-mode-layer]").forEach(i => {
  i.addEventListener("change", () => {
    layerVisible[i.dataset.modeLayer] = i.checked;
    applyLayers();
  });
});
document.getElementById("rail-layer").addEventListener("change", e => {
  layerVisible.rail = e.target.checked;
  applyLayers();
  if (HIST) applyDate(curISO);
});
document.getElementById("river-layer").addEventListener("change", e => {
  riverVisible = e.target.checked;
  applyLayers();
});

document.getElementById("station-search").addEventListener("input", e => {
  const q = e.target.value.trim().toLowerCase();
  const box = document.getElementById("search-results");
  box.replaceChildren();
  if (q.length < 2) return;
  const hits = STATE.stations
    .filter(s => (!s.activeLines || s.activeLines.size) && s.name.toLowerCase().includes(q)) // only stations open on the chosen date
    .slice(0, 12);
  for (const s of hits) {
    const row = node("div", "", [document.createTextNode(s.name)]);
    row.addEventListener("click", () => {
      box.replaceChildren();
      document.getElementById("station-search").value = "";
      onStationClick(s.id);
    });
    box.appendChild(row);
  }
});

// marker sizes depend on the map's on-screen width, so refresh them whenever it changes (window resize, late layout)
new ResizeObserver(() => { if (STATE && vb) applyViewBox(); }).observe(svg);

// pan
let drag = null;
svg.addEventListener("mousedown", e => {
  drag = { x: e.clientX, y: e.clientY };
  svg.classList.add("dragging");
});
window.addEventListener("mouseup", () => { drag = null; svg.classList.remove("dragging"); });
svg.addEventListener("mousemove", e => {
  if (!drag) return;
  const scale = vb.w / svgWidth();
  vb.x -= (e.clientX - drag.x) * scale;
  vb.y -= (e.clientY - drag.y) * scale;
  drag = { x: e.clientX, y: e.clientY };
  applyViewBox();
});
// zoom
svg.addEventListener("wheel", e => {
  e.preventDefault();
  const p = svgPoint(e);
  const f = e.deltaY > 0 ? 1.12 : 1 / 1.12;
  const nw = vb.w * f, nh = vb.h * f;
  vb.x = p.x - (p.x - vb.x) * (nw / vb.w);
  vb.y = p.y - (p.y - vb.y) * (nh / vb.h);
  vb.w = nw; vb.h = nh;
  applyViewBox();
}, { passive: false });

// ---- time travel -----------------------------------------------------------
// data/history.json (build_history.py): every link with the dates it existed, every station with the dates a line served it.
// The slider moves in months from Jan 1863; a month's date is its LAST day, so everything that opened in it is included.

let HIST = null;
let ACTIVE_LINE_IDS = null; // ids of the lines with a running link on the slider's date (null until history loads)
let curISO = "9999-12-31";
let playing = false, playRaf = 0, playMonth = 0;
const START_YEAR = 1863, MONTHS = (2026 - START_YEAR) * 12; // slider 0 .. MONTHS-1
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function monthToISO(m) {
  const y = START_YEAR + Math.floor(m / 12), mo = m % 12;
  const last = new Date(Date.UTC(y, mo + 1, 0)).getUTCDate();
  return `${y}-${String(mo + 1).padStart(2, "0")}-${String(last).padStart(2, "0")}`;
}

function haversineKm(la1, lo1, la2, lo2) {
  const r = Math.PI / 180, dp = (la2 - la1) * r, dl = (lo2 - lo1) * r;
  const h = Math.sin(dp / 2) ** 2 + Math.cos(la1 * r) * Math.cos(la2 * r) * Math.sin(dl / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
}

function renderHistory() {
  const gEdges = document.getElementById("edges");
  gEdges.replaceChildren();
  const groups = new Map();
  for (const l of STATE.lines) {
    const g = el("g", { "data-line": l.id, "data-mode": l.mode });
    groups.set(l.id, g);
    gEdges.appendChild(g);
  }
  const lineById = new Map(STATE.lines.map(l => [l.id, l]));
  for (const lk of HIST.links) {
    const sa = byId.get(lk.a), sb = byId.get(lk.b), line = lineById.get(lk.line);
    lk.el = el("line", {
      class: "edge",
      x1: sa.x, y1: sa.y, x2: sb.x, y2: sb.y,
      stroke: line.color,
      "stroke-width": line.mode === "tube" ? 150 : 130,
    });
    lk.km = haversineKm(sa.lat, sa.lon, sb.lat, sb.lon);
    groups.get(lk.line).appendChild(lk.el);
  }
  for (const s of STATE.stations) {
    const h = HIST.stations[s.id];
    s.first = h ? h.first_served : null;
  }
  // axis labels under the slider
  const ticks = document.getElementById("tl-ticks");
  ticks.replaceChildren();
  for (const y of [1863, 1900, 1950, 2000, 2025]) {
    const t = document.createElement("span");
    t.textContent = y;
    t.style.left = `${(((y - START_YEAR) * 12) / (MONTHS - 1)) * 100}%`;
    ticks.appendChild(t);
  }
  document.getElementById("timebar").hidden = false;
  // deep link: #1971-07 jumps to a month; #1971-07&from=<station id>&to=<station id> also plans that journey
  const parts = location.hash.slice(1).split("&");
  const fromHash = /^(\d{4})(?:-(\d{1,2}))?$/.exec(parts[0]);
  const m = fromHash ? Math.min(MONTHS - 1, Math.max(0, (+fromHash[1] - START_YEAR) * 12 + (fromHash[2] ? +fromHash[2] - 1 : 11))) : MONTHS - 1;
  const kv = Object.fromEntries(parts.slice(1).map(p => p.split("=")));
  setMonth(m);
  if (kv.from && byId.has(kv.from) && kv.to && byId.has(kv.to)) { selA = kv.from; selB = kv.to; updateSelection(); }
}

function setMonth(m, prevM = null) {
  document.getElementById("tl-slider").value = m;
  applyDate(monthToISO(m), prevM == null ? null : monthToISO(prevM));
  const y = START_YEAR + Math.floor(m / 12);
  document.getElementById("tl-year").textContent = y;
  document.getElementById("tl-month").textContent = MON[m % 12];
  document.getElementById("tl-note").hidden = m >= MONTHS - 1;
  updateCoverCount();
  if (!playing) refreshJourney(); // while playing, re-planning every frame would just flicker
}

let journeyTimer = 0;
function refreshJourney() {
  clearTimeout(journeyTimer);
  journeyTimer = setTimeout(() => { if (selA && selB && currentMode === "journey") updateSelection(); }, 180);
}

function applyDate(iso, prevISO) {
  curISO = iso;
  const act = new Map(); // station id -> Set of line ids running on it at this date
  ACTIVE_LINE_IDS = new Set();
  let km = 0;
  const lines = new Set();
  for (const lk of HIST.links) {
    const on = lk.from <= iso && (lk.to === null || iso < lk.to);
    lk.el.style.display = on ? "" : "none";
    if (!on) continue;
    ACTIVE_LINE_IDS.add(lk.line);
    for (const id of [lk.a, lk.b]) {
      if (!act.has(id)) act.set(id, new Set());
      act.get(id).add(lk.line);
    }
    if (layerVisible[LINE_MODE.get(lk.line)]) { km += lk.km; lines.add(lk.line); }
  }
  for (const s of STATE.stations) {
    s.activeLines = act.get(s.id) || new Set();
    s.interchange = s.activeLines.size > 1;
    s.rPx = s.interchange ? 4.2 : 2.6;
    s.rFixed = s.interchange ? 75 : 55;
    s.el.classList.toggle("interchange", s.interchange);
  }
  applyLayers();
  updateLod();
  updateMarkerSizes();
  const shown = STATE.stations.filter(s => s.el.style.display !== "none").length;
  const rail = RAIL ? applyRailDate(iso, prevISO) : null;
  document.getElementById("tl-stats").innerHTML =
    `<b>${shown}</b> stations · <b>${lines.size}</b> lines · <b>${Math.round(km)}</b> km of track` +
    (rail && layerVisible.rail ? ` · <b>${rail.open}</b> rail stations` : "");
  // what just opened or closed (since the previous frame), for the ticker
  const news = document.getElementById("tl-news");
  if (prevISO && prevISO < iso) {
    const tidy = n => n.replace(/ (Underground|DLR|Rail|tube|railway) (Station|station)$/, "").replace(/ (railway|tube) station$/i, "");
    const fresh = STATE.stations.filter(s => s.first && s.first > prevISO && s.first <= iso && s.el.style.display !== "none").map(s => tidy(s.name));
    const opened = [...fresh, ...(rail && layerVisible.rail ? rail.opened : [])];
    const list = (label, names) => `<i>${label}:</i> ${names.slice(0, 4).join(", ")}${names.length > 4 ? ` <i>+${names.length - 4} more</i>` : ""}`;
    const parts = [];
    if (opened.length) parts.push(list("Opened", opened));
    if (rail && layerVisible.rail && rail.closed.length) parts.push(list("Closed", rail.closed));
    if (parts.length) news.innerHTML = parts.join("  ·  ");
  } else if (!prevISO) {
    news.textContent = "";
  }
}

// ---- National Rail + former stations (data/rail_history.json) -------------------------------

let RAIL = null;

function renderRail() {
  const gEdges = document.getElementById("rail-edges");
  const gStations = document.getElementById("rail-stations");
  gEdges.replaceChildren();
  gStations.replaceChildren();
  const pos = new Map();
  RAIL.list = [];
  for (const [id, s] of Object.entries(RAIL.stations)) {
    const p = project(s.lat, s.lon);
    s.id = id;
    s.x = p.x;
    s.y = p.y;
    pos.set(id, s);
    const g = el("g", { class: "rail-stn" });
    s.dotEl = el("circle", { class: "rail-dot" + (s.closed ? " former" : ""), cx: s.x, cy: s.y, r: 60 });
    g.appendChild(s.dotEl);
    g.addEventListener("mousemove", ev => showRailTooltip(s, ev));
    g.addEventListener("mouseleave", hideTooltip);
    gStations.appendChild(g);
    s.el = g;
    RAIL.list.push(s);
  }
  for (const s of STATE.stations) pos.set(s.id, s); // links can end at a TfL station
  for (const lk of RAIL.links) {
    const a = pos.get(lk.a), b = pos.get(lk.b);
    if (!a || !b) { lk.el = null; continue; }
    lk.el = el("line", { class: "rail-edge" + (lk.kind === "inferred" ? " inferred" : ""), x1: a.x, y1: a.y, x2: b.x, y2: b.y, "stroke-width": 70 });
    gEdges.appendChild(lk.el);
  }
}

function showRailTooltip(s, ev) {
  tooltip.hidden = false;
  const year = d => (d ? d.slice(0, 4) : "");
  tooltip.textContent = `${s.name.replace(/ (railway|tube) station$/i, "")} · rail ${year(s.opened)}${s.closed ? "–" + year(s.closed) : "–"}`;
  tooltip.style.left = ev.clientX + 12 + "px";
  tooltip.style.top = ev.clientY - 8 + "px";
}

function applyRailDate(iso, prevISO) {
  let open = 0;
  const opened = [], closed = [];
  for (const s of RAIL.list) {
    const on = s.opened <= iso && (s.closed === null || iso < s.closed);
    s.el.style.display = on ? "" : "none";
    if (on) open++;
    if (prevISO && prevISO < iso) {
      if (s.opened > prevISO && s.opened <= iso) opened.push(s.name.replace(/ (railway|tube) station$/i, ""));
      if (s.closed && s.closed > prevISO && s.closed <= iso) closed.push(s.name.replace(/ (railway|tube) station$/i, ""));
    }
  }
  for (const lk of RAIL.links) {
    if (!lk.el) continue;
    lk.el.style.display = lk.from <= iso && (lk.to === null || iso < lk.to) ? "" : "none";
  }
  return { open, opened, closed };
}

function loadRail() {
  fetch("/api/rail")
    .then(r => (r.ok ? r.json() : null))
    .then(r => {
      if (!r || !r.links) return;
      RAIL = r;
      renderRail();
      updateMarkerSizes();
      applyLayers();
      if (HIST) applyDate(curISO);
    })
    .catch(() => {});
}

function stopPlay() {
  const wasPlaying = playing;
  playing = false;
  cancelAnimationFrame(playRaf);
  document.getElementById("tl-play").textContent = "▶";
  if (wasPlaying) refreshJourney(); // plan the journey for the date we stopped on
}

function startPlay() {
  const slider = document.getElementById("tl-slider");
  if (+slider.value >= MONTHS - 1) slider.value = 0;
  playMonth = +slider.value;
  playing = true;
  document.getElementById("tl-play").textContent = "❚❚";
  let last = performance.now(), shownM = Math.floor(playMonth);
  const tick = now => {
    if (!playing) return;
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    playMonth += dt * Number(document.getElementById("tl-speed").value) * 12;
    const m = Math.min(MONTHS - 1, Math.floor(playMonth));
    if (m !== shownM) { setMonth(m, shownM); shownM = m; }
    if (m >= MONTHS - 1) return stopPlay();
    playRaf = requestAnimationFrame(tick);
  };
  playRaf = requestAnimationFrame(tick);
}

document.getElementById("tl-play").addEventListener("click", () => (playing ? stopPlay() : startPlay()));
document.getElementById("tl-slider").addEventListener("input", e => { stopPlay(); setMonth(+e.target.value); });
document.getElementById("tl-now").addEventListener("click", () => { stopPlay(); setMonth(MONTHS - 1); });

function loadHistory() {
  fetch("/api/history")
    .then(r => (r.ok ? r.json() : null))
    .then(h => { if (h && h.links) { HIST = h; renderHistory(); } })
    .catch(() => {});
}

// ---- boot -----------------------------------------------------------------

fetch("/api/state").then(r => r.json()).then(data => {
  STATE = data;
  for (const l of STATE.lines) LINE_MODE.set(l.id, l.mode);
  for (const s of STATE.stations) byId.set(s.id, s);
  vb = projectAll();
  applyViewBox();
  renderMap();
  updateCoverCount();
  fetch("/api/river").then(r => r.json()).then(d => renderRiver(d.parts));
  loadHistory();
  loadRail();
});
