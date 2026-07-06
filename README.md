# Team India Cricket Tracker 🏏

Follow the Indian men's and women's cricket teams: what's live, what's next,
the playing XIs, and every international result of the year.

**Live site:** https://danpune.github.io/india-cricket-tracker/

- **Up next / live** — the current or next India match with a countdown
  (or live score), venue, and playing XIs once the toss is done.
- **Current tour** — every match of the series in progress, results included.
- **Coming up** — all announced future tours with dates and venues.
- **2026 so far** — the season record, series by series, wins and losses
  color-coded (including the 🏆 T20 World Cup title).

## How it works

- `index.html` — the whole site: one self-contained page, no dependencies,
  no cookies, no tracking.
- `fetch_data.py` — pulls from ESPN's public (unofficial) cricket feeds every
  30 minutes via GitHub Actions → `data.json` (current state) and
  `history.json` (append-only season record).
- `seed_history.py` — one-off backfill of the season record from
  [cricsheet.org](https://cricsheet.org).

Scores update within ~30 minutes of a match finishing. Data is unofficial and
may lag or contain errors; nothing here is affiliated with the BCCI, ICC, or ESPN.
