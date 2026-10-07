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

from graph import TubeGraph
from solver import ChallengeSolver
from pathlib import Path
import json

app = Flask(__name__)
graph = TubeGraph()
solver = ChallengeSolver(graph)
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
    if not a or not b or a not in graph.stations or b not in graph.stations:
        return jsonify({"error": "unknown station id(s)"}), 400
    result = graph.route(a, b)
    if result is None:
        return jsonify({"error": "no route found"}), 404
    return jsonify(result)


@app.post("/api/challenge/solve")
def challenge_solve():
    body = request.get_json(force=True, silent=True) or {}
    objective = body.get("objective", "hops")
    rule = body.get("rule", "lenient")
    include_modes = body.get("include_modes", [])
    if not isinstance(include_modes, list):
        return jsonify({"error": "include_modes must be a list"}), 400
    cover = [
        lid
        for lid, line in graph.lines.items()
        if line.get("mode") == "tube" or line.get("mode") in include_modes
    ]
    try:
        budget = float(body.get("budget_seconds", 8))
    except (TypeError, ValueError):
        return jsonify({"error": "budget_seconds must be a number"}), 400
    budget = min(max(budget, 1.0), 60.0)
    try:
        result = solver.solve(
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
