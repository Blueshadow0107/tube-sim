"""Regression checks for year-aware journeys and the challenge (no server needed).

Usage: ./.venv/bin/python check_year_routes.py      (exits non-zero on the first failure)
"""
import sys

from app import app, graph

client = app.test_client()
by_name = {}
for sid, st in graph.stations.items():
    by_name.setdefault(st["name"].replace(" Underground Station", "").replace(" Rail Station", ""), sid)


def sid(name: str) -> str:
    return by_name[name]


def route(a: str, b: str, date: str | None = None):
    q = f"/api/route?from={sid(a)}&to={sid(b)}" + (f"&date={date}" if date else "")
    r = client.get(q)
    return r.status_code, r.get_json()


def check(cond: bool, msg: str) -> None:
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        sys.exit(1)


# 1. today is unchanged
code, r = route("Paddington", "Abbey Wood")
check(code == 200 and [l["line"] for l in r["legs"]] == ["elizabeth"], "today: Paddington -> Abbey Wood rides the Elizabeth line direct")
code, r = route("Paddington", "Abbey Wood", "2025-12-31")
check(code == 200 and r["legs"][0]["line"] == "elizabeth", "date=2025-12-31 behaves like today")

# 2. before the Elizabeth line's core opened, Abbey Wood is not on the TfL network
code, r = route("Paddington", "Abbey Wood", "2021-12-31")
check(code == 404 and "Abbey Wood" in r["error"], f"2021: Abbey Wood is not open yet ({r.get('error')})")
code, r = route("Paddington", "Abbey Wood", "2022-06-30")
check(code == 200 and r["legs"][0]["line"] == "elizabeth", "June 2022: Elizabeth line core is open")

# 3. the Victoria line arrives in stages
code, r = route("Brixton", "Oxford Circus", "1970-12-31")
check(code == 404, "1970: Brixton is not open yet")
code, r = route("Brixton", "Oxford Circus", "1971-12-31")
check(code == 200 and r["legs"][0]["line"] == "victoria" and len(r["legs"]) == 1, "end of 1971: Brixton -> Oxford Circus on the Victoria line")
code, r = route("Walthamstow Central", "Warren Street", "1968-12-31")
check(code == 200 and r["legs"][0]["line"] == "victoria", "end of 1968: Victoria line runs to Warren Street")
code, r = route("Walthamstow Central", "Victoria", "1968-12-31")
vic = [l for l in r["legs"] if l["line"] == "victoria"]
check(code == 200 and vic and "Victoria" not in vic[-1]["to_name"] and len(r["legs"]) > 1,
      f"end of 1968: Victoria station exists (District/Circle) but the Victoria line stops at {vic[-1]['to_name'] if vic else '?'}, so the trip needs a change")

# 4. Pimlico opens in September 1972: before that the train skips it
_, r71 = route("Victoria", "Vauxhall", "1972-08-31")
_, r73 = route("Victoria", "Vauxhall", "1972-10-31")
check(r71["totals"]["stops"] == 1 and r73["totals"]["stops"] == 2, f"Victoria -> Vauxhall: 1 stop before Pimlico opened, 2 after ({r71['totals']['stops']}, {r73['totals']['stops']})")

# 5. input handling
r = client.get(f"/api/route?from={sid('Paddington')}&to={sid('Bank')}&date=1950")
check(r.status_code == 400, "malformed date -> 400")

# 6. challenge
r = client.post("/api/challenge/solve", json={"objective": "hops", "rule": "lenient", "budget_seconds": 12})
d = r.get_json()
check(r.status_code == 200 and d["solved"] and d["lines_to_cover"] == 11 and d["totals"]["hops"] == 11, f"today: 11 tube lines solved in 11 hops ({d.get('totals')})")
r = client.post("/api/challenge/solve", json={"objective": "hops", "rule": "lenient", "budget_seconds": 8, "date": "1930-06-30"})
d = r.get_json()
check(r.status_code == 200 and d["solved"] and d["lines_to_cover"] == 9, f"June 1930: {d.get('lines_to_cover')} lines to cover, solved in {d['totals']['hops']} hops")
r = client.post("/api/challenge/solve", json={"date": "1862-06-30"})
check(r.status_code == 400, "1862: no lines running -> 400")
print("all checks passed")
