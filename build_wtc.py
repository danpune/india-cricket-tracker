#!/usr/bin/env python3
"""Refresh wtc.json — ICC World Test Championship standings.

WHY A BROWSER: there is no fetchable source. Checked and rejected (Aug 2026):
ICC's standings page returns 326 KB WITHOUT the numbers to any plain HTTP request
(honest UA, browser UA, full Sec-Fetch headers — even a same-origin fetch from inside
a real browser); no standings API call appears in the network log at all; ICC's
rankings/content-gateway APIs 404 on standings; ESPN's WTC league (19430) 404s on
/standings and its scoreboard returns only that day's two teams with ranks that
contradict ICC. The table is injected after hydration, so it must be rendered.

FAIL-SAFE: anything short of a complete, sane table leaves wtc.json untouched — a
stale-but-dated card beats a blank or half-scraped one. The UI always shows the
as-of date, so staleness is visible rather than disguised.
"""
import json
import os
import sys
from datetime import datetime, timezone

URL = "https://www.icc-cricket.com/tournaments/world-test-championship/standings"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wtc.json")
NAMES = {"AUS": "Australia", "SA": "South Africa", "NZ": "New Zealand", "IND": "India",
         "ENG": "England", "SL": "Sri Lanka", "PAK": "Pakistan", "BAN": "Bangladesh",
         "WI": "West Indies", "ZIM": "Zimbabwe", "AFG": "Afghanistan", "IRE": "Ireland"}

# Columns as rendered: POS TEAM PLAYED WON LOST DRAW DED POINTS PCT
# DED = points deducted for slow over rates (England were docked 14 in this cycle) —
# it is NOT a "tied" column, so played == W+L+D and points == 12W+4D+6T - DED.
COLS = ["pos", "team", "played", "won", "lost", "draw", "ded", "points", "pct"]


def scrape():
    from playwright.sync_api import sync_playwright
    rows = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            pg = b.new_page(user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"))
            pg.goto(URL, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(6000)          # let the table hydrate
            # read the real cells rather than regexing innerText — column order is
            # asserted against the header row below, so a layout change fails loudly
            rows = pg.evaluate("""() => {
              return [...document.querySelectorAll('.si-table-row')].map(e => ({
                cells: [...e.querySelectorAll('.si-table-data')].map(c => c.innerText.trim()),
                team: (e.querySelector('img[alt]') || {}).alt || ''
              })).filter(r => r.cells.length);
            }""")
        finally:
            b.close()
    header = next((r["cells"] for r in rows if r["cells"] and r["cells"][0].upper() == "POS"), None)
    if header and [h.lower() for h in header] != COLS[:len(header)]:
        raise ValueError(f"ICC changed the columns: {header}")
    table = []
    for r in rows:
        c, abbr = r["cells"], (r.get("team") or "").strip().upper()
        if abbr not in NAMES or len(c) < 9:
            continue
        try:
            table.append({"rank": int(c[0]), "abbr": abbr, "name": NAMES[abbr],
                          "played": int(c[2]), "won": int(c[3]), "lost": int(c[4]),
                          "drawn": int(c[5]), "deducted": int(c[6]),
                          "points": int(c[7]), "pct": float(c[8])})
        except ValueError:
            continue
    table.sort(key=lambda x: x["rank"])
    return table


def sane(table):
    """Refuse anything that isn't a plausible, complete WTC table."""
    if len(table) < 8:
        return "only %d rows" % len(table)
    if [t["rank"] for t in table] != list(range(1, len(table) + 1)):
        return "ranks not 1..n"
    if not any(t["abbr"] == "IND" for t in table):
        return "India missing"
    if any(not (0 <= t["pct"] <= 100) for t in table):
        return "pct out of range"
    for t in table:  # results must reconcile, and points must match the stated system
        if t["won"] + t["lost"] + t["drawn"] != t["played"]:
            return f"{t['abbr']} W+L+D != played"
        if t["won"] * 12 + t["drawn"] * 4 - t["deducted"] != t["points"]:
            return f"{t['abbr']} points don't match 12W+4D-deductions"
    if table != sorted(table, key=lambda x: -x["pct"]):
        return "pct order disagrees with rank"
    return None


def main():
    try:
        table = scrape()
    except Exception as e:
        print(f"wtc: scrape failed ({e}) — keeping existing wtc.json", file=sys.stderr)
        return 0
    why = sane(table)
    if why:
        print(f"wtc: rejected scrape ({why}) — keeping existing wtc.json", file=sys.stderr)
        return 0
    india = next(t for t in table if t["abbr"] == "IND")
    doc = {
        "_howto": "Auto-refreshed by build_wtc.py (headless render — ICC serves no usable "
                  "feed; see the module docstring). Fail-safe: a failed or implausible "
                  "scrape leaves this file untouched, and the UI always shows 'verified'.",
        "cycle": "2025–2027",
        "finalNote": "Top 2 play the final in 2027",
        "points": "12 for a win · 6 for a tie · 4 for a draw · deductions for slow over rates",
        "url": URL,
        "verified": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "teams": len(table),
        "india": {"rank": india["rank"], "played": india["played"],
                  "points": india["points"], "pct": india["pct"]},
        "top": [{"abbr": t["abbr"], "name": t["name"], "pct": t["pct"]} for t in table[:2]],
        "table": table,
    }
    old = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT))
        except Exception:
            pass
    if old.get("table") == table:
        print("wtc: unchanged")
        return 0
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=1)
    print(f"wtc.json updated: India {india['rank']} of {len(table)} "
          f"({india['pct']}%), leaders {table[0]['abbr']}/{table[1]['abbr']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
