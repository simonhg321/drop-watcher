# Drop Watcher — SMS Wiring Handoff

## Status
The SMS code is written and deployed. It's waiting on Twilio A2P 10DLC approval (submitted, billed, pending since ~2026-03-14). Expected approval: Monday 2026-03-16.

## What's already done

### Code (all on ironman, ready to run)
- **sms_alerter.py** — complete, tested structure:
  - `send_sms_alert(alert)` — main entry, called by alerter.py on every CRITICAL drop
  - Only fires for `priority == 'critical'`
  - Reads `watchers.json`, finds watchers with `sms_approved: True` and a `phone` number
  - Sends via Twilio REST API (`twilio.rest.Client`)
  - Dedup: tracks sent SMS in `sms_sent.jsonl` (alert_id + phone combo)
  - Never raises exceptions — silently fails so email path is never blocked
  - 160-char SMS limit handled (truncates gracefully)
  - Message format: `DROP WATCHER: CRITICAL — {source}. {url} Reply STOP to unsubscribe.`
  - Has test mode: `python3 sms_alerter.py test +1xxxxxxxxxx`

- **alerter.py** line 340 — already calls `send_sms_alert(alert)` after every immediate email alert
- **watcher_signup.py** — stores `phone` and `sms_approved: False` on every new watcher
- **privacy.html** — full Twilio A2P 10DLC compliant SMS terms (opt-in, STOP, HELP, frequency, carrier disclosure, no data sharing)

### Twilio account
- Account SID, Auth Token, and FROM number (+19282498690) are in `/etc/drop-watcher/.env` on ironman
- Env vars: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`

### Signup form (watchlist.html)
- Already collects phone number field
- Has SMS consent checkbox

## What needs to happen once A2P is approved

### 1. Test the Twilio connection
```bash
cd ~/drop-watcher
python3 sms_alerter.py test +1YOURPHONENUMBER
```
This sends a test SMS. If it works, Twilio is wired correctly.

### 2. Flip sms_approved for Simon's watches
Currently all watchers have `sms_approved: False`. To enable SMS for your phone:
```python
# Quick script or manual edit of /var/lib/drop-watcher/watchers.json
# Find watchers with your email, set sms_approved: True
```

### 3. Wire the signup form to set sms_approved
In `watcher_signup.py`, the signup route currently hardcodes `sms_approved: False`.
Need to change it to respect the consent checkbox:
```python
'sms_approved': bool(data.get('sms_consent')),
```
And make sure `watchlist.html` sends `sms_consent: true` when the checkbox is checked.

### 4. STOP/HELP handling
Two options:
- **Twilio built-in**: Configure Advanced Opt-Out in the Twilio Messaging Service settings. Twilio auto-responds to STOP/HELP without hitting your server.
- **Webhook**: Set up a `/api/sms-webhook` endpoint that receives inbound SMS, parses STOP/HELP, and updates watchers.json. More control but more code.

Recommendation: Start with Twilio built-in. Add webhook later if needed.

### 5. Test end-to-end
- Sign up with phone + SMS consent
- Wait for (or trigger) a CRITICAL drop
- Confirm SMS arrives
- Reply STOP, confirm opt-out works

## File locations
| What | Where |
|------|-------|
| SMS sending code | `sms_alerter.py` (project root) |
| Called from | `alerter.py` line 340 |
| Twilio creds | `/etc/drop-watcher/.env` on ironman |
| Watcher data | `/var/lib/drop-watcher/watchers.json` |
| SMS sent log | `/var/log/drop-watcher/sms_sent.jsonl` |
| Privacy/SMS terms | `html/privacy.html` |
| Signup form | `html/watchlist.html` |
| Signup API | `watcher_signup.py` |

## Why SMS matters
On 2026-03-15 Drop Watcher caught its first real drop (Strider knives). By the time Simon checked email, they were gone. SMS is the difference between catching a drop and reading about one you missed.
