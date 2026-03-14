# Copyright (c) 2026 Simon HGR — instockornot.club — ELv2 License
"""
watchdog.py — Self-healing watchdog for Drop Watcher services
Runs via cron every 2 minutes: */2 * * * * python3 /home/shg/drop-watcher/watchdog.py

Checks services, auto-restarts if down. Only emails if restart fails.
HGR
"""

import json
import os
import subprocess
import sys
import time
import logging
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [watchdog] %(message)s')
log = logging.getLogger(__name__)

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
STATE_FILE   = os.path.join(BASE_DIR, 'logs', 'watchdog_state.json')
COOLDOWN_MIN = 30


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def should_alert(state, check_name):
    last = state.get(check_name)
    if not last:
        return True
    last_dt = datetime.fromisoformat(last)
    return datetime.now(timezone.utc) - last_dt > timedelta(minutes=COOLDOWN_MIN)


def send_alert(subject, body):
    try:
        from alerter import send_email
        send_email(
            f"[WATCHDOG] {subject}",
            f"<pre style='font-family:monospace;background:#0a0a0a;color:#f0f0f0;padding:24px'>{body}</pre>",
            body
        )
        log.info(f"Alert sent: {subject}")
    except Exception as e:
        log.error(f"Failed to send alert: {e}")


# ── Heal actions ─────────────────────────────────────────────────────────────

def heal_gunicorn():
    """Kill zombie port, restart via supervisor."""
    log.info("Healing gunicorn — killing port 5001 and restarting")
    subprocess.run(['/usr/bin/sudo', '/usr/bin/fuser', '-k', '5001/tcp'], capture_output=True)
    time.sleep(2)
    subprocess.run(['/usr/bin/sudo', '/usr/bin/supervisorctl', 'restart', 'watcher_signup'], capture_output=True)
    time.sleep(3)


def heal_web_watcher():
    log.info("Healing web_watcher — restarting via supervisor")
    subprocess.run(['/usr/bin/sudo', '/usr/bin/supervisorctl', 'restart', 'web_watcher'], capture_output=True)
    time.sleep(3)


def heal_apache():
    log.info("Healing apache — restarting")
    subprocess.run(['/usr/bin/sudo', '/usr/bin/systemctl', 'restart', 'apache2'], capture_output=True)
    time.sleep(3)


# ── Health checks ────────────────────────────────────────────────────────────

def check_gunicorn():
    import requests
    try:
        r = requests.get('http://127.0.0.1:5001/api/stats', timeout=5)
        if r.status_code == 200:
            return True, "ok"
        return False, f"status {r.status_code}"
    except Exception as e:
        return False, str(e)


def check_web_watcher():
    try:
        result = subprocess.run(
            ['/usr/bin/sudo', '/usr/bin/supervisorctl', 'status', 'web_watcher'],
            capture_output=True, text=True, timeout=10
        )
        if 'RUNNING' in result.stdout:
            return True, "ok"
        return False, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def check_apache():
    import requests
    try:
        r = requests.get('https://127.0.0.1/', timeout=5, verify=False, headers={'Host': 'instockornot.club'})
        if r.status_code == 200:
            return True, "ok"
        return False, f"status {r.status_code}"
    except Exception as e:
        return False, str(e)


def check_disk():
    import shutil
    total, used, free = shutil.disk_usage('/')
    pct = (used / total) * 100
    if pct > 90:
        return False, f"{pct:.0f}% used, {free / (1024**3):.1f}GB free"
    return True, f"{pct:.0f}% used"


# ── Main ─────────────────────────────────────────────────────────────────────

CHECKS = {
    'gunicorn':    {'check': check_gunicorn,    'heal': heal_gunicorn},
    'web_watcher': {'check': check_web_watcher, 'heal': heal_web_watcher},
    'apache':      {'check': check_apache,      'heal': heal_apache},
    'disk':        {'check': check_disk,         'heal': None},
}


def run():
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()
    still_broken = []

    for name, spec in CHECKS.items():
        ok, detail = spec['check']()

        if ok:
            if name in state:
                log.info(f"{name}: recovered")
            else:
                log.info(f"{name}: ok")
            state.pop(name, None)
            continue

        log.warning(f"{name}: FAIL — {detail}")

        # Try to heal
        if spec['heal']:
            spec['heal']()
            # Re-check after heal
            ok2, detail2 = spec['check']()
            if ok2:
                log.info(f"{name}: healed itself")
                state.pop(name, None)
                continue
            else:
                log.error(f"{name}: heal FAILED — {detail2}")
                still_broken.append((name, detail2))
        else:
            still_broken.append((name, detail))

    # Only email if heal didn't work
    for name, detail in still_broken:
        if should_alert(state, name):
            send_alert(
                f"{name} is DOWN — auto-heal failed",
                f"Service: {name}\nStatus: FAILED after auto-heal attempt\nDetail: {detail}\nTime: {now}\nHost: ironman (instockornot.club)"
            )
            state[name] = now

    save_state(state)

    if not still_broken:
        log.info("All checks passed.")
    else:
        log.warning(f"{len(still_broken)} service(s) still down after heal: {[f[0] for f in still_broken]}")


if __name__ == '__main__':
    run()
