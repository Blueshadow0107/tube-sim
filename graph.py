"""Tube network graph: build from the TfL snapshot, route A->B, serialize for the UI.

Static model (no timetables, per project decision):
  - edge cost in km = haversine distance between adjacent stations
  - ride time estimate = km at SPEED_KMH plus DWELL_MIN per stop arrived at
  - interchange = TRANSFER_MIN flat penalty; start waits START_WAIT_MIN
"""

import heapq
import itertools
import json
import math
from pathlib import Path

DATA = Path(__file__).parent / "data" / "tfl_snapshot.json"

SPEED_KMH = 32.0
DWELL_MIN = 0.4
TRANSFER_MIN = 4.0
START_WAIT_MIN = 2.0

MODE_SPEEDS_FALLBACK = {
    "tube": 32.0,
    "overground": 48.0,
    "dlr": 45.0,
    "elizabeth-line": 70.0,
}


def haversine_km(a_lat, a_lon, b_lat, b_lon):
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


HISTORY = Path(__file__).parent / "data" / "history.json"


def dated_snapshot(snapshot, history, iso):
    """Today's snapshot restricted to what was running on `iso` (YYYY-MM-DD), using the link lifetimes in history.json.

    Lines with no running link that day disappear; a station keeps only the lines that served it that day and
    disappears if none did. Station coordinates and line colours are today's.
    """
    edges_by_line, served = {}, {}
    for lk in history["links"]:
        if lk["from"] <= iso and (lk["to"] is None or iso < lk["to"]):
            edges_by_line.setdefault(lk["line"], []).append([lk["a"], lk["b"]])
            for s in (lk["a"], lk["b"]):
                served.setdefault(s, set()).add(lk["line"])
    lines = [{**line, "edges": edges_by_line[line["id"]]} for line in snapshot["lines"] if line["id"] in edges_by_line]
    stations = {sid: {**snapshot["stations"][sid], "lines": sorted(ls)} for sid, ls in served.items()}
    return {**snapshot, "lines": lines, "stations": stations}


