#!/bin/bash
# email_check.sh — Email deliverability diagnostic for instockornot.club
# Checks SPF, DKIM, DMARC, MX, and common issues
# HGR

DOMAIN="instockornot.club"
DKIM_SELECTOR="resend"

echo "════════════════════════════════════════════"
echo "  EMAIL DELIVERABILITY CHECK — $DOMAIN"
echo "════════════════════════════════════════════"
echo ""

# ── SPF ──────────────────────────────────────────────────────────────────────
echo "── SPF ──"
SPF=$(dig +short TXT "$DOMAIN" | grep "v=spf1")
if [ -z "$SPF" ]; then
  echo "  ✗  NO SPF RECORD FOUND"
else
  echo "  $SPF"
  # Check for common issues
  if echo "$SPF" | grep -q "~all"; then
    echo "  ⚠  Soft fail (~all) — Yahoo/iCloud prefer -all (hard fail)"
  elif echo "$SPF" | grep -q "\-all"; then
    echo "  ✓  Hard fail (-all) — good"
  elif echo "$SPF" | grep -q "?all"; then
    echo "  ⚠  Neutral (?all) — tighten to -all"
  fi
  if echo "$SPF" | grep -q "include:resend"; then
    echo "  ✓  Resend included in SPF"
  elif echo "$SPF" | grep -q "resend"; then
    echo "  ✓  Resend referenced in SPF"
  else
    echo "  ⚠  Resend not found in SPF — check include"
  fi
fi
echo ""

# ── DKIM ─────────────────────────────────────────────────────────────────────
echo "── DKIM ──"
DKIM=$(dig +short TXT "${DKIM_SELECTOR}._domainkey.${DOMAIN}")
if [ -z "$DKIM" ]; then
  echo "  ✗  NO DKIM RECORD for ${DKIM_SELECTOR}._domainkey.${DOMAIN}"
  echo "     Try: dig TXT ${DKIM_SELECTOR}._domainkey.${DOMAIN}"
  # Check CNAME (Resend often uses CNAME for DKIM)
  DKIM_CNAME=$(dig +short CNAME "${DKIM_SELECTOR}._domainkey.${DOMAIN}")
  if [ -n "$DKIM_CNAME" ]; then
    echo "  ✓  CNAME found: $DKIM_CNAME"
    echo "     (Resend uses CNAME delegation — this is correct)"
  fi
else
  echo "  ✓  DKIM record found"
  echo "  $DKIM" | head -2
fi
echo ""

# ── DMARC ────────────────────────────────────────────────────────────────────
echo "── DMARC ──"
DMARC=$(dig +short TXT "_dmarc.${DOMAIN}")
if [ -z "$DMARC" ]; then
  echo "  ✗  NO DMARC RECORD"
  echo "     Yahoo will almost certainly spam you without DMARC"
else
  echo "  $DMARC"
  if echo "$DMARC" | grep -q "p=none"; then
    echo "  ⚠  Policy is p=none — Yahoo treats this as 'not serious'"
    echo "     Recommend: p=quarantine (or p=reject once confident)"
  elif echo "$DMARC" | grep -q "p=quarantine"; then
    echo "  ✓  Policy is p=quarantine — solid"
  elif echo "$DMARC" | grep -q "p=reject"; then
    echo "  ✓  Policy is p=reject — strictest, good"
  fi
  if echo "$DMARC" | grep -q "rua="; then
    echo "  ✓  Aggregate reports (rua) configured"
  else
    echo "  ⚠  No rua= tag — you're flying blind on DMARC failures"
    echo "     Add rua=mailto:dmarc@${DOMAIN} to get reports"
  fi
fi
echo ""

# ── MX ───────────────────────────────────────────────────────────────────────
echo "── MX ──"
MX=$(dig +short MX "$DOMAIN")
if [ -z "$MX" ]; then
  echo "  ⚠  No MX records — not required for sending but helps reputation"
else
  echo "$MX" | while read line; do echo "  $line"; done
fi
echo ""

# ── Reverse DNS / PTR ────────────────────────────────────────────────────────
echo "── DOMAIN A RECORD ──"
A_RECORD=$(dig +short A "$DOMAIN")
if [ -n "$A_RECORD" ]; then
  echo "  A: $A_RECORD"
  PTR=$(dig +short -x "$A_RECORD")
  if [ -n "$PTR" ]; then
    echo "  PTR: $PTR"
    echo "  ✓  Reverse DNS exists"
  else
    echo "  ⚠  No reverse DNS (PTR) — some providers penalize this"
  fi
fi
echo ""

# ── Blacklist quick check ────────────────────────────────────────────────────
echo "── BLACKLIST SPOT CHECK ──"
if [ -n "$A_RECORD" ]; then
  REVERSED=$(echo "$A_RECORD" | awk -F. '{print $4"."$3"."$2"."$1}')
  for BL in zen.spamhaus.org bl.spamcop.net b.barracudacentral.org; do
    RESULT=$(dig +short "${REVERSED}.${BL}" 2>/dev/null)
    if [ -n "$RESULT" ]; then
      echo "  ✗  LISTED on $BL — $RESULT"
    else
      echo "  ✓  Clean on $BL"
    fi
  done
else
  echo "  (skipped — no A record)"
fi
echo ""

# ── Yahoo-specific notes ─────────────────────────────────────────────────────
echo "── YAHOO / AOL NOTES ──"
echo "  Yahoo requires ALL of:"
echo "    1. Valid SPF with hard fail (-all)"
echo "    2. DKIM signing that matches From: domain exactly"
echo "    3. DMARC with p=quarantine or p=reject"
echo "    4. From: domain must match DKIM d= domain"
echo "    5. Unsubscribe headers (you have these ✓)"
echo "    6. Low complaint rate (< 0.3%)"
echo ""
echo "  As of Feb 2024, Yahoo enforces RFC 5321 strictly."
echo "  If Resend signs with d=resend.dev instead of d=${DOMAIN},"
echo "  DMARC alignment FAILS and Yahoo spams you."
echo ""
echo "  Check: In Resend dashboard → Domains → verify that"
echo "  'Custom DKIM signing' is ON for ${DOMAIN}"
echo ""

# ── iCloud notes ─────────────────────────────────────────────────────────────
echo "── iCLOUD NOTES ──"
echo "  iCloud delays are normal for new/low-volume senders."
echo "  Apple's system learns over time. Key factors:"
echo "    1. Consistent sending volume (don't spike)"
echo "    2. Low bounce rate"
echo "    3. User engagement (opens, clicks)"
echo "    4. Domain age and reputation"
echo "  Not much you can do except be patient and legit."
echo ""

echo "════════════════════════════════════════════"
echo "  Done. Check Resend dashboard for bounce/complaint rates."
echo "════════════════════════════════════════════"
