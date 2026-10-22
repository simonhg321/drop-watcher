#!/usr/bin/env python3
"""
test_host_cooldown.py — Corp directive 207 compliance (task #31):
  1. distinct per-machine User-Agent, shared DropWatcher/1.0 gone from every fetcher
  2. per-host 24h cooldown on 429 + blocked.log + one email alert per block,
     wired into BOTH fetch paths (safe_fetch.fetch_text and web_watcher.fetch_page)
  (lunar_hunter retired 2026-10-22 per Simon — hgr-watch owns grail polling)
Run: python3 -m pytest tests/test_host_cooldown.py -v
"""
import glob
import importlib
import os
import socket
import sys
from datetime import datetime, timezone, timedelta

import pytest
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'agents'))

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k, sub in [('DW_CONFIG_DIR', 'config'), ('DW_DATA_DIR', 'data'),
                   ('DW_LOG_DIR', 'logs'), ('DW_WWW_DIR', 'www')]:
        monkeypatch.setenv(k, str(tmp_path / sub))
        (tmp_path / sub).mkdir()
    monkeypatch.setenv('DW_CODE_DIR', str(tmp_path))
    monkeypatch.setenv('DW_ENV_FILE', str(tmp_path / '.env'))
    monkeypatch.setenv('DW_DB', str(tmp_path / 'data' / 'test.db'))
    import paths; importlib.reload(paths)
    import db; importlib.reload(db)
    import host_cooldown; importlib.reload(host_cooldown)
    sent = []
    monkeypatch.setattr(host_cooldown, '_alert', lambda subj, body: sent.append(subj) or True)
    host_cooldown._sent = sent
    yield host_cooldown
    # Put the reloaded modules back on the real env so later test files don't
    # read config through a paths module still pointing at this tmp dir.
    monkeypatch.undo()
    importlib.reload(paths); importlib.reload(db); importlib.reload(host_cooldown)


class FakeResp:
    def __init__(self, status=200, body=b'<html>ok</html>', headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.content = body
        self.is_redirect = False
    def close(self): pass
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f'{self.status_code}')


# ── 1. User-Agent ────────────────────────────────────────────────────────────

def test_user_agent_is_distinct_per_machine(env):
    ua = env.USER_AGENT
    assert 'DropWatcher/1.0' not in ua
    assert socket.gethostname() in ua
    assert 'instockornot.club' in ua


def test_no_fetcher_still_uses_shared_ua():
    offenders = []
    for f in glob.glob(os.path.join(ROOT, '*.py')) + glob.glob(os.path.join(ROOT, 'agents', '*.py')):
        with open(f, errors='replace') as fh:
            if 'DropWatcher/1.0' in fh.read():
                offenders.append(os.path.relpath(f, ROOT))
    assert offenders == []


# ── 2. cooldown core ─────────────────────────────────────────────────────────

def test_host_of_normalizes_www_and_case(env):
    assert env.host_of('https://WWW.KnifeJoy.com/collections/x') == 'knifejoy.com'
    assert env.host_of('https://southernedges.com/products/y.js') == 'southernedges.com'


def test_fresh_host_is_not_blocked(env):
    assert env.is_blocked('https://knifejoy.com/a', now=NOW) is False


def test_record_429_blocks_host_for_24h(env):
    env.record_429('https://www.knifejoy.com/a.js', now=NOW)
    assert env.is_blocked('https://knifejoy.com/other', now=NOW + timedelta(hours=23)) is True
    assert env.is_blocked('https://knifejoy.com/other', now=NOW + timedelta(hours=24, seconds=1)) is False


def test_block_is_per_host_not_global(env):
    env.record_429('https://knifejoy.com/a', now=NOW)
    assert env.is_blocked('https://southernedges.com/a', now=NOW) is False


def test_block_survives_process_restart(env):
    env.record_429('https://knifejoy.com/a', now=NOW)
    importlib.reload(env)   # fresh module, same DB
    assert env.is_blocked('https://knifejoy.com/a', now=NOW) is True


