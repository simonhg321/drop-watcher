#!/usr/bin/env python3
"""
alerter.py
Drop Watcher — SMTP Alert System
Sends immediate emails for critical/high alerts.
Sends daily digest for all alerts.
HGR
"""

import os
import json
import smtplib
import logging
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# ── Load environment ──────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))

# ── Config ────────────────────────────────────────────────────────────────────
SMTP_HOST     = 'smtp.gmail.com'
SMTP_PORT     = 587
SMTP_USER     = os.environ.get('SMTP_USER')
SMTP_PASSWORD = os.environ.get('SMTP_APP_PASSWORD')
ALERT_TO      = os.environ.get('SMTP_USER')  # send to yourself

LOG_DIR       = os.path.join(BASE_DIR, 'logs')
DROPS_LOG     = os.path.join(LOG_DIR, 'drops.jsonl')
SENT_LOG      = os.path.join(LOG_DIR, 'alerts_sent.jsonl')

IMMEDIATE_PRIORITIES = {'critical', 'high'}

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger('alerter')

# ── SMTP sender ───────────────────────────────────────────────────────────────
def send_email(subject, body_html, body_text):
    if not SMTP_USER or not SMTP_PASSWORD:
        log.error("SMTP credentials not configured in .env")
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = f"Drop Watcher <{SMTP_USER}>"
    msg['To']      = ALERT_TO

    msg.attach(MIMEText(body_text, 'plain'))
    msg.attach(MIMEText(body_html, 'html'))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, ALERT_TO, msg.as_string())
        log.info(f"Email sent: {subject}")
        return True
    except Exception as e:
        log.error(f"Failed to send email: {e}")
        return False

