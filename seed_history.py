#!/usr/bin/env python3
"""One-off seeder: build history.json from cricsheet.org per-team archives.

Downloads India men's + women's match JSONs and converts every completed 2026
international into the history.json shape that fetch_data.py appends to.
Safe to re-run: it rebuilds only cricsheet-sourced entries (id cs_*) and keeps
espn_* entries added later by fetch_data.py.
"""
import io
import json
import os
import urllib.request
import zipfile

SINCE = "2025-01-01"
ZIPS = {
    "men": "https://cricsheet.org/downloads/india_male_json.zip",
    "women": "https://cricsheet.org/downloads/india_female_json.zip",
}
FORMAT_MAP = {"T20": "T20I", "IT20": "T20I", "ODI": "ODI", "ODM": "ODI", "Test": "Test", "MDM": "Test"}
HISTORY = os.path.join(os.path.dirname(__file__), "history.json")


def overs_str(inn):
    balls = 0
    for over in inn.get("overs", []):
        for d in over["deliveries"]:
            ex = d.get("extras", {})
            if "wides" not in ex and "noballs" not in ex:
                balls += 1
    return f"{balls // 6}.{balls % 6}" if balls % 6 else str(balls // 6)


def innings_score(inn, limited):
    runs = sum(d["runs"]["total"] for o in inn.get("overs", []) for d in o["deliveries"])
    wkts = sum(len(d.get("wickets", [])) for o in inn.get("overs", []) for d in o["deliveries"])
    s = str(runs) if wkts == 10 else f"{runs}/{wkts}"
    if inn.get("declared"):
        s += "d"
    if limited:
        s += f" ({overs_str(inn)} ov)"
    return s


def result_text(info):
    out = info["outcome"]
    if out.get("result") == "no result":
        return "No result", "nr"
    if out.get("result") == "draw" or "draw" in out.get("result", ""):
        return "Match drawn", "draw"
    winner = out.get("winner")
    if out.get("result") == "tie" or (not winner and out.get("eliminator")):
        w = out.get("eliminator")
        return (f"Match tied ({w} won the Super Over)" if w else "Match tied"), "tie"
    if not winner:
        return out.get("result", ""), "nr"
    by = out.get("by", {})
    if "innings" in by:
        margin = f"an innings and {by.get('runs', 0)} runs"
    elif "runs" in by:
        margin = f"{by['runs']} run" + ("s" if by["runs"] != 1 else "")
    elif "wickets" in by:
        margin = f"{by['wickets']} wicket" + ("s" if by["wickets"] != 1 else "")
    else:
        margin = ""
    txt = f"{winner} won" + (f" by {margin}" if margin else "")
    if out.get("method"):
        txt += f" ({out['method']})"
    return txt, ("won" if winner == "India" else "lost")


BOWLER_WICKETS = ("bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket")
HOW_SHORT = {"caught": "c", "bowled": "b", "lbw": "lbw", "stumped": "st",
             "caught and bowled": "c&b", "hit wicket": "hit wkt", "run out": "run out"}


def overs_of(balls):
    return f"{balls // 6}.{balls % 6}" if balls % 6 else str(balls // 6)


def innings_detail(d, info, limited):
    """Per-innings batting/bowling cards computed from ball-by-ball data."""
    out = []
    for inn in d.get("innings", []):
        if inn.get("super_over"):
            continue
        order, bat, bowl = [], {}, {}
        runs_total = wkts = 0
        for o in inn.get("overs", []):
            for dl in o["deliveries"]:
                b, bw = dl["batter"], dl["bowler"]
                for nm in (b, dl["non_striker"]):
                    if nm not in bat:
                        bat[nm] = {"r": 0, "b": 0, "how": None}
                        order.append(nm)
                ex = dl.get("extras", {})
                bat[b]["r"] += dl["runs"]["batter"]
                if "wides" not in ex:
                    bat[b]["b"] += 1
                e = bowl.setdefault(bw, {"balls": 0, "r": 0, "w": 0})
                if "wides" not in ex and "noballs" not in ex:
                    e["balls"] += 1
                e["r"] += dl["runs"]["total"] - ex.get("byes", 0) - ex.get("legbyes", 0) - ex.get("penalty", 0)
                runs_total += dl["runs"]["total"]
                for wk in dl.get("wickets", []):
                    wkts += 1
                    po = wk["player_out"]
                    if po not in bat:
                        bat[po] = {"r": 0, "b": 0, "how": None}
                        order.append(po)
                    bat[po]["how"] = HOW_SHORT.get(wk["kind"], wk["kind"])
                    if wk["kind"] in BOWLER_WICKETS:
                        e["w"] += 1
        total = str(runs_total) if wkts == 10 else f"{runs_total}/{wkts}"
        if inn.get("declared"):
            total += "d"
        if limited:
            total += f" ({overs_of(sum(v['balls'] for v in bowl.values()))} ov)"
        dnb = [p for p in info.get("players", {}).get(inn["team"], []) if p not in order]
        out.append({
            "t": inn["team"],
            "total": total,
            "bat": [[nm, bat[nm]["r"], bat[nm]["b"], bat[nm]["how"] or "not out"] for nm in order],
            "dnb": dnb,
            "bowl": [[nm, overs_of(v["balls"]), v["r"], v["w"]] for nm, v in bowl.items()],
        })
    return out


def convert(match_id, d, gender):
    info = d["info"]
    if info["dates"][0] < SINCE or info.get("team_type") != "international":
        return None
    fmt = FORMAT_MAP.get(info["match_type"])
    if not fmt:
        return None
    limited = fmt != "Test"
    per_team = {t: [] for t in info["teams"]}
    for inn in d.get("innings", []):
        if inn.get("super_over"):
            continue
        per_team[inn["team"]].append(innings_score(inn, limited))
    result, india = result_text(info)
    ev = info.get("event", {})
    label = ev.get("name", "")
    if ev.get("stage"):
        matchno = ev["stage"]
    elif ev.get("group") is not None:
        matchno = f"Match {ev.get('match_number', '?')}"
    elif ev.get("match_number"):
        n = ev["match_number"]
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n if n < 20 else n % 10, "th")
        matchno = f"{n}{suf} {fmt}"
    else:
        matchno = fmt
    return {
        "id": f"cs_{match_id}",
        "date": info["dates"][0],
        "gender": gender,
        "format": fmt,
        "series": label,
        "matchNo": matchno,
        "venue": info.get("venue", ""),
        "city": info.get("city", ""),
        "teams": [{"name": t, "score": " & ".join(per_team[t])} for t in info["teams"]],
        "result": result,
        "india": india,
        "innings": innings_detail(d, info, limited),
    }


def main():
    entries = []
    for gender, url in ZIPS.items():
        with urllib.request.urlopen(url, timeout=60) as r:
            z = zipfile.ZipFile(io.BytesIO(r.read()))
        for name in z.namelist():
            if not name.endswith(".json"):
                continue
            m = convert(name[:-5], json.loads(z.read(name)), gender)
            if m:
                entries.append(m)
    kept = []
    if os.path.exists(HISTORY):
        kept = [m for m in json.load(open(HISTORY))["matches"] if not m["id"].startswith("cs_")]
    def key(m):
        return (m["date"], frozenset(t["name"].replace(" Women", "") for t in m["teams"]), m["gender"])
    seen = {key(m) for m in kept}
    entries = [m for m in entries if key(m) not in seen]
    entries.extend(kept)
    entries.sort(key=lambda m: m["date"])
    assert entries, "no matches converted — refusing to write empty history"
    with open(HISTORY, "w") as f:
        json.dump({"source": "cricsheet.org + ESPN", "matches": entries}, f, indent=1)
    print(f"history.json: {len(entries)} matches ({sum(1 for m in entries if m['gender']=='men')} men, "
          f"{sum(1 for m in entries if m['gender']=='women')} women)")


if __name__ == "__main__":
    main()
