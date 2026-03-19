#!/bin/bash
# sync_check.sh — Verify sync state across Mac, GitHub, and ironman
# Run from your Mac in the drop-watcher directory
# HGR

echo "════════════════════════════════════════════"
echo "  DROP WATCHER SYNC CHECK"
echo "════════════════════════════════════════════"
echo ""

# ── Local state ──────────────────────────────────────────────────────────────
echo "── LOCAL (Mac) ──"
BRANCH=$(git branch --show-current)
echo "  Branch:     $BRANCH"
echo "  Last commit: $(git log --oneline -1)"
echo ""

# ── Uncommitted changes ─────────────────────────────────────────────────────
DIRTY=$(git status --porcelain | grep -v '^\?\?' | wc -l | tr -d ' ')
UNTRACKED=$(git status --porcelain | grep '^\?\?' | wc -l | tr -d ' ')
if [ "$DIRTY" -gt 0 ]; then
  echo "  ⚠  $DIRTY uncommitted changes"
  git status --porcelain | grep -v '^\?\?'
else
  echo "  ✓  Working tree clean"
fi
if [ "$UNTRACKED" -gt 0 ]; then
  echo "  ⚠  $UNTRACKED untracked files"
fi
echo ""

# ── GitHub sync ──────────────────────────────────────────────────────────────
echo "── GITHUB ──"
git fetch origin --quiet 2>/dev/null

for b in main v2; do
  LOCAL=$(git rev-parse $b 2>/dev/null)
  REMOTE=$(git rev-parse origin/$b 2>/dev/null)
  if [ -z "$LOCAL" ]; then
    echo "  $b: branch not found locally"
  elif [ -z "$REMOTE" ]; then
    echo "  $b: not on GitHub"
  elif [ "$LOCAL" = "$REMOTE" ]; then
    echo "  ✓  $b in sync with GitHub"
  else
    AHEAD=$(git rev-list origin/$b..$b --count 2>/dev/null)
    BEHIND=$(git rev-list $b..origin/$b --count 2>/dev/null)
    echo "  ⚠  $b: ${AHEAD} ahead, ${BEHIND} behind GitHub"
  fi
done
echo ""

# ── Ironman sync ─────────────────────────────────────────────────────────────
echo "── IRONMAN ──"
echo "  Checking key files..."

# Files to check — the ones that matter
FILES="watcher_signup.py per_user_alerter.py alerter.py sms_alerter.py paths.py agents/web_watcher.py agents/feed_watcher.py agents/ai_interpreter.py"

MISMATCHED=0
for f in $FILES; do
  LOCAL_MD5=$(md5 -q "$f" 2>/dev/null || md5sum "$f" 2>/dev/null | cut -d' ' -f1)
  REMOTE_MD5=$(ssh shg@instockornot.club "md5sum ~/drop-watcher/$f 2>/dev/null" | cut -d' ' -f1)
  if [ -z "$REMOTE_MD5" ]; then
    echo "  ⚠  $f: missing on ironman"
    MISMATCHED=$((MISMATCHED+1))
  elif [ "$LOCAL_MD5" != "$REMOTE_MD5" ]; then
    echo "  ⚠  $f: DIFFERS"
    MISMATCHED=$((MISMATCHED+1))
  fi
done

# Check webroot HTML
HTML_FILES="index.html watchlist.html my-alerts.html get-my-link.html privacy.html"
for f in $HTML_FILES; do
  LOCAL_MD5=$(md5 -q "html/$f" 2>/dev/null || md5sum "html/$f" 2>/dev/null | cut -d' ' -f1)
  REMOTE_MD5=$(ssh shg@instockornot.club "md5sum /var/www/html/$f 2>/dev/null" | cut -d' ' -f1)
  if [ -z "$REMOTE_MD5" ]; then
    echo "  ⚠  html/$f: missing on ironman webroot"
    MISMATCHED=$((MISMATCHED+1))
  elif [ "$LOCAL_MD5" != "$REMOTE_MD5" ]; then
    echo "  ⚠  html/$f: DIFFERS (webroot)"
    MISMATCHED=$((MISMATCHED+1))
  fi
done

if [ "$MISMATCHED" -eq 0 ]; then
  echo "  ✓  All key files match ironman"
else
  echo ""
  echo "  $MISMATCHED file(s) out of sync with ironman"
fi
echo ""

# ── Ironman services ─────────────────────────────────────────────────────────
echo "── IRONMAN SERVICES ──"
ssh shg@instockornot.club "sudo supervisorctl status 2>/dev/null"
echo ""

echo "════════════════════════════════════════════"
echo "  Done. You're the sysadm."
echo "════════════════════════════════════════════"
