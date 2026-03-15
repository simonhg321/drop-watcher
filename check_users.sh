#!/bin/bash
python3 -c "
import json
w = json.load(open('/var/lib/drop-watcher/watchers.json'))
active  = [x for x in w if x.get('active')]
pending = [x for x in w if not x.get('active')]
print(f'Total:   {len(w)}')
print(f'Active:  {len(active)}')
print(f'Pending: {len(pending)}')
for x in w:
    status = 'ACTIVE' if x.get('active') else 'PENDING'
    print(f'  {status} | {x[\"email\"]} | {x.get(\"url\",\"\")} | {x.get(\"keywords\",\"\")}')
"
