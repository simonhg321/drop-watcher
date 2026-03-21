#!/bin/bash
# sync_audit.sh — Compare Mac repo against ironman (code + webroot + config)
# Run from Mac in the drop-watcher directory
# HGR

set -o pipefail

HOST="${DW_SSH_HOST:?Set DW_SSH_HOST in your shell profile}"
REMOTE_CODE="~/drop-watcher"
REMOTE_WEB="/var/www/html"
REMOTE_CONF="/etc/drop-watcher"
REMOTE_SUPV="/etc/supervisor/conf.d/drop-watcher.conf"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'

MISMATCHED=0
MISSING=0
MATCHED=0

compare() {
  local local_file="$1"
  local remote_file="$2"
  local label="$3"

  if [ ! -f "$local_file" ]; then
    echo -e "  ${YELLOW}SKIP${RESET}  $label  ${DIM}(not in local repo)${RESET}"
    return
  fi

  LOCAL_MD5=$(md5 -q "$local_file" 2>/dev/null || md5sum "$local_file" 2>/dev/null | cut -d' ' -f1)
  REMOTE_MD5=$(ssh "$HOST" "md5sum $remote_file 2>/dev/null" | cut -d' ' -f1)

  if [ -z "$REMOTE_MD5" ]; then
    echo -e "  ${RED}MISSING${RESET}  $label  ${DIM}→ not on ironman${RESET}"
    MISSING=$((MISSING+1))
  elif [ "$LOCAL_MD5" = "$REMOTE_MD5" ]; then
    echo -e "  ${GREEN}✓${RESET}  $label"
    MATCHED=$((MATCHED+1))
  else
    echo -e "  ${RED}DIFFERS${RESET}  $label"
    MISMATCHED=$((MISMATCHED+1))
  fi
}

echo ""
echo -e "${BOLD}════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  DROP WATCHER — SYNC AUDIT${RESET}"
echo -e "${DIM}  $(date '+%Y-%m-%d %H:%M:%S')${RESET}"
echo -e "${BOLD}════════════════════════════════════════════${RESET}"

# ── 1. Python files → ~/drop-watcher/ ────────────────────────────────────────
echo ""
echo -e "${BOLD}── PYTHON CODE → ~/drop-watcher/ ──${RESET}"
for f in \
  alerter.py \
  discord_logger.py \
  generate_alerts.py \
  generate_traffic.py \
  morning_briefer.py \
  paths.py \
  per_user_alerter.py \
  preflight.py \
  safe_fetch.py \
  sms_alerter.py \
  watchdog.py \
  watcher_io.py \
  watcher_signup.py \
; do
  compare "$f" "$REMOTE_CODE/$f" "$f"
done

echo ""
echo -e "${BOLD}── AGENTS → ~/drop-watcher/agents/ ──${RESET}"
for f in \
  agents/ai_interpreter.py \
  agents/feed_watcher.py \
  agents/web_watcher.py \
; do
  compare "$f" "$REMOTE_CODE/$f" "$f"
done

# ── 2. Config → ~/drop-watcher/config/ AND /etc/drop-watcher/ ────────────────
echo ""
echo -e "${BOLD}── CONFIG → ~/drop-watcher/config/ ──${RESET}"
for f in \
  config/sources.yaml \
  config/makers.yaml \
  config/cool_list.yaml \
  config/settings.yaml \
; do
  compare "$f" "$REMOTE_CODE/$f" "$f"
done

echo ""
echo -e "${BOLD}── CONFIG → /etc/drop-watcher/ ──${RESET}"
for f in sources.yaml makers.yaml cool_list.yaml settings.yaml; do
  compare "config/$f" "$REMOTE_CONF/$f" "/etc/drop-watcher/$f"
done

# ── 3. Supervisor conf ───────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}── SUPERVISOR CONF ──${RESET}"
compare "conf/drop-watcher.conf" "$REMOTE_CODE/conf/drop-watcher.conf" "conf/drop-watcher.conf (repo)"
compare "conf/drop-watcher.conf" "$REMOTE_SUPV" "/etc/supervisor/conf.d/ (live)"

# ── 4. HTML → /var/www/html/ ─────────────────────────────────────────────────
echo ""
echo -e "${BOLD}── HTML → /var/www/html/ ──${RESET}"
for f in \
  index.html \
  watchlist.html \
  my-alerts.html \
  get-my-link.html \
  privacy.html \
  hgr.html \
  alerts.html \
  sms-optin.html \
  robots.txt \
; do
  compare "html/$f" "$REMOTE_WEB/$f" "html/$f"
done

# ── 5. Ops scripts → ~/drop-watcher/bin/ ─────────────────────────────────────
echo ""
echo -e "${BOLD}── BIN SCRIPTS → ~/drop-watcher/bin/ ──${RESET}"
for f in bin/*.sh bin/*.py; do
  [ -f "$f" ] && compare "$f" "$REMOTE_CODE/$f" "$f"
done

# ── 6. Files on ironman that SHOULDN'T exist ──────────────────────────────────
echo ""
echo -e "${BOLD}── IRONMAN GHOSTS (should not exist) ──${RESET}"
GHOSTS=$(ssh "$HOST" "ls \
  ~/drop-watcher/orchestrator.py \
  ~/drop-watcher/.env \
  ~/drop-watcher/config/watchers.jso? \
  ~/drop-watcher/index.html \
  ~/drop-watcher/watchlist.html \
  ~/drop-watcher/gunicorn.ctl \
  ~/drop-watcher/web/ \
  /var/www/html/watcher_status.html \
  /var/www/html/all_the_things.html \
  /var/www/html/terms.html \
  /var/www/html/watcher_signup.py \
  /var/www/html/watchlist.html-bak \
  /var/www/html/what-we-watch.html \
  /var/www/html/sitemap.xml \
  2>/dev/null")

if [ -z "$GHOSTS" ]; then
  echo -e "  ${GREEN}✓${RESET}  No ghost files found"
else
  echo "$GHOSTS" | while read -r g; do
    echo -e "  ${RED}GHOST${RESET}  $g  ${DIM}→ should be deleted${RESET}"
  done
fi

# ── 7. Services ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}── IRONMAN SERVICES ──${RESET}"
ssh "$HOST" "sudo supervisorctl status 2>/dev/null" | while read -r line; do
  if echo "$line" | grep -q "RUNNING"; then
    echo -e "  ${GREEN}✓${RESET}  $line"
  else
    echo -e "  ${RED}!${RESET}  $line"
  fi
done

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}════════════════════════════════════════════${RESET}"
TOTAL=$((MATCHED + MISMATCHED + MISSING))
echo -e "  ${GREEN}MATCH${RESET}   $MATCHED / $TOTAL"
echo -e "  ${RED}DIFFER${RESET}  $MISMATCHED / $TOTAL"
echo -e "  ${RED}MISSING${RESET} $MISSING / $TOTAL"

if [ "$MISMATCHED" -eq 0 ] && [ "$MISSING" -eq 0 ]; then
  echo ""
  echo -e "  ${GREEN}${BOLD}All synced.${RESET}"
else
  echo ""
  echo -e "  ${YELLOW}Run 'ship' then 'bash ~/drop-watcher/bin/sync_ironman.sh' on ironman.${RESET}"
fi
echo -e "${BOLD}════════════════════════════════════════════${RESET}"
