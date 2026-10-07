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
