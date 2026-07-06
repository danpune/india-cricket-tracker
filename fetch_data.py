#!/usr/bin/env python3
"""Fetch Team India match data from ESPN's unofficial cricket API.

Outputs:
  data.json    — regenerated every run: all matches (results/live/fixtures) of
                 known India series, playing XIs for today's matches, series notes.
  history.json — append-only: finalized matches (seeded from cricsheet.org by
                 seed_history.py, extended here with ESPN results).

Fail-safe: if the fetch yields nothing, exits non-zero without touching files.
"""
import html
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://site.api.espn.com/apis/site/v2/sports/cricket"
HEADER_FEED = "https://site.web.api.espn.com/apis/v2/scoreboard/header?sport=cricket&region=in&lang=en"
DIR = os.path.dirname(os.path.abspath(__file__))

# Verified ESPN league ids for announced India tours (umbrella "tour of" ids
# cover every format of the tour). Discovery below picks up anything new
# (World Cups, Asia Cup, freshly announced tours) on match days.
SERIES = {
    # men
    "23810": "men",    # India tour of England 2026
    "24258": "men",    # India tour of Ireland 2026
    "24227": "men",    # Afghanistan tour of India 2026
    "24301": "men",    # India tour of Zimbabwe 2026
    "24567": "men",    # India tour of Sri Lanka 2026
    "24283": "men",    # Zimbabwe tour of India 2026/27
    "24286": "men",    # Sri Lanka tour of India 2026/27
    "24289": "men",    # West Indies tour of India 2026/27
    "24281": "men",    # Australia tour of India 2026/27
    "24469": "men",    # India tour of New Zealand 2026/27
    # women
    "23814": "women",  # India Women tour of England 2026
    "24233": "women",  # India Women tour of South Africa 2026
    "24371": "women",  # Zimbabwe Women tour of India 2026/27
    "24559": "women",  # India Women tour of South Africa 2026/27
}
EXCLUDE = ("Under-19", "India A", "Champions")


def get(url):
    # the API 504s intermittently; a dropped date = a silently missing fixture
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def norm_format(cls):
    """'Women's Test'→Test, 'Women T20'→T20I, 'Other T20'→T20 (warm-up)."""
    intl = not cls.startswith("Other")
    if "Test" in cls:
        return "Test" if intl else "FC"
    if "T20" in cls:
        return "T20I" if intl else "T20"
    if "OD" in cls:
        return "ODI" if intl else "List A"
    return cls


def norm_team(name):
    return name.replace(" Women", "").strip()


def hist_key(date, team_names, gender):
    return (date[:10], frozenset(norm_team(t) for t in team_names), gender)


def is_india_match(event):
    teams = [c["team"]["displayName"] for c in event["competitions"][0]["competitors"]]
    return any(norm_team(t) == "India" for t in teams) and not any(x in t for t in teams for x in EXCLUDE)


RANK_URL = ("https://assets-icc.sportz.io/cricket/v1/ranking"
            "?client_id=tPZJbRgIub3Vua93%2FDWtyQ%3D%3D&feed_format=json&lang=en")
RANK_COMBOS = {"men": ["test", "odi", "t20"], "women": ["odiw", "t20w"]}  # no women's Test rankings exist
RANK_FMT = {"test": "Test", "odi": "ODI", "t20": "T20I", "odiw": "ODI", "t20w": "T20I"}


def fetch_rankings():
    """Official ICC rankings via the feed icc-cricket.com itself uses (public client id).
    Returns None on any failure — stale rankings beat partial ones."""
    out = {}
    for gender, cts in RANK_COMBOS.items():
        g = {}
        for ct in cts:
            entry = {}
            for ty in ("team", "bat", "bowl"):
                try:
                    time.sleep(0.15)
                    rk = get(f"{RANK_URL}&comp_type={ct}&type={ty}")["data"]["bat-rank"]
                except Exception:
                    return None
                entry[ty] = [{
                    "no": r.get("no", ""),
                    "name": r.get("Player-name") or r.get("team_name", ""),
                    "team": r.get("Country_name") or r.get("team_name", ""),
                    "rating": r.get("Rating") or r.get("Points", ""),
                } for r in rk.get("rank", [])[:10]]
                entry["updated"] = rk.get("rank_date", "")
            g[RANK_FMT[ct]] = entry
        out[gender] = g
    return out


def discover(known):
    """Find India series not in the seed list from the live header feed."""
    found = {}
    try:
        d = get(HEADER_FEED)
    except Exception:
        return found
    for sport in d.get("sports", []):
        for lg in sport.get("leagues", []):
            lid = str(lg.get("id"))
            if lid in known or any(x in lg.get("name", "") for x in EXCLUDE):
                continue
            names = " ".join(e.get("name", "") for e in lg.get("events", []))
            if "India Women" in names or ("India" in names and "Women" in lg.get("name", "")):
                found[lid] = "women"
            elif "India" in names and "India Under" not in names and "India A " not in names:
                found[lid] = "men"
    return found


