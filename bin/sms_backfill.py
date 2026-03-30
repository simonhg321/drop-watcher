#!/usr/bin/env python3
"""One-time backfill — pull Twilio SMS history into sms_sent.jsonl."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from dotenv import load_dotenv
load_dotenv('/etc/drop-watcher/.env')
from twilio.rest import Client
import paths

client = Client(os.environ['TWILIO_ACCOUNT_SID'], os.environ['TWILIO_AUTH_TOKEN'])
messages = client.messages.list()

count = 0
with open(paths.SMS_SENT_JSONL, 'a') as f:
    for m in messages:
        if m.direction != 'outbound-api':
            continue
        entry = {
            'alert_id': m.sid,
            'phone': m.to,
            'sent_at': m.date_sent.isoformat() if m.date_sent else '',
            'status': m.status,
        }
        f.write(json.dumps(entry) + '\n')
        count += 1

print(f"Backfilled {count} messages to {paths.SMS_SENT_JSONL}")
