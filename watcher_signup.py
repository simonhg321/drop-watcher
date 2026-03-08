# Copyright (c) 2026 Simon HGR — instockornot.club — ELv2 License
"""
watcher_signup.py — Flask API for public watch signups
Receives POST /api/watch, writes to watchers.json

Run: gunicorn -w 2 -b 127.0.0.1:5001 watcher_signup:app
Apache proxies /api/watch → localhost:5001
"""

import json
import os
import uuid
import logging
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
WATCHERS_FILE = os.path.join(BASE_DIR, 'config', 'watchers.json')

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def load_watchers():
    if not os.path.exists(WATCHERS_FILE):
        return []
    with open(WATCHERS_FILE) as f:
        return json.load(f)


def save_watchers(watchers):
    os.makedirs(os.path.dirname(WATCHERS_FILE), exist_ok=True)
    with open(WATCHERS_FILE, 'w') as f:
        json.dump(watchers, f, indent=2)


@app.route('/api/watch', methods=['POST'])
def watch():
    data = request.get_json(force=True)

    # Validate required fields
    required = ['url', 'keywords', 'email']
    for field in required:
        if not data.get(field, '').strip():
            return jsonify({'error': f'Missing required field: {field}'}), 400

    # Build watcher entry
    entry = {
        'id':        str(uuid.uuid4())[:8],
        'url':       data['url'].strip(),
        'keywords':  data['keywords'].strip(),
        'email':     data['email'].strip().lower(),
        'name':      data.get('name', '').strip(),
        'priority':  data.get('priority', 'high'),
        'active':    True,
        'created':   datetime.now(timezone.utc).isoformat(),
        'last_alert': None,
        'alert_count': 0
    }

    watchers = load_watchers()

    # Deduplicate: same email + url combo
    existing = [w for w in watchers if w['email'] == entry['email'] and w['url'] == entry['url']]
    if existing:
        log.info(f"Duplicate watcher for {entry['email']} / {entry['url']} — updating keywords")
        existing[0]['keywords'] = entry['keywords']
        existing[0]['priority'] = entry['priority']
        save_watchers(watchers)
        return jsonify({'status': 'updated', 'id': existing[0]['id']}), 200

    watchers.append(entry)
    save_watchers(watchers)

    log.info(f"New watcher: {entry['id']} | {entry['email']} | {entry['url']}")
    return jsonify({'status': 'created', 'id': entry['id']}), 201


@app.route('/api/unsubscribe/<watcher_id>', methods=['GET', 'POST'])
def unsubscribe(watcher_id):
    watchers = load_watchers()
    for w in watchers:
        if w['id'] == watcher_id:
            w['active'] = False
            save_watchers(watchers)
            return jsonify({'status': 'unsubscribed'}), 200
    return jsonify({'error': 'Not found'}), 404


@app.route('/api/watchers', methods=['GET'])
def list_watchers():
    """Admin endpoint — restrict to localhost or internal IP in Apache"""
    watchers = load_watchers()
    active = [w for w in watchers if w.get('active')]
    return jsonify({'count': len(active), 'watchers': active}), 200


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=False)
