#!/usr/bin/env python3
"""Check Twilio SMS delivery status by message SID."""
import os, sys
from dotenv import load_dotenv
load_dotenv('/etc/drop-watcher/.env')
from twilio.rest import Client

if len(sys.argv) < 2:
    print("Usage: python3 bin/sms_status.py SM_SID_HERE")
    sys.exit(1)

c = Client(os.environ['TWILIO_ACCOUNT_SID'], os.environ['TWILIO_AUTH_TOKEN'])
m = c.messages(sys.argv[1]).fetch()
print(f"Status: {m.status}")
print(f"Error:  {m.error_code} — {m.error_message}")
print(f"To:     {m.to}")
print(f"From:   {m.from_}")
print(f"Sent:   {m.date_sent}")
