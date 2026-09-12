#!/usr/bin/env python3
"""Probe a range of ESPN cricket league ids and print name + calendar span.

Kept because the women's domestic ids ROTATE each season (2021->20045, 2022->21176,
2024->22578) instead of rolling like men's Ranji 8050, so finding a new season means
scanning for an id nobody has seen. 8000-25600 is already swept (see CLAUDE.md) --
scan ABOVE 25600 when the women's season starts.

    python3 tools_probe_leagues.py 25600 27000 | grep -i women
"""
import json, urllib.request, concurrent.futures as cf

UA={"User-Agent":"india-cricket-tracker (+https://github.com/danpune/india-cricket-tracker)"}
def peek(lid):
    try:
        req=urllib.request.Request(
            f"https://site.api.espn.com/apis/site/v2/sports/cricket/{lid}/scoreboard",headers=UA)
        with urllib.request.urlopen(req,timeout=12) as r:
            d=json.load(r)
        L=(d.get("leagues") or [{}])[0]
        nm=L.get("name") or ""
        cal=[c[:10] for c in L.get("calendar",[])]
        if not nm: return None
        return (str(lid), nm, cal[0] if cal else "", cal[-1] if cal else "")
    except Exception:
        return None
import sys
lo,hi=int(sys.argv[1]),int(sys.argv[2])
hits=[]
with cf.ThreadPoolExecutor(max_workers=24) as ex:
    for r in ex.map(peek, range(lo,hi)):
        if r: hits.append(r)
for h in sorted(hits,key=lambda x:x[2] or "",reverse=True):
    print("\t".join(h))
print(f"-- {len(hits)} leagues in {lo}-{hi}", file=sys.stderr)
