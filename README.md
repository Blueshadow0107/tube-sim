# Tube Sim

London Tube journey planner + all-lines challenge solver. Flask backend, vanilla-JS SVG map, data from a static TfL API snapshot (no key needed).

**Network:** 11 tube lines plus optional Overground (6 lines), DLR, and Elizabeth line — 420 hub-merged stations in the current snapshot. Non-tube lines are off by default; toggle them under *Map layers*. The River Thames (real OSM geometry, cached in `data/thames.json`) renders beneath the network like on the tube map, with its own toggle.

**Time travel:** a slider along the bottom of the map replays the network from 1863 to 2025 (play, speed, station/line/km counts, an "Opened:" ticker). Open `/#1971-07` to jump to a month. Journeys and the challenge use the network as it was on the date shown (TfL modes only).

## Run

```sh
python -m venv .venv && ./.venv/bin/pip install -r requirements.txt   # once
./.venv/bin/python app.py                                              # serves http://127.0.0.1:5080
```

Refresh the network data (rewrites `data/tfl_snapshot.json`):

```sh
./.venv/bin/python fetch_data.py     # stations + lines
./.venv/bin/python fetch_river.py    # Thames geometry (OSM Overpass, cached to data/thames.json)
```

## Modes

**Journey** — click station A, click station B. Fastest route by estimated time (per-mode speed: tube 32, Overground 48, DLR 45, Elizabeth 70 km/h + 0.4 min/stop dwell + 4 min/transfer + 2 min initial wait), drawn with colored legs, a direction-flow animation, numbered transfer badges, and station labels.

**Challenge** — the custom run: cover the selected lines in one run while minimising stations passed and distance, and **never stop at the same station twice**. Changing lines at a station you already stopped at is banned; riding *through* a station without getting off does not count as stopping (strict mode, selectable in the UI, counts ride-throughs too). Tick Overground/DLR/Elizabeth under *Also cover* to widen the challenge (11 → 19 lines).

The solver is a beam search over `(station, covered-lines bitmask, stopped-stations bitmask)` with a one-hop-per-uncovered-line heuristic, run to a time budget. Results are verified (all lines covered, no repeated stop, every leg rideable) but not proven mathematically optimal — longer think times find better runs.

### Current records

| Cover set | Objective | Result |
|---|---|---|
| 11 tube lines | fewest stations | **11 hops / 8.14 km / 12 stops** — Oxford Circus → Green Park → Piccadilly Circus → Charing Cross → Embankment → Westminster → Waterloo → Bank → Liverpool Street → Moorgate → Barbican → Farringdon. Optimal (11 = one hop per line, the floor). |
| all 19 lines | fewest stations | **~94 hops / ~127 km** — a long spiral out to Upminster/Romford/Walthamstow; valid and verified, quality depends on think time. |

## Layout

- `fetch_data.py` — TfL snapshot → `data/tfl_snapshot.json`; per-line undirected edge sets; stations merged by `hubNaptanCode` so the same physical station is one node across modes
- `fetch_river.py` — Thames multipolyline from OSM Overpass → `data/thames.json` (served at `/api/river`)
- `graph.py` — graph build, per-line ride paths, Dijkstra routing (`/api/route`), map state serializer, per-mode speed estimates
- `solver.py` — all-lines challenge beam search + result verifier; `solve(line_ids=...)` covers any subset
- `app.py` — Flask server (port **5080**; 5000 is taken by piper-tts)
- `templates/`, `static/` — single-page SVG map UI

## Limitations

- Static graph: edge times are distance estimates at per-mode average speeds, not timetables.
- TfL sequences mix stopping patterns, so a line's edge set includes fast-service skips (e.g. Metropolitan Wembley Park ↔ Finchley Road direct).
- Hub merging follows TfL's own station grouping; a few walking interchanges TfL keeps separate (e.g. Bank ↔ Monument) stay separate nodes.
- TfL treats some same-name pairs (Edgware Road tube stations) as separate hubs; they are not merged.
- The 19-line run is heuristic — raise think time for better results.

Rebuild the history (Wikidata is rate-limited and sometimes slow, so the fetch retries):

```sh
./.venv/bin/python fetch_history.py    # data/wikidata_london_rail.json
./.venv/bin/python build_history.py    # data/history.json + data/line_fixes_review.md
```

## Data and licence

Powered by TfL Open Data. Contains OS data © Crown copyright and database rights 2016 and Geomni UK Map data © and database rights 2019.

The historical network (1863–2025) is built from Wikidata, which is available under CC0.

The code is released under the [MIT licence](LICENSE); the licence covers the code only, and the data keeps the terms of its sources above.

## Deploy

Container-ready: `docker build -t tube-sim . && docker run -p 8080:8080 tube-sim` (gunicorn, honours `$PORT`).

- **Render:** New → Blueprint → pick this repo (`render.yaml`). Free tier sleeps when idle.
- **Fly.io:** `fly launch --copy-config --no-deploy && fly deploy` (`fly.toml`, scales to zero).

The challenge solver is CPU-heavy (~25 s search); a 1-CPU free instance is fine for demos.
