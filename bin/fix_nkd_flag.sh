#!/usr/bin/env bash
# fix_nkd_flag.sh — add DW_NKD_ENABLED="1" to web_watcher's supervisor env so
# event-driven alert emails carry the NKD "I Scored One" button (BUG: flag was
# only in crontab, so instant alerts — the majority — shipped without it since
# ~Apr 23). Idempotent. Needs sudo.
# Run:  sudo bash ~/drop-watcher/bin/fix_nkd_flag.sh
# HGR
set -euo pipefail

CONF=/etc/supervisor/conf.d/drop-watcher.conf
STAMP="$(date +%F-%H%M)"

if grep -q 'DW_NKD_ENABLED' "$CONF"; then
  echo "already set — nothing to do:"
  grep -n 'DW_NKD_ENABLED' "$CONF"
  exit 0
fi

cp -p "$CONF" "$CONF.bak-$STAMP"
echo "backup: $CONF.bak-$STAMP"

# Append the flag to the [program:web_watcher] environment= line only (line 9
# today, but match by content not number: the first environment= line after the
# web_watcher program header).
python3 - "$CONF" <<'EOF'
import sys
path = sys.argv[1]
lines = open(path).readlines()
in_ww = False
done = False
for i, ln in enumerate(lines):
    if ln.strip().startswith('[program:'):
        in_ww = ln.strip() == '[program:web_watcher]'
    if in_ww and ln.startswith('environment=') and not done:
        lines[i] = ln.rstrip('\n') + ',DW_NKD_ENABLED="1"\n'
        done = True
if not done:
    sys.exit('ERROR: web_watcher environment= line not found — aborting, file untouched')
open(path, 'w').writelines(lines)
print('patched:', lines[i].strip())
EOF

supervisorctl reread
supervisorctl update
supervisorctl restart web_watcher
sleep 3
supervisorctl status web_watcher

PID=$(supervisorctl pid web_watcher)
if tr '\0' '\n' < "/proc/$PID/environ" | grep -q '^DW_NKD_ENABLED=1$'; then
  echo "VERIFIED ✓ — web_watcher now runs with DW_NKD_ENABLED=1"
else
  echo "✗ flag not visible in process env — check $CONF"
  exit 1
fi
