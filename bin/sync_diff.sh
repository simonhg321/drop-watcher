#!/bin/bash
# sync_diff.sh — Show actual diffs between Mac repo and ironman
# Run from Mac in the drop-watcher directory
# HGR

set -o pipefail

HOST="${DW_SSH_HOST:?Set DW_SSH_HOST in your shell profile}"
REMOTE_CODE="~/drop-watcher"
REMOTE_WEB="/var/www/html"
REMOTE_CONF="/etc/drop-watcher"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

DIFFCOUNT=0
MATCHCOUNT=0
MISSINGCOUNT=0

show_diff() {
  local local_file="$1"
  local remote_file="$2"
  local label="$3"

  if [ ! -f "$local_file" ]; then
    return
  fi

  LOCAL_MD5=$(md5 -q "$local_file" 2>/dev/null || md5sum "$local_file" 2>/dev/null | cut -d' ' -f1)
  REMOTE_MD5=$(ssh "$HOST" "md5sum $remote_file 2>/dev/null" | cut -d' ' -f1)

  if [ -z "$REMOTE_MD5" ]; then
    echo -e "  ${RED}MISSING${RESET}  $label  ${DIM}→ not on ironman${RESET}"
    MISSINGCOUNT=$((MISSINGCOUNT+1))
    return
  fi

  if [ "$LOCAL_MD5" = "$REMOTE_MD5" ]; then
    MATCHCOUNT=$((MATCHCOUNT+1))
    return
  fi

  DIFFCOUNT=$((DIFFCOUNT+1))
  echo ""
  echo -e "${BOLD}${YELLOW}═══ DIFFERS: $label ═══${RESET}"
  echo -e "${DIM}  mac (local) vs ironman (remote)${RESET}"
  echo ""
  diff --color=always -u \
    <(ssh "$HOST" "cat $remote_file 2>/dev/null") \
    "$local_file" \
    --label "ironman:$label" \
    --label "mac:$label" \
    | head -60
  echo ""
}

echo ""
echo -e "${BOLD}════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  DROP WATCHER — SYNC DIFF${RESET}"
echo -e "${DIM}  $(date '+%Y-%m-%d %H:%M:%S')${RESET}"
echo -e "${BOLD}════════════════════════════════════════════${RESET}"

# Python
echo ""
echo -e "${BOLD}── PYTHON ──${RESET}"
for f in \
  alerter.py \
  discord_logger.py \
  generate_alerts.py \
  generate_traffic.py \
  generate_security.py \
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
  show_diff "$f" "$REMOTE_CODE/$f" "$f"
done

# Agents
echo ""
echo -e "${BOLD}── AGENTS ──${RESET}"
for f in \
  agents/ai_interpreter.py \
  agents/feed_watcher.py \
  agents/web_watcher.py \
; do
  show_diff "$f" "$REMOTE_CODE/$f" "$f"
done

# Config
echo ""
echo -e "${BOLD}── CONFIG (/etc/drop-watcher/) ──${RESET}"
for f in sources.yaml makers.yaml cool_list.yaml settings.yaml; do
  show_diff "config/$f" "$REMOTE_CONF/$f" "config/$f"
done

# HTML (public)
echo ""
echo -e "${BOLD}── PUBLIC HTML ──${RESET}"
for f in \
  index.html \
  watchlist.html \
  my-alerts.html \
  get-my-link.html \
  privacy.html \
  hgr.html \
  alerts.html \
  sms-optin.html \
  what-we-watch.html \
  terms.html \
  robots.txt \
; do
  show_diff "html/$f" "$REMOTE_WEB/$f" "html/$f"
done

# HTML (admin)
echo ""
echo -e "${BOLD}── ADMIN HTML ──${RESET}"
show_diff "html/stats/dashboard.html" "$REMOTE_WEB/stats/dashboard.html" "stats/dashboard.html"

# Supervisor
echo ""
echo -e "${BOLD}── SUPERVISOR ──${RESET}"
show_diff "conf/drop-watcher.conf" "/etc/supervisor/conf.d/drop-watcher.conf" "conf/drop-watcher.conf"

# Bin
echo ""
echo -e "${BOLD}── BIN SCRIPTS ──${RESET}"
for f in bin/*.sh bin/*.py; do
  [ -f "$f" ] && show_diff "$f" "$REMOTE_CODE/$f" "$f"
done

# Summary
echo ""
echo -e "${BOLD}════════════════════════════════════════════${RESET}"
echo -e "  ${GREEN}MATCH${RESET}    $MATCHCOUNT"
echo -e "  ${YELLOW}DIFFERS${RESET}  $DIFFCOUNT"
echo -e "  ${RED}MISSING${RESET}  $MISSINGCOUNT"
echo -e "${BOLD}════════════════════════════════════════════${RESET}"
