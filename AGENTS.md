# tube-sim — Agent Guide

London Tube journey planner + all-lines challenge solver, with a year slider (1863 → 2025). User-facing docs: `README.md`.

## Commands

- **Run:** `systemctl --user start tube-sim` (not enabled at login; toggle from the waybar services panel) or `./.venv/bin/python app.py` → http://127.0.0.1:5080 (**5000 belongs to piper-tts**).
- **Refresh TfL data:** `./.venv/bin/python fetch_data.py` (rewrites `data/tfl_snapshot.json`; keyless API).
- **No test suite.** Sanity-check with `/api/route?from=&to=[&date=YYYY-MM-DD]` and `POST /api/challenge/solve`; run `./.venv/bin/python check_year_routes.py` after touching `graph.py`, `app.py` routing, or the history data.
- A stale dev server holding 5080 serves 404 for static files if its worktree was deleted — `ss -ltnp | grep 5080` before debugging.

## Network, graph, solver

- **Data model** (`fetch_data.py`): modes = tube + overground (6 named lines) + dlr + elizabeth-line. TfL returns fragmented per-direction sequences mixing stopping patterns, so each line is reduced to an **undirected edge set** (union of consecutive-station pairs) — don't reintroduce "branches". Stations are **merged by `hubNaptanCode`**: the same physical station has different naptan ids per mode, and without the merge the modes never connect and the solver stalls.
- **Graph** (`graph.py`): `TubeGraph` = per-line + union adjacency, haversine-km weights. Times use per-mode speeds from the snapshot (`speeds_kmh`: tube 32, overground 48, dlr 45, elizabeth 70) + 0.4 min dwell/stop, 4 min transfer, 2 min initial wait. `route()` is Dijkstra over `(station, current-line)` so transfers are penalised.
- **Solver** (`solver.py`): beam search over `(station, covered-mask, stopped-mask)` bitmasks; alight points limited to interchanges/termini (plus the completing leg). Objectives `hops` | `km` | `balanced`; rules `lenient` (ride-through free) | `strict` (ride-through counts as visiting). `solve(line_ids=...)` covers any subset. **Call `verify()` after any solver change.**
- **Regression anchors:** tube-only hops optimum = 11 hops / 8.14 km (11 is the provable floor); all-19 solve covers 19 lines (~94 hops at 25 s); Paddington → Abbey Wood rides the Elizabeth line direct.

## Time travel

The network is today's TfL snapshot plus dated history. **Journeys and the challenge are year-aware:** `date=` builds a graph from links alive that day (`graph.dated_snapshot`, via `app.network_for(date)`, cached per month; no date or ≥ 2025-12-31 = today unchanged). A station with no running link that day is "not open yet" (404); a challenge with no tube lines that day is 400. National Rail / former stations are drawn but **not routable**.

- **Data chain:** `fetch_history.py` (Wikidata → `data/wikidata_london_rail.json`, ~960 stations with open/close dates; several small bounding boxes because one big one times out, with retries) → `build_history.py` (matches the 420 snapshot stations by name + position, applies `data/line_fixes.json`, writes `data/history.json` + review sheet `data/line_fixes_review.md`). `preview_history.py` draws a contact sheet (needs matplotlib, e.g. the city-sim venv).
- **Model** (`timeline.py`, pure functions): a line serves a station from `max(station opening, section/line date)`; at every date the served set changes, active stations are joined along the line, **skipping unserved degree-2 stations** but never through a junction → link lifetimes `{line, a, b, from, to}`. Don't replace with "edge = max of endpoint dates" — it breaks new links between old stations (Jubilee extension, Victoria line).
- **`data/line_fixes.json`** is the hand-written part: per-line `start`, `sections [from, to, date, confidence]`, and `station_dates` for the 13 stations Wikidata matching missed. Dates are recall with a confidence tag, to be reviewed; `build_history.py` fails if any line's final network differs from today's and flags sections where Wikidata says a station opened later.
- **National Rail + former stations** (grey layer, on by default): `fetch_closed.py` (Wikipedia categories → Wikidata → `data/closed_stations.json`, 171 stations) → `fetch_wikitext.py` (infobox open/close/reopen events, category years as fallback, neighbours; pages cached in gitignored `data/cache/`) → `build_rail.py` (resolves neighbours by normalised name + nearest, adds a dashed `kind: "inferred"` nearest-station link within 2.5 km for orphans, drops links > 10 km) → `data/rail_history.json`, served at `/api/rail`. Wikipedia/Wikidata rate-limit hard (HTTP 429): fetchers pace at 1 req/s and honour `Retry-After`.
- **Known limits:** temporary closures parsed but not drawn; 33 stations without an opening date are dropped; Tramlink stops show as long links.
- **Not done:** London population layer (CitySim data), temporary closures, routing over National Rail.

## Frontend (`static/map.js`, vanilla JS + SVG, no build)

- Equirectangular projection. Route drawing uses the animated dash "flow" overlay + numbered leg badges + station labels — **no arrow markers** (they cluttered transfer clusters).
- Station markers use a fixed viewBox radius (`rFixed`: 75 interchange / 55 minor, in `renderMap`) so they shrink with the lines; past `rFixed/rPx` the screen floor (`rPx` 4.2/2.6) takes over. Non-interchange stations LOD-fade wider than `LOD_FULL_WIDTH`; a station hides when all its line modes are toggled off (`applyLayers`).
- River Thames layer (`data/thames.json` ← `fetch_river.py`, `/api/river`) draws beneath the network. Layer visibility and the challenge cover-set are independent toggles.
- Time travel: `/api/history` → one SVG `<line>` per link with its lifetime; `applyDate(iso)` shows/hides links and stations and updates stats + the "Opened:" ticker. Slider = months from Jan 1863 (a month's date is its last day). Deep links: `/#1971-07`, journey `/#1971-12&from=HUBBRX&to=940GZZLUOXC`.
- CSS: halo/dot rules must be `.station .halo` / `.station .dot` (children); read map width via `getBoundingClientRect()` (`svgWidth()`), not `clientWidth`. `node(tag, cls, children)` accepts plain text.
