"""Fetch London railway station history from Wikidata: opening/closing dates, coordinates, recorded neighbours.

Stations: every item in a few bounding boxes (Greater London plus the Reading and Chesham/Amersham corridors that
tube-sim's Elizabeth and Metropolitan lines reach) typed as a railway station (any subclass), plus items typed
former / disused / closed station. Edges: P197 "adjacent station" statements, with the P81 "connecting line" qualifier.
Several small boxes are used because one big box makes the query service time out.

Output: data/wikidata_london_rail.json   (./.venv/bin/python fetch_history.py; the WDQS endpoint rate-limits, so it retries)
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "wikidata_london_rail.json"
BOXES = [  # (south-west lon, lat), (north-east lon, lat)
    ((-0.56, 51.26), (0.38, 51.72)),    # Greater London
    ((-1.05, 51.38), (-0.56, 51.56)),   # Reading, Twyford, Maidenhead, Taplow, Burnham, Slough
    ((-0.72, 51.60), (-0.56, 51.72)),   # Amersham, Chesham, Chalfont & Latimer
]
LABEL = 'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }'


def box(b) -> str:
    (w, s), (e, n) = b
    return (f'SERVICE wikibase:box {{ ?s wdt:P625 ?coord . bd:serviceParam wikibase:cornerSouthWest "Point({w} {s})"^^geo:wktLiteral ; '
            f'wikibase:cornerNorthEast "Point({e} {n})"^^geo:wktLiteral . }}')


def sparql(q: str, tries: int = 5) -> list[dict]:
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q)
    req = urllib.request.Request(url, headers={"User-Agent": "tube-sim/0.2 (personal research project)"})
    for _ in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=170) as r:
                return json.load(r)["results"]["bindings"]
        except urllib.error.HTTPError as e:
            wait = int(e.headers.get("Retry-After", 30)) if e.code == 429 else 15
        except Exception:
            wait = 20
        print("  retrying in", wait, "s", flush=True)
        time.sleep(wait)
    raise SystemExit("Wikidata query failed")


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[1]


def main() -> None:
    stations: dict[str, dict] = {}
    adj_rows: list[dict] = []

    def add(rows: list[dict], former: bool) -> None:
        for b in rows:
            d = stations.setdefault(qid(b["s"]["value"]), {"name": b["sLabel"]["value"], "open": set(), "close": set(), "classes": set(), "lat": None, "lon": None})
            m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", b["coord"]["value"])
            if m:
                d["lon"], d["lat"] = float(m.group(1)), float(m.group(2))
            if "open" in b:
                d["open"].add(b["open"]["value"][:10])
            if "close" in b:
                d["close"].add(b["close"]["value"][:10])
            if "clsLabel" in b:
                d["classes"].add(b["clsLabel"]["value"])
            if former:
                d["classes"].add("former/disused")

    for i, b in enumerate(BOXES):
        print(f"box {i + 1}/{len(BOXES)}: stations ...", flush=True)
        add(sparql(f"""SELECT ?s ?sLabel ?coord ?open ?close ?clsLabel WHERE {{ {box(b)}
          ?s wdt:P31 ?cls . ?cls wdt:P279* wd:Q55488 .
          OPTIONAL {{ ?s wdt:P1619 ?open }} OPTIONAL {{ ?s wdt:P3999 ?close }} {LABEL} }}"""), False)
        time.sleep(4)
        print(f"box {i + 1}/{len(BOXES)}: former / disused stations ...", flush=True)
        add(sparql(f"""SELECT ?s ?sLabel ?coord ?open ?close ?clsLabel WHERE {{ {box(b)}
          ?s wdt:P31 ?cls . ?cls wdt:P279* wd:Q55488 .
          FILTER EXISTS {{ ?s wdt:P31 ?x . ?x rdfs:label ?l . FILTER(LANG(?l) = 'en' && (CONTAINS(LCASE(?l), 'former') || CONTAINS(LCASE(?l), 'disused') || CONTAINS(LCASE(?l), 'closed') || CONTAINS(LCASE(?l), 'abandoned'))) }}
          OPTIONAL {{ ?s wdt:P1619 ?open }} OPTIONAL {{ ?s wdt:P3999 ?close }} {LABEL} }}"""), True)
        time.sleep(4)
        print(f"box {i + 1}/{len(BOXES)}: adjacency ...", flush=True)
        adj_rows += sparql(f"""SELECT ?s ?b ?lineLabel WHERE {{ {box(b)}
          ?s p:P197 ?st . ?st ps:P197 ?b . OPTIONAL {{ ?st pq:P81 ?line }} {LABEL} }}""")
        time.sleep(4)
    edges = sorted({(qid(b["s"]["value"]), qid(b["b"]["value"]), b.get("lineLabel", {}).get("value", "")) for b in adj_rows})
    edges = [list(e) for e in edges if e[0] in stations and e[1] in stations]
    out = {"stations": {k: {**v, "open": sorted(v["open"]), "close": sorted(v["close"]), "classes": sorted(v["classes"])} for k, v in stations.items() if v["lat"] is not None},
           "edges": edges}
    OUT.write_text(json.dumps(out, ensure_ascii=False))
    n = len(out["stations"])
    print(f"{n} stations ({sum(1 for v in out['stations'].values() if v['open'])} dated, {sum(1 for v in out['stations'].values() if v['close'])} closed), {len(edges)} recorded links -> {OUT}")


if __name__ == "__main__":
    main()
