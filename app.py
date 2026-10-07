"""Tube Sim web server.

Endpoints:
  GET  /                      map UI
  GET  /api/state             all stations + line edges for rendering
  GET  /api/history           link lifetimes + station service dates (time slider)
  GET  /api/rail              National Rail + closed stations and link lifetimes (time slider)
  GET  /api/route?from=&to=   fastest route between two station ids
  POST /api/challenge/solve   all-lines challenge solver (JSON body:
                              objective hops|km|balanced,
                              rule lenient|strict, budget_seconds)
"""

from flask import Flask, jsonify, render_template, request

from graph import HISTORY, TubeGraph, dated_snapshot
from solver import ChallengeSolver
from pathlib import Path
import json
import re

app = Flask(__name__)
graph = TubeGraph()
solver = ChallengeSolver(graph)
_history = json.loads(HISTORY.read_text()) if HISTORY.exists() else None
_networks = {}  # "YYYY-MM" -> (TubeGraph, ChallengeSolver) for that month's last-day network
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LATEST = "2025-12-31"


def network_for(date):
    """(graph, solver) for the network running on `date`; None / today / no history -> today's snapshot.

    Dates are quantised to their month so the cache stays small (the map's slider moves in months anyway).
    """
    if not date or date >= LATEST or _history is None:
        return graph, solver
    key = date[:7]
    if key not in _networks:
        last_day = f"{key}-31"  # string compare is enough: every link boundary is a real date <= the 31st
        g = TubeGraph(data=dated_snapshot(graph.data, _history, last_day))
        _networks[key] = (g, ChallengeSolver(g))
    return _networks[key]
RIVER_PATH = Path(__file__).parent / "data" / "thames.json"
HISTORY_PATH = Path(__file__).parent / "data" / "history.json"
RAIL_PATH = Path(__file__).parent / "data" / "rail_history.json"


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def state():
    return jsonify(graph.serialize_state())


@app.get("/api/history")
def history():
    """Link lifetimes + station service dates (built by build_history.py) for the time slider."""
    if not HISTORY_PATH.exists():
        return jsonify({"error": "history data missing — run fetch_history.py then build_history.py"}), 404
    return app.response_class(HISTORY_PATH.read_text(), mimetype="application/json")


@app.get("/api/rail")
def rail():
    """National Rail + closed stations and their link lifetimes (built by build_rail.py) for the time slider."""
    if not RAIL_PATH.exists():
        return jsonify({"error": "rail data missing — run fetch_closed.py, fetch_wikitext.py, build_rail.py"}), 404
    return app.response_class(RAIL_PATH.read_text(), mimetype="application/json")


@app.get("/api/river")
def river():
    if not RIVER_PATH.exists():
        return jsonify({"error": "river data missing — run fetch_river.py"}), 404
    return jsonify(json.loads(RIVER_PATH.read_text()))


@app.get("/api/route")
def route():
    a = request.args.get("from")
    b = request.args.get("to")
    date = request.args.get("date")
    if date and not DATE_RE.match(date):
        return jsonify({"error": "date must be YYYY-MM-DD"}), 400
    g, _ = network_for(date)
    if not a or not b or a not in graph.stations or b not in graph.stations:
        return jsonify({"error": "unknown station id(s)"}), 400
    if a not in g.stations or b not in g.stations:
        gone = [graph.stations[s]["name"] for s in (a, b) if s not in g.stations]
        return jsonify({"error": f"{' and '.join(gone)} not open yet on {date}"}), 404
    result = g.route(a, b)
    if result is None:
        return jsonify({"error": "no route found on that date"}), 404
    return jsonify(result)


@app.post("/api/challenge/solve")
def challenge_solve():
    body = request.get_json(force=True, silent=True) or {}
    objective = body.get("objective", "hops")
    rule = body.get("rule", "lenient")
    include_modes = body.get("include_modes", [])
    if not isinstance(include_modes, list):
        return jsonify({"error": "include_modes must be a list"}), 400
    date = body.get("date")
    if date and not (isinstance(date, str) and DATE_RE.match(date)):
        return jsonify({"error": "date must be YYYY-MM-DD"}), 400
    g, s = network_for(date)
    cover = [
        lid
        for lid, line in g.lines.items()
        if line.get("mode") == "tube" or line.get("mode") in include_modes
    ]
    if not cover:
        return jsonify({"error": f"no lines running on {date} to cover"}), 400
    try:
        budget = float(body.get("budget_seconds", 8))
    except (TypeError, ValueError):
        return jsonify({"error": "budget_seconds must be a number"}), 400
    budget = min(max(budget, 1.0), 60.0)
    try:
        result = s.solve(
            objective=objective,
            rule=rule,
            budget_seconds=budget,
            line_ids=cover,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    result["lines_to_cover"] = len(cover)
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5080, threaded=True)
