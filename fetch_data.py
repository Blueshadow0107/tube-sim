"""Fetch a static snapshot of the London Tube network from the TfL API.

No API key required. Run once to create data/tfl_snapshot.json; re-run any
time to refresh (e.g. after network changes or station renames).

The API returns ordered stop sequences per direction/branch, fragmented into
segments, and different sequences for the same line may represent different
stopping patterns (e.g. Metropolitan fast services that skip stations).
We therefore reduce each line to the union of consecutive-station pairs
across every sequence — an undirected multi-pattern edge set. Both routing
and the challenge solver build per-line adjacency from these edges.

Usage: python fetch_data.py
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "https://api.tfl.gov.uk"
OUT = Path(__file__).parent / "data" / "tfl_snapshot.json"

MODES = ("tube", "overground", "dlr", "elizabeth-line")

# Canonical map colours.
LINE_COLORS = {
    # tube
    "bakerloo": "#B36305",
    "central": "#E32017",
    "circle": "#FFD300",
    "district": "#00782A",
    "hammersmith-city": "#F3A9BB",
    "jubilee": "#A0A5A9",
    "metropolitan": "#9B0056",
    "northern": "#000000",
    "piccadilly": "#003688",
    "victoria": "#0098D4",
    "waterloo-city": "#95CDBA",
    # overground (2024 rebrand names)
    "liberty": "#6C7276",
    "lioness": "#FBAE00",
    "mildmay": "#009FE3",
    "suffragette": "#00A166",
    "weaver": "#9C1B2E",
    "windrush": "#D22730",
    # others
    "dlr": "#00A4A7",
    "elizabeth": "#6950A1",
}

# Typical cruising speeds for the static time estimate (km/h).
MODE_SPEEDS = {
    "tube": 32.0,
    "overground": 48.0,
    "dlr": 45.0,
    "elizabeth-line": 70.0,
}


def get(path, **params):
    r = requests.get(f"{API}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def clean_name(name):
    for suffix in (" Underground Station", " Rail Station", " DLR Station"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def fetch_line_list():
    lines = []
    for mode in MODES:
        for l in get(f"/Line/Mode/{mode}"):
            lines.append((l["id"], l["name"], mode))
    unexpected = [i for i, _, _ in lines if i not in LINE_COLORS]
    if unexpected:
        print(f"WARNING: lines without a hardcoded colour: {unexpected}", file=sys.stderr)
    return lines


def fetch_line_detail(line_id):
    """Return (stations dict, hub map, undirected edge set) for one line.

    stations keyed by naptan id; hub map: naptan -> hubNaptanCode (or itself).
    """
    seq_data = get(f"/Line/{line_id}/Route/Sequence/all", excludeEmptyStops=True)
    stops_data = get(f"/Line/{line_id}/StopPoints")

    stations = {}
    hubs = {}
    for sp in stops_data:
        sid = sp["naptanId"]
        hubs[sid] = sp.get("hubNaptanCode") or sid
        zone = None
        for prop in sp.get("additionalProperties", []):
            if prop.get("key") == "Zone":
                zone = prop.get("value")
                break
        stations[sid] = {
            "name": clean_name(sp["commonName"]),
            "lat": sp["lat"],
            "lon": sp["lon"],
            "zone": zone,
            "on_line": True,
        }

    edges = set()
    for seq in seq_data.get("stopPointSequences", []):
        stops = seq["stopPoint"]
        for sp in stops:
            sid = sp["id"]
            if sid not in stations:
                stations[sid] = {
                    "name": clean_name(sp["name"]),
                    "lat": sp["lat"],
                    "lon": sp["lon"],
                    "zone": None,
                    "on_line": True,
                }
        for a, b in zip(stops, stops[1:]):
            edges.add((a["id"], b["id"]))

    return stations, hubs, sorted(edges)


def main():
    line_list = fetch_line_list()
    print(f"Lines: {len(line_list)}")

    all_stations = {}
    hub_by_naptan = {}
    lines = []
    for lid, lname, mode in line_list:
        stations, hubs, edges = fetch_line_detail(lid)
        hub_by_naptan.update(hubs)
        for sid, st in stations.items():
            if sid not in all_stations:
                all_stations[sid] = {
                    "name": st["name"],
                    "lat": st["lat"],
                    "lon": st["lon"],
                    "zone": st["zone"],
                    "lines": set(),
                }
            if all_stations[sid]["zone"] is None:
                all_stations[sid]["zone"] = st["zone"]
            all_stations[sid]["lines"].add(lid)
        lines.append(
            {
                "id": lid,
                "name": lname,
                "color": LINE_COLORS.get(lid, "#888888"),
                "mode": mode,
                "edges": edges,
            }
        )
        print(f"  {lid} ({mode}): {len(edges)} edges")
        time.sleep(0.2)  # be polite to the keyless API

    # Merge stops into station hubs (hubNaptanCode): the same physical
    # station appears under different naptan ids across modes (e.g. tube
    # Farringdon 940GZZLU... vs Elizabeth 910G...). Canonical node = hub.
    canonical = {}
    for naptan in all_stations:
        canonical[naptan] = hub_by_naptan.get(naptan, naptan)

    def merge_stations():
        merged = {}
        for naptan, st in all_stations.items():
            cid = canonical[naptan]
            if cid not in merged:
                merged[cid] = {
                    "name": st["name"],
                    "lat": st["lat"],
                    "lon": st["lon"],
                    "zone": st["zone"],
                    "lines": set(st["lines"]),
                }
            else:
                m = merged[cid]
                m["lines"] |= st["lines"]
                if m["zone"] is None:
                    m["zone"] = st["zone"]
                # prefer the shorter (usually tube) name: drop mode qualifiers
                if len(st["name"]) < len(m["name"]):
                    m["name"] = st["name"]
        return merged

    merged_stations = merge_stations()

    dropped_self_loops = 0
    for line in lines:
        remapped = set()
        for a, b in line["edges"]:
            ca, cb = canonical[a], canonical[b]
            if ca == cb:
                dropped_self_loops += 1
                continue
            remapped.add(tuple(sorted((ca, cb))))
        line["edges"] = sorted(remapped)

    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "modes": list(MODES),
        "speeds_kmh": MODE_SPEEDS,
        "lines": lines,
        "stations": {
            sid: {
                "name": st["name"],
                "lat": st["lat"],
                "lon": st["lon"],
                "zone": st["zone"],
                "lines": sorted(st["lines"]),
            }
            for sid, st in sorted(merged_stations.items())
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, indent=1))
    n_edges = sum(len(l["edges"]) for l in lines)
    print(
        f"Wrote {OUT}: {len(snapshot['stations'])} stations (hub-merged), "
        f"{len(lines)} lines, {n_edges} line edges, "
        f"{dropped_self_loops} intra-hub edges dropped"
    )


if __name__ == "__main__":
    main()
