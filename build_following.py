#!/usr/bin/env python3
"""Backfill follow.json: franchise-cricket appearances for followed players.

International appearances are computed client-side from data.json/history.json
(always fresh via the cron); this script covers what those files don't —
franchise leagues — from cricsheet.org team archives. Re-run to refresh
(e.g. after an IPL season). Merge-not-needed: output is fully rebuilt.
"""
import io
import json
import os
import re
import urllib.request
import zipfile

SINCE = "2026-01-01"
FOLLOW = [{
    "name": "Vaibhav Sooryavanshi",           # ESPN spelling; cricsheet uses Suryavanshi
    "pattern": r"s[ou]{1,2}ryavanshi",
    "note": "India & Rajasthan Royals",
    "gender": "men",
    "zips": [("IPL", "https://cricsheet.org/downloads/rajasthan_royals_json.zip")],
}]
OUT = os.path.join(os.path.dirname(__file__), "follow.json")


def player_line(d, pat):
    """(bat [r, b, how], bowl [overs, runs, wkts]) for the matched player, or None."""
    bat = bowl = None
    name = None
    for inn in d.get("innings", []):
        if inn.get("super_over"):
            continue
        r = b = 0
        how = None
        bowler = {"balls": 0, "r": 0, "w": 0}
        batted = bowled = False
        for o in inn.get("overs", []):
            for dl in o["deliveries"]:
                ex = dl.get("extras", {})
                if pat.search(dl["batter"]):
                    name = name or dl["batter"]
                    batted = True
                    r += dl["runs"]["batter"]
                    if "wides" not in ex:
                        b += 1
                if pat.search(dl["bowler"]):
                    name = name or dl["bowler"]
                    bowled = True
                    if "wides" not in ex and "noballs" not in ex:
                        bowler["balls"] += 1
                    bowler["r"] += dl["runs"]["total"] - ex.get("byes", 0) - ex.get("legbyes", 0) - ex.get("penalty", 0)
                for wk in dl.get("wickets", []):
                    if pat.search(wk["player_out"]):
                        how = wk["kind"]
                    if pat.search(dl["bowler"]) and wk["kind"] not in ("run out", "retired hurt", "retired out"):
                        bowler["w"] += 1
        if batted:
            bat = [r, b, "not out" if how is None else how]
        if bowled:
            ov = f"{bowler['balls'] // 6}.{bowler['balls'] % 6}" if bowler["balls"] % 6 else str(bowler["balls"] // 6)
            bowl = [ov, bowler["r"], bowler["w"]]
    return name, bat, bowl


def main():
    out = []
    for f in FOLLOW:
        pat = re.compile(f["pattern"], re.I)
        apps = []
        for comp, url in f["zips"]:
            with urllib.request.urlopen(url, timeout=120) as r:
                z = zipfile.ZipFile(io.BytesIO(r.read()))
            for nm in z.namelist():
                if not nm.endswith(".json"):
                    continue
                d = json.loads(z.read(nm))
                info = d["info"]
                if info["dates"][0] < SINCE:
                    continue
                name, bat, bowl = player_line(d, pat)
                if not (bat or bowl):
                    continue
                team = next((t for t in info["teams"] if any(pat.search(p) for p in info.get("players", {}).get(t, []))), None)
                vs = next((t for t in info["teams"] if t != team), "?")
                won = info.get("outcome", {}).get("winner")
                apps.append({
                    "date": info["dates"][0],
                    "comp": comp,
                    "label": (lambda ev: ev.get("stage") or (f"Match {ev['match_number']}" if ev.get("match_number") else comp))(info.get("event", {})),
                    "team": team, "vs": vs,
                    "city": info.get("city", ""),
                    "bat": bat, "bowl": bowl,
                    "won": (won == team) if won else None,
                })
        apps.sort(key=lambda a: a["date"])
        out.append({"name": f["name"], "note": f["note"], "gender": f["gender"],
                    "pattern": f["pattern"], "appearances": apps})
        runs = sum(a["bat"][0] for a in apps if a["bat"])
        print(f"{f['name']}: {len(apps)} franchise appearances, {runs} runs")
    with open(OUT, "w") as fp:
        json.dump({"players": out}, fp, indent=1)


if __name__ == "__main__":
    main()
