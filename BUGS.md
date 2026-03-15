# Drop Watcher — Known Bugs

## BUG-007: Stale web/ directory in repo
**Logged:** 2026-03-14
**Severity:** Low (no user impact yet, but a landmine)
**Description:** `web/html/` contains old copies of HTML files including `.bak` files. These are not served but could cause confusion about which version is canonical. The real webroot is `/var/www/html/` on ironman.
**Fix:** Delete `web/` directory from repo and ironman. Ensure ship alias only copies from project root.

## BUG-008: orchestrator.py is an empty file
**Logged:** 2026-03-14
**Severity:** Trivial
**Description:** `orchestrator.py` is a 1-line empty file. Nothing imports it. Likely a placeholder from early development.
**Fix:** Delete it.
