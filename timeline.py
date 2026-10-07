"""Turn today's line graphs + station dates + the fix table into link lifetimes.

For each line: station S is served from max(its own opening date, the date of the earliest section/line start that covers
it) until its closing date (if any). At every date where the set of served stations changes, the active stations are joined
along the line, skipping over stations that are not served yet (trains ran past them), but never through a branch junction.
Each link then gets a lifetime [from, to) in ISO dates (to = None while it still exists).

Pure functions, no I/O: build_history.py feeds them and writes data/history.json.
"""
from __future__ import annotations

import re
from collections import deque

SUFFIX = re.compile(r"\s*\b(underground station|dlr station|rail station|station)\b\s*$", re.I)


def clean(name: str) -> str:
    s = SUFFIX.sub("", name).replace("(Berks)", "").strip().lower()
    return s.replace("'", "").replace("’", "").replace(".", "")


def resolve(names: dict[str, str], query: str) -> str:
    """Find the line's station whose cleaned name equals, else starts with, the query (case-insensitive)."""
    q = clean(query)
    exact = [k for k, n in names.items() if clean(n) == q]
    if exact:
        return exact[0]
    pre = sorted((k for k, n in names.items() if clean(n).startswith(q)), key=lambda k: len(names[k]))
    if pre:
        return pre[0]
    raise KeyError(f"station {query!r} not on this line")


def shortest_path(adj: dict[str, set[str]], a: str, b: str) -> list[str]:
    prev = {a: None}
    dq = deque([a])
    while dq:
        u = dq.popleft()
        if u == b:
            break
        for v in adj[u]:
            if v not in prev:
                prev[v] = u
                dq.append(v)
    if b not in prev:
        raise ValueError("no path between section ends")
    out, cur = [], b
    while cur is not None:
        out.append(cur)
        cur = prev[cur]
    return out[::-1]


def served_windows(adj, names, opened, closed, start, sections):
    """node -> (served_from, served_to). Dates are ISO strings; None for open-ended."""
    sec_from: dict[str, str] = {}
    for a, b, date, _conf in sections:
        for node in shortest_path(adj, resolve(names, a), resolve(names, b)):
            if node not in sec_from or date < sec_from[node]:
                sec_from[node] = date
    out = {}
    for node in adj:
        base = sec_from.get(node, start)
        o = opened.get(node)
        out[node] = (max(o, base) if o else base, closed.get(node))
    return out


def contract(adj, active: set[str]) -> set[tuple[str, str]]:
    """Join active stations along the line, bridging unserved degree-2 stations; never bridge across a junction."""
    edges: set[tuple[str, str]] = set()
    for u in active:
        for w in adj[u]:
            prev, cur, seen = u, w, {u}
            while cur not in active and len(adj[cur]) == 2 and cur not in seen:
                seen.add(cur)
                nxt = next(x for x in adj[cur] if x != prev)
                prev, cur = cur, nxt
            if cur in active and cur != u:
                edges.add((min(u, cur), max(u, cur)))
    return edges


def link_lifetimes(adj, windows) -> list[dict]:
    points = sorted({d for f, t in windows.values() for d in (f, t) if d})
    live: dict[tuple[str, str], str] = {}
    out = []
    for p in points:
        active = {n for n, (f, t) in windows.items() if f <= p and (t is None or p < t)}
        now = contract(adj, active)
        for e in list(live):
            if e not in now:
                out.append({"a": e[0], "b": e[1], "from": live.pop(e), "to": p})
        for e in now:
            live.setdefault(e, p)
    out += [{"a": e[0], "b": e[1], "from": f, "to": None} for e, f in live.items()]
    return sorted(out, key=lambda x: (x["from"], x["a"], x["b"]))
