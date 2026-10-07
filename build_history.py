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
from pathlib import Path

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


if __name__ == "__main__":
    main()
