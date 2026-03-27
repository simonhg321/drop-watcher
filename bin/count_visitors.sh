#!/bin/bash
# Count unique visitors from pageviews.jsonl on ironman
# SGH
ssh shg@instockornot.club "python3 -c \"
import json
vids = set()
with open('/var/log/drop-watcher/pageviews.jsonl') as f:
    for line in f:
        try:
            e = json.loads(line.strip())
            vids.add(e.get('vid',''))
        except:
            pass
print(f'{len(vids)} unique visitors from {sum(1 for _ in open(\"/var/log/drop-watcher/pageviews.jsonl\"))} pageviews')
\""