def test_record_429_appends_blocked_log(env):
    env.record_429('https://knifejoy.com/a.js', now=NOW)
    line = open(env.BLOCKED_LOG).read().strip()
    assert 'knifejoy.com' in line and '429' in line and 'url=https://knifejoy.com/a.js' in line
    assert str(env.BLOCKED_LOG).startswith(os.environ['DW_DATA_DIR'])


def test_alert_sent_once_per_block_not_per_429(env):
    env.record_429('https://knifejoy.com/a', now=NOW)
    env.record_429('https://knifejoy.com/b', now=NOW + timedelta(minutes=5))
    env.record_429('https://knifejoy.com/c', now=NOW + timedelta(hours=1))
    assert len(env._sent) == 1
    assert 'knifejoy.com' in env._sent[0]
    # new block after expiry alerts again
    env.record_429('https://knifejoy.com/d', now=NOW + timedelta(hours=25))
    assert len(env._sent) == 2


def test_alert_failure_does_not_break_block(env, monkeypatch):
    def boom(subj, body): raise RuntimeError('smtp down')
    monkeypatch.setattr(env, '_alert', boom)
    env.record_429('https://knifejoy.com/a', now=NOW)
    assert env.is_blocked('https://knifejoy.com/a', now=NOW) is True


# ── 2b. wired into safe_fetch.fetch_text (lunar_hunter / dealer_scout path) ──

def test_fetch_text_429_returns_none_and_blocks(env, monkeypatch):
    import safe_fetch
    monkeypatch.setattr(safe_fetch, 'is_safe_url', lambda u: (True, ''))
    monkeypatch.setattr(requests, 'get', lambda *a, **k: FakeResp(429))
    assert safe_fetch.fetch_text('https://knifejoy.com/a') is None
    assert env.is_blocked('https://knifejoy.com/zzz') is True


def test_fetch_text_skips_blocked_host_without_network(env, monkeypatch):
    import safe_fetch
    monkeypatch.setattr(safe_fetch, 'is_safe_url', lambda u: (True, ''))
    env.record_429('https://knifejoy.com/a')
    calls = []
    monkeypatch.setattr(requests, 'get', lambda *a, **k: calls.append(a) or FakeResp(200))
    assert safe_fetch.fetch_text('https://knifejoy.com/b') is None
    assert calls == []


def test_fetch_text_sends_distinct_ua_by_default(env, monkeypatch):
    import safe_fetch
    monkeypatch.setattr(safe_fetch, 'is_safe_url', lambda u: (True, ''))
    seen = {}
    def fake_get(url, headers=None, **k):
        seen.update(headers or {}); return FakeResp(200)
    monkeypatch.setattr(requests, 'get', fake_get)
    assert safe_fetch.fetch_text('https://knifejoy.com/a') == '<html>ok</html>'
    assert seen.get('User-Agent') == env.USER_AGENT


# ── 2c. wired into web_watcher.fetch_page ────────────────────────────────────

@pytest.fixture
def ww(env, monkeypatch):
    import web_watcher
    importlib.reload(web_watcher)
    monkeypatch.setattr(web_watcher, 'is_safe_url', lambda u: (True, ''))
    return web_watcher


def _fake_session(status, calls):
    class S:
        def mount(self, *a, **k): pass
        def get(self, url, **k):
            calls.append((url, k.get('headers', {})))
            return FakeResp(status)
    return S


def test_web_watcher_fetch_page_429_blocks_host(ww, env, monkeypatch):
    calls = []
    monkeypatch.setattr(ww.requests, 'Session', _fake_session(429, calls))
    assert ww.fetch_page('https://southernedges.com/collections/x') is None
    assert env.is_blocked('https://southernedges.com/products/y') is True
    assert calls[0][1]['User-Agent'] == env.USER_AGENT


def test_web_watcher_fetch_page_skips_blocked_host(ww, env, monkeypatch):
    env.record_429('https://southernedges.com/a')
    calls = []
    monkeypatch.setattr(ww.requests, 'Session', _fake_session(200, calls))
    assert ww.fetch_page('https://southernedges.com/collections/x') is None
    assert calls == []
