"""Read Wikipedia station pages for opening/closing events and neighbouring stations.

Input : data/closed_stations.json (fetch_closed.py) and the stations in data/station_history.json that are NOT in today's
        TfL snapshot (build_history.py); their English Wikipedia titles come from Wikidata sitelinks.
Output: data/wikitext_rail.json   {qid: {title, opened, closed, opened_year, closed_year, gaps, neighbours}}

What is parsed from each page's wikitext:
  - infobox event pairs (years1/events1, years2/events2, ...): "Opened", "Closed", "Reopened" with a day-level date;
  - fallback years from categories ("Railway stations in Great Britain opened in 1874" / "closed in 1990");
  - neighbours from any template with previous/next/left/right parameters (adjacent stations, s-rail-national, s-line ...).
Paced and retrying; a few minutes for ~650 pages.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
OUT = DATA / "wikitext_rail.json"
CACHE = DATA / "cache" / "wikitext_raw.json"
UA = {"User-Agent": "tube-sim/0.2 (personal research project)"}
WP = "https://en.wikipedia.org/w/api.php"
WD = "https://www.wikidata.org/w/api.php"
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}


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
    raise SystemExit("API kept failing")


# ---- date parsing -----------------------------------------------------------

def parse_date(text: str) -> tuple[str, int] | None:
    """Return (ISO date, precision) with precision 3=day, 2=month, 1=year, or None."""
    t = text
    m = re.search(r"\{\{\s*(?:start|end)[ _]date(?: and age)?\s*\|\s*(\d{4})(?:\s*\|\s*(\d{1,2}))?(?:\s*\|\s*(\d{1,2}))?", t, re.I)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        return f"{y}-{int(mo or 1):02d}-{int(d or 1):02d}", 3 if d else 2 if mo else 1
    t = re.sub(r"\{\{[^{}]*\}\}|<[^>]+>|\[\[[^\]|]*\||\]\]|\[\[|'''?", " ", t)
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", t)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}", 3
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", t)
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}", 3
    m = re.search(r"([A-Za-z]+)\s+(\d{4})", t)
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}-01", 2
    m = re.search(r"\b(1[6-9]\d\d|20[0-2]\d)\b", t)
    if m:
        return f"{m.group(1)}-01-01", 1
    return None


def infobox_events(txt: str) -> list[tuple[str, int, str]]:
    """[(date, precision, event text)] from years<N>/events<N> pairs and plain opened/closed params."""
    m = re.search(r"\{\{\s*Infobox[^|{}]*", txt, re.I)
    if not m:
        return []
    block = txt[m.start(): m.start() + 12000]
    ev: list[tuple[str, int, str]] = []
    years = {int(n or 0): v for n, v in re.findall(r"\|\s*years?(\d*)\s*=\s*([^\n]*)", block, re.I)}
    events = {int(n or 0): v for n, v in re.findall(r"\|\s*events?(\d*)\s*=\s*([^\n]*)", block, re.I)}
    for n in sorted(set(years) & set(events)):
        d = parse_date(years[n])
        if d:
            ev.append((d[0], d[1], events[n]))
    for key, label in (("opened", "Opened"), ("open", "Opened"), ("closed", "Closed"), ("close", "Closed")):
        for v in re.findall(rf"\|\s*{key}\s*=\s*([^\n]*)", block, re.I):
            d = parse_date(v)
            if d:
                ev.append((d[0], d[1], label))
    return ev


def life_from_events(ev: list[tuple[str, int, str]]) -> dict:
    """First opening, final closing (if the last relevant event is a closure) and temporary closures ('gaps')."""
    ev = sorted(set(ev))
    out: dict = {"opened": None, "closed": None, "gaps": []}
    state, last_close = None, None
    for d, _p, text in ev:
        low = re.sub(r"<[^>]+>|\{\{[^{}]*\}\}|\[\[|\]\]", " ", text).lower().strip()
        if re.search(r"re-?open|resum|restor", low):
            if last_close:
                out["gaps"].append([last_close, d])
                last_close = None
            state = "open"
        elif re.match(r"(station )?clos|closed|withdraw|ceased|abandon", low) or re.search(r"\bclosed\b|\bclosure\b", low):
            last_close, state = d, "closed"
        elif re.match(r"(first )?opened|open(ing)?\b", low) or re.search(r"\bopened\b", low):
            if out["opened"] is None:
                out["opened"] = d
            state = state or "open"
    if state == "closed" and last_close:
        out["closed"] = last_close
    if out["opened"] and out["closed"] and out["opened"] > out["closed"]:
        out["opened"] = None  # an unrelated event was read as the opening
    return out


def category_years(txt: str) -> tuple[str | None, str | None]:
    o = re.findall(r"\[\[Category:[^\]]*? opened in (\d{4})", txt)
    c = re.findall(r"\[\[Category:[^\]]*? closed in (\d{4})", txt)
    return (min(o) if o else None, max(c) if c else None)


# ---- neighbours ---------------------------------------------------------------

STN_TEMPLATE = re.compile(r"\{\{\s*(?:stnlnk|stn link|rws|rail station link|stn)\s*\|\s*([^|}]+)", re.I)


def link_text(v: str) -> str | None:
    """Station name from a parameter value: [[Target|label]], {{stnlnk|Name}}, {{rws|Name||...}} or plain text."""
    m = STN_TEMPLATE.search(v)
    if m:
        t = m.group(1)
    else:
        v = re.sub(r"<[^>]+>|\{\{[^{}]*\}\}", " ", v)
        m = re.search(r"\[\[([^\]|#]+)", v)
        t = m.group(1) if m else v
    t = re.sub(r"\[\[|\]\]|'''?", "", t).strip()
    t = re.sub(r"\s+(railway|tube|underground|rail|DLR|tram|metro)?\s*(station|stop)\s*(\(.*\))?$", "", t, flags=re.I).strip()
    t = re.sub(r"\s*\(.*\)$", "", t).strip()
    return t if t and len(t) < 60 and not t.lower().startswith(("none", "terminus", "terminal", "end of", "line", "-", "{{")) else None


def read_value(txt: str, pos: int) -> str:
    """Parameter value starting at pos: up to the next '|' or '}}' that is not inside [[..]] or {{..}}."""
    depth, i = 0, pos
    while i < len(txt):
        two = txt[i:i + 2]
        if two in ("[[", "{{"):
            depth += 1
            i += 2
            continue
        if two in ("]]", "}}"):
            if depth == 0:
                break
            depth -= 1
            i += 2
            continue
        if txt[i] == "|" and depth == 0:
            break
        i += 1
    return txt[pos:i]


def neighbours(txt: str) -> list[list[str | None]]:
    """[(station name, line)] from previous/next/left/right parameters; 'line' is the nearest preceding line=/route= value."""
    out: list[list[str | None]] = []
    seen = set()
    line = None
    for m in re.finditer(r"\|\s*(line|route|previous|next|left|right)\d*\s*=", txt, re.I):
        key, val = m.group(1).lower(), read_value(txt, m.end())
        if key in ("line", "route"):
            line = re.sub(r"\[\[([^\]|]*\|)?|\]\]|\{\{[^{}]*\}\}|<[^>]+>|'''?", "", val).strip() or None
            continue
        for part in re.split(r"<br\s*/?>|\n", val):
            nm = link_text(part)
            if nm and (nm, line) not in seen:
                seen.add((nm, line))
                out.append([nm, line])
    return out[:14]


# ---- fetch --------------------------------------------------------------------

def titles_for_extras(qids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(0, len(qids), 40):
        d = api(WD, {"action": "wbgetentities", "ids": "|".join(qids[i:i + 40]), "props": "sitelinks", "sitefilter": "enwiki"})
        for q, e in d.get("entities", {}).items():
            t = e.get("sitelinks", {}).get("enwiki", {}).get("title")
            if t:
                out[q] = t
    return out


def main() -> None:
    closed = json.load(open(DATA / "closed_stations.json"))
    hist = json.load(open(DATA / "station_history.json"))
    extra_q = [q for q, *_ in hist["extra_wikidata"] if q not in closed]
    titles = {q: v["title"] for q, v in closed.items()}
    print(len(titles), "closed-station pages;", len(extra_q), "other Wikidata stations to look up")
    titles.update(titles_for_extras(extra_q))
    print(len(titles), "pages to read")
    q_of_title = {t: q for q, t in titles.items()}
    # raw pages are cached (data/cache is gitignored) so a parser fix does not need a re-download
    CACHE.parent.mkdir(exist_ok=True)
    raw: dict[str, dict] = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    items = sorted(q_of_title)
    todo = [t for t in items if q_of_title[t] not in raw]
    for i in range(0, len(todo), 20):
        batch = todo[i:i + 20]
        d = api(WP, {"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "titles": "|".join(batch), "redirects": 1})
        redirect = {r["from"]: r["to"] for r in d["query"].get("redirects", [])}
        want = {redirect.get(t, t): q_of_title[t] for t in batch}
        for p in d["query"]["pages"]:
            if "revisions" not in p or p["title"] not in want:
                continue
            raw[want[p["title"]]] = {"title": p["title"], "text": p["revisions"][0]["slots"]["main"]["content"]}
        if (i // 20) % 5 == 0:
            print(f"  fetched {min(i + 20, len(todo))}/{len(todo)} pages", flush=True)
    CACHE.write_text(json.dumps(raw, ensure_ascii=False))
    out: dict[str, dict] = {}
    for q, page in raw.items():
        txt = page["text"]
        life = life_from_events(infobox_events(txt))
        oy, cy = category_years(txt)
        out[q] = {"title": page["title"], **life, "opened_year": oy, "closed_year": cy, "neighbours": neighbours(txt)}
    OUT.write_text(json.dumps(out, ensure_ascii=False))
    n = len(out)
    print(f"{n} pages parsed -> {OUT}")
    print(f"  opened (infobox) {sum(1 for v in out.values() if v['opened'])}, closed (infobox) {sum(1 for v in out.values() if v['closed'])}, "
          f"closed year from categories {sum(1 for v in out.values() if v['closed_year'])}, with neighbours {sum(1 for v in out.values() if v['neighbours'])}")


if __name__ == "__main__":
    main()
