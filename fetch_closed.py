"""Closed and former London railway stations: Wikipedia categories -> Wikidata entities (dates, coordinates, neighbours).

Why this route: Wikidata's own typing (query service) knows only ~25 former/disused stations in London, but Wikipedia's
"Former railway stations in <London borough>" and "Disused London Underground" categories list the stations people have
actually written up. We take those page titles, map them to Wikidata items (pageprops), then read each item's claims through
the entity API (steadier than SPARQL): P625 coordinates, P1619 opened, P3999 closed, P197 adjacent station (+P81 line qualifier).

Output: data/closed_stations.json   (./.venv/bin/python fetch_closed.py; paced and retrying, takes a few minutes)
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "closed_stations.json"
UA = {"User-Agent": "tube-sim/0.2 (personal research project)"}
BOX = (-0.56, 51.26, 0.38, 51.72)  # keep Greater London only (lon_min, lat_min, lon_max, lat_max)


def api(base: str, params: dict) -> dict:
    url = f"{base}?{urllib.parse.urlencode({**params, 'format': 'json', 'formatversion': 2})}"
    for attempt in range(8):
        try:
            time.sleep(1.0)
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            wait = int(e.headers.get("Retry-After", 20 * (attempt + 1)))
        except Exception:
            wait = 15
        print("  retrying in", wait, "s", flush=True)
        time.sleep(wait)
    raise SystemExit("API kept failing: " + base)


WP = "https://en.wikipedia.org/w/api.php"
WD = "https://www.wikidata.org/w/api.php"


def london_categories() -> list[str]:
    cats: list[str] = []
    for prefix in ("Disused railway stations in", "Former railway stations in", "Disused London Underground", "Former London Underground",
                   "Closed London Underground", "Disused stations on"):
        cont: dict = {}
        while True:
            d = api(WP, {"action": "query", "list": "allcategories", "acprefix": prefix, "aclimit": 500, **cont})
            cats += [c["category"] for c in d["query"]["allcategories"]]
            if "continue" not in d:
                break
            cont = d["continue"]
    keep = [c for c in cats if ("London" in c or "Middlesex" in c) and "Londonderry" not in c]
    return sorted(set(keep))


def category_pages(cats: list[str]) -> dict[str, str]:
    pages: dict[str, str] = {}
    for c in cats:
        cont: dict = {}
        while True:
            d = api(WP, {"action": "query", "list": "categorymembers", "cmtitle": "Category:" + c, "cmlimit": 500, "cmtype": "page", **cont})
            for m in d["query"]["categorymembers"]:
                pages.setdefault(m["title"], c)
            if "continue" not in d:
                break
            cont = d["continue"]
    return pages


def qids_for(titles: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(0, len(titles), 40):
        d = api(WP, {"action": "query", "prop": "pageprops", "ppprop": "wikibase_item", "titles": "|".join(titles[i:i + 40]), "redirects": 1})
        for p in d["query"]["pages"]:
            q = p.get("pageprops", {}).get("wikibase_item")
            if q:
                out[p["title"]] = q
    return out


def time_val(claim: dict) -> str | None:
    v = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
    if not v or "time" not in v:
        return None
    t = v["time"].lstrip("+")
    y, mo, d = t[:10].split("-")
    if int(y) < 1000:
        return None
    return f"{y}-{mo if mo != '00' else '01'}-{d if d != '00' else '01'}"


def entities(qids: list[str]) -> dict[str, dict]:
    ents: dict[str, dict] = {}
    for i in range(0, len(qids), 40):
        d = api(WD, {"action": "wbgetentities", "ids": "|".join(qids[i:i + 40]), "props": "claims|labels", "languages": "en"})
        ents.update(d.get("entities", {}))
    return ents


def main() -> None:
    cats = london_categories()
    print(len(cats), "London categories")
    pages = category_pages(cats)
    print(len(pages), "pages")
    q_of = qids_for(sorted(pages))
    print(len(q_of), "with a Wikidata item")
    ents = entities(sorted(set(q_of.values())))
    out: dict[str, dict] = {}
    skipped = 0
    for title, q in q_of.items():
        e = ents.get(q, {})
        cl = e.get("claims", {})
        co = cl.get("P625", [{}])[0].get("mainsnak", {}).get("datavalue", {}).get("value")
        if not co or not (BOX[0] <= co["longitude"] <= BOX[2] and BOX[1] <= co["latitude"] <= BOX[3]):
            skipped += 1
            continue
        adj = []
        for c in cl.get("P197", []):
            tgt = c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
            line = [x.get("datavalue", {}).get("value", {}).get("id") for x in c.get("qualifiers", {}).get("P81", [])]
            if tgt:
                adj.append([tgt, line[0] if line else None])
        out[q] = {
            "name": e.get("labels", {}).get("en", {}).get("value", title),
            "title": title, "category": pages[title],
            "lat": co["latitude"], "lon": co["longitude"],
            "open": sorted({t for c in cl.get("P1619", []) if (t := time_val(c))}),
            "close": sorted({t for c in cl.get("P3999", []) if (t := time_val(c))}),
            "adjacent": adj,
        }
    OUT.write_text(json.dumps(out, ensure_ascii=False))
    n = len(out)
    print(f"{n} London-area stations kept ({skipped} outside the box or without coordinates) -> {OUT}")
    print(f"  with an opening date {sum(1 for v in out.values() if v['open'])}, closing date {sum(1 for v in out.values() if v['close'])}, "
          f"recorded neighbours {sum(1 for v in out.values() if v['adjacent'])}")


if __name__ == "__main__":
    main()
