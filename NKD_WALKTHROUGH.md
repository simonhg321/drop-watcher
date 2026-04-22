# NKD Walkthrough — end-to-end test

Test the whole flow without flipping the live flag. Each step tells you what "passing" looks like.

## Prep: reload gunicorn so new routes load

```bash
sudo supervisorctl restart watcher_signup
# Or whatever it's named. Find it with: sudo supervisorctl status
```

**Pass:** `watcher_signup RUNNING   pid XXXXX, uptime 0:00:02`

---

## Step 1 — Wall endpoint alive (empty list expected)

```bash
curl -s https://instockornot.club/api/nkd/wall
```

**Pass:** `{"entries":[],"ok":true}`
**Fail:** 404 / 500 / HTML error page → gunicorn didn't reload, retry the restart.

---

## Step 2 — Generate a test token against your own watcher

```bash
cd /home/shg/drop-watcher
python3 -c "
import nkd, db
w = [x for x in db.get_active_watchers() if 'gibson.simon1' in x['email'] or 'simonhg' in x['email']][0]
print('watcher_id:', w['id'])
print('email:', w['email'])
t = nkd.make_token(w['id'], 'https://example.com/fake-knife-drop')
print()
print('TEST URL:')
print('https://instockornot.club/nkd.html?t=' + t)
"
```

**Pass:** prints a URL. Copy it.

---

## Step 3 — GET the token via API

```bash
# Paste the token portion only (after ?t=) into TOKEN, or curl the URL directly:
TOKEN=<paste-just-the-token-here>
curl -s "https://instockornot.club/api/nkd/$TOKEN" | python3 -m json.tool
```

**Pass:** JSON with `"ok": true`, your name, keywords, `drop_url`, `already_scored: false`.
**Fail:** `ok:false` → token malformed, or watcher no longer active.

---

## Step 4 — Open the landing page in a browser

Paste the TEST URL from step 2 into a browser.

**Pass:**
- Page loads with green "NKD" header
- Shows the fake drop URL
- Shows your keywords
- Has a note box, image URL box, checkbox for wall, green submit button

**Fail scenarios:**
- "Link expired or invalid" → token got corrupted in copy, or secret file permissions wrong (see `/var/lib/drop-watcher/nkd.secret`)
- Blank page → check browser devtools for JS errors, probably a typo in the HTML

---

## Step 5 — Submit with note + wall opt-in

In the form:
- Note: `test submission, ignore`
- Image URL: `https://i.imgur.com/test.jpg` (or leave blank — optional)
- Check "Show on the public wins wall"
- Click **Record My Score**

**Pass:** "🔪 Locked in. Thanks for telling us." success banner appears.

---

## Step 6 — Confirm the row landed in the DB

```bash
sqlite3 -header /var/lib/drop-watcher/dropwatcher.db \
  "SELECT id, watcher_id, drop_url, note, image_url, show_on_wall, scored_at FROM nkd_scores ORDER BY id DESC LIMIT 5;"
```

(may need `sudo` prefix)

**Pass:** your submission is the top row, fields populated correctly.

---

## Step 7 — The wall shows your score

Open https://instockornot.club/wall.html

**Pass:** your score is visible — "Anon" or your name, "just now", the note, source link.
**Fail:** empty wall → check `show_on_wall` column in step 6 (must be `1`).

---

## Step 8 — Dedupe: second submit should fail cleanly

Reload the same test URL from step 2. 

**Pass:** page shows "Already logged. Enjoy the blade. 🔪" — no form.

Or via curl:
```bash
curl -s -X POST -H 'Content-Type: application/json' -d '{"note":"dup"}' \
  "https://instockornot.club/api/nkd/$TOKEN"
```
**Pass:** `{"ok":false,"msg":"Already recorded. Thanks!"}` with HTTP 409.

---

## Step 9 — Tampered token rejected

```bash
BAD_TOKEN="${TOKEN}XXXX"
curl -s "https://instockornot.club/api/nkd/$BAD_TOKEN"
```

**Pass:** `{"ok":false,"msg":"Link expired or invalid."}` with HTTP 400.

---

## Step 10 — (Only if you want to go live) Email button

Flip the flag and trigger a real alerter run:

```bash
# In your cron / supervisor env, set DW_NKD_ENABLED=1
# Then force a run:
DW_NKD_ENABLED=1 python3 /home/shg/drop-watcher/per_user_alerter.py
```

**Pass:** next real alert email has a green "🔪 I Scored One →" button below the Dashboard button.

---

## Cleanup after testing

If you want the test rows gone:

```bash
sudo sqlite3 /var/lib/drop-watcher/dropwatcher.db "DELETE FROM nkd_scores WHERE note LIKE '%test%';"
```

That's it. Steps 1-9 don't touch production alert emails at all — safe to run any time.
