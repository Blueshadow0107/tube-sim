"""Merge National Rail + closed stations into data/rail_history.json (stations, link lifetimes).

Inputs : tfl_snapshot.json + station_history.json + history.json (today's TfL network and its history),
         wikidata_london_rail.json (current stations + recorded neighbours), closed_stations.json (Wikipedia categories via Wikidata),
         wikitext_rail.json (infobox dates, category years, neighbour names).
Output : data/rail_history.json  {stations: {id: {...}}, links: [{a, b, from, to, kind, line}]}, plus a coverage report.

Station set: every station that is NOT already a TfL snapshot station, i.e. National Rail and closed ones ("rail" mode).
Lifetime of a station: opened = infobox > Wikidata > category year; closed = infobox > Wikidata > category year; the infobox's
temporary closures ('gaps') are recorded but not applied yet.
Links between stations: (1) neighbours named on the station's Wikipedia page, resolved to a station by normalised name (nearest if
several); (2) Wikidata P197 pairs; (3) fallback for a station left with no link at all: the nearest station that overlaps it in
time within 2.5 km, flagged kind="inferred". A link exists while both ends exist. Links between two TfL stations are not added
(the TfL timeline already draws them).

Usage: python3 build_rail.py
"""
import json
import math
import re
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
FAR = "9999-12-31"


def norm(name: str) -> str:
    s = name.lower().replace("&", " and ").replace("’", "'")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\b(underground|tube|railway|rail|dlr|overground|elizabeth line|london|station|stop|halt|junction)\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\bst\b", "saint", s)
    return re.sub(r"\s+", " ", s).strip()


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la = math.radians((a[0] + b[0]) / 2)
    return math.hypot((a[0] - b[0]) * 111.19, (a[1] - b[1]) * 111.19 * math.cos(la))


def iso(d: str | None, floor: bool = True) -> str | None:
    return d if d and re.match(r"\d{4}-\d{2}-\d{2}$", d) else None


