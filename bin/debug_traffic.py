#!/usr/bin/env python3
"""Debug traffic dashboard visitor counts."""
import sys
sys.path.insert(0, '/home/shg/drop-watcher')
from generate_traffic import load_pageviews

pv = load_pageviews()
print(f"total views:   {pv['total_views']}")
print(f"unique vids:   {len(pv['unique_vids'])}")
print(f"24h views:     {pv['views_24h']}")
print(f"24h unique:    {len(pv['vids_24h'])}")
print(f"top paths:     {dict(sorted(pv['by_path'].items(), key=lambda x: x[1], reverse=True)[:5])}")
print(f"external refs: {dict(pv['by_ref'])}")
print(f"journeys:      {len(pv['journeys'])} visitors in 24h")
