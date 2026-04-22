# NKD Ship Checklist — AM of 2026-04-23

## What's built (no prod touched)

- `nkd.py` — stateless HMAC tokens + DB helpers. Secret at `/var/lib/drop-watcher/nkd.secret` (mode 600).
- `db.py` — `nkd_scores` table appended to SCHEMA (auto-creates on next connection).
- `per_user_alerter.py` — adds "🔪 I Scored One →" button to alert email. **Feature-flagged behind `DW_NKD_ENABLED=1`** — defaults off, does not ship until you flip it.
- `watcher_signup.py` — new routes: `GET /api/nkd/<token>`, `POST /api/nkd/<token>`, `GET /api/nkd/wall`.
- `/var/www/html/nkd.html` — landing page ("you scored — tell us about it").
- `/var/www/html/wall.html` — public wins wall.

## What already works

- Token generation + verification: tested, tamper-detection works.
- Secret file auto-generated on first token.
- All four touched Python files pass `ast.parse` (no syntax errors).
- DB table created next time `db.get_db()` is called — the existing code already runs `_init_db` on every connection, so a schema migration is automatic.

## Smoke tests before flipping the flag

```bash
# 1. Make sure watcher_signup reloads the new routes
sudo supervisorctl restart watcher_signup   # or whatever it's called in supervisor.conf

# 2. Hit the wall endpoint — should return empty list
curl -s https://instockornot.club/api/nkd/wall

# 3. Generate a test token + verify against a real watcher id
python3 -c "import nkd, db;
w = db.get_active_watchers()[0];
t = nkd.make_token(w['id'], 'https://example.com/fake-drop');
print('Test URL: https://instockornot.club/nkd.html?t=' + t)"
# Open that URL in a browser — should see the form.
# Fill it out, submit, check the wall at /wall.html.
```

## Ship it

```bash
# 1. Verify supervisor config for the alerter cron
grep -r NKD /etc/supervisor/conf.d/ /etc/environment

# 2. Set DW_NKD_ENABLED=1 in the alerter's environment.
# Edit /etc/supervisor/conf.d/drop-watcher.conf (or wherever the alerter env lives),
# add DW_NKD_ENABLED="1" to the environment= line for per_user_alerter,
# and do the same in crontab if per_user_alerter is run via cron.

# 3. For cron-driven runs (every 10 min), prepend to the crontab line:
# DW_NKD_ENABLED=1 python3 /home/shg/drop-watcher/per_user_alerter.py ...

# 4. Reload
sudo supervisorctl reread && sudo supervisorctl update
# or re-edit crontab with crontab -e

# 5. Watch one real alert land — confirm the button is green and the link works.
```

## Rollback

- Flip `DW_NKD_ENABLED` back to `0` (or unset) — button disappears on next alert.
- New table + endpoints are harmless if unused.

## Follow-ups (not for AM)

- Direct image upload (thumbnails, S3-equivalent on ironman).
- Moderation queue for wall posts (right now opt-in public is unmoderated).
- Add `nkd_scored` count to stats page — conversion rate per keyword / per source.
- Email: send a quiet "thanks for logging your score" confirmation.
