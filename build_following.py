#!/usr/bin/env python3
"""Build follow.json: every non-international appearance a followed player makes.

International appearances are computed client-side from data.json/history.json
(always fresh via the cron). This script covers everything those files miss:

  • franchise leagues (IPL) from cricsheet.org team archives — ball-by-ball exact,
    but only published after a season, so it is a backfill;
  • Indian DOMESTIC cricket (Duleep, Ranji, SMAT, Vijay Hazare) from ESPN, matched on
    the player's ESPN athlete id rather than a name regex.

The domestic half is why this runs daily. Without it the card went silent for seven
weeks while Vaibhav Sooryavanshi opened the batting for East Zone through the Duleep
Trophy — including the final the site was showing on its own front page.

Incremental: event ids already examined are remembered in follow.json, so a re-run
only fetches matches it has never seen.
"""
import io
import json
import os
import re
import urllib.request
import zipfile
from datetime import date, datetime, timedelta

SINCE = "2026-01-01"
FOLLOW = [{
    "name": "Vaibhav Sooryavanshi",           # ESPN spelling; cricsheet uses Suryavanshi
    "pattern": r"s[ou]{1,2}ryavanshi",
    "espnId": "1408688",                      # www.espncricinfo.com/ci/content/player/1408688.html
    "note": "India · Rajasthan Royals · East Zone",
    "gender": "men",
    "zips": [("IPL", "https://cricsheet.org/downloads/rajasthan_royals_json.zip")],
}]
OUT = os.path.join(os.path.dirname(__file__), "follow.json")

ESPN = "https://site.api.espn.com/apis/site/v2/sports/cricket"
# An honest project UA — ESPN's edge 403s spoofed browser agents from servers.
UA = {"User-Agent": "india-cricket-tracker (+https://github.com/danpune/india-cricket-tracker)"}
# The Indian domestic competitions a followed player can turn out in. IPL (8048) is
# deliberately NOT here: cricsheet already covers it ball-by-ball above, and scanning
# it twice would double-count every innings.
DOM_LEAGUES = ["8630", "8050", "8661", "8890"]   # Duleep · Ranji · SMAT · Vijay Hazare


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


def espn_get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def _stats(node):
    """ESPN buries a player's card at linescores[].linescores[].statistics.categories[]."""
    out = {}
    for cat in (node.get("statistics") or {}).get("categories", []):
        for st in cat.get("stats", []):
            out[st["name"]] = st.get("displayValue")
    return out


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def espn_event_ids(lid, since):
    """Every event id on a league's calendar between `since` and today."""
    board = espn_get(f"{ESPN}/{lid}/scoreboard")
    league = board["leagues"][0]
    today = date.today().isoformat()
    ids = []
    for d in [c[:10] for c in league.get("calendar", [])]:
        if not (since <= d <= today):
            continue
        try:
            evs = espn_get(f"{ESPN}/{lid}/scoreboard?dates={d.replace('-', '')}").get("events", [])
        except Exception:
            continue
        ids += [e["id"] for e in evs if "id" in e]
    return league.get("name", lid), sorted(set(ids))