def parse_event(e, series_name, series_id, gender):
    c = e["competitions"][0]
    st = e["status"]["type"]
    state = st.get("state", "pre")  # pre | in | post
    teams = []
    for t in c["competitors"]:
        teams.append({
            "name": t["team"]["displayName"],
            "abbr": t["team"].get("abbreviation", ""),
            "score": t.get("score", "") or "",
            # the API mixes bool true and string "true" across leagues
            "winner": str(t.get("winner", "")).lower() == "true",
        })
    india_won = any(t["winner"] and norm_team(t["name"]) == "India" for t in teams)
    other_won = any(t["winner"] and norm_team(t["name"]) != "India" for t in teams)
    india = ""
    if state == "post":
        desc = st.get("description", "")
        india = ("won" if india_won else "lost" if other_won else
                 "nr" if "No result" in desc or "Abandoned" in desc else
                 "tie" if "Tie" in desc else "draw" if "Draw" in desc else "nr")
    return {
        "id": f"espn_{e['id']}",
        "eventId": e["id"],
        "date": e["date"],
        "gender": gender,
        "format": norm_format(c.get("class", {}).get("generalClassCard", "")),
        "series": series_name,
        "seriesId": series_id,
        "matchNo": c.get("description", ""),
        "venue": c.get("venue", {}).get("fullName", ""),
        "state": state,
        "statusDetail": st.get("detail", ""),
        "statusDesc": st.get("description", ""),
        "teams": teams,
        "result": "",
        "india": india,
    }


def innings_from_summary(d):
    """Batting/bowling cards per innings from the summary rosters."""
    per, team_players = {}, {}
    totals = {}
    for comp in (d.get("header", {}).get("competitions") or [{}])[:1]:
        for c in comp.get("competitors", []):
            for ls in c.get("linescores", []):
                r, w, o = ls.get("runs"), ls.get("wickets"), ls.get("overs")
                if r is None:
                    continue
                t = str(int(r)) if w == 10 else f"{int(r)}/{int(w)}" if w is not None else str(int(r))
                if o:
                    t += f" ({o} ov)"
                totals[(c.get("team", {}).get("displayName"), int(ls.get("period", 0)))] = t
    for side in d.get("rosters", []):
        team = side.get("team", {}).get("displayName", "?")
        names = []
        for p in side.get("roster", []):
            nm = p.get("athlete", {}).get("displayName", "")
            names.append(nm)
            for perl in p.get("linescores", []):
                pd = perl.get("period", 1)
                for inner in perl.get("linescores", []):
                    st = {x["name"]: x["displayValue"] for cat in inner.get("statistics", {}).get("categories", [])
                          for x in cat.get("stats", [])}
                    e = per.setdefault(pd, {"team": None, "bat": [], "bowl": []})
                    if st.get("batted") == "1":
                        e["team"] = team
                        how = st.get("dismissalCard") or ("not out" if st.get("outs") == "0" else "")
                        e["bat"].append((int(st.get("battingPosition") or 99), nm,
                                         int(st.get("runs") or 0), int(st.get("ballsFaced") or 0), how or "not out"))
                    try:
                        ov = float(st.get("overs") or 0)
                    except ValueError:
                        ov = 0
                    if ov > 0:
                        e["bowl"].append([nm, st.get("overs"), int(st.get("conceded") or 0),
                                          int(st.get("wickets") or 0)])
        team_players[team] = names
    innings = []
    for pd in sorted(per):
        e = per[pd]
        if not e["bat"]:
            continue
        batted = {b[1] for b in e["bat"]}
        innings.append({
            "t": e["team"],
            "total": totals.get((e["team"], pd), ""),
            "bat": [[b[1], b[2], b[3], b[4]] for b in sorted(e["bat"])],
            "dnb": [n for n in team_players.get(e["team"], []) if n not in batted],
            "bowl": e["bowl"],
        })
    return innings


def enrich_from_summary(match):
    """Result sentence, series note and playing XIs live in the summary feed."""
    try:
        d = get(f"{BASE}/{match['seriesId']}/summary?event={match['eventId']}")
    except Exception:
        return
    comp = (d.get("header", {}).get("competitions") or [{}])[0]
    match["result"] = html.unescape(comp.get("status", {}).get("summary", ""))
    for n in d.get("notes", []):
        if n.get("type") == "seriesnote":
            match["seriesNote"] = html.unescape(n.get("text", ""))
    xi = {}
    for side in d.get("rosters", []):
        players = []
        for p in side.get("roster", []):
            a = p.get("athlete", {})
            nm = a.get("displayName", "")
            if p.get("captain"):
                nm += " (c)"
            if p.get("keeper") or p.get("wicketKeeper"):
                nm += " †"
            players.append(nm)
        if players:
            xi[side.get("team", {}).get("displayName", "?")] = players
    if xi:
        match["xi"] = xi
    inns = innings_from_summary(d)
    if inns:
        match["innings"] = inns


