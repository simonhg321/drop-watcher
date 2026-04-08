# Drop Watcher — Ironman Cheatsheet

## Pipeline
| Command | What |
|---------|------|
| `python3 ~/drop-watcher/bin/ai_calls.py user 5` | Last 5 user watch AI calls |
| `python3 ~/drop-watcher/bin/ai_calls.py curated 5` | Last 5 curated AI calls |
| `python3 ~/drop-watcher/bin/ai_calls.py all 10` | Last 10 AI calls (both) |
| `python3 ~/drop-watcher/bin/adm/active_user_watches.py` | All active watches by URL |
| `python3 ~/drop-watcher/bin/adm/find_watcher.py TERM` | Find watches by URL fragment |
| `python3 ~/drop-watcher/bin/adm/watch_statuses.py` | Watcher counts and field keys |
| `python3 ~/drop-watcher/bin/adm/cleanup_watches.py` | Dry run URL cleanup |

## Monitoring
| Command | What |
|---------|------|
| `sudo supervisorctl status` | All services |
| `tail -f /var/log/drop-watcher/web_watcher.log` | Live scraper log |
| `tail -20 /var/log/drop-watcher/drops.jsonl` | Recent drops |
| `python3 ~/drop-watcher/bin/token_report.py 7` | API token usage (7 days) |
| `python3 ~/drop-watcher/bin/sms_report.py` | SMS delivery stats |
| `python3 ~/drop-watcher/bin/ai_audit.py` | AI call audit |

## Services
| Command | What |
|---------|------|
| `sudo supervisorctl restart watcher_signup` | Restart Flask API |
| `sudo supervisorctl restart web_watcher` | Restart scraper |
| `sudo supervisorctl restart onboarding_sse` | Restart Go SSE |

## Data
| Path | What |
|------|------|
| `/var/lib/drop-watcher/watchers.json` | All watches (PII) |
| `/var/log/drop-watcher/drops.jsonl` | All drops detected |
| `/var/log/drop-watcher/api_usage.jsonl` | Haiku token usage |
| `/etc/drop-watcher/.env` | Secrets |
| `/etc/drop-watcher/sources.yaml` | Curated sources |

## Sync
| Command | What |
|---------|------|
| `bash ~/drop-watcher/bin/sync_audit.sh` | 3-way sync check (from Mac) |
| `bash ~/drop-watcher/bin/sync_ironman.sh` | Deploy after ship (on ironman) |