# ── Track sent alerts ─────────────────────────────────────────────────────────
def already_sent(alert_id):
    if not os.path.exists(SENT_LOG):
        return False
    with open(SENT_LOG, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get('alert_id') == alert_id:
                    return True
            except:
                continue
    return False

def mark_sent(alert_id, alert_type):
    with open(SENT_LOG, 'a') as f:
        f.write(json.dumps({
            'alert_id': alert_id,
            'type': alert_type,
            'sent_at': datetime.now(timezone.utc).isoformat()
        }) + '\n')

def make_alert_id(alert):
    return f"{alert.get('timestamp','')}_{alert.get('source','')}"

# ── Format immediate alert email ──────────────────────────────────────────────
def format_immediate_email(alert):
    priority = alert.get('priority', 'high').upper()
    source   = alert.get('source', 'Unknown')
    url      = alert.get('url', '#')
    ts       = alert.get('timestamp', '')

    notable_items = alert.get('notable_items', [])
    matches       = alert.get('matches', [])
    drop          = alert.get('drop_announcement', {})
    summary       = alert.get('page_summary', '')

    subject = f"[DROP WATCHER] {priority} — {source}"

    # Plain text
    text_lines = [
        f"DROP WATCHER ALERT",
        f"Priority: {priority}",
        f"Site: {source}",
        f"URL: {url}",
        f"Time: {ts}",
        f"",
    ]

    if drop and drop.get('detected'):
        text_lines += [
            f"🔥 DROP ANNOUNCEMENT",
            f"Maker: {drop.get('maker', '')}",
            f"What: {drop.get('description', '')}",
            f"When: {drop.get('timing', 'unknown')}",
            f"Confidence: {drop.get('confidence', '')}",
            f"",
        ]

    if notable_items:
        text_lines.append("Notable Items:")
        for item in notable_items:
            text_lines.append(f"  → {item}")
        text_lines.append("")

    if summary:
        text_lines.append(f"Summary: {summary}")

    if matches and not notable_items:
        text_lines.append(f"Matched keywords: {', '.join(matches[:15])}")

    text_lines += ["", "HGR", "instockornot.club"]
    body_text = '\n'.join(text_lines)

    # HTML
    priority_color = '#e74c3c' if priority == 'CRITICAL' else '#e67e22'

    notable_html = ''
    if notable_items:
        items = ''.join(f'<li style="margin:4px 0">{item}</li>' for item in notable_items)
        notable_html = f'<ul style="color:#d0d0d0;padding-left:20px">{items}</ul><div style="margin-top:8px"><a href="{url}" style="color:#e67e22">{url}</a></div>'
    drop_html = ''
    if drop and drop.get('detected'):
        drop_html = f"""
        <div style="background:rgba(192,57,43,0.2);border-left:3px solid #e74c3c;padding:12px 16px;margin:16px 0">
            <div style="color:#e74c3c;font-weight:bold;font-size:16px">🔥 DROP ANNOUNCEMENT</div>
            <div style="color:#d0d0d0;margin-top:8px">
                <strong>Maker:</strong> {drop.get('maker', '')}<br>
                <strong>What:</strong> {drop.get('description', '')}<br>
                <strong>When:</strong> {drop.get('timing', 'unknown')}<br>
                <strong>Confidence:</strong> {drop.get('confidence', '')}
                <br><a href="{url}" style="color:#e67e22">{url}</a>
            </div>
        </div>"""

    matches_html = ''
    if matches and not notable_items:
        matches_html = f'<p style="color:#888;font-size:12px">Matched: {", ".join(matches[:15])}</p>'

    summary_html = f'<p style="color:#888;font-style:italic;margin-top:12px">{summary}</p>' if summary else ''

    body_html = f"""
    <html><body style="background:#0a0a0a;color:#f0f0f0;font-family:'Courier New',monospace;padding:24px;max-width:600px">
        <h1 style="font-size:28px;letter-spacing:2px;margin:0">DROP <span style="color:#c0392b">WATCHER</span></h1>
        <div style="height:2px;background:linear-gradient(90deg,transparent,#c0392b,#e67e22,#c0392b,transparent);margin:12px 0 24px"></div>

        <div style="display:flex;gap:12px;align-items:center;margin-bottom:16px">
            <span style="color:{priority_color};font-size:18px;font-weight:bold;letter-spacing:2px">{priority}</span>
            <span style="color:#888;font-size:12px">{ts}</span>
        </div>

        <div style="background:#1c1c1c;padding:16px;margin-bottom:16px">
            <div style="color:#888;font-size:11px;letter-spacing:2px;margin-bottom:8px">SITE</div>
            <div style="font-size:20px;font-weight:bold;margin-bottom:12px">{source}</div>
            <a href="{url}" style="display:inline-block;background:#c0392b;color:#ffffff;font-size:14px;font-weight:bold;letter-spacing:2px;padding:12px 24px;text-decoration:none;margin-bottom:8px">→ GO TO SITE NOW</a>
            <div style="margin-top:8px"><a href="{url}" style="color:#888;font-size:11px">{url}</a></div>
        </div>

        {drop_html}
        {notable_html}
        {summary_html}
        {matches_html}

        <div style="margin-top:32px;padding-top:16px;border-top:1px solid #2a2a2a;color:#888;font-size:11px;letter-spacing:2px">
            instockornot.club — <a href="https://instockornot.club/alerts.html" style="color:#e67e22">VIEW ALL ALERTS</a>
            <div style="margin-top:8px;color:#c0392b;font-size:16px;font-weight:bold">HGR</div>
        </div>
    </body></html>"""

    return subject, body_html, body_text

# ── Format daily digest email ─────────────────────────────────────────────────
def format_digest_email(alerts):
    now   = datetime.now()
    count = len(alerts)

    subject = f"[DROP WATCHER] Daily Digest — {count} alerts — {now.strftime('%Y-%m-%d')}"

    critical = [a for a in alerts if a.get('priority') == 'critical']
    high     = [a for a in alerts if a.get('priority') == 'high']
    medium   = [a for a in alerts if a.get('priority') == 'medium']

    def alert_row(alert):
        source  = alert.get('source', 'Unknown')
        url     = alert.get('url', '#')
        ts      = alert.get('timestamp', '')[:16].replace('T', ' ')
        items   = alert.get('notable_items', [])
        matches = alert.get('matches', [])
        detail  = items[0] if items else (', '.join(matches[:3]) if matches else '')
        return f'<tr><td style="padding:6px 12px;color:#d0d0d0"><a href="{url}" style="color:#d0d0d0">{source}</a></td><td style="padding:6px 12px;color:#888;font-size:11px">{ts}</td><td style="padding:6px 12px;color:#888;font-size:11px">{detail}</td></tr>'

    def section(title, color, alerts_list):
        if not alerts_list:
            return ''
        rows = ''.join(alert_row(a) for a in alerts_list)
        return f"""
        <h3 style="color:{color};letter-spacing:2px;margin:24px 0 8px">{title} ({len(alerts_list)})</h3>
        <table style="width:100%;border-collapse:collapse;background:#1c1c1c">
            <thead><tr>
                <th style="text-align:left;padding:6px 12px;color:#888;font-size:11px;letter-spacing:2px;border-bottom:1px solid #2a2a2a">SITE</th>
                <th style="text-align:left;padding:6px 12px;color:#888;font-size:11px;letter-spacing:2px;border-bottom:1px solid #2a2a2a">TIME</th>
                <th style="text-align:left;padding:6px 12px;color:#888;font-size:11px;letter-spacing:2px;border-bottom:1px solid #2a2a2a">DETAIL</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>"""

    body_html = f"""
    <html><body style="background:#0a0a0a;color:#f0f0f0;font-family:'Courier New',monospace;padding:24px;max-width:700px">
        <h1 style="font-size:28px;letter-spacing:2px;margin:0">DROP <span style="color:#c0392b">WATCHER</span></h1>
        <div style="height:2px;background:linear-gradient(90deg,transparent,#c0392b,#e67e22,#c0392b,transparent);margin:12px 0 24px"></div>
        <h2 style="color:#888;font-size:14px;letter-spacing:3px;font-weight:normal">DAILY DIGEST — {now.strftime('%Y-%m-%d')}</h2>

        <div style="display:flex;gap:24px;margin:24px 0">
            <div style="background:#1c1c1c;padding:12px 20px;text-align:center">
                <div style="color:#888;font-size:10px;letter-spacing:2px">TOTAL</div>
                <div style="color:#f0f0f0;font-size:24px">{count}</div>
            </div>
            <div style="background:#1c1c1c;padding:12px 20px;text-align:center">
                <div style="color:#888;font-size:10px;letter-spacing:2px">CRITICAL</div>
                <div style="color:#e74c3c;font-size:24px">{len(critical)}</div>
            </div>
            <div style="background:#1c1c1c;padding:12px 20px;text-align:center">
                <div style="color:#888;font-size:10px;letter-spacing:2px">HIGH</div>
                <div style="color:#e67e22;font-size:24px">{len(high)}</div>
            </div>
            <div style="background:#1c1c1c;padding:12px 20px;text-align:center">
                <div style="color:#888;font-size:10px;letter-spacing:2px">MEDIUM</div>
                <div style="color:#f1c40f;font-size:24px">{len(medium)}</div>
            </div>
        </div>

        {section('🔥 CRITICAL', '#e74c3c', critical)}
        {section('⚡ HIGH', '#e67e22', high)}
        {section('· MEDIUM', '#f1c40f', medium)}

        <div style="margin-top:32px;padding-top:16px;border-top:1px solid #2a2a2a;color:#888;font-size:11px;letter-spacing:2px">
            <a href="https://instockornot.club/alerts.html" style="color:#e67e22">VIEW FULL ALERTS PAGE</a>
            <div style="margin-top:8px;color:#c0392b;font-size:16px;font-weight:bold">HGR</div>
        </div>
    </body></html>"""

    body_text = f"Drop Watcher Daily Digest — {now.strftime('%Y-%m-%d')}\n{count} total alerts\nCritical: {len(critical)} High: {len(high)} Medium: {len(medium)}\n\nSee https://instockornot.club/alerts.html\n\nHGR"

    return subject, body_html, body_text

# ── Send immediate alerts for new high/critical drops ────────────────────────
def send_immediate_alerts():
    if not os.path.exists(DROPS_LOG):
        return

    # Only look at alerts from last 35 minutes (slightly more than poll interval)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=35)
    sent_count = 0

    with open(DROPS_LOG, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                alert = json.loads(line)
                priority = alert.get('priority', 'medium').lower()

                if priority not in IMMEDIATE_PRIORITIES:
                    continue

                ts_str = alert.get('timestamp', '')
                if ts_str:
                    ts = datetime.fromisoformat(ts_str)
                    if ts < cutoff:
                        continue

                alert_id = make_alert_id(alert)
                if already_sent(alert_id):
                    continue

                subject, body_html, body_text = format_immediate_email(alert)
                if send_email(subject, body_html, body_text):
                    mark_sent(alert_id, 'immediate')
                    sent_count += 1

            except json.JSONDecodeError:
                continue

    if sent_count:
        log.info(f"Sent {sent_count} immediate alert emails")

# ── Send daily digest ─────────────────────────────────────────────────────────
def send_daily_digest():
    if not os.path.exists(DROPS_LOG):
        log.info("No drops log found — skipping digest")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    alerts = []

    with open(DROPS_LOG, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                alert = json.loads(line)
                ts_str = alert.get('timestamp', '')
                if ts_str:
                    ts = datetime.fromisoformat(ts_str)
                    if ts > cutoff:
                        alerts.append(alert)
            except json.JSONDecodeError:
                continue

    subject, body_html, body_text = format_digest_email(alerts)
    if send_email(subject, body_html, body_text):
        log.info(f"Daily digest sent — {len(alerts)} alerts")

# ── Test ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'digest':
        log.info("Sending daily digest...")
        send_daily_digest()
    elif len(sys.argv) > 1 and sys.argv[1] == 'test':
        log.info("Sending test email...")
        test_alert = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'priority': 'high',
            'source': 'Test Site',
            'url': 'https://instockornot.club',
            'notable_items': ['CRK Damascus Sebenza 31 — 1 in stock', 'Hinderer XM-18 Steel Flame — 1 in stock'],
            'page_summary': 'Test alert from Drop Watcher system.',
            'drop_announcement': {
                'detected': True,
                'maker': 'Steel Flame',
                'description': 'New pendant drop',
                'timing': 'Friday at noon',
                'confidence': 'high'
            }
        }
        subject, body_html, body_text = format_immediate_email(test_alert)
        success = send_email(subject, body_html, body_text)
        print("✓ Test email sent!" if success else "✗ Test email failed — check logs")
    else:
        log.info("Checking for unsent immediate alerts...")
        send_immediate_alerts()