class TubeGraph:
    def __init__(self, path=DATA, data=None):
        self.data = data if data is not None else json.loads(Path(path).read_text())
        self.stations = self.data["stations"]
        self.lines = {l["id"]: l for l in self.data["lines"]}
        self.mode_speeds = {
            **MODE_SPEEDS_FALLBACK,
            **self.data.get("speeds_kmh", {}),
        }

        self.km = {}  # (a,b) with a<b -> km
        self.line_adj = {}  # line -> {station: {neighbor: km}}
        self.adj = {}  # station -> {neighbor: km} across all lines
        self.lines_by_station = {}  # station -> set of line ids

        for st_id, st in self.stations.items():
            self.lines_by_station[st_id] = set(st["lines"])
            self.adj.setdefault(st_id, {})

        for line in self.data["lines"]:
            la = self.line_adj.setdefault(line["id"], {})
            for a, b in line["edges"]:
                d = haversine_km(
                    self.stations[a]["lat"], self.stations[a]["lon"],
                    self.stations[b]["lat"], self.stations[b]["lon"],
                )
                self.km[tuple(sorted((a, b)))] = d
                la.setdefault(a, {})[b] = d
                la.setdefault(b, {})[a] = d
                self.adj[a][b] = d
                self.adj[b][a] = d

    def edge_km(self, a, b):
        return self.km[tuple(sorted((a, b)))]

    def ride_paths(self, line_id, start):
        """Dijkstra over one line's subgraph from `start`.

        Returns {station: (hops, km, path)} — shortest path per reachable
        station, hops primary, km tiebreak. A "path" is the list of station
        ids from start to that station riding only this line.
        """
        adj = self.line_adj[line_id]
        if start not in adj:
            return {}
        best = {start: (0, 0.0, [start])}
        pq = [(0, 0.0, start)]
        while pq:
            hops, dist, s = heapq.heappop(pq)
            h0, d0, _ = best[s]
            if (hops, dist) != (h0, d0):
                continue
            for t, d in adj[s].items():
                nh, nd = hops + 1, dist + d
                if (nh, nd) < (best.get(t, (math.inf, math.inf, None))[0],
                               best.get(t, (math.inf, math.inf, None))[1]):
                    best[t] = (nh, nd, best[s][2] + [t])
                    heapq.heappush(pq, (nh, nd, t))
        return best

    def route(self, a, b):
        """Dijkstra on (station, current-line) states. Returns legs + totals."""
        if a == b:
            return None
        dist = {(a, None): 0.0}  # (station, line|None) -> minutes
        hops = {(a, None): 0}
        prev = {}
        counter = itertools.count()
        pq = [(0.0, 0, next(counter), a, None)]
        goal = None
        while pq:
            cost, h, _, s, line = heapq.heappop(pq)
            if cost != dist.get((s, line)):
                continue
            if s == b:
                goal = (s, line)
                break
            if line is None:
                # board any line serving this station
                for lid in sorted(self.lines_by_station[s]):
                    key = (s, lid)
                    if cost < dist.get(key, math.inf):
                        dist[key] = cost
                        hops[key] = h
                        prev[key] = (s, None)
                        heapq.heappush(pq, (cost, h, next(counter), s, lid))
            else:
                # transfer to another line here
                tkey = (s, None)
                if cost + TRANSFER_MIN < dist.get(tkey, math.inf):
                    dist[tkey] = cost + TRANSFER_MIN
                    hops[tkey] = h
                    prev[tkey] = (s, line)
                    heapq.heappush(pq, (cost + TRANSFER_MIN, h, next(counter), s, None))
                # ride to each neighbour on the current line
                speed = self.mode_speeds.get(self.lines[line].get("mode", "tube"), SPEED_KMH)
                for t, d in self.line_adj[line].get(s, {}).items():
                    nd = cost + d / speed * 60 + DWELL_MIN
                    nh = h + 1
                    k2 = (t, line)
                    if (nd, nh) < (dist.get(k2, math.inf), hops.get(k2, math.inf)):
                        dist[k2] = nd
                        hops[k2] = nh
                        prev[k2] = (s, line)
                        heapq.heappush(pq, (nd, nh, next(counter), t, line))

        if goal is None:
            return None

        chain = []
        cur = goal
        while cur in prev:
            chain.append(cur)
            cur = prev[cur]
        chain.append((a, None))
        chain.reverse()

        # group consecutive same-line states into legs
        legs = []
        for s, line in chain:
            if line is None:
                continue
            if legs and legs[-1]["line"] == line:
                legs[-1]["path"].append(s)
            else:
                legs.append({"line": line, "path": [s]})

        total_km = 0.0
        total_hops = 0
        for leg in legs:
            path = leg["path"]
            leg["km"] = sum(self.edge_km(x, y) for x, y in zip(path, path[1:]))
            leg["stops"] = len(path) - 1
            total_km += leg["km"]
            total_hops += leg["stops"]

        return {
            "from": a,
            "to": b,
            "legs": [
                {
                    "line": l["line"],
                    "line_name": self.lines[l["line"]]["name"],
                    "color": self.lines[l["line"]]["color"],
                    "from": l["path"][0],
                    "to": l["path"][-1],
                    "from_name": self.stations[l["path"][0]]["name"],
                    "to_name": self.stations[l["path"][-1]]["name"],
                    "stops": l["stops"],
                    "km": round(l["km"], 2),
                    "path": l["path"],
                }
                for l in legs
            ],
            "totals": {
                "minutes": round(dist[goal] + START_WAIT_MIN, 1),
                "km": round(total_km, 2),
                "stops": total_hops,
                "transfers": len(legs) - 1,
            },
        }

    def serialize_state(self):
        """One JSON-safe blob for the frontend to render the map."""
        return {
            "stations": [
                {
                    "id": sid,
                    "name": st["name"],
                    "lat": st["lat"],
                    "lon": st["lon"],
                    "zone": st["zone"],
                    "lines": st["lines"],
                    "interchange": len(st["lines"]) > 1,
                }
                for sid, st in self.stations.items()
            ],
            "lines": [
                {
                    "id": l["id"],
                    "name": l["name"],
                    "color": l["color"],
                    "mode": l.get("mode", "tube"),
                    "edges": l["edges"],
                }
                for l in self.data["lines"]
            ],
            "speeds_kmh": self.mode_speeds,
        }
