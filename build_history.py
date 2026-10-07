"""Attach Wikidata opening/closing dates to tube-sim's current stations.

Reads data/tfl_snapshot.json (today's TfL network) and data/wikidata_london_rail.json (fetch_history.py).
A snapshot station (possibly a merged interchange hub) matches every Wikidata station that is close enough AND whose
normalised name matches. Output: data/station_history.json with per-station opened/closed and the unmatched leftovers.

Usage: ./.venv/bin/python build_history.py
"""
import difflib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

from timeline import link_lifetimes, resolve, served_windows, shortest_path

DATA = Path(__file__).resolve().parent / "data"
SUFFIX = re.compile(r"\b(underground|tube|railway|rail|dlr|overground|elizabeth line|london|station|stop)\b", re.I)


def norm(name: str) -> str:
    s = name.lower().replace("&", " and ").replace("’", "'")
    s = re.sub(r"\(.*?\)", " ", s)
    s = SUFFIX.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\bst\b", "saint", s)
    return re.sub(r"\s+", " ", s).strip()


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la = math.radians((a[0] + b[0]) / 2)
    return math.hypot((a[0] - b[0]) * 111.19, (a[1] - b[1]) * 111.19 * math.cos(la))


def main() -> None:
    snap = json.load(open(DATA / "tfl_snapshot.json"))
    wd = json.load(open(DATA / "wikidata_london_rail.json"))
    wst = {q: {**v, "n": norm(v["name"])} for q, v in wd["stations"].items()}

    matched: dict[str, list[str]] = {}
    used: set[str] = set()
    for key, st in snap["stations"].items():
        parts = [norm(p) for p in re.split(r"/| and (?=[A-Z])", st["name"])] + [norm(st["name"])]
        cand = []
        for q, w in wst.items():
            d = km((st["lat"], st["lon"]), (w["lat"], w["lon"]))
            if d > 1.0:
                continue
            score = max(difflib.SequenceMatcher(None, p, w["n"]).ratio() for p in parts if p) if w["n"] else 0
            if score >= 0.82 or (score >= 0.7 and d < 0.25):
                cand.append((score, d, q))
        cand.sort(key=lambda c: (-c[0], c[1]))
        keep = [q for s, d, q in cand if s >= max(0.82, cand[0][0] - 0.12)] if cand else []
        if keep:
            matched[key] = keep
            used.update(keep)

    out = {}
    for key, qs in matched.items():
        opens = [min(wst[q]["open"]) for q in qs if wst[q]["open"]]
        closes = [max(wst[q]["close"]) for q in qs if wst[q]["close"]]
        out[key] = {"wikidata": qs, "opened": min(opens) if opens else None, "closed": (max(closes) if len(closes) == len(qs) else None)}
    unmatched_snap = [(k, v["name"]) for k, v in snap["stations"].items() if k not in matched]
    extras = [(q, w["name"], min(w["open"]) if w["open"] else None, max(w["close"]) if w["close"] else None) for q, w in wst.items() if q not in used]

    (DATA / "station_history.json").write_text(json.dumps({"stations": out, "unmatched_snapshot": unmatched_snap, "extra_wikidata": extras}, ensure_ascii=False))
    n = len(snap["stations"])
    dated = sum(1 for v in out.values() if v["opened"])
    print(f"snapshot stations {n}: matched {len(matched)} ({len(matched)/n:.0%}), with an opening date {dated} ({dated/n:.0%})")
    print(f"unmatched snapshot stations ({len(unmatched_snap)}): {[n_ for _, n_ in unmatched_snap][:25]}")
    print(f"wikidata stations not in today's TfL snapshot: {len(extras)} (National Rail, closed, or unmatched)")
    yrs = sorted(int(v['opened'][:4]) for v in out.values() if v['opened'] and v['opened'][:4].isdigit())
    print("opening years of matched stations:", yrs[:3], "...", yrs[-3:], "| median", yrs[len(yrs)//2])
    manual = json.load(open(DATA / "line_fixes.json"))["station_dates"]
    for key, name in unmatched_snap:
        if name in manual:
            out[key] = {"wikidata": [], "opened": manual[name], "closed": None, "manual": True}
    build_timeline(snap, out)


def build_timeline(snap: dict, hist: dict) -> None:
    fixes = json.load(open(DATA / "line_fixes.json"))["lines"]
    st = snap["stations"]
    all_links: list[dict] = []
    review = ["# Line fix table, review sheet", "",
              "Every section of `data/line_fixes.json` with the number of stations it covers. A row is flagged when a station on it opened "
              "**after** the section date (by Wikidata), which means the date in my table is probably too early.", ""]
    first_served: dict[str, str] = {}
    last_served: dict[str, str | None] = {}
    problems = 0
    for line in snap["lines"]:
        adj: dict[str, set[str]] = defaultdict(set)
        for a, b in line["edges"]:
            adj[a].add(b)
            adj[b].add(a)
        names = {k: st[k]["name"] for k in adj}
        opened = {k: hist[k]["opened"] for k in adj if k in hist and hist[k]["opened"]}
        closed = {k: hist[k]["closed"] for k in adj if k in hist and hist[k]["closed"]}
        fx = fixes[line["id"]]
        win = served_windows(adj, names, opened, closed, fx["start"], fx["sections"])
        links = link_lifetimes(adj, win)
        for lk in links:
            lk["line"] = line["id"]
        all_links += links
        for k, (f, t) in win.items():
            first_served[k] = min(first_served.get(k, f), f)
            prev_t = last_served.get(k, "")
            last_served[k] = None if (prev_t is None or t is None) else max(prev_t, t)
        today = {(min(a, b), max(a, b)) for a, b in line["edges"]}
        final = {(lk["a"], lk["b"]) for lk in links if lk["to"] is None}
        if final != today:
            problems += 1
            print(f"  !! {line['id']}: final network differs from today's (missing {len(today - final)}, extra {len(final - today)})")
        review.append(f"## {line['name']} (start {fx['start']})")
        review.append("| section | date | conf | stations | flags |")
        review.append("|---|---|---|---|---|")
        for a, b, date, conf in fx["sections"]:
            path = shortest_path(adj, resolve(names, a), resolve(names, b))
            late = [(names[n], opened[n]) for n in path if n in opened and opened[n][:7] > date[:7]]
            flag = "; ".join(f"{n} opened {o}" for n, o in late[:4])
            review.append(f"| {a} → {b} | {date} | {conf} | {len(path)} | {flag} |")
        review.append("")
    stations = {k: {"name": v["name"], "lat": v["lat"], "lon": v["lon"], "zone": v.get("zone"),
                    "opened": hist.get(k, {}).get("opened"), "closed": hist.get(k, {}).get("closed"),
                    "first_served": first_served.get(k), "last_served": last_served.get(k)}
                for k, v in st.items() if k in first_served}
    (DATA / "history.json").write_text(json.dumps({"stations": stations, "links": all_links}, ensure_ascii=False))
    (DATA / "line_fixes_review.md").write_text("\n".join(review))
    print(f"history: {len(all_links)} link lifetimes over {len(stations)} stations; lines whose final network differs from today's: {problems}")
    for y in ("1870-01-01", "1900-01-01", "1930-01-01", "1960-01-01", "1990-01-01", "2010-01-01", "2025-12-31"):
        sv = {k for k, v in stations.items() if v["first_served"] and v["first_served"] <= y and (v["last_served"] is None or y < v["last_served"])}
        ed = [lk for lk in all_links if lk["from"] <= y and (lk["to"] is None or y < lk["to"])]
        print(f"  {y[:4]}: {len(sv):3d} served stations, {len(ed):3d} line links")


if __name__ == "__main__":
    main()
