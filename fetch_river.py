"""Fetch River Thames geometry (Greater London + Reading reach) from OpenStreetMap.

Run once; writes data/thames.json as a multipolyline in lat/lon, which
app.py serves at /api/river and the map draws beneath the network.

Usage: python fetch_river.py
"""

import json
from pathlib import Path

import requests

OVERPASS = "https://overpass-api.de/api/interprepreter"
OUT = Path(__file__).parent / "data" / "thames.json"

# Covers Reading (west) to the Thames Barrier (east), Hertford spread (north)
# to Gatwick-ish (south).
BBOX = "51.20,-1.05,51.75,0.40"

QUERY = f"""
[out:json][timeout:120];
way["waterway"="river"]["name"="River Thames"]({BBOX});
out geom;
"""


def simplify(points, eps=0.0006):
    """Drop points within eps degrees of the line between their neighbours."""
    if len(points) < 3:
        return points
    out = [points[0]]
    for p in points[1:-1]:
        lx, ly = out[-1]
        if abs(p[0] - lx) + abs(p[1] - ly) > eps:
            out.append(p)
    out.append(points[-1])
    return out


def main():
    headers = {"User-Agent": "tube-sim-local/1.0 (personal journey planner)"}
    last_err = None
    for endpoint in ("https://overpass-api.de/api/interpreter",
                     "https://overpass.kumi.systems/api/interpreter"):
        try:
            r = requests.post(endpoint, data={"data": QUERY}, headers=headers, timeout=150)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:  # try next mirror
            last_err = e
    else:
        raise last_err

    parts = []
    for way in data.get("elements", []):
        geom = way.get("geometry")
        if not geom or len(geom) < 2:
            continue
        coords = [(g["lat"], g["lon"]) for g in geom]
        parts.append(simplify(coords))

    total = sum(len(p) for p in parts)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"parts": parts}))
    print(f"Wrote {OUT}: {len(parts)} segments, {total} points")


if __name__ == "__main__":
    main()
