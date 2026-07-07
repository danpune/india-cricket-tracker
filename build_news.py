#!/usr/bin/env python3
"""Fill news.json: cricket headlines + latest talk/analysis videos.

- Headlines: ESPNcricinfo's India news RSS (title + link only — a headline list,
  like any RSS reader; the stories stay on cricinfo).
- Talk: latest uploads from followed commentary channels (Cricbuzz, Harsha
  Bhogle), scraped from the channel /videos page exactly like build_highlights
  (YouTube's RSS feeds 404 as of 2026). Links only, nothing re-hosted.

Fully rebuilt each run; fail-safe per source (a dead source keeps its previous
section). Runs in CI with `|| true`.
"""
import json
import os
import sys
import xml.etree.ElementTree as ET

from build_highlights import channel_videos, fetch

RSS = ("Cricinfo", "https://www.espncricinfo.com/rss/content/story/feeds/6.xml")
CHANNELS = [  # label, verified handle
    ("Cricbuzz", "@cricbuzz"),
    ("Harsha Bhogle", "@bhogle_harsha"),
]
OUT = os.path.join(os.path.dirname(__file__), "news.json")


def headlines():
    root = ET.fromstring(fetch(RSS[1]))
    out = []
    for it in root.find("channel").findall("item")[:10]:
        title, link = it.findtext("title", ""), it.findtext("link", "")
        if title and link:
            out.append({"t": title.strip(), "u": link.strip(),
                        "d": (it.findtext("pubDate") or "")[:16].strip()})
    return out


def main():
    old = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT))
        except Exception:
            pass
    doc = {"headlines": old.get("headlines", []), "talk": old.get("talk", [])}
    try:
        hs = headlines()
        if hs:
            doc["headlines"] = hs
    except Exception as e:
        print(f"news: headlines failed ({e}) — keeping previous", file=sys.stderr)
    talk = []
    for label, handle in CHANNELS:
        try:
            vids = channel_videos(handle)[:6]
        except Exception as e:
            print(f"news: {handle} failed ({e}) — keeping previous", file=sys.stderr)
            vids = None
        if vids:
            talk.append({"channel": label, "handle": handle,
                         "videos": [{"yt": v, "t": t} for v, t in vids]})
        else:
            prev = next((s for s in old.get("talk", []) if s.get("handle") == handle), None)
            if prev:
                talk.append(prev)
    if talk:
        doc["talk"] = talk
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=1)
    print(f"news.json: {len(doc['headlines'])} headlines, "
          f"{sum(len(s['videos']) for s in doc['talk'])} videos from {len(doc['talk'])} channels")


if __name__ == "__main__":
    main()
