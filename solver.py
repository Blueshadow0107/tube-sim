"""All-lines challenge solver.

Challenge (user-defined): find a run that covers every tube line while
minimising stations passed and distance, and never stopping at the same
station twice. Changing lines at a station you already stopped at is banned;
riding *through* a station without getting off does not count as stopping.

Rules:
  lenient (default) — only board/alight stops join the "stopped" set;
                      riding through a station is free and does not ban it
                      from being stopped at later.
  strict            — every station the train stops at during a leg
                      (including ones you ride through) joins the set.

Search: beam search over (station, covered-lines bitmask, stopped-stations
bitmask). Heuristic = one hop per uncovered line. Time-budgeted; returns the
best run found, verified (coverage, no-revisit, walkable legs) but not
mathematically proven optimal.
"""

import heapq
import itertools
import time

from graph import DWELL_MIN, SPEED_KMH, START_WAIT_MIN, TRANSFER_MIN

OBJECTIVES = {
    "hops": (1.0, 0.01),     # minimise stations passed; km breaks ties
    "km": (0.05, 1.0),       # minimise distance; hops break ties
    "balanced": (1.0, 1.0),  # mix of both
}


class ChallengeSolver:
    def __init__(self, graph):
        self.graph = graph
        self.lines = sorted(graph.lines)
        self.line_index = {lid: i for i, lid in enumerate(self.lines)}
        self.full_mask = (1 << len(self.lines)) - 1
        self.station_index = {sid: i for i, sid in enumerate(graph.stations)}
        self.ride_cache = {}

        # termini per line (degree 1 in that line's subgraph)
        self.termini = {}
        for lid, adj in graph.line_adj.items():
            self.termini[lid] = {s for s, nbrs in adj.items() if len(nbrs) == 1}

        # alight candidates per (line, station): cached ride paths, so a leg
        # only ends at an interchange or a terminus (getting off at a
        # non-interchange mid-branch is never useful except as the final
        # stop, which the expansion handles by allowing any alight point
        # when the leg covers the last uncovered line)
        self.alight_cache = {}

    def _rides(self, line_id, station):
        key = (line_id, station)
        if key not in self.ride_cache:
            self.ride_cache[key] = self.graph.ride_paths(line_id, station)
        return self.ride_cache[key]

    def _alight_points(self, line_id, station):
        key = (line_id, station)
        if key not in self.alight_cache:
            rides = self._rides(line_id, station)
            pts = [
                (t, h, k, path)
                for t, (h, k, path) in rides.items()
                if t != station
                and (len(self.graph.lines_by_station[t]) > 1 or t in self.termini[line_id])
            ]
            self.alight_cache[key] = pts
        return self.alight_cache[key]

    def solve(self, objective="hops", rule="lenient", budget_seconds=8.0,
              beam_width=2000, line_ids=None):
        if objective not in OBJECTIVES:
            raise ValueError(f"objective must be one of {sorted(OBJECTIVES)}")
        if rule not in ("lenient", "strict"):
            raise ValueError("rule must be 'lenient' or 'strict'")
        # lines to cover this run (defaults to everything in the snapshot)
        lines = sorted(line_ids) if line_ids else sorted(self.graph.lines)
        line_index = {lid: i for i, lid in enumerate(lines)}
        full_mask = (1 << len(lines)) - 1
        w_hops, w_km = OBJECTIVES[objective]

        def score(h, k):
            return h * w_hops + k * w_km

        def heuristic(station, mask):
            remaining = bin(full_mask ^ mask).count("1")
            if remaining == 0:
                return 0.0
            serves_uncovered = any(
                l in line_index and not (mask >> line_index[l]) & 1
                for l in self.graph.lines_by_station[station]
            )
            return float(remaining + (0 if serves_uncovered else 1))

        # state: dict(station, mask, stopped(int bitmask), hops, km, legs)
        start = time.monotonic()
        # starting mid-branch is dominated: start at interchanges or termini
        starts = [
            sid
            for sid in self.graph.stations
            if len(self.graph.lines_by_station[sid]) > 1
            or any(sid in t for t in self.termini.values())
        ]
        beam = [
            {
                "station": sid,
                "mask": 0,
                "stopped": 1 << self.station_index[sid],
                "hops": 0,
                "km": 0.0,
                "legs": [],
            }
            for sid in starts
        ]

        best_goal = None
        rounds = 0
        expansions = 0
        while time.monotonic() - start < budget_seconds and beam:
            rounds += 1
            children = []
            for st in beam:
                if st["mask"] == full_mask:
                    continue  # already complete; kept only as candidate
                for lid in self.graph.lines_by_station[st["station"]]:
                    if lid not in line_index:
                        continue  # line not in this run's cover set
                    bit = 1 << line_index[lid]
                    new_mask = st["mask"] | bit
                    completing = new_mask == full_mask
                    for t, h, k, path in self._alight_points(lid, st["station"]):
                        if not completing:
                            if bit & st["mask"]:
                                # repositioning on an already-covered line:
                                # only useful to reach a station serving an
                                # uncovered line
                                if not any(
                                    l in line_index and not (st["mask"] >> line_index[l]) & 1
                                    for l in self.graph.lines_by_station[t]
                                ):
                                    continue
                            else:
                                # riding a new line: any interchange/terminus
                                # alight point is fine
                                pass
                        # when `completing`, all alight points are allowed
                        if rule == "lenient":
                            adds = 1 << self.station_index[t]
                        else:
                            # strict: every station the train stops at AFTER
                            # boarding counts (boarding station is not new);
                            # path[0] is the current station, so skip it
                            adds = 0
                            for p in path[1:]:
                                adds |= 1 << self.station_index[p]
                        if adds & st["stopped"]:
                            continue
                        child = {
                            "station": t,
                            "mask": new_mask,
                            "stopped": st["stopped"] | adds,
                            "hops": st["hops"] + h,
                            "km": st["km"] + k,
                            "legs": st["legs"] + [(lid, path)],
                        }
                        expansions += 1
                        if completing:
                            if best_goal is None or score(child["hops"], child["km"]) < score(
                                best_goal["hops"], best_goal["km"]
                            ):
                                best_goal = child
                        else:
                            children.append(child)

            if not children:
                break
            # dedupe by (station, mask): keep the 2 most promising variants
            buckets = {}
            for ch in children:
                key = (ch["station"], ch["mask"])
                bucket = buckets.setdefault(key, [])
                bucket.append(ch)
                bucket.sort(key=lambda c: score(c["hops"], c["km"]))
                del bucket[2:]
            # prune dominated variants (stopped superset, no better score)
            survivors = []
            for bucket in buckets.values():
                kept = []
                for cand in sorted(bucket, key=lambda c: bin(c["stopped"]).count("1")):
                    if any(
                        cand["stopped"] & k["stopped"] == k["stopped"]
                        and score(cand["hops"], cand["km"]) >= score(k["hops"], k["km"])
                        for k in kept
                    ):
                        continue
                    kept.append(cand)
                survivors.extend(kept)
            # keep top beam_width by score + heuristic
            ranked = heapq.nsmallest(
                beam_width,
                survivors,
                key=lambda c: score(c["hops"], c["km"]) + heuristic(c["station"], c["mask"]),
            )
            beam = ranked

        elapsed = time.monotonic() - start
        if best_goal is None:
            return {
                "solved": False,
                "reason": "no complete run found in budget",
                "seconds": round(elapsed, 2),
                "rounds": rounds,
                "expansions": expansions,
            }
        result = self._format(best_goal, objective, rule, lines)
        result["seconds"] = round(elapsed, 2)
        result["beam_width"] = beam_width
        result["rounds"] = rounds
        result["expansions"] = expansions
        self.verify(result)
        return result

    def _format(self, st, objective, rule, target_lines):
        legs = []
        total_km = 0.0
        total_hops = 0
        minutes = 0.0
        for lid, path in st["legs"]:
            km = sum(self.graph.edge_km(x, y) for x, y in zip(path, path[1:]))
            total_km += km
            total_hops += len(path) - 1
            speed = self.graph.mode_speeds.get(
                self.graph.lines[lid].get("mode", "tube"), SPEED_KMH
            )
            minutes += km / speed * 60 + DWELL_MIN * (len(path) - 1)
            legs.append({
                "line": lid,
                "line_name": self.graph.lines[lid]["name"],
                "color": self.graph.lines[lid]["color"],
                "from": path[0],
                "to": path[-1],
                "from_name": self.graph.stations[path[0]]["name"],
                "to_name": self.graph.stations[path[-1]]["name"],
                "stops": len(path) - 1,
                "km": round(km, 2),
                "path": path,
            })
        stops_made = bin(st["stopped"]).count("1")
        minutes += TRANSFER_MIN * (len(legs) - 1) + START_WAIT_MIN
        return {
            "solved": True,
            "objective": objective,
            "rule": rule,
            "lines_target": sorted(target_lines),
            "legs": legs,
            "lines_covered": sorted({l["line"] for l in legs}),
            "totals": {
                "stops_made": stops_made,
                "hops": total_hops,
                "km": round(total_km, 2),
                "transfers": len(legs) - 1,
                "legs": len(legs),
                "minutes": round(minutes, 1),
            },
        }

    def verify(self, result):
        """Guarantee checks: coverage, no-revisit, walkable legs."""
        assert set(result["lines_covered"]) == set(result["lines_target"]), "not all lines covered"
        seen = set()
        for leg in result["legs"]:
            adj = self.graph.line_adj[leg["line"]]
            path = leg["path"]
            for a, b in zip(path, path[1:]):
                assert b in adj.get(a, {}), f"leg not rideable on {leg['line']}: {a}->{b}"
            if not seen:
                seen.add(path[0])
            assert path[-1] not in seen, f"station stopped at twice: {path[-1]}"
            seen.add(path[-1])
            if result["rule"] == "strict":
                for stop in path[1:-1]:
                    assert stop not in seen, f"station passed through twice: {stop}"
                    seen.add(stop)
        return True
