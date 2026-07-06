#!/usr/bin/env python3
"""
Fill highlights.json: finished India matches -> official YouTube highlight video ids.

Cricket rights belong to the HOME board, so each series maps to that board's
official channel (verify the handle before adding — @bcci on YouTube is a spoof
channel; the ECB's is @officialenglandcricket, found via youtube.com/user/ecbcricket).

Scrapes the channel /videos page (latest ~30 uploads), matches titles against
finished matches in data.json (both team names + "Highlights" + the match's
ordinal and format token — a tour has five T20Is between the same two teams),
then verifies EVERY candidate via YouTube oEmbed: author_url must equal the
official channel URL (author_name is spoofable — learned on worldcup2026).

Merge-only and fail-safe: never removes entries, exits 0 on any fetch failure.
Runs in CI after fetch_data.py with `|| true`. Stdlib only, no API key.
"""
import json
import os
import re
import sys
import urllib.request

CHANNELS = {  # seriesId -> official channel handle of the rights-holding home board
    "23810": "@officialenglandcricket",  # India tour of England 2026
    "23814": "@officialenglandcricket",  # India Women tour of England 2026
    # extend as tours near (verify first!): ICC events -> "@ICC"
}
FMT_TOKENS = {"T20I": ("t20",), "ODI": ("odi", "one day"), "Test": ("test",)}
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "en"}


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def channel_videos(handle):
    """(videoId, title) for the channel's latest uploads, newest first."""
    html = fetch(f"https://www.youtube.com/{handle}/videos")
    m = re.search(r"var ytInitialData = ({.*?});</script>", html)
    if not m:
        return []
    vids = []

    def walk(o):
        if isinstance(o, dict):
            lv = o.get("lockupViewModel")
            if lv and lv.get("contentType") == "LOCKUP_CONTENT_TYPE_VIDEO":
                title = (((lv.get("metadata") or {}).get("lockupMetadataViewModel") or {})
                         .get("title") or {}).get("content", "")
                if lv.get("contentId") and title:
                    vids.append((lv["contentId"], title))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(json.loads(m.group(1)))
    return vids


def official(video_id, handle):
    """True iff YouTube oEmbed says this video belongs to the official channel."""
    try:
        d = json.loads(fetch("https://www.youtube.com/oembed?format=json&url="
                             f"https://www.youtube.com/watch?v={video_id}"))
    except Exception:
        return False
    return (d.get("author_url") or "").lower().rstrip("/") == \
        f"https://www.youtube.com/{handle}".lower()


def title_matches(title, m):
    t = title.lower()
    if "highlight" not in t:
        return False
    teams = [x["name"].replace(" Women", "").lower() for x in m["teams"]]
    if not all(x in t for x in teams):
        return False
    if (m["gender"] == "women") != ("women" in t):
        return False
    no = m["matchNo"].lower()
    fmt = FMT_TOKENS.get(m["format"], ())
    ordinal = re.match(r"(\d+(?:st|nd|rd|th))", no)
    if ordinal:  # bilateral series: need the ordinal AND a format token
        return ordinal.group(1) in t and any(x in t for x in fmt)
    if "final" in no:  # tournament knockouts: "Final" / "Semi Final"
        return no in t
    if no.startswith("match "):  # tournament group games
        return no in t
    if no == "only test":
        return "test" in t
    return False


def main():
    data = json.load(open("data.json", encoding="utf-8"))
    path = "highlights.json"
    doc = {"_howto": "Auto-filled by build_highlights.py: match id -> official YouTube "
                     "highlight video. Every entry is oEmbed-verified against the home "
                     "board's official channel. Manual entries welcome; merge-only.",
           "highlights": {}}
    if os.path.exists(path):
        try:
            doc = json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    hl = doc.setdefault("highlights", {})
    todo = [m for m in data.get("matches", [])
            if m["state"] == "post" and m["seriesId"] in CHANNELS and m["id"] not in hl]
    if not todo:
        print("highlights: nothing to do")
        return
    cache = {}
    added = 0
    for m in todo:
        handle = CHANNELS[m["seriesId"]]
        if handle not in cache:
            try:
                cache[handle] = channel_videos(handle)
            except Exception as e:
                print(f"highlights: {handle} fetch failed ({e}) — skipping", file=sys.stderr)
                cache[handle] = []
        for vid, title in cache[handle]:
            if title_matches(title, m) and official(vid, handle):
                hl[m["id"]] = {"yt": vid, "title": title}
                added += 1
                print(f"  {m['matchNo']} {m['series'][:30]} -> {vid} | {title[:60]}")
                break
    if added:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1)
    print(f"highlights.json: +{added} ({len(hl)} total)")


if __name__ == "__main__":
    main()
