#!/usr/bin/env python3
"""
test_flap_guard.py — flap guard: pause a watch that sends >N emails in a rolling
window with zero human outbound clicks (Simon 2026-07-17). Reactivation restarts
the counter at zero via watchers.flap_reset_at.
Run: python3 -m pytest tests/test_flap_guard.py -v
"""

import os
import sys
import importlib
import uuid
from datetime import datetime, timezone, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

NOW = datetime.now(timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('DW_CODE_DIR', str(tmp_path))
    monkeypatch.setenv('DW_CONFIG_DIR', str(tmp_path / 'config'))
    monkeypatch.setenv('DW_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('DW_LOG_DIR', str(tmp_path / 'logs'))
    monkeypatch.setenv('DW_WWW_DIR', str(tmp_path / 'www'))
    monkeypatch.setenv('DW_ENV_FILE', str(tmp_path / '.env'))
    monkeypatch.setenv('DW_DB', str(tmp_path / 'data' / 'test.db'))
    monkeypatch.delenv('DW_FLAP_GUARD', raising=False)
    for d in ['config', 'data', 'logs', 'www']:
        (tmp_path / d).mkdir()
    import paths; importlib.reload(paths)
    import db; importlib.reload(db)
    import flap_guard; importlib.reload(flap_guard)
    return db, flap_guard


def _mk_watcher(db, **overrides):
    w = {
        'id': uuid.uuid4().hex[:8],
        'email': 'user@example.com',
        'url': 'https://jtknives.com/crk.html',
        'keywords': 'umnumzaan',
        'unsubscribe_token': 'tok_' + uuid.uuid4().hex,
        'created': NOW.isoformat(),
        'active': 1,
    }
    w.update(overrides)
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO watchers (id, email, url, keywords, unsubscribe_token, created, active)"
            " VALUES (:id, :email, :url, :keywords, :unsubscribe_token, :created, :active)", w)
    return db.get_watcher_by_id(w['id'])


def _send_emails(db, watcher_id, n, ts=None):
    for _ in range(n):
        db.record_sent_alert('user@example.com', 'email',
                             ts=(ts or NOW.isoformat()), watcher_id=watcher_id)


def _click(db, watcher_id, scanner=0, ts=None):
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO outbound_clicks (watcher_id, dest_url, dest_domain, clicked_at, scanner)"
            " VALUES (?,?,?,?,?)",
            (watcher_id, 'https://jtknives.com/x', 'jtknives.com',
             (ts or NOW.isoformat()), scanner))


# ── should_pause decision ────────────────────────────────────────────────────

def test_no_pause_at_threshold(env):
    db, fg = env
    w = _mk_watcher(db)
    _send_emails(db, w['id'], 5)
    assert fg.should_pause(w, NOW) is False


def test_pause_past_threshold_no_clicks(env):
    db, fg = env
    w = _mk_watcher(db)
    _send_emails(db, w['id'], 6)
    assert fg.should_pause(w, NOW) is True


def test_human_click_in_window_prevents_pause(env):
    db, fg = env
    w = _mk_watcher(db)
    _send_emails(db, w['id'], 6)
    _click(db, w['id'], scanner=0)
    assert fg.should_pause(w, NOW) is False


def test_scanner_click_does_not_count(env):
    db, fg = env
    w = _mk_watcher(db)
    _send_emails(db, w['id'], 6)
    _click(db, w['id'], scanner=1)
    assert fg.should_pause(w, NOW) is True


def test_old_emails_fall_out_of_window(env):
    db, fg = env
    w = _mk_watcher(db)
    old = (NOW - timedelta(days=5)).isoformat()
    _send_emails(db, w['id'], 6, ts=old)
    assert fg.should_pause(w, NOW) is False


def test_other_watchers_emails_do_not_count(env):
    db, fg = env
    w = _mk_watcher(db)
    other = _mk_watcher(db, email='other@example.com')
    _send_emails(db, other['id'], 6)
    _send_emails(db, w['id'], 1)
    assert fg.should_pause(w, NOW) is False


def test_reactivation_restarts_counter(env):
    db, fg = env
    w = _mk_watcher(db)
    _send_emails(db, w['id'], 6, ts=(NOW - timedelta(days=1)).isoformat())
    db.update_watcher(w['id'], flap_reset_at=NOW.isoformat())
    w = db.get_watcher_by_id(w['id'])
    assert fg.should_pause(w, NOW + timedelta(minutes=1)) is False


def test_fails_open_on_db_error(env, monkeypatch):
    db, fg = env
    w = _mk_watcher(db)
    _send_emails(db, w['id'], 6)
    monkeypatch.setattr(fg.db, 'count_watch_emails',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('locked')))
    assert fg.should_pause(w, NOW) is False


def test_disabled_via_env(env, monkeypatch):
    db, fg = env
    monkeypatch.setenv('DW_FLAP_GUARD', '0')
    w = _mk_watcher(db)
    _send_emails(db, w['id'], 6)
    assert fg.should_pause(w, NOW) is False


# ── pause action in per_user_alerter ─────────────────────────────────────────

def test_pause_action_deactivates_and_emails(env, monkeypatch):
    db, fg = env
    import per_user_alerter; importlib.reload(per_user_alerter)
    w = _mk_watcher(db)
    sent = []
    monkeypatch.setattr(per_user_alerter, 'send_email',
                        lambda subject, html, txt, to_addr: sent.append((subject, to_addr)) or True)
    per_user_alerter.pause_watch_for_flapping(w, NOW)
    w2 = db.get_watcher_by_id(w['id'])
    assert not w2['active']
    assert w2['flap_paused_at']
    assert len(sent) == 1 and sent[0][1] == 'user@example.com'
    # the pause email itself must not feed the flap counter
    assert db.count_watch_emails(w['id'], (NOW - timedelta(days=1)).isoformat()) == 0


# ── reactivate route (watcher_signup) ────────────────────────────────────────

@pytest.fixture
def client(env):
    db, fg = env
    if 'watcher_signup' in sys.modules:
        del sys.modules['watcher_signup']
    import watcher_signup
    importlib.reload(watcher_signup)
    watcher_signup.app.config['TESTING'] = True
    with watcher_signup.app.test_client() as c:
        yield db, c


def test_reactivate_get_shows_confirm_only(client):
    db, c = client
    w = _mk_watcher(db, active=0)
    db.update_watcher(w['id'], flap_paused_at=NOW.isoformat())
    r = c.get(f"/api/reactivate/{w['id']}/{w['unsubscribe_token']}")
    assert r.status_code == 200
    assert not db.get_watcher_by_id(w['id'])['active']   # GET must not reactivate


def test_reactivate_post_restores_watch(client):
    db, c = client
    w = _mk_watcher(db, active=0)
    db.update_watcher(w['id'], flap_paused_at=NOW.isoformat(), strikes=7)
    r = c.post(f"/api/reactivate/{w['id']}/{w['unsubscribe_token']}")
    assert r.status_code == 200
    w2 = db.get_watcher_by_id(w['id'])
    assert w2['active']
    assert w2['strikes'] == 0
    assert w2['flap_reset_at']          # counter restarted at zero
    assert not w2['flap_paused_at']


def test_reactivate_bad_token_404(client):
    db, c = client
    w = _mk_watcher(db, active=0)
    r = c.post(f"/api/reactivate/{w['id']}/wrong-token")
    assert r.status_code == 404
    assert not db.get_watcher_by_id(w['id'])['active']
