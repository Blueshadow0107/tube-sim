"""Contact sheet of the network through time from data/history.json (needs matplotlib; any interpreter that has it).

Usage: python3 preview_history.py   -> data/history_preview.png
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt

DATA = Path(__file__).resolve().parent / "data"
YEARS = ["1870-01-01", "1900-01-01", "1930-01-01", "1960-01-01", "1990-01-01", "2025-12-31"]


def main() -> None:
    hist = json.load(open(DATA / "history.json"))
    snap = json.load(open(DATA / "tfl_snapshot.json"))
    colour = {l["id"]: l["color"] for l in snap["lines"]}
    st = hist["stations"]
    fig, axes = plt.subplots(2, 3, figsize=(15, 9.4), facecolor="#101418")
    for ax, y in zip(axes.flat, YEARS):
        ax.set_facecolor("#101418")
        live = [l for l in hist["links"] if l["from"] <= y and (l["to"] is None or y < l["to"])]
        for l in live:
            a, b = st[l["a"]], st[l["b"]]
            ax.plot([a["lon"], b["lon"]], [a["lat"], b["lat"]], color=colour[l["line"]], lw=1.6, solid_capstyle="round")
        served = [s for s in st.values() if s["first_served"] and s["first_served"] <= y and (s["last_served"] is None or y < s["last_served"])]
        ax.scatter([s["lon"] for s in served], [s["lat"] for s in served], s=7, color="#f2f2f2", zorder=3)
        ax.set_xlim(-0.62, 0.35)
        ax.set_ylim(51.3, 51.72)
        ax.set_aspect(1 / 0.62)
        ax.set_title(f"{y[:4]}   {len(served)} stations, {len(live)} links", color="#e6e6e6", fontsize=12)
        ax.axis("off")
    fig.tight_layout()
    out = DATA / "history_preview.png"
    fig.savefig(out, dpi=100, facecolor=fig.get_facecolor())
    print("wrote", out)


if __name__ == "__main__":
    main()
