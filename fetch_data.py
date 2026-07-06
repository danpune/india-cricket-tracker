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
        # an active series (still has matches to play) is swept in full so the
        # current-tour view has its past results; completed series only need
        # whatever history.json is missing
        active = any(day[:10] >= today for day in calendar)
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
        })
        added += 1
    if added:
        history["matches"].sort(key=lambda x: x["date"])
        with open(history_path, "w") as f:
            json.dump(history, f, indent=1)

    matches.sort(key=lambda x: x["date"])
    with open(data_path, "w") as f:
        json.dump({
            "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "matches": matches,
            "series": series_meta,
            "meta": {"discovered": all_discovered},
        }, f, indent=1)
    print(f"data.json: {len(matches)} matches across {len(series_meta)} series; history +{added}")


if __name__ == "__main__":
    main()
