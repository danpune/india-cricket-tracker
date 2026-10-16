#!/usr/bin/env python3
"""Self-check: run `python3 test_fetch.py` after fetch_data.py, BEFORE committing.

Asserts only, no framework — the point is to be a gate in the pipeline, not a test
suite. It catches the failure that matters here: data that is WRONG rather than
missing. A crash announces itself; a silently bad commit does not.

Exits non-zero on failure, so the workflow stops before publishing bad data.
"""
import json, os, re, subprocess, sys
from datetime import datetime, timezone

# Kept in step with fetch_data.NOT_A_RESULT. A finished match once shipped carrying
# "Starts at 14:00 local time" — ESPN flips state to post while status.summary still
# holds the pre-match line — and a truthiness check waves that straight through.
NOT_A_RESULT = re.compile(r"^\s*(starts at|match (starts|scheduled)|scheduled|tba)\b", re.I)

d = json.load(open("data.json"))
now = datetime.now(timezone.utc)

# 1. the file is fresh and not somehow stamped in the future
updated = datetime.strptime(d["updated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
assert updated <= now, f"updated is in the future: {d['updated']}"

M = d["matches"]
assert M, "no matches at all — refusing to publish an empty file"

# 2. identity: a duplicate id silently merges two matches in the UI
ids = [m["id"] for m in M]
assert len(set(ids)) == len(ids), f"duplicate match ids: {len(ids) - len(set(ids))}"

# 3. every match carries what the page needs to render it
for m in M:
    for k in ("id", "date", "format", "gender", "state"):
        assert m.get(k), f"match {m.get('id')} missing {k}"
    assert m["gender"] in ("men", "women"), f"odd gender {m['gender']!r}"
    assert m["state"] in ("pre", "in", "post"), f"odd state {m['state']!r}"

# 4. a finished match must have a result, and must not be in the future.
#    This is the shape of the bug that has bitten the sibling projects: an upstream
#    feed reporting a scheduled match as complete.
stamp = now.strftime("%Y-%m-%dT%H:%MZ")
for m in M:
    if m["state"] == "post":
        assert m.get("result"), f"finished match {m['id']} has no result"
        assert not NOT_A_RESULT.match(m["result"]), \
            f"finished match {m['id']} has a pre-match line as its result: {m['result']!r}"
        assert m["date"] <= stamp, f"finished match {m['id']} kicks off in the future ({m['date']})"

# 5. every match points at a series the page can name
sids = {s["id"] for s in d["series"]}
orphans = [m["id"] for m in M if m.get("seriesId") not in sids]
assert not orphans, f"{len(orphans)} matches reference an unknown series, e.g. {orphans[0]}"

# 6. completeness, not just well-formedness: a partial upstream failure writes a
#    smaller file that passes every check above. Counts only grow inside a season,
#    so compare against the last published build and refuse a sudden fall.
try:
    prev = json.loads(subprocess.run(["git", "show", "HEAD:data.json"], check=True,
                                     capture_output=True, text=True).stdout)
except Exception:
    prev = None                     # first run, or no git: nothing to compare against
if prev:
    for label, now_n, was_n in (("matches", len(M), len(prev["matches"])),
                                ("series", len(d["series"]), len(prev["series"]))):
        assert now_n >= was_n * 0.9, \
            f"{label} fell {was_n} -> {now_n}: refusing to publish a partial picture"

print(f"all checks passed — {len(M)} matches, {len(d['series'])} series, "
      f"updated {d['updated']}")
