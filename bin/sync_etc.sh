#!/usr/bin/env bash
# sync_etc.sh — deploy repo YAML configs to /etc/drop-watcher with backups +
# pre/post validation, then restart web_watcher to load them. Needs sudo.
# Run:  bash ~/drop-watcher/bin/sync_etc.sh        (35 chars — paste-safe)
# HGR
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)/config"
ETC="/etc/drop-watcher"
FILES=(sources.yaml makers.yaml cool_list.yaml)
STAMP="$(date +%F-%H%M)"

echo "=== 1. Pre-flight: repo files parse as YAML ==="
for f in "${FILES[@]}"; do
  [ -f "$REPO/$f" ] || { echo "  ✗ missing $REPO/$f — ABORT"; exit 1; }
  if python3 -c "import yaml; yaml.safe_load(open('$REPO/$f'))" 2>/dev/null; then
    echo "  ✓ $f"
  else
    echo "  ✗ $f failed to parse — ABORT (nothing touched)"; exit 1
  fi
done

echo "=== 2. Backup /etc → .bak-$STAMP ==="
for f in "${FILES[@]}"; do
  [ -f "$ETC/$f" ] && sudo cp -p "$ETC/$f" "$ETC/$f.bak-$STAMP" && echo "  ✓ $f"
done

echo "=== 3. Copy repo → /etc, restore owner/perms ==="
for f in "${FILES[@]}"; do sudo cp "$REPO/$f" "$ETC/$f"; done
sudo chown shg:shg "$ETC"/*.yaml
sudo chmod 640 "$ETC"/*.yaml
echo "  ✓ done"

echo "=== 4. Post-check: /etc matches repo + parses ==="
for f in "${FILES[@]}"; do
  diff -q "$REPO/$f" "$ETC/$f" >/dev/null || { echo "  ✗ $f differs — ABORT"; exit 1; }
  python3 -c "import yaml; yaml.safe_load(open('$ETC/$f'))" || { echo "  ✗ $f unparseable — ABORT"; exit 1; }
  echo "  ✓ $f in sync + parses"
done

echo "=== 5. Restart web_watcher (load new config) ==="
sudo supervisorctl restart web_watcher
sleep 3
sudo supervisorctl status web_watcher

echo ""
echo "SYNCED ✓  (backups: $ETC/*.bak-$STAMP)"
