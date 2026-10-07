# tube-sim/ — Agent Guide

London Tube journey planner + all-lines challenge solver. See `README.md` for user-facing docs.

## Commands

- Run: `./.venv/bin/python app.py` → http://127.0.0.1:5080 (port 5080; **5000 belongs to piper-tts**)
- Refresh data: `./.venv/bin/python fetch_data.py` (rewrites `data/tfl_snapshot.json`; keyless TfL API)
- No tests; sanity-check changes with the API endpoints (`/api/route?from=&to=`, `POST /api/challenge/solve`)

## Architecture notes

- **Data model** (`fetch_data.py`): modes = tube + overground (6 named lines) + dlr + elizabeth-line. TfL returns fragmented ordered sequences per direction/branch, mixing stopping patterns (fast services skip stops). Reduced to per-line **undirected edge sets** (union of consecutive-station pairs). Stations are **merged by `hubNaptanCode`** — the same physical station has different naptan ids across modes (tube `940GZZLU…` vs Elizabeth `910G…`), and without this merge the modes never connect and the solver stalls (regression: all-19 coverage stuck at 11). Don't reintroduce "branches" — the edge-set model is deliberate.
- **Graph** (`graph.py`): `TubeGraph` builds adjacency per line + union adjacency; edge weight = haversine km. Time estimates use **per-mode speeds** from the snapshot's `speeds_kmh` (tube 32, overground 48, dlr 45, elizabeth 70 km/h) + 0.4 min dwell/stop, 4 min transfer, 2 min initial wait. `route()` is Dijkstra over `(station, current-line)` states so transfers are penalised correctly.
- **Solver** (`solver.py`): beam search over `(station, covered-mask, stopped-mask)` int bitmasks; alight points restricted to interchanges/termini (plus any alight point on the completing leg) to keep expansions tractable. Objectives: `hops` | `km` | `balanced`; rules: `lenient` (ride-through free) | `strict` (ride-through counts as visiting). `solve(line_ids=...)` covers any line subset (UI default: tube lines only; +8 with extras). `verify()` asserts coverage + no-revisit + rideable legs — call it after any solver change.
- **Regression checks**: tube-only hops optimum = 11 hops / 8.14 km (Oxford Circus → … → Farringdon chain; 11 is the provable floor). All-19 solve must cover 19 lines (~94 hops at 25 s budget). Route sanity: Paddington → Abbey Wood rides the Elizabeth line direct.
- Frontend is vanilla JS + SVG, no build step. Geographic equirectangular projection. Route drawing: no arrow markers (they cluttered transfer clusters into "overlapping triangles") — use the animated dash "flow" overlay + numbered leg badges + station labels instead. Station markers use a **fixed viewBox radius** (`rFixed`: 75 interchange / 55 minor, in `renderMap`) so they shrink on screen at the same rate as the fixed-width lines when zooming out; once zoomed in past `rFixed/rPx` the screen-size floor (`rPx`: 4.2/2.6) takes over so dense clusters stay delineated. Diameter therefore never exceeds ~0.7× line width (the 1.2× cap is never reached; the river is not a line and plays no part). Non-interchange stations also LOD-fade when the view is wider than `LOD_FULL_WIDTH`, and every station hides when all the line modes it serves are toggled off (`applyLayers`).
- The River Thames layer (`data/thames.json` from `fetch_river.py`, served at `/api/river`) draws beneath the network (bank casing + fill polylines) so lines cross over it; toggle in the layers panel.
- Map layer visibility and the challenge cover-set are independent toggles in the UI.

## Time travel (history) — added 2026-10

The map has a year slider (1863 → 2025). The network is today's TfL snapshot plus dated history; the journey planner and challenge solver still use **today's** network (year-aware routing is a planned step).

- **Data chain:** `fetch_history.py` (Wikidata → `data/wikidata_london_rail.json`: ~960 London-area stations with open/close dates, P197 neighbours; several small bounding boxes because one big box times out the query service, which is flaky, so it retries) → `build_history.py` (matches the 420 snapshot stations to Wikidata by name + position, applies `data/line_fixes.json`, writes `data/history.json` and the review sheet `data/line_fixes_review.md`). `preview_history.py` draws a contact sheet (`data/history_preview.png`; needs matplotlib, e.g. the city-sim venv).
- **Model** (`timeline.py`, pure functions): a line serves a station from `max(station opening date, section/line date)`. At every date where the served set changes, active stations are joined along the line, **skipping unserved degree-2 stations** (trains ran past Pimlico before 1972) but never through a junction. Output is link lifetimes `{line, a, b, from, to}`. Don't replace this with "edge = max of endpoint dates": it breaks new links between old stations (Jubilee extension, Victoria line).
- **`data/line_fixes.json`** holds the hand-written part: per-line `start`, `sections` `[from, to, date, confidence]` (path between the two stations in the line graph), and `station_dates` for the 13 stations Wikidata matching missed. The dates are the author's recall (confidence high/med/low), to be reviewed; `build_history.py` fails the check if any line's final network differs from today's, and flags sections where Wikidata says a station opened later.
- **Frontend** (`static/map.js`, "time travel" section): `/api/history` → one SVG `<line>` per link with its lifetime; `applyDate(iso)` shows/hides links and stations, restyles interchanges, updates the stats and the "Opened:" ticker. The slider is in **months from Jan 1863**; a month's date is its last day. Deep link: `/#1971-07`.
- **CSS gotcha fixed:** halo/dot rules must be `.station .halo` / `.station .dot` (children), not `.station.halo`; the old selectors never matched and drew black blobs. The map width is read via `getBoundingClientRect()` (`svgWidth()`), not `clientWidth`.
- **Not yet done:** National Rail stations/links, closures beyond the 52 Wikidata records, year-aware routing, London population underneath.