def main():
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    history_path = os.path.join(DIR, "history.json")
    data_path = os.path.join(DIR, "data.json")
    history = json.load(open(history_path)) if os.path.exists(history_path) else {"matches": []}
    old_meta = {}
    if os.path.exists(data_path):
        try:
            old_meta = json.load(open(data_path)).get("meta", {})
        except Exception:
            pass

    known = dict(SERIES)
    for lid, g in old_meta.get("discovered", {}).items():
        known.setdefault(lid, g)
    discovered = discover(known)
    known.update(discovered)
    all_discovered = {**old_meta.get("discovered", {}), **discovered}

    hist_dirty = [False]
    hist_keys = {hist_key(m["date"], [t["name"] for t in m["teams"]], m["gender"]) for m in history["matches"]}
    hist_ids = {m["id"] for m in history["matches"]}

    matches, series_meta = [], []
    for sid, gender in known.items():
        try:
            board = get(f"{BASE}/{sid}/scoreboard")
            league = board["leagues"][0]
        except Exception:
            continue
        name = league.get("name", "")
        calendar = league.get("calendar", [])
        series_meta.append({"id": sid, "name": name, "gender": gender})
        seen = set()
        events = list(board.get("events", []))
        # a series active in the last 30 days is swept in full — keeps the
        # current-tour view complete and gives build_highlights.py a window in
        # which boards post their videos; older completed series only need
        # whatever history.json is missing
        recent = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        active = any(day[:10] >= recent for day in calendar)
        for day in calendar:
            date = day[:10]
            if not active and date < today and \
                    any(m["date"][:10] == date and m["gender"] == gender for m in history["matches"]):
                continue
            if date == today:
                continue  # today's events came with the plain scoreboard call
            try:
                time.sleep(0.2)  # stay polite: ~40 calls/run against an unofficial API
                events += get(f"{BASE}/{sid}/scoreboard?dates={date.replace('-', '')}").get("events", [])
            except Exception:
                continue
        for e in events:
            # some dates return a bare {} event
            if "id" not in e or e["id"] in seen or not is_india_match(e):
                continue
            seen.add(e["id"])
            m = parse_event(e, name, sid, gender)
            # summary call only where it adds something: finals need the result
            # sentence, live/today matches need XIs and the series note
            if m["state"] == "post":
                key = hist_key(m["date"], [t["name"] for t in m["teams"]], m["gender"])
                rec = next((h for h in history["matches"]
                            if h["id"] == m["id"]
                            or hist_key(h["date"], [t["name"] for t in h["teams"]], h["gender"]) == key), None)
                if rec:
                    m["result"] = rec["result"]
                    m["india"] = rec["india"]
                    if rec.get("innings"):
                        m["innings"] = rec["innings"]
                    elif rec["id"].startswith("espn_"):
                        # older espn entry recorded before scorecards existed — backfill once
                        enrich_from_summary(m)
                        if m.get("innings"):
                            rec["innings"] = m["innings"]
                            hist_dirty[0] = True
                else:
                    enrich_from_summary(m)
            elif m["state"] == "in" or (m["state"] == "pre" and m["date"][:10] <= (now + timedelta(hours=18)).strftime("%Y-%m-%d")):
                enrich_from_summary(m)
            matches.append(m)

    if not matches:
        print("fetch yielded no matches — keeping existing files", file=sys.stderr)
        sys.exit(1)

    # append newly finalized matches to history
    added = 0
    for m in matches:
        if m["state"] != "post" or m["id"] in hist_ids:
            continue
        if m["format"] not in ("Test", "ODI", "T20I"):
            continue  # warm-ups/tour games don't belong in the year record
        if hist_key(m["date"], [t["name"] for t in m["teams"]], m["gender"]) in hist_keys:
            continue
        history["matches"].append({
            "id": m["id"], "date": m["date"][:10], "gender": m["gender"],
            "format": m["format"], "series": m["series"], "matchNo": m["matchNo"],
            "venue": m["venue"], "city": "",
            "teams": [{"name": t["name"], "score": t["score"]} for t in m["teams"]],
            "result": m["result"] or m["statusDesc"], "india": m["india"],
            "innings": m.get("innings", []),
        })
        added += 1
    if added or hist_dirty[0]:
        history["matches"].sort(key=lambda x: x["date"])
        with open(history_path, "w") as f:
            json.dump(history, f, indent=1)

    rankings = fetch_rankings()
    if rankings is None:
        rankings = old_meta.get("_rankings") or {}
        try:
            rankings = json.load(open(data_path)).get("rankings", {})
        except Exception:
            rankings = {}

    matches.sort(key=lambda x: x["date"])
    with open(data_path, "w") as f:
        json.dump({
            "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "matches": matches,
            "series": series_meta,
            "rankings": rankings,
            "meta": {"discovered": all_discovered},
        }, f, indent=1)
    print(f"data.json: {len(matches)} matches across {len(series_meta)} series; history +{added}")


if __name__ == "__main__":
    main()
