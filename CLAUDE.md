# Team India Cricket Tracker — project notes

LIVE: https://danpune.github.io/india-cricket-tracker/ · repo `danpune/india-cricket-tracker`
Sibling of `~/grandslams` (tennis) and `~/worldcup2026` — same playbook, deliberately independent.

## Architecture
- `index.html` — the entire site, self-contained (inline CSS + vanilla JS, system fonts,
  no dependencies, no cookies/tracking/keys). Sections: header → men/women toggle
  (localStorage) → hero (live score or next-match countdown, playing XIs) →
  current tour → coming up (future series) → results timeline (2025→, grouped by year,
  W/L color-coded, 🏆 banner for tournament titles) → footer. Light + dark via prefers-color-scheme.
- `fetch_data.py` → `data.json` (all matches of known India series: results/live/fixtures,
  XIs for today's matches) + appends finalized matches to `history.json` (append-only
  season record, seeded from cricsheet by `seed_history.py`).
- `.github/workflows/update-data.yml` — every 30 min, SHA-pinned, rebase-before-push,
  fail-safe (exits non-zero without writing when the fetch comes back empty).

## Data source (free, no key, unofficial — same ESPN family as the tennis tracker)
- Series discovery: `site.web.api.espn.com/apis/v2/scoreboard/header?sport=cricket&region=in&lang=en`
  shows only leagues with matches ~today → `fetch_data.py` keeps a verified seed list of
  India series league ids (`SERIES`) + auto-discovers new ones on match days (persisted
  via `data.json` meta.discovered).
- Per-series: `site.api.espn.com/.../cricket/{leagueId}/scoreboard` returns ~today only;
  full fixtures come from `leagues[0].calendar` + one `?dates=YYYYMMDD` call per day.
  Umbrella "tour of" ids cover all formats of a tour; use those, not per-format sub-ids.
- Result sentence ("England won by 4 wkts") + playing XIs + series note live ONLY in
  `.../summary?event={id}` (`header.competitions[0].status.summary`, `rosters[]`, seriesnote).
- League ids are probeable sequentially (~23600–24600 for 2026 tours) — how the seed
  list was built. `hs-consumer-api.espncricinfo.com` and espn.com/espn.in HTML are
  Akamai-blocked from curl; don't bother.

## API landmines (all hit during the build — keep the guards)
- `competitors[].winner` is bool `true` in some leagues, STRING `"true"`/`"false"` in
  others — always `str(x).lower()=="true"`.
- Intermittent 502/504s → `get()` retries ×3; a dropped date = silently missing fixture.
- Some `?dates=` calls return a bare `{}` in `events[]` — guard `"id" not in e`.
- Result strings arrive HTML-escaped (`&amp;`) — `html.unescape`.
- Format class strings vary: "Women's Test", "Women T20", "Other T20" (warm-up) —
  `norm_format()` maps them; only Test/ODI/T20I enter history.

## Conventions (same as the tennis project — follow them)
- **Edit `index.html` with Python `str.replace`, never the Edit tool.** After every edit:
  `python3 -c "import re;h=open('index.html').read();m=re.search(r'<script>(.*?)</script>',h,re.S);open('/tmp/ci.js','w').write(m.group(1))" && node --check /tmp/ci.js`
- Never fabricate sports data — fetch it or verify it; unknown ⇒ "TBA"/nothing.
- Verify UI changes in a real browser before committing (local: `python3 -m http.server 4610`).
- No PII; commit author is the GitHub noreply alias.
- History dedupe key is (date, normalized team set, gender) — cricsheet says "India",
  ESPN says "India Women"; `norm_team()` strips the suffix.

## Roadmap
1. Extend `SERIES` when new tours are announced (probe the id range, or let discovery
   catch them on match day).
2. Scorecard drill-down (batting/bowling tables from the summary endpoint).
3. Points-table for World Cups / Asia Cup when one is live.
4. Per-match official highlights (YouTube oEmbed verification — port from worldcup2026).
