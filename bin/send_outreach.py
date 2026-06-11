# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""Send the P_R_DROP wave-2 webmaster outreach emails via Resend.

Parses the wave-2 sections (## 7..## 14) of docs/outreach_emails_2026-06-11.md
so the markdown stays the single canonical copy. Plain-text, person-to-person:
From "Simon Gibson <simon@instockornot.club>", no HTML shell, no list headers.

Modes:
  (no flag)        DRY RUN — print to/subject/cc for each email, send nothing.
  --test ADDR      send the FIRST email to ADDR only, subject-tagged [TEST].
  --test ADDR N    send email #N (7-14) to ADDR instead.
  --send           send all 8 to the real dealers. Simon-authorized 2026-06-11.

Uses httpx (api.resend.com 403s urllib's UA — CF rule 1010).
HGR
"""
import os
import re
import sys
import time

import httpx

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import paths
from dotenv import load_dotenv
load_dotenv(paths.ENV_FILE, override=True)

EMAILS_MD = os.path.join(BASE, 'docs', 'outreach_emails_2026-06-11.md')
FROM_ADDRESS = 'Simon Gibson <simon@instockornot.club>'
RESEND_API_URL = 'https://api.resend.com/emails'
WAVE2 = range(7, 15)


def parse_emails():
    src = open(EMAILS_MD).read()
    out = []
    for m in re.finditer(
            r'^## (\d+)\. ([^\n]+?) — to: ([^\n]+)\n+\*\*Subject: ([^\n]+)\*\*\n+(.*?)\n---',
            src, re.M | re.S):
        num, name, to_raw, subject, body = m.groups()
        if int(num) not in WAVE2:
            continue
        cc = None
        ccm = re.search(r'\(cc:\s*([^)]+)\)', to_raw)
        if ccm:
            cc = ccm.group(1).strip()
        to = to_raw.split('(')[0].strip()
        body = body.strip().replace('`', '')   # no markdown backticks in plain text
        out.append({'num': int(num), 'name': name.strip(), 'to': to,
                    'cc': cc, 'subject': subject.strip(), 'body': body})
    return out


def _linkify(escaped_text):
    # Trailing punctuation stays outside the href, or the link 404s.
    return re.sub(r'(https?://[^\s<]+?)([.,;:!?)]*)(?=\s|$)',
                  r'<a href="\1" style="color:#c75b12;text-decoration:underline;">\1</a>\2',
                  escaped_text)


def build_html(e):
    """Render the plain-text body as a clean, light, professional email.
    Paragraphs from blank lines; the '- ' bullet block becomes the allowlist
    card; URLs become links. Deliberately not flashy — the audience is shop
    owners who distrust marketing-looking bot mail."""
    import html as html_mod
    parts = []
    for para in e['body'].split('\n\n'):
        lines = para.strip().split('\n')
        if all(l.startswith('- ') for l in lines):
            items = ''.join(
                f'<div style="padding:2px 0;">{html_mod.escape(l[2:])}</div>'
                for l in lines)
            parts.append(
                f'<div style="background:#f6f4ef;border:1px solid #e4dfd4;border-radius:6px;'
                f'padding:14px 18px;margin:18px 0;font-family:Consolas,Menlo,monospace;'
                f'font-size:13px;color:#3d3a33;">{items}</div>')
        elif lines[0].startswith('Thanks'):
            # Signature block: keep its line breaks.
            text = _linkify('<br>'.join(html_mod.escape(l) for l in lines))
            parts.append(
                f'<p style="margin:0 0 16px;color:#3d3a33;font-size:15px;line-height:1.65;">'
                f'{text}</p>')
        else:
            text = _linkify(html_mod.escape(' '.join(lines)))
            parts.append(
                f'<p style="margin:0 0 16px;color:#3d3a33;font-size:15px;line-height:1.65;">'
                f'{text}</p>')
    body_html = ''.join(parts)
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#efece5;">
  <div style="max-width:620px;margin:0 auto;padding:28px 16px;
              font-family:Georgia,'Times New Roman',serif;">
    <div style="background:#fffdf9;border:1px solid #e4dfd4;border-radius:8px;overflow:hidden;">
      <div style="padding:22px 32px;border-bottom:3px solid #c75b12;">
        <span style="font-size:19px;color:#2b2823;letter-spacing:0.02em;">Drop&nbsp;Watcher</span>
        <span style="font-size:13px;color:#8a8374;"> &nbsp;·&nbsp; instockornot.club</span>
      </div>
      <div style="padding:28px 32px 12px;">{body_html}</div>
      <div style="padding:16px 32px;border-top:1px solid #eee9df;background:#faf8f3;
                  font-size:12px;color:#8a8374;line-height:1.5;">
        Sent personally by Simon Gibson · instockornot.club ·
        <a href="mailto:simon@instockornot.club" style="color:#c75b12;">simon@instockornot.club</a><br>
        A free restock-alert service for knife collectors. We read, we never buy.
      </div>
    </div>
  </div>
</body></html>"""


def send_one(e, to_override=None, tag_test=False):
    payload = {
        'from': FROM_ADDRESS,
        'to': [to_override or e['to']],
        'subject': (f"[TEST — would go to {e['to']}] " if tag_test else '') + e['subject'],
        'text': e['body'],
        'html': build_html(e),
        'reply_to': 'simon@instockornot.club',
    }
    if e['cc'] and not to_override:
        payload['cc'] = [e['cc']]
    r = httpx.post(RESEND_API_URL, json=payload, timeout=20,
                   headers={'Authorization': f"Bearer {os.environ['RESEND_API_KEY']}",
                            'Content-Type': 'application/json'})
    ok = r.status_code in (200, 201)
    print(f"  #{e['num']} {e['name']:24s} -> {payload['to'][0]:38s} "
          f"{'OK ' + r.json().get('id', '') if ok else 'FAIL ' + r.text[:120]}")
    return ok


def main():
    emails = parse_emails()
    if len(emails) != 8:
        print(f"WARNING: parsed {len(emails)} wave-2 emails, expected 8");
    if '--test' in sys.argv:
        i = sys.argv.index('--test')
        addr = sys.argv[i + 1]
        num = int(sys.argv[i + 2]) if len(sys.argv) > i + 2 else 7
        e = next(x for x in emails if x['num'] == num)
        print(f"TEST send of #{num} ({e['name']}) to {addr}:")
        send_one(e, to_override=addr, tag_test=True)
    elif '--send' in sys.argv:
        print(f"SENDING {len(emails)} outreach emails for real:")
        sent = 0
        for e in emails:
            sent += send_one(e)
            time.sleep(1.5)   # gentle on Resend rate limits
        print(f"{sent}/{len(emails)} sent.")
    else:
        print("DRY RUN (use --test ADDR [N] or --send):")
        for e in emails:
            cc = f"  cc: {e['cc']}" if e['cc'] else ''
            print(f"  #{e['num']} {e['name']:24s} -> {e['to']}{cc}")
            print(f"      Subject: {e['subject']}  ({len(e['body'])} chars)")


if __name__ == '__main__':
    main()
