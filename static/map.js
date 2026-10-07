/* Tube Sim map UI. Vanilla JS, no build step. */

const svg = document.getElementById("map");
const viewport = document.getElementById("viewport");
const tooltip = document.getElementById("tooltip");

let STATE = null; // {stations: [...], lines: [...]}
const byId = new Map();

const layerVisible = { tube: true, overground: false, dlr: false, "elizabeth-line": false };
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
  const xs = STATE.stations.map(s => s.x);
  const ys = STATE.stations.map(s => s.y);
  const pad = 800;
  return {
    x: Math.min(...xs) - pad,
    y: Math.min(...ys) - pad,
    w: Math.max(...xs) - Math.min(...xs) + 2 * pad,
    h: Math.max(...ys) - Math.min(...ys) + 2 * pad,
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
  const scale = vb.w / svg.clientWidth; // viewBox units per CSS px
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
  for (const s of STATE.stations) {
    const vis = s.lines.some(lid => layerVisible[LINE_MODE.get(lid)]);
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
    fetch(`/api/route?from=${encodeURIComponent(selA)}&to=${encodeURIComponent(selB)}`)
      .then(r => r.json())
      .then(data => {
        if (data.error) { res.textContent = data.error; return; }
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
    body: JSON.stringify({ objective, rule, budget_seconds: budget, include_modes: includeModes }),
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

function updateCoverCount() {
  const n = 11 + [...document.querySelectorAll("#ch-modes input:checked")]
    .reduce((acc, i) => acc + (i.value === "overground" ? 6 : 1), 0);
  document.getElementById("ch-cover-count").textContent = `Covering ${n} lines`;
}

// ---- shared little builders ----------------------------------------------

function node(tag, cls, children) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  for (const c of children) e.appendChild(c);
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
document.getElementById("river-layer").addEventListener("change", e => {
  riverVisible = e.target.checked;
  applyLayers();
});

document.getElementById("station-search").addEventListener("input", e => {
  const q = e.target.value.trim().toLowerCase();
  const box = document.getElementById("search-results");
  box.replaceChildren();
  if (q.length < 2) return;
  const hits = STATE.stations.filter(s => s.name.toLowerCase().includes(q)).slice(0, 12);
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

// pan
let drag = null;
svg.addEventListener("mousedown", e => {
  drag = { x: e.clientX, y: e.clientY };
  svg.classList.add("dragging");
});
window.addEventListener("mouseup", () => { drag = null; svg.classList.remove("dragging"); });
svg.addEventListener("mousemove", e => {
  if (!drag) return;
  const scale = vb.w / svg.clientWidth;
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
});
