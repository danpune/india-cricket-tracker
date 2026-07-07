# Team India Cricket Tracker — project notes

LIVE: https://danpune.github.io/india-cricket-tracker/ · repo `danpune/india-cricket-tracker`
Sibling of `~/grandslams` (tennis) and `~/worldcup2026` — same playbook, deliberately independent.

## Architecture
- `index.html` — the entire site, self-contained (inline CSS + vanilla JS, system fonts,
  no dependencies, no cookies/tracking/keys). Sections: header → men/women/news/about toggle
  (gender persisted in localStorage; About = purpose, sources, non-affiliation, privacy,
  rights-holder contact — mirrors the tennis site's about section) → hero (live score or next-match countdown, playing XIs) →
  current tour (scheduled rows carry 📅 GCal/iCal add-to-calendar links, durations by
  format: T20I 4h · ODI 8.5h · Test = Day-1 start + note) → coming up (future series) → results timeline (2025→, grouped by year,
  W/L color-coded, 🏆 banner for tournament titles) → footer. Every finished match row
  expands into a full scorecard (batting R/B + dismissal kind, DNB list, bowling O/R/W). Light + dark via prefers-color-scheme.
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

## Win odds (Polymarket — same approach as the tennis tracker)
- `stamp_odds()` in fetch_data.py: gamma API `events?tag_slug=cricket&closed=false`
  &start_date_min=now-2d. Main event = title WITHOUT a " - <side market>" suffix
  (side events: Toss Match Double / Most Sixes / Team Top Batter). Winner market =
  the one whose `question` == event title, outcomes = the two team names (JSON
  strings, parse them). One open main event per series at a time → stamped onto the
  series' NEXT pre match only, then removed from the pool; 0 or 2+ candidate events
  ⇒ skipped. Tests are SKIPPED (Polymarket models them as three Yes/No win/win/draw
  markets, usually thin). `o` = [P(teamA), P(teamB)] in our team order. Fail-safe.
- Disclaimer lives in the footer + About tab (market prices, not betting advice,
  not affiliated) — keep it if odds display changes.
- DECISION (2026-07): Polymarket is the ONLY odds source, deliberately. Evaluated and
  rejected: ESPN odds/pickcenter (empty for cricket), Kalshi (no cricket), Betfair/
  odds aggregators (key-gated, betting-operator optics), Manifold (ad-hoc coverage,
  play-money — could be a labeled gap-filler someday, not a backbone).

## News & talk
- `build_news.py` → `news.json`: (a) headlines from ESPNcricinfo's public RSS
  (`espncricinfo.com/rss/content/story/feeds/6.xml` = India feed — WORKS from curl,
  unlike their consumer API); (b) latest videos from commentary channels (Cricbuzz
  UCSRQXk5yErn4e14vN76upOw, Harsha Bhogle UCMdAkUOInD8GSuuacxWd-ag) via the same
  channel_videos() scrape as highlights — YouTube's RSS feeds (feeds/videos.xml) 404
  as of 2026, don't try them. Links + thumbnails only, nothing re-hosted; per-source
  fail-safe keeps the previous section. Gavaskar/Shastri have no own channels — they
  appear via Cricbuzz shows. Runs in CI with `|| true`.

## Following (⭐ player cards)
- `build_following.py` → `follow.json`: franchise appearances (IPL etc.) computed from
  cricsheet TEAM archives (rajasthan_royals_json.zip) — one-off, re-run after a season.
- International appearances are computed CLIENT-SIDE in followingHTML() by regex-scanning
  the innings/xi of data.json+history.json (stays fresh via the cron, zero extra calls).
- SPELLING TRAP: ESPN says "Vaibhav Sooryavanshi", cricsheet says "V Suryavanshi" —
  pattern `s[ou]{1,2}ryavanshi` catches both (the {2} version silently missed cricsheet).
- To follow another player: add to FOLLOW in build_following.py (name/pattern/gender/
  note/team-zips), re-run it, done — the UI reads follow.json.

## Rankings
- Official ICC rankings via the feed icc-cricket.com's own frontend calls (curl-able,
  no auth beyond the public client id baked into their site):
  `assets-icc.sportz.io/cricket/v1/ranking?client_id=tPZJbRgIub3Vua93%2FDWtyQ%3D%3D&feed_format=json&lang=en&comp_type={test|odi|t20|odiw|t20w}&type={team|bat|bowl}`
  Payload: `data["bat-rank"].rank[]` (yes, "bat-rank" for every type). Player rows use
  `Player-name`/`Country_name`/`Points`; team rows `team_name`/`Rating`.
  NO women's Test rankings exist (ICC doesn't publish them) — UI omits that chip.
  Fail-safe: any per-call failure ⇒ keep previous run's rankings verbatim.
  Found by watching the browser's network tab — espncricinfo.com/rankings and ESPN's
  rankings API 404 for cricket, and icc-cricket.com serves curl an empty app shell.

## Highlights
- `build_highlights.py` → `highlights.json` (match id → {yt}). Ported from the tennis
  project: scrape home board's channel /videos (ytInitialData → lockupViewModel), match
  title by "Highlights" + both team names + ordinal + format token (ECB titles say
  "IT20" for T20I; gender guard: 'women' in title iff women's match), verify EVERY id
  via oEmbed author_url. Rights sit with the HOME board → CHANNELS maps seriesId→handle;
  VERIFY handles before adding (@bcci on YouTube is a SPOOF; ECB = @officialenglandcricket,
  found via legacy youtube.com/user/ecbcricket → canonicalBaseUrl). UI bridges ids:
  cricsheet cs_<id> and espn_<id> share the numeric part (cricsheet files use cricinfo ids).
  Merge-only, fail-safe, runs in CI with `|| true`.
- Second source: bcci.tv (official BCCI site) for India-HOME series — server-rendered,
  curl-able listing at bcci.tv/international/{men|women}/videos with
  `data-videoslug="<id>/<slug>"` (Brightcove player). Matched by slug tokens
  (ind/afg abbrs + ordinal + format + "match-highlights"); Tests only get per-day
  "session" clips there, which we deliberately skip (no single recap exists).
  Entries carry {url} instead of {yt}; the UI handles both. BCCI_SERIES maps home
  series ids → listing path. fetch_data sweeps series active in the last 30 days in
  FULL so completed-tour matches stay in data.json during the highlight-posting window.

## Scorecards (two sources, one shape)
- history: `seed_history.py` computes cards from cricsheet ball-by-ball (bowler runs
  exclude byes/legbyes/penalty; run-outs aren't bowler wickets; wides aren't balls faced).
- new matches: `fetch_data.py:innings_from_summary()` reads per-player stats from the
  summary `rosters[].roster[].linescores[].linescores[].statistics` (stat names:
  batted/runs/ballsFaced/battingPosition/dismissalCard/overs/conceded/wickets); innings
  totals from `header.competitions[0].competitors[].linescores`. The summary endpoint
  keys on event id — the league id in the path is ignored.
- shape per innings: {t, total, bat:[[name,r,b,how]], dnb:[], bowl:[[name,o,r,w]]}.

## Roadmap
1. Extend `SERIES` when new tours are announced (probe the id range, or let discovery
   catch them on match day).
2. Points-table for World Cups / Asia Cup when one is live.
3. Verify + add official channel handles to build_highlights.py CHANNELS as tours
   near: Zimbabwe Cricket (Jul 2026), Sri Lanka Cricket (Aug), NZC (Oct), @ICC for
   ICC events. India-home series already covered via bcci.tv (BCCI_SERIES).
4. Per-match official highlights (YouTube oEmbed verification — port from worldcup2026).
