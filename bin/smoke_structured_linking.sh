#!/usr/bin/env bash
# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#
# smoke_structured_linking.sh — post-merge verification for the structured
# item->link resolution work (S55). Two parts:
#   1. REGRESSION  — deterministic pytest covering the extractors, the confidence
#                    floor, the same-site guard, and the literal #6289 mislink.
#   2. SMOKE       — live, read-only fetch of real dealers proving structured
#                    deep-links resolve in the wild (tier 1 + tier 3).
#
# Run after merging to main (from the repo root): bin/smoke_structured_linking.sh
# Exit non-zero if either part fails.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "############################################################"
echo "# 1/2 REGRESSION (deterministic pytest)"
echo "############################################################"
python3 -m pytest tests/test_product_extract.py tests/test_linkpick_alert.py -q
reg=$?

echo
echo "############################################################"
echo "# 2/2 SMOKE (live, read-only — hits real dealer sites)"
echo "############################################################"
python3 bin/smoke_structured_linking.py
smoke=$?

echo
if [ "$reg" -eq 0 ] && [ "$smoke" -eq 0 ]; then
  echo "OVERALL: PASS ✅  (regression + smoke both green)"
  exit 0
fi
echo "OVERALL: FAIL ❌  (regression exit=$reg, smoke exit=$smoke)"
exit 1