def main() -> None:
    snap = json.load(open(DATA / "tfl_snapshot.json"))
    shist = json.load(open(DATA / "station_history.json"))
    wd = json.load(open(DATA / "wikidata_london_rail.json"))
    closed = json.load(open(DATA / "closed_stations.json"))
    wt = json.load(open(DATA / "wikitext_rail.json"))
    tfl_q = {q for v in shist["stations"].values() for q in v["wikidata"]}

    # ---- station universe (QID keyed), excluding anything already a TfL snapshot station
    st: dict[str, dict] = {}
    for q, v in wd["stations"].items():
        if q in tfl_q:
            continue
        st[q] = {"name": v["name"], "lat": v["lat"], "lon": v["lon"], "open": sorted(v["open"]), "close": sorted(v["close"]), "src": "wikidata"}
    for q, v in closed.items():
        if q in tfl_q:
            continue
        cur = st.setdefault(q, {"name": v["name"], "lat": v["lat"], "lon": v["lon"], "open": [], "close": [], "src": "wikipedia"})
        cur["open"] = sorted(set(cur["open"]) | set(v["open"]))
        cur["close"] = sorted(set(cur["close"]) | set(v["close"]))
        cur["former"] = True
    for q, s in st.items():
        w = wt.get(q, {})
        s["title"] = w.get("title", s["name"])
        s["opened"] = iso(w.get("opened")) or (s["open"][0] if s["open"] else None) or (f"{w['opened_year']}-01-01" if w.get("opened_year") else None)
        s["closed"] = iso(w.get("closed")) or (s["close"][-1] if s["close"] else None) or (f"{w['closed_year']}-12-31" if w.get("closed_year") else None)
        s["gaps"] = w.get("gaps", [])
        if s["opened"] and s["closed"] and s["opened"] > s["closed"]:
            s["opened"] = None
    undated = [q for q, s in st.items() if not s["opened"]]
    print(f"{len(st)} non-TfL stations; {sum(1 for s in st.values() if s['closed'])} with a closing date; {len(undated)} without an opening date (dropped)")
    for q in undated:
        del st[q]

    # ---- name index for resolving neighbour names (also TfL stations, so rail links can end at them)
    by_name: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    for q, s in st.items():
        by_name[norm(s["name"])].append((q, s["lat"], s["lon"]))
        by_name[norm(s["title"])].append((q, s["lat"], s["lon"]))
    tfl_name: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    for k, s in snap["stations"].items():
        tfl_name[norm(s["name"])].append((k, s["lat"], s["lon"]))

    def resolve(name: str, near: tuple[float, float]):
        n = norm(name)
        cand = by_name.get(n, []) + tfl_name.get(n, [])
        if not cand:
            return None
        return min(cand, key=lambda c: km(near, (c[1], c[2])))[0] if min(km(near, (c[1], c[2])) for c in cand) < 12 else None

    links: dict[tuple[str, str], dict] = {}

    def add(a: str, b: str, kind: str, line: str | None) -> None:
        if a == b:
            return
        if a in snap["stations"] and b in snap["stations"]:
            return  # TfL-to-TfL links come from the TfL timeline
        key = (min(a, b), max(a, b))
        if key not in links:
            links[key] = {"a": key[0], "b": key[1], "kind": kind, "line": line}

    for q, s in st.items():
        for name, line in wt.get(q, {}).get("neighbours", []):
            r = resolve(name, (s["lat"], s["lon"]))
            if r:
                add(q, r, "recorded", line)
    for a, b, line in wd["edges"]:
        if a in st and (b in st or b in tfl_q):
            tb = b
            if b in tfl_q:  # map a TfL-matched Wikidata item back to its snapshot key
                tb = next((k for k, v in shist["stations"].items() if b in v["wikidata"]), None)
            if tb:
                add(a, tb, "recorded", line)
        elif b in st and a in tfl_q:
            ta = next((k for k, v in shist["stations"].items() if a in v["wikidata"]), None)
            if ta:
                add(ta, b, "recorded", line)
    n_rec = len(links)

    def life(x: str) -> tuple[str, str]:
        if x in st:
            return st[x]["opened"], st[x]["closed"] or FAR
        h = shist["stations"].get(x, {})
        return h.get("opened") or "1863-01-01", h.get("closed") or FAR

    def pos(x: str) -> tuple[float, float]:
        s = st.get(x) or snap["stations"][x]
        return s["lat"], s["lon"]

    # ---- fallback: stations with no link yet get the nearest time-overlapping station
    linked = {x for k in links for x in k}
    everyone = list(st) + list(snap["stations"])
    n_fb = 0
    for q in list(st):
        if q in linked:
            continue
        o, c = life(q)
        best = None
        for other in everyone:
            if other == q:
                continue
            o2, c2 = life(other)
            if max(o, o2) >= min(c, c2):
                continue
            d = km(pos(q), pos(other))
            if d < 2.5 and (best is None or d < best[0]):
                best = (d, other)
        if best:
            add(q, best[1], "inferred", None)
            n_fb += 1
    print(f"links: {n_rec} recorded, {n_fb} inferred (fallback)")

    out_links = []
    dropped = 0
    for (a, b), l in links.items():
        if km(pos(a), pos(b)) > 10 and "high speed" not in (l["line"] or "").lower():
            dropped += 1  # almost always a neighbour name resolved to the wrong place
            continue
        oa, ca = life(a)
        ob, cb = life(b)
        f, t = max(oa, ob), min(ca, cb)
        if f < t:
            out_links.append({**l, "from": f, "to": None if t == FAR else t})
    print(f"dropped {dropped} links longer than 10 km")
    stations = {q: {"name": s["name"], "lat": s["lat"], "lon": s["lon"], "opened": s["opened"], "closed": s["closed"], "gaps": s["gaps"], "former": bool(s.get("former") or s["closed"])}
                for q, s in st.items()}
    (DATA / "rail_history.json").write_text(json.dumps({"stations": stations, "links": out_links}, ensure_ascii=False))
    linked2 = {x for l in out_links for x in (l["a"], l["b"])}
    print(f"wrote data/rail_history.json: {len(stations)} stations, {len(out_links)} links; stations with a link: {sum(1 for q in stations if q in linked2)}")
    for y in ("1850-01-01", "1900-01-01", "1950-01-01", "1990-01-01", "2025-12-31"):
        live = [q for q, s in stations.items() if s["opened"] <= y and (s["closed"] is None or y < s["closed"])]
        print(f"  {y[:4]}: {len(live)} rail stations open, {sum(1 for l in out_links if l['from'] <= y and (l['to'] is None or y < l['to']))} links")


if __name__ == "__main__":
    main()