def espn_card(lid, comp, eid, aid):
    """(appearance | None, finished?) for the followed player in one event.

    A first-class match gives him up to two innings, so both are kept — reporting only
    the first would have shown his 92 in the Duleep semi-final and silently dropped the
    40 that followed it.
    """
    s = espn_get(f"{ESPN}/{lid}/summary?event={eid}")
    c = (s.get("header", {}).get("competitions") or [{}])[0]
    team, bats, bowls = None, [], []
    for side in s.get("rosters", []):
        for p in side.get("roster", []):
            if (p.get("athlete") or {}).get("id") != aid:
                continue
            team = (side.get("team") or {}).get("displayName", "")
            for per in p.get("linescores", []):
                for inn in per.get("linescores", []) or []:
                    d = _stats(inn)
                    if d.get("batted") == "1":
                        # `dismissal == "0"` is the authority for a not-out: ESPN leaves
                        # dismissalCard EMPTY for bowled, so a blank card is not "not out".
                        bats.append([_int(d.get("runs")), _int(d.get("ballsFaced")),
                                     "not out" if d.get("dismissal") == "0"
                                     else (d.get("dismissalCard") or "b")])
                    if d.get("overs") and d.get("overs") not in ("0", "0.0"):
                        bowls.append([d.get("overs"), _int(d.get("conceded")), _int(d.get("wickets"))])
    # Only trust "he did not play" when a roster was actually present. ESPN does return
    # HTTP 200 with an empty rosters[], and marking that event seen would drop a real
    # appearance permanently — nothing ever looks at it again.
    done = ((c.get("status", {}).get("type", {}) or {}).get("state") == "post"
            and bool(s.get("rosters")))
    if not team or not (bats or bowls):
        return None, done
    sides = c.get("competitors", [])
    vs = next((t["team"]["displayName"] for t in sides
               if t.get("team", {}).get("displayName") != team), "?")
    # ESPN returns `winner` as a bool in some leagues and the STRING "true" in others.
    winner = next((t["team"]["displayName"] for t in sides
                   if str(t.get("winner", "")).lower() == "true"), None)
    if winner is None:
        # Domestic finals come back with winner 'false' on BOTH sides even when one
        # clearly won — the 2026/27 Duleep final did. ESPN's own match note names the
        # winner; use that rather than inferring one from the scores, and leave it
        # unknown if the note does not say.
        note = next((n.get("text", "") for n in (s.get("notes") or [])), "")
        for t in sides:
            nm = t.get("team", {}).get("displayName", "")
            if nm and re.search(re.escape(nm) + r"\s+won\b", note, re.I):
                winner = nm
                break
    venue = (c.get("venue") or {}).get("fullName", "")
    return {
        "date": c.get("date", "")[:10],
        "comp": comp,
        "label": c.get("description", "") or comp,
        "team": team, "vs": vs,
        "city": venue.split(",")[-1].strip(),
        "bat": bats[0] if bats else None,
        "bat2": bats[1] if len(bats) > 1 else None,
        "bowl": bowls[0] if bowls else None,
        "bowl2": bowls[1] if len(bowls) > 1 else None,
        "won": (winner == team) if winner else None,
    }, done


def espn_domestic(aid, seen):
    """Domestic appearances for one athlete. `seen` is mutated with every event id
    examined, so tomorrow's run only pays for matches played since today's."""
    apps = []
    for lid in DOM_LEAGUES:
        try:
            comp, ids = espn_event_ids(lid, SINCE)
        except Exception:
            continue                      # fail-safe: a dead league id just contributes nothing
        for eid in ids:
            if eid in seen:
                continue
            try:
                a, done = espn_card(lid, comp, eid, aid)
            except Exception:
                continue
            # Only stop re-checking an event once it is FINISHED. Marking an in-progress
            # match seen would freeze it at day-one figures forever — and a Duleep or
            # Ranji match runs four days, so a daily run would hit that every time.
            if done:
                seen.add(eid)
            if a:
                apps.append(a)
    return apps


def main():
    prior = {}
    if os.path.exists(OUT):
        try:
            prior = {p["name"]: p for p in json.load(open(OUT)).get("players", [])}
        except Exception:
            pass
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
        # carry forward what previous runs already learned, then add only what is new
        prev = prior.get(f["name"], {})
        seen = set(prev.get("seen") or [])
        kept = [a for a in prev.get("appearances", []) if a.get("comp") not in
                {c for c, _ in f["zips"]}]          # franchise half is rebuilt above
        if f.get("espnId"):
            kept += espn_domestic(f["espnId"], seen)
        apps += kept
        # one appearance per (date, competition) — a re-run must not duplicate
        uniq = {}
        for a in apps:
            uniq[(a["date"], a["comp"])] = a
        apps = sorted(uniq.values(), key=lambda a: a["date"])
        out.append({"name": f["name"], "note": f["note"], "gender": f["gender"],
                    "pattern": f["pattern"], "espnId": f.get("espnId"),
                    "teams": sorted({a["team"] for a in apps if a.get("team")}),
                    "seen": sorted(seen), "appearances": apps})
        runs = sum(a["bat"][0] for a in apps if a["bat"]) + \
               sum(a["bat2"][0] for a in apps if a.get("bat2"))
        comps = {}
        for a in apps:
            comps[a["comp"]] = comps.get(a["comp"], 0) + 1
        print(f"{f['name']}: {len(apps)} appearances {comps}, {runs} runs")
    with open(OUT, "w") as fp:
        json.dump({"players": out}, fp, indent=1)


if __name__ == "__main__":
    main()
