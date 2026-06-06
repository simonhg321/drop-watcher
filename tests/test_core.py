#!/usr/bin/env python3
"""
test_core.py — Drop Watcher core tests
Run: python3 -m pytest tests/ -v
No network calls, no prod data, no side effects.
HGR
"""

import json
import os
import sys
import tempfile
import shutil
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

# ── Setup paths so imports work ──────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'agents'))


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_env(tmp_path):
    """Set up a temp environment with all paths pointing to tmp_path."""
    os.environ['DW_CODE_DIR'] = str(tmp_path)
    os.environ['DW_CONFIG_DIR'] = str(tmp_path / 'config')
    os.environ['DW_DATA_DIR'] = str(tmp_path / 'data')
    os.environ['DW_LOG_DIR'] = str(tmp_path / 'logs')
    os.environ['DW_WWW_DIR'] = str(tmp_path / 'www')
    os.environ['DW_ENV_FILE'] = str(tmp_path / '.env')
    os.environ['DW_DB'] = str(tmp_path / 'data' / 'test.db')

    for d in ['config', 'data', 'logs', 'www']:
        (tmp_path / d).mkdir()

    # Write empty .env
    (tmp_path / '.env').write_text('')

    # Reload paths and db modules with new env vars
    import importlib
    import paths
    importlib.reload(paths)
    import db
    db.DB_PATH = os.environ['DW_DB']

    yield tmp_path

    # Cleanup env vars
    for k in ['DW_CODE_DIR', 'DW_CONFIG_DIR', 'DW_DATA_DIR', 'DW_LOG_DIR', 'DW_WWW_DIR', 'DW_ENV_FILE', 'DW_DB']:
        os.environ.pop(k, None)
    importlib.reload(paths)


@pytest.fixture
def sample_watchers():
    """A set of test watchers."""
    token = str(uuid.uuid4())
    return [
        {
            'id': 'w001',
            'email': 'test@example.com',
            'url': 'https://www.knifejoy.com/collections/hinderer',
            'keywords': 'damascus, steel flame',
            'priority': 'high',
            'name': 'Test User',
            'phone': '',
            'sms_approved': False,
            'active': True,
            'verify_token': None,
            'unsubscribe_token': token,
            'created': datetime.now(timezone.utc).isoformat(),
            'last_alert': None,
            'alert_count': 0,
        },
        {
            'id': 'w002',
            'email': 'test@example.com',
            'url': 'https://www.steelflame.com',
            'keywords': 'killbox, crusader',
            'priority': 'high',
            'name': 'Test User',
            'phone': '',
            'sms_approved': False,
            'active': True,
            'verify_token': None,
            'unsubscribe_token': token,
            'created': datetime.now(timezone.utc).isoformat(),
            'last_alert': None,
            'alert_count': 0,
        },
        {
            'id': 'w003',
            'email': 'other@example.com',
            'url': 'https://www.knifejoy.com/collections/hinderer',
            'keywords': 'xm-18',
            'priority': 'medium',
            'name': 'Other User',
            'phone': '',
            'sms_approved': False,
            'active': False,  # not verified
            'verify_token': str(uuid.uuid4()),
            'unsubscribe_token': str(uuid.uuid4()),
            'created': datetime.now(timezone.utc).isoformat(),
            'last_alert': None,
            'alert_count': 0,
        },
    ]


@pytest.fixture
def sample_drops():
    """Recent drops for testing alert matching."""
    now = datetime.now(timezone.utc)
    return [
        {
            'timestamp': now.isoformat(),
            'url': 'https://www.knifejoy.com/collections/hinderer',
            'source': 'KnifeJoy',
            'page_summary': 'New Hinderer XM-18 Damascus Steel Flame collab just dropped',
            'notable_items': ['Hinderer XM-18 Damascus', 'Steel Flame clip'],
            'priority': 'critical',
            'alert_worthy': True,
        },
        {
            'timestamp': now.isoformat(),
            'url': 'https://www.steelflame.com',
            'source': 'Steel Flame',
            'page_summary': 'New killbox pendants in stock',
            'notable_items': ['Killbox pendant brass'],
            'priority': 'high',
            'alert_worthy': True,
        },
        {
            'timestamp': now.isoformat(),
            'url': 'https://www.dlttrading.com/newest-arrivals',
            'source': 'DLT Trading',
            'page_summary': 'Standard Spyderco Para 3 restock',
            'notable_items': ['Spyderco Para 3'],
            'priority': 'medium',
            'alert_worthy': True,
        },
        {
            'timestamp': (now - timedelta(hours=2)).isoformat(),
            'url': 'https://www.knifejoy.com/collections/hinderer',
            'source': 'KnifeJoy',
            'page_summary': 'Hinderer XM-24 standard titanium in stock',
            'notable_items': ['XM-24 titanium'],
            'priority': 'medium',
            'alert_worthy': True,
        },
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SIGNUP PIPELINE (watcher_signup.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSignupAPI:
    """Test the Flask signup routes."""

    @pytest.fixture
    def client(self, tmp_env):
        """Flask test client with mocked email sending."""
        import importlib
        import paths
        importlib.reload(paths)
        import db
        db.DB_PATH = os.environ['DW_DB']

        # Must reload watcher_signup after paths
        if 'watcher_signup' in sys.modules:
            del sys.modules['watcher_signup']

        with patch.dict(os.environ, {'RESEND_API_KEY': 'test-key'}):
            import watcher_signup
            importlib.reload(watcher_signup)
            watcher_signup.app.config['TESTING'] = True
            # tmp_env has an empty sources.yaml, so every domain looks "new" and would
            # hit the knife-gate (real network + AI). Stub both so signup tests stay
            # offline and deterministic: curated domains classify as knife dealers.
            watcher_signup._fetch_page_text = lambda u: 'knives in stock'
            watcher_signup.classify_dealer = lambda u, t: {
                'is_dealer': True, 'category': 'knife/EDC retailer',
                'brands': ['Chris Reeve'], 'confidence': 0.9, 'reason': 'test'}
            with watcher_signup.app.test_client() as c:
                yield c

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.quick_keyword_check', return_value=[])
    def test_signup_creates_watcher(self, mock_check, mock_email, client, tmp_env):
        """POST /api/watch creates a new watcher."""
        resp = client.post('/api/watch', json={
            'url': 'https://www.knifejoy.com',
            'keywords': 'hinderer, damascus',
            'email': 'new@example.com',
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['status'] == 'created'
        assert 'id' in data

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.quick_keyword_check', return_value=[])
    def test_signup_missing_email(self, mock_check, mock_email, client):
        """POST /api/watch without email returns 400."""
        resp = client.post('/api/watch', json={
            'url': 'https://www.knifejoy.com',
            'keywords': 'hinderer',
        })
        assert resp.status_code == 400

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.quick_keyword_check', return_value=[])
    def test_signup_missing_url(self, mock_check, mock_email, client):
        """POST /api/watch without URL is now a GLOBAL watch — still 400 if no maker
        is supplied (url optional, but global watches require a maker). (S54)"""
        resp = client.post('/api/watch', json={
            'keywords': 'hinderer',
            'email': 'test@example.com',
        })
        assert resp.status_code == 400
        assert 'maker' in resp.get_json()['error'].lower()

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.quick_keyword_check', return_value=[])
    def test_signup_invalid_email(self, mock_check, mock_email, client):
        """POST /api/watch with bad email returns 400."""
        resp = client.post('/api/watch', json={
            'url': 'https://www.knifejoy.com',
            'keywords': 'hinderer',
            'email': 'not-an-email',
        })
        assert resp.status_code == 400

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.quick_keyword_check', return_value=[])
    def test_duplicate_signup_updates(self, mock_check, mock_email, client, tmp_env):
        """Second signup with same email+url updates keywords, returns 200."""
        payload = {
            'url': 'https://www.knifejoy.com',
            'keywords': 'hinderer',
            'email': 'dup@example.com',
        }
        resp1 = client.post('/api/watch', json=payload)
        assert resp1.status_code == 201

        payload['keywords'] = 'hinderer, damascus'
        resp2 = client.post('/api/watch', json=payload)
        assert resp2.status_code == 200
        assert resp2.get_json()['status'] == 'updated'

    @patch('watcher_signup.send_confirmation_email', return_value=True)
    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.quick_keyword_check', return_value=[])
    def test_second_url_reuses_token(self, mock_check, mock_verify, mock_confirm, client, tmp_env):
        """Second URL for same email reuses the unsubscribe token."""
        resp1 = client.post('/api/watch', json={
            'url': 'https://www.knifejoy.com',
            'keywords': 'hinderer',
            'email': 'multi@example.com',
        })
        assert resp1.status_code == 201
        id1 = resp1.get_json()['id']

        # Verify first watch
        import db
        w = db.get_watcher_by_id(id1)
        token = w['verify_token']
        assert token is not None

        # Verify
        with patch('watcher_signup.quick_keyword_check', return_value=[]):
            client.get(f'/api/verify/{token}')

        # Second signup — same email, different URL
        resp2 = client.post('/api/watch', json={
            'url': 'https://www.steelflame.com',
            'keywords': 'killbox',
            'email': 'multi@example.com',
        })
        assert resp2.status_code == 201

        # Check both watches share the same unsubscribe token
        watchers = db.get_watchers_by_email('multi@example.com')
        tokens = set(w['unsubscribe_token'] for w in watchers)
        assert len(tokens) == 1, "All watches for same email should share one token"

    @patch('watcher_signup.send_confirmation_email', return_value=True)
    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.quick_keyword_check', return_value=[])
    def test_verify_activates_all_watches(self, mock_check, mock_verify, mock_confirm, client, tmp_env):
        """Verifying one watch activates ALL watches for that email."""
        # Create two watches
        client.post('/api/watch', json={
            'url': 'https://www.knifejoy.com', 'keywords': 'hinderer', 'email': 'verify@example.com',
        })
        client.post('/api/watch', json={
            'url': 'https://www.steelflame.com', 'keywords': 'killbox', 'email': 'verify@example.com',
        })

        # Get verify token from first watch
        import db
        watchers = db.get_watchers_by_email('verify@example.com')
        token = None
        for w in watchers:
            if w.get('verify_token'):
                token = w['verify_token']
                break

        # Verify
        with patch('watcher_signup.quick_keyword_check', return_value=[]):
            resp = client.get(f'/api/verify/{token}')
        assert resp.status_code == 200

        # Both should now be active
        watchers = db.get_watchers_by_email('verify@example.com')
        active = [w for w in watchers if w['active']]
        assert len(active) == 2

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.quick_keyword_check', return_value=[])
    def test_unsubscribe_deactivates_all(self, mock_check, mock_email, client, tmp_env):
        """Unsubscribe deactivates ALL watches for that email."""
        # Create and manually activate
        client.post('/api/watch', json={
            'url': 'https://www.knifejoy.com', 'keywords': 'hinderer', 'email': 'unsub@example.com',
        })

        import db
        watchers = db.get_watchers_by_email('unsub@example.com')
        for w in watchers:
            db.update_watcher(w['id'], active=True)

        unsub_token = watchers[0]['unsubscribe_token']
        resp = client.get(f'/api/unsubscribe/{unsub_token}')
        assert resp.status_code == 200

        watchers = db.get_watchers_by_email('unsub@example.com')
        active = [w for w in watchers if w['active']]
        assert len(active) == 0

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.quick_keyword_check', return_value=[])
    def test_stop_one_watch(self, mock_check, mock_email, client, tmp_env):
        """DELETE /api/my-watch/<id> removes only that watch."""
        resp = client.post('/api/watch', json={
            'url': 'https://www.knifejoy.com', 'keywords': 'hinderer', 'email': 'stop@example.com',
        })
        wid = resp.get_json()['id']

        # Need token for auth
        import db
        w = db.get_watcher_by_id(wid)
        token = w['unsubscribe_token']
        resp = client.delete(f'/api/my-watch/{wid}?token={token}')
        assert resp.status_code == 200

        assert db.get_watcher_by_id(wid) is None

    def test_resend_link_no_leak(self, client):
        """Resend-link returns 200 even for unknown emails (no email enumeration)."""
        resp = client.post('/api/resend-link', json={'email': 'nobody@example.com'})
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'sent'

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.quick_keyword_check', return_value=[])
    def test_my_alerts_preserves_url_case(self, mock_check, mock_email, client, tmp_env):
        """my-alerts must return the original-cased watch URL — Shopify handles are
        case-sensitive, so a lowercased /collections/Chris-Reeve 404s (S51 bug b)."""
        mixed = 'https://www.knifejoy.com/collections/Chris-Reeve'
        resp = client.post('/api/watch', json={
            'url': mixed, 'keywords': 'sebenza', 'email': 'case@example.com',
        })
        wid = resp.get_json()['id']
        import db
        db.update_watcher(wid, active=True)
        token = db.get_watcher_by_id(wid)['unsubscribe_token']
        resp = client.get(f'/api/my-alerts/{token}')
        assert resp.status_code == 200
        urls = [w['url'] for w in resp.get_json()['watches']]
        assert mixed in urls, f"expected original case preserved, got {urls}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ALERT MATCHING (per_user_alerter.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAlertMatching:
    """Test the per_user_alerter matching logic."""

    def test_domain_match(self):
        """domain_from_url extracts domain correctly."""
        from per_user_alerter import domain_from_url
        assert domain_from_url('https://www.knifejoy.com/collections/hinderer') == 'knifejoy.com'
        assert domain_from_url('https://knifejoy.com') == 'knifejoy.com'
        assert domain_from_url('http://www.steelflame.com/shop') == 'steelflame.com'

    def test_keywords_match_basic(self):
        """keywords_match finds matching keywords in text."""
        from per_user_alerter import keywords_match
        text = 'new hinderer xm-18 damascus steel flame collab just dropped'
        assert 'damascus' in keywords_match(text, 'damascus, steel flame')
        assert 'steel flame' in keywords_match(text, 'damascus, steel flame')

    def test_keywords_match_comma_split(self):
        """Multi-word keywords separated by commas stay intact."""
        from per_user_alerter import keywords_match
        text = 'chris reeve sebenza in stock now'
        matches = keywords_match(text, 'in stock, chris reeve')
        assert 'in stock' in matches
        assert 'chris reeve' in matches

    def test_keywords_no_match(self):
        """keywords_match returns empty when nothing matches."""
        from per_user_alerter import keywords_match
        text = 'standard spyderco para 3 restock'
        assert keywords_match(text, 'damascus, steel flame') == []

    def test_keywords_case_insensitive(self):
        """Matching is case insensitive."""
        from per_user_alerter import keywords_match
        text = 'hinderer xm-18 damascus steel flame'
        assert 'damascus' in keywords_match(text, 'Damascus')

    def test_domain_must_match(self):
        """Drops from unrelated domains should not match."""
        from per_user_alerter import domain_from_url, keywords_match
        watcher_domain = domain_from_url('https://www.knifejoy.com/hinderer')
        drop_domain = domain_from_url('https://www.dlttrading.com/new-arrivals')
        assert watcher_domain != drop_domain

    def test_cooldown_key_unique(self):
        """Different keyword sets produce different cooldown keys."""
        from per_user_alerter import cooldown_key
        k1 = cooldown_key('w001', 'https://example.com', ['damascus'])
        k2 = cooldown_key('w001', 'https://example.com', ['steel flame'])
        k3 = cooldown_key('w001', 'https://example.com', ['damascus'])
        assert k1 != k2
        assert k1 == k3  # same inputs = same key

    def test_cooldown_key_different_watchers(self):
        """Same URL+keywords for different watchers produce different keys."""
        from per_user_alerter import cooldown_key
        k1 = cooldown_key('w001', 'https://example.com', ['damascus'])
        k2 = cooldown_key('w002', 'https://example.com', ['damascus'])
        assert k1 != k2

    def test_cooldown_expires(self, tmp_env):
        """Cooldown entries expire after the configured hours."""
        import db
        # Mark a cooldown now
        db.mark_cooldown('test-ck', recipient='test@example.com')
        assert db.is_cooldown_active('test-ck', hours=6)
        # Check with 0 hours — should not be active (already expired)
        assert not db.is_cooldown_active('test-ck', hours=0)

    def test_inactive_watcher_skipped(self, sample_watchers, sample_drops):
        """Inactive (unverified) watchers don't get alerts."""
        from per_user_alerter import domain_from_url, keywords_match
        inactive = [w for w in sample_watchers if not w['active']]
        assert len(inactive) == 1
        w = inactive[0]
        # Even though keywords match, watcher is inactive
        drop = sample_drops[3]  # XM-24 from knifejoy
        w_domain = domain_from_url(w['url'])
        d_domain = domain_from_url(drop['url'])
        assert w_domain == d_domain
        # The run() function filters on w.get('active') — inactive skipped


# ═══════════════════════════════════════════════════════════════════════════════
# 3. AI INTERPRETER OUTPUT PARSING
# ═══════════════════════════════════════════════════════════════════════════════

class TestAIInterpreter:
    """Test ai_interpreter.py parsing and error handling."""

    def test_parse_clean_json(self):
        """Clean JSON from Claude is parsed correctly."""
        raw = '{"alert_worthy": true, "priority": "critical", "makers_found": ["Hinderer"]}'
        result = json.loads(raw)
        assert result['alert_worthy'] is True
        assert result['priority'] == 'critical'

    def test_parse_markdown_wrapped_json(self):
        """JSON wrapped in ```json ... ``` is handled."""
        raw = '```json\n{"alert_worthy": true, "priority": "high"}\n```'
        # This is the parsing logic from ai_interpreter.py
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        result = json.loads(raw)
        assert result['priority'] == 'high'

    def test_parse_backtick_only_wrapped(self):
        """JSON wrapped in ``` ... ``` (no language tag) is handled."""
        raw = '```\n{"alert_worthy": false, "priority": "medium"}\n```'
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        result = json.loads(raw)
        assert result['alert_worthy'] is False

    def test_garbage_response_fails_gracefully(self):
        """Garbage from Claude doesn't crash — returns None."""
        raw = 'I cannot analyze this page because...'
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = None
        assert result is None

    @patch('anthropic.Anthropic')
    def test_log_api_usage(self, mock_anthropic, tmp_env):
        """log_api_usage writes token counts to SQLite."""
        import importlib
        import paths
        importlib.reload(paths)
        import db
        db.DB_PATH = os.environ['DW_DB']

        if 'agents.ai_interpreter' in sys.modules:
            del sys.modules['agents.ai_interpreter']

        # Mock the message object
        mock_message = MagicMock()
        mock_message.usage.input_tokens = 1500
        mock_message.usage.output_tokens = 300

        from agents.ai_interpreter import log_api_usage
        log_api_usage('analyze_page', 'KnifeJoy', mock_message)

        summary = db.get_api_usage_summary()
        assert summary['total_calls'] == 1
        assert summary['total_in'] == 1500
        assert summary['total_out'] == 300


# ═══════════════════════════════════════════════════════════════════════════════
# 4. SSRF PROTECTION (safe_fetch.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSRF:
    """Test safe_fetch.py blocks dangerous URLs."""

    def test_blocks_private_ip(self):
        """Private IPs are blocked."""
        from safe_fetch import is_safe_url
        with patch('socket.getaddrinfo', return_value=[
            (2, 1, 6, '', ('192.168.1.1', 0)),
        ]):
            safe, reason = is_safe_url('http://internal.example.com')
            assert safe is False
            assert 'internal' in reason.lower() or 'reserved' in reason.lower()

    def test_blocks_localhost(self):
        """Localhost is blocked."""
        from safe_fetch import is_safe_url
        with patch('socket.getaddrinfo', return_value=[
            (2, 1, 6, '', ('127.0.0.1', 0)),
        ]):
            safe, _ = is_safe_url('http://localhost')
            assert safe is False

    def test_blocks_metadata_endpoint(self):
        """Cloud metadata endpoints are blocked."""
        from safe_fetch import is_safe_url
        with patch('socket.getaddrinfo', return_value=[
            (2, 1, 6, '', ('169.254.169.254', 0)),
        ]):
            safe, _ = is_safe_url('http://169.254.169.254/latest/meta-data/')
            assert safe is False

    def test_blocks_metadata_hostname(self):
        """Known metadata hostnames are blocked."""
        from safe_fetch import is_safe_url
        safe, _ = is_safe_url('http://metadata.google.internal/computeMetadata/v1/')
        assert safe is False

    def test_allows_public_url(self):
        """Public URLs are allowed."""
        from safe_fetch import is_safe_url
        with patch('socket.getaddrinfo', return_value=[
            (2, 1, 6, '', ('104.21.45.67', 0)),
        ]):
            safe, reason = is_safe_url('https://www.knifejoy.com')
            assert safe is True

    def test_blocks_non_http(self):
        """Non-HTTP schemes are blocked."""
        from safe_fetch import is_safe_url
        safe, _ = is_safe_url('ftp://example.com/file')
        assert safe is False
        safe, _ = is_safe_url('file:///etc/passwd')
        assert safe is False

    def test_blocks_no_hostname(self):
        """URLs without hostname are blocked."""
        from safe_fetch import is_safe_url
        safe, _ = is_safe_url('https://')
        assert safe is False


# ═══════════════════════════════════════════════════════════════════════════════
# 5. FILE I/O SAFETY
# ═══════════════════════════════════════════════════════════════════════════════

class TestFileIO:
    """Test SQLite database operations."""

    def test_empty_db_returns_empty(self, tmp_env):
        """get_active_watchers returns [] on fresh db."""
        import db
        result = db.get_active_watchers()
        assert result == []

    def test_add_and_read_watcher(self, tmp_env):
        """add_watcher + get_watcher_by_id round-trip."""
        import db
        watcher = {
            'id': 'test1', 'email': 'x@example.com', 'url': 'https://example.com',
            'keywords': 'test', 'name': '', 'priority': 'high', 'phone': '',
            'sms_approved': False, 'sms_verify_code': None, 'sms_verify_expires': None,
            'active': True, 'verify_token': None,
            'unsubscribe_token': 'tok-123', 'created': '2026-01-01T00:00:00',
            'last_alert': None, 'alert_count': 0,
        }
        db.add_watcher(watcher)
        loaded = db.get_watcher_by_id('test1')
        assert loaded is not None
        assert loaded['email'] == 'x@example.com'

    def test_cooldown_tracking(self, tmp_env):
        """Cooldown key can be checked and marked."""
        import db
        assert not db.is_cooldown_active('test-key', hours=6)
        db.mark_cooldown('test-key', recipient='test@example.com')
        assert db.is_cooldown_active('test-key', hours=6)

    def test_drop_round_trip(self, tmp_env):
        """add_drop + get_recent_drops round-trip."""
        import db
        drop = {
            'source': 'Test', 'url': 'https://example.com',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'priority': 'high', 'page_summary': 'Test drop',
            'notable_items': ['Item 1'], 'alert_worthy': True,
        }
        db.add_drop(drop)
        drops = db.get_recent_drops(hours=1)
        assert len(drops) == 1
        assert drops[0]['source'] == 'Test'


# ═══════════════════════════════════════════════════════════════════════════════
# 6. DISCORD LOGGER DEDUP
# ═══════════════════════════════════════════════════════════════════════════════

class TestDiscordLogger:
    """Test discord_logger.py dedup logic."""

    def test_drop_id_deterministic(self):
        """Same drop produces same ID."""
        from discord_logger import drop_id
        drop = {'timestamp': '2026-03-20T12:00:00', 'url': 'https://example.com', 'source': 'Test'}
        id1 = drop_id(drop)
        id2 = drop_id(drop)
        assert id1 == id2

    def test_drop_id_different_drops(self):
        """Different drops produce different IDs."""
        from discord_logger import drop_id
        d1 = {'timestamp': '2026-03-20T12:00:00', 'url': 'https://example.com', 'source': 'A'}
        d2 = {'timestamp': '2026-03-20T12:00:00', 'url': 'https://example.com', 'source': 'B'}
        assert drop_id(d1) != drop_id(d2)

    def test_prune_sent_removes_old(self):
        """prune_sent removes entries older than 48h."""
        from discord_logger import prune_sent
        now = datetime.now(timezone.utc)
        sent = {
            'old': (now - timedelta(hours=49)).isoformat(),
            'new': (now - timedelta(hours=1)).isoformat(),
        }
        pruned = prune_sent(sent)
        assert 'old' not in pruned
        assert 'new' in pruned

    def test_format_embed_structure(self):
        """format_embed returns valid Discord embed structure."""
        from discord_logger import format_embed
        drop = {
            'priority': 'critical',
            'source': 'KnifeJoy',
            'url': 'https://www.knifejoy.com',
            'page_summary': 'Hinderer XM-18 Damascus dropped',
            'notable_items': ['XM-18 Damascus'],
            'timestamp': '2026-03-20T12:00:00+00:00',
        }
        embed = format_embed(drop)
        assert 'title' in embed
        assert 'description' in embed
        assert 'color' in embed
        assert 'CRITICAL' in embed['title']
        assert embed['url'] == 'https://www.knifejoy.com'


# ═══════════════════════════════════════════════════════════════════════════════
# 7. TOKEN REPORT
# ═══════════════════════════════════════════════════════════════════════════════

class TestTokenReport:
    """Test bin/token_report.py data loading."""

    def test_load_empty(self, tmp_env):
        """No usage file returns empty list."""
        sys.path.insert(0, os.path.join(ROOT, 'bin'))
        if 'token_report' in sys.modules:
            del sys.modules['token_report']
        import importlib
        import paths
        importlib.reload(paths)
        from token_report import load_usage
        result = load_usage(days=1)
        assert result == []

    def test_load_with_data(self, tmp_env):
        """Usage file with entries loads correctly."""
        import importlib
        import paths
        importlib.reload(paths)

        now = datetime.now(timezone.utc)
        entries = [
            {'ts': now.isoformat(), 'caller': 'analyze_page', 'site': 'Test',
             'model': 'haiku', 'input_tokens': 1000, 'output_tokens': 200},
            {'ts': (now - timedelta(hours=2)).isoformat(), 'caller': 'morning_briefing', 'site': 'n/a',
             'model': 'haiku', 'input_tokens': 500, 'output_tokens': 100},
        ]
        with open(paths.API_USAGE_JSONL, 'w') as f:
            for e in entries:
                f.write(json.dumps(e) + '\n')

        sys.path.insert(0, os.path.join(ROOT, 'bin'))
        if 'token_report' in sys.modules:
            del sys.modules['token_report']
        from token_report import load_usage
        result = load_usage(days=1)
        assert len(result) == 2

    def test_load_filters_by_days(self, tmp_env):
        """load_usage filters out entries older than N days."""
        import importlib
        import paths
        importlib.reload(paths)

        now = datetime.now(timezone.utc)
        entries = [
            {'ts': now.isoformat(), 'caller': 'analyze_page', 'site': 'Test',
             'model': 'haiku', 'input_tokens': 1000, 'output_tokens': 200},
            {'ts': (now - timedelta(days=5)).isoformat(), 'caller': 'old_call', 'site': 'Old',
             'model': 'haiku', 'input_tokens': 500, 'output_tokens': 100},
        ]
        with open(paths.API_USAGE_JSONL, 'w') as f:
            for e in entries:
                f.write(json.dumps(e) + '\n')

        sys.path.insert(0, os.path.join(ROOT, 'bin'))
        if 'token_report' in sys.modules:
            del sys.modules['token_report']
        from token_report import load_usage
        result = load_usage(days=1)
        assert len(result) == 1
        assert result[0]['caller'] == 'analyze_page'


# ═══════════════════════════════════════════════════════════════════════════════
# P0 BUGFIXES — S51 code-review (2026-06-06, Session 52)
# ═══════════════════════════════════════════════════════════════════════════════

class TestP0Bugfixes:
    """Regression tests for the href + AI-null P0 bugs from docs/2026-06-05-code-review-plan.md."""

    # (a) collection_fetch: a handle-less product must NOT deep-link to the whole collection.
    def test_parse_products_handleless_no_collection_deeplink(self):
        import collection_fetch
        base = 'https://shop.example.com/collections/knives'
        prods = [{'title': 'Mystery Item', 'variants': [{'available': True, 'price': '10'}]}]  # no handle
        out = collection_fetch._parse_products(prods, base)
        assert len(out) == 1
        assert out[0]['url'] != base           # never point an item link at the collection
        assert not out[0]['url']               # empty → downstream skips deep-link, falls back to page link

    def test_parse_products_with_handle_deeplinks(self):
        import collection_fetch
        base = 'https://shop.example.com/collections/knives'
        prods = [{'title': 'Cool Knife', 'handle': 'cool-knife',
                  'variants': [{'available': True, 'price': '99'}]}]
        out = collection_fetch._parse_products(prods, base)
        assert out[0]['url'] == 'https://shop.example.com/products/cool-knife'

    # (d) build_alert_email must survive AI JSON nulls (priority/page_summary/notable_items == None).
    def test_build_alert_email_survives_null_ai_fields(self):
        import per_user_alerter
        watcher = {'id': 'w1', 'name': 'Tester', 'unsubscribe_token': 'tok-123'}
        drop = {
            'url': 'https://shop.example.com/collections/knives',
            'source': 'Example Shop',
            'page_summary': None,
            'notable_items': None,
            'priority': None,
            'products': None,
        }
        subject, html, text = per_user_alerter.build_alert_email(watcher, ['damascus'], drop)
        assert 'damascus' in text.lower()
        assert html  # rendered without raising
        assert 'None' not in (text.split('View:')[0])  # null summary not stringified into the body

    # (c) generate_security: log-derived values (UA, request path, IP) must be HTML-escaped
    #     before rendering into security.html (stored XSS into Simon's admin browser).
    def test_security_report_escapes_log_data(self):
        import generate_security
        payload = '<script>alert(1)</script>'
        data = {
            'total_requests': 1, 'unique_ips': 1, 'total_bytes': 10, 'scanner_attempts': 1,
            'bad_ua_summary': {payload: 2},
            'rate_abusers': {'1.2.3.4': 150},
            'ip_ua': {'1.2.3.4': {payload}},
            'scanners': {'5.6.7.8': ['/' + payload, '/.env']},
            'top_ips': [('1.2.3.4', 150)],
            'ip_404s': {}, 'ip_bytes': {},
            'top_404_ips': [],
            'status_counts': {200: 5},
            'top_paths': [('/' + payload, 99)],
        }
        out = generate_security.generate_html(data)
        assert '<script>alert(1)</script>' not in out   # never rendered raw
        assert '&lt;script&gt;' in out                  # escaped instead


# ═══════════════════════════════════════════════════════════════════════════════
# P1 SECURITY — S51 code-review (SSRF guard on the recurring fetch + signup)
# ═══════════════════════════════════════════════════════════════════════════════

class TestP1Security:
    """SSRF must be blocked on the stored/recurring watch-fetch path, not just preview."""

    def test_fetch_page_refuses_loopback(self):
        import web_watcher
        # Must return None WITHOUT issuing the request (is_safe_url blocks pre-connect).
        assert web_watcher.fetch_page('http://127.0.0.1:5001/') is None

    def test_fetch_page_refuses_metadata_ip(self):
        import web_watcher
        assert web_watcher.fetch_page('http://169.254.169.254/latest/meta-data/') is None

    def test_fetch_page_refuses_non_http(self):
        import web_watcher
        assert web_watcher.fetch_page('file:///etc/passwd') is None


class TestSignupSSRF:
    """Signup must reject internal targets at write-time (before they're stored + polled)."""

    @pytest.fixture
    def client(self, tmp_env):
        import importlib
        import paths
        importlib.reload(paths)
        import db
        db.DB_PATH = os.environ['DW_DB']
        if 'watcher_signup' in sys.modules:
            del sys.modules['watcher_signup']
        with patch.dict(os.environ, {'RESEND_API_KEY': 'test-key'}):
            import watcher_signup
            importlib.reload(watcher_signup)
            watcher_signup.app.config['TESTING'] = True
            with watcher_signup.app.test_client() as c:
                yield c

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.quick_keyword_check', return_value=[])
    def test_signup_rejects_internal_url(self, mock_check, mock_email, client, tmp_env):
        resp = client.post('/api/watch', json={
            'url': 'http://169.254.169.254/latest/meta-data/',
            'keywords': 'token', 'email': 'attacker@example.com',
        })
        assert resp.status_code == 400
        import db
        assert db.get_watchers_by_email('attacker@example.com') == []  # never stored


# ═══════════════════════════════════════════════════════════════════════════════
# MATCHING PRIMITIVE — direct boundary assertions (S51 P4: was 0 direct tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMatching:
    """kw_matches boundary logic — a word-like keyword must not fire inside a larger word."""

    def test_alnum_keyword_is_boundary_bounded(self):
        from matching import kw_matches
        assert not kw_matches('axe', 'fully relaxed fit')      # not inside 'relaxed'
        assert not kw_matches('tin', 'continental divide')     # not inside 'continental'
        assert kw_matches('axe', 'a broad axe here')           # standalone word
        assert kw_matches('tin', 'a tin opener')               # standalone word

    def test_boundaries_are_non_alnum_not_just_space(self):
        from matching import kw_matches
        assert kw_matches('xm-18', 'hinderer xm-18, blue')     # comma boundary
        assert kw_matches('para3', '(para3)')                  # paren boundaries

    def test_punctuation_edged_keyword_is_plain_substring(self):
        from matching import kw_matches
        # leading punctuation → boundary anchoring doesn't apply, plain substring
        assert kw_matches('<script', 'evil <script>alert</script>')

    def test_empty_keyword_never_matches(self):
        from matching import kw_matches
        assert not kw_matches('', 'anything at all')

    def test_compiled_pattern_is_cached(self):
        from matching import _bounded_pattern
        assert _bounded_pattern('damascus') is _bounded_pattern('damascus')  # lru_cache hit


class TestPageFingerprint:
    """Normalized change-detection: cosmetic churn must NOT bust the cache (no paid AI);
    real stock/title changes MUST. (S51 P3b)"""

    def test_cosmetic_change_same_fingerprint_for_shopify(self):
        import web_watcher
        prods = [{'title': 'Sebenza 31', 'available': True}]
        a = web_watcher.page_fingerprint('cart(0) ... 5 viewing now', prods)
        b = web_watcher.page_fingerprint('cart(2) ... 19 viewing now', prods)  # cosmetic only
        assert a == b

    def test_stock_change_differs(self):
        import web_watcher
        a = web_watcher.page_fingerprint('x', [{'title': 'Sebenza 31', 'available': False}])
        b = web_watcher.page_fingerprint('x', [{'title': 'Sebenza 31', 'available': True}])
        assert a != b

    def test_non_shopify_falls_back_to_raw_text(self):
        import web_watcher
        a = web_watcher.page_fingerprint('page version one', [])
        b = web_watcher.page_fingerprint('page version two', [])
        assert a != b


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL WATCH MATCHING (per_user_alerter.global_watch_matches)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGlobalMatch:
    def test_global_fires_on_maker_and_coollist(self):
        from per_user_alerter import global_watch_matches
        text = "chris reeve knives large sebenza 25 in damascus — in stock"
        assert global_watch_matches('Chris Reeve', 'damascus, cgg', text) == ['damascus']

    def test_global_no_fire_wrong_maker(self):
        from per_user_alerter import global_watch_matches
        text = "spyderco paramilitary 2 damascus sprint run"
        assert global_watch_matches('Chris Reeve', 'damascus', text) == []

    def test_global_no_fire_maker_without_coollist(self):
        from per_user_alerter import global_watch_matches
        text = "chris reeve small sebenza 31 magnacut — in stock"
        assert global_watch_matches('Chris Reeve', 'damascus, cgg', text) == []

    def test_global_alias_satisfies_maker(self):
        from per_user_alerter import global_watch_matches
        text = "crk inkosi insingo damascus drop"   # 'crk' alias, no literal 'chris reeve'
        assert global_watch_matches('Chris Reeve', 'damascus', text) == ['damascus']

    def test_global_watch_skips_user_drop_fires_on_curated(self, tmp_env):
        """A GLOBAL watcher must NOT fire on a (user)-sourced drop; it MUST fire on a
        curated drop with identical text. Exercises run() end-to-end. (S54 Issue 1)"""
        import per_user_alerter
        import uuid

        token = str(uuid.uuid4())
        global_watcher = {
            'id': 'gw001',
            'email': 'global@example.com',
            'url': '',           # empty URL → global watch
            'keywords': 'damascus',
            'maker': 'Chris Reeve',
            'name': 'Global Watcher',
            'phone': '',
            'sms_approved': False,
            'active': True,
            'verify_token': None,
            'unsubscribe_token': token,
            'created': datetime.now(timezone.utc).isoformat(),
            'last_alert': None,
            'alert_count': 0,
        }

        now = datetime.now(timezone.utc)
        # Both drops contain the same text that would match the global watcher.
        # Only the source tag differs.
        user_drop = {
            'timestamp': now.isoformat(),
            'url': 'https://www.knifejoy.com/collections/chris-reeve',
            'source': 'KnifeJoy (user)',      # (user)-sourced → global must skip
            'page_summary': 'chris reeve knives damascus in stock',
            'notable_items': [],
            'keywords_found': [],
            'page_excerpt': '',
            'priority': 'high',
            'alert_worthy': True,
        }
        curated_drop = {
            'timestamp': now.isoformat(),
            'url': 'https://www.bladehq.com/collections/chris-reeve',
            'source': 'BladeHQ',              # curated → global MUST fire
            'page_summary': 'chris reeve knives damascus in stock',
            'notable_items': [],
            'keywords_found': [],
            'page_excerpt': '',
            'priority': 'high',
            'alert_worthy': True,
        }

        with patch('per_user_alerter.db.get_active_watchers', return_value=[global_watcher]), \
             patch('per_user_alerter.load_recent_drops', return_value=[user_drop, curated_drop]), \
             patch('per_user_alerter.db.is_cooldown_active', return_value=False), \
             patch('per_user_alerter.db.mark_cooldown'), \
             patch('per_user_alerter.db.update_watcher'), \
             patch('per_user_alerter.send_email', return_value=True) as mock_send:

            per_user_alerter.run()

        # Must have been called exactly once — for the curated drop only.
        assert mock_send.call_count == 1, (
            f"Expected exactly 1 alert (curated drop only), got {mock_send.call_count}. "
            "Global watch must skip (user)-sourced drops."
        )
        # Verify the alert was for the curated drop URL, not the user drop.
        _subj, _html, _txt, kwargs = (
            mock_send.call_args[0] + (mock_send.call_args[1],)
        )
        assert 'bladehq' in _txt.lower() or 'bladehq' in _html.lower(), (
            "Alert email should reference the curated (BladeHQ) drop, not the user drop"
        )


class TestFetchText:
    """safe_fetch.fetch_text — shared SSRF-guarded, never-raising fetch used by the
    cron scrapers (dealer_scout fetches user-added domains). (S52)"""

    def test_blocks_loopback(self):
        from safe_fetch import fetch_text
        assert fetch_text('http://127.0.0.1:5001/') is None

    def test_blocks_metadata_ip(self):
        from safe_fetch import fetch_text
        assert fetch_text('http://169.254.169.254/latest/meta-data/') is None

    def test_blocks_non_http(self):
        from safe_fetch import fetch_text
        assert fetch_text('file:///etc/passwd') is None

    def test_never_raises_on_garbage(self):
        from safe_fetch import fetch_text
        assert fetch_text('http://') is None  # no hostname → None, not an exception


class TestUrlNormalization:
    """Shared watch-matching normalizers (urls.py) — must agree everywhere so a watch
    drop can't be stamped one way and matched another (silent miss). (S52)"""

    def test_normalize_basic(self):
        from urls import normalize_watch_url as n
        assert n('https://www.knifejoy.com/collections/Hinderer/') == 'knifejoy.com/collections/hinderer'
        assert n('http://shop.com') == 'shop.com'
        assert n('https://WWW.Shop.com/X') == 'shop.com/x'

    def test_normalize_strips_whitespace(self):
        from urls import normalize_watch_url as n
        assert n('  https://shop.com/x  ') == 'shop.com/x'   # the latent edge the old pua impl missed

    def test_normalize_handles_none_empty(self):
        from urls import normalize_watch_url as n
        assert n(None) == '' and n('') == ''

    def test_domain_basic(self):
        from urls import domain_from_url as d
        assert d('https://www.knifejoy.com/collections/x') == 'knifejoy.com'
        assert d('http://Shop.com/a/b') == 'shop.com'

    def test_embedded_scheme_preserved_in_path(self):
        from urls import normalize_watch_url as n
        assert n('https://sub.shop.com/http://x') == 'sub.shop.com/http://x'  # only prefix stripped


class TestConfigLoad:
    """Shared scraper config helpers (config_load.py) — web_watcher + feed_watcher
    must build the same keyword list + pre-filter identically. (S52)"""

    def test_build_keywords_flattens_and_dedupes(self):
        from config_load import build_keywords
        cool = {'keywords': {'grails': ['Sebenza', 'Lunar']}}
        makers = {'makers': [{'name': 'Chris Reeve', 'aliases': ['CRK', 'crk']}],
                  'collaborations': [{'aliases': ['CGG']}]}
        kws = build_keywords(cool, makers)
        assert set(kws) == {'sebenza', 'lunar', 'chris reeve', 'crk', 'cgg'}  # lowercased + deduped

    def test_prefilter_loose_substring(self):
        from config_load import prefilter
        assert prefilter('New SEBENZA 31 in stock', ['sebenza'])
        assert not prefilter('nothing here', ['sebenza'])


class TestCollectionFetch:
    """collection_fetch — the Shopify deep-link engine (S52: was thinly tested)."""

    def test_shopify_products_url_for_collection(self):
        import collection_fetch as cf
        assert cf.shopify_products_url('https://shop.com/collections/chris-reeve') == \
            'https://shop.com/collections/chris-reeve/products.json'
        assert cf.shopify_products_url('https://shop.com/collections/crk?sort=x') == \
            'https://shop.com/collections/crk/products.json'

    def test_shopify_products_url_none_for_non_collection(self):
        import collection_fetch as cf
        assert cf.shopify_products_url('https://shop.com/products/foo') is None
        assert cf.shopify_products_url('https://shop.com/') is None

    def test_parse_products_tags_list_and_string(self):
        import collection_fetch as cf
        base = 'https://shop.com/collections/x'
        out = cf._parse_products([
            {'title': 'A', 'handle': 'a', 'tags': ['steel', ' flame '], 'variants': [{'available': True, 'price': '10'}]},
            {'title': 'B', 'handle': 'b', 'tags': 'damascus, knife', 'variants': [{'available': False, 'price': '20'}]},
        ], base)
        assert out[0]['tags'] == ['steel', 'flame']        # list, trimmed
        assert out[1]['tags'] == ['damascus', 'knife']     # comma-string split
        assert out[0]['available'] is True and out[1]['available'] is False

    def test_parse_products_available_if_any_variant(self):
        import collection_fetch as cf
        out = cf._parse_products([
            {'title': 'A', 'handle': 'a', 'variants': [{'available': False}, {'available': True}]},
        ], 'https://shop.com/collections/x')
        assert out[0]['available'] is True
        assert out[0]['price'] == ''  # first variant had no price key

    def test_product_line_format(self):
        import collection_fetch as cf
        line = cf._product_line({'title': 'Sebenza', 'vendor': 'CRK', 'available': True,
                                 'price': '500', 'tags': ['grail']})
        assert 'Sebenza' in line and 'IN STOCK' in line and '$500' in line and 'grail' in line
        sold = cf._product_line({'title': 'X', 'vendor': 'Y', 'available': False, 'price': '1', 'tags': []})
        assert 'SOLD OUT' in sold


class TestEbayScan:
    """lunar_hunter eBay Browse API scanner — the authenticated path that sidesteps
    the IP-level 403s on eBay item/search pages. Dormant until creds are set. (S53)"""

    @pytest.fixture
    def lh(self, tmp_path, monkeypatch):
        # Point logging at tmp so importing lunar_hunter writes no real-log side effect.
        monkeypatch.setenv('DW_LOG_DIR', str(tmp_path))
        import importlib
        import paths
        importlib.reload(paths)
        import lunar_hunter as _lh
        importlib.reload(_lh)
        return _lh

    def _resp(self, payload, status=200):
        r = MagicMock(status_code=status)
        r.json.return_value = payload
        r.raise_for_status.return_value = None
        return r

    def test_scan_ebay_dormant_without_creds(self, lh, monkeypatch):
        monkeypatch.delenv('DW_EBAY_CLIENT_ID', raising=False)
        monkeypatch.delenv('DW_EBAY_CLIENT_SECRET', raising=False)

        def no_http(*a, **k):
            raise AssertionError('scan_ebay made an HTTP call with creds unset')
        monkeypatch.setattr(lh.requests, 'post', no_http)
        monkeypatch.setattr(lh.requests, 'get', no_http)

        assert lh.scan_ebay() == []

    def test_ebay_token_parses_access_token(self, lh, monkeypatch):
        monkeypatch.setattr(lh.requests, 'post',
                            lambda *a, **k: self._resp({'access_token': 'TKN123', 'expires_in': 7200}))
        assert lh._ebay_token('id', 'secret') == 'TKN123'

    def test_ebay_token_none_on_failure(self, lh, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError('network down')
        monkeypatch.setattr(lh.requests, 'post', boom)
        assert lh._ebay_token('id', 'secret') is None

    def test_finds_from_summaries_filters_unrelated(self, lh):
        summaries = [
            {'title': 'Chris Reeve Lunar Landing CGG Damascus',
             'itemWebUrl': 'https://www.ebay.com/itm/1', 'price': {'value': '2500.00'}},
            {'title': 'CRKT Lunar folding pocket knife',  # 'lunar' but not Reeve → must drop
             'itemWebUrl': 'https://www.ebay.com/itm/2', 'price': {'value': '40.00'}},
        ]
        finds = lh._ebay_finds_from_summaries(summaries)
        assert len(finds) == 1
        f = finds[0]
        assert f['source'] == 'eBay'
        assert f['url'] == 'https://www.ebay.com/itm/1'
        assert f['price'] == '2500.00'
        assert f['in_stock'] is None     # active listing != dealer stock → "LISTED"
        assert f['deep'] is True
        assert 'Lunar Landing' in f['title']

    def test_finds_from_summaries_handles_missing_price(self, lh):
        finds = lh._ebay_finds_from_summaries([
            {'title': 'Chris Reeve Lunar Landing', 'itemWebUrl': 'https://www.ebay.com/itm/3'},
        ])
        assert len(finds) == 1
        assert finds[0]['price'] == ''

    def test_scan_ebay_end_to_end_mocked(self, lh, monkeypatch):
        monkeypatch.setenv('DW_EBAY_CLIENT_ID', 'id')
        monkeypatch.setenv('DW_EBAY_CLIENT_SECRET', 'secret')
        monkeypatch.setattr(lh.requests, 'post',
                            lambda *a, **k: self._resp({'access_token': 'T'}))
        monkeypatch.setattr(lh.requests, 'get',
                            lambda *a, **k: self._resp({'itemSummaries': [
                                {'title': 'Chris Reeve Lunar Landing CGG',
                                 'itemWebUrl': 'https://www.ebay.com/itm/9',
                                 'price': {'value': '3000'}}]}))
        finds = lh.scan_ebay()
        assert len(finds) == 1
        assert finds[0]['url'] == 'https://www.ebay.com/itm/9'
        assert finds[0]['source'] == 'eBay'

    def test_scan_ebay_search_failure_returns_empty(self, lh, monkeypatch):
        monkeypatch.setenv('DW_EBAY_CLIENT_ID', 'id')
        monkeypatch.setenv('DW_EBAY_CLIENT_SECRET', 'secret')
        monkeypatch.setattr(lh.requests, 'post',
                            lambda *a, **k: self._resp({'access_token': 'T'}))

        def boom(*a, **k):
            raise RuntimeError('ebay 500')
        monkeypatch.setattr(lh.requests, 'get', boom)
        assert lh.scan_ebay() == []

    def test_ebay_active_reflects_creds(self, lh, monkeypatch):
        monkeypatch.delenv('DW_EBAY_CLIENT_ID', raising=False)
        monkeypatch.delenv('DW_EBAY_CLIENT_SECRET', raising=False)
        assert lh._ebay_active() is False
        monkeypatch.setenv('DW_EBAY_CLIENT_ID', 'id')
        monkeypatch.setenv('DW_EBAY_CLIENT_SECRET', 'secret')
        assert lh._ebay_active() is True

    def test_armed_email_lists_ebay_in_fleet_when_active(self, lh, monkeypatch):
        monkeypatch.setenv('DW_EBAY_CLIENT_ID', 'id')
        monkeypatch.setenv('DW_EBAY_CLIENT_SECRET', 'secret')
        _subj, html, txt = lh.build_armed_email()
        assert 'eBay' in html
        assert 'eBay' not in ', '.join(lh.BLIND_SPOTS)  # constant unchanged
        # active → not parked in the blind-spot sentence
        assert 'eBay (no API creds' not in html

    def test_armed_email_marks_ebay_blind_when_dormant(self, lh, monkeypatch):
        monkeypatch.delenv('DW_EBAY_CLIENT_ID', raising=False)
        monkeypatch.delenv('DW_EBAY_CLIENT_SECRET', raising=False)
        _subj, html, txt = lh.build_armed_email()
        assert 'eBay (no API creds' in html


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL WATCH MODEL — maker column (S54)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGlobalWatchModel:
    def test_add_watcher_persists_maker_and_empty_url(self, tmp_env):
        import db, uuid
        wid = str(uuid.uuid4())[:8]
        db.add_watcher({
            'id': wid, 'email': 'a@b.com', 'url': '', 'keywords': 'damascus,cgg',
            'maker': 'Chris Reeve', 'unsubscribe_token': 't', 'active': True,
            'created': '2026-06-06T00:00:00+00:00',
        })
        with db.get_db() as c:
            row = c.execute("SELECT url, maker FROM watchers WHERE id=?", (wid,)).fetchone()
        assert row['url'] == '' and row['maker'] == 'Chris Reeve'


# ═══════════════════════════════════════════════════════════════════════════════
# NEW-SHOP CAP (db.count_recent_new_shop_watches) — S54
# ═══════════════════════════════════════════════════════════════════════════════

class TestNewShopCap:
    def test_counts_recent_watches_to_unknown_domains(self, tmp_env):
        import db, uuid
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        for u in ['https://newshop.com/a', 'https://knifejoy.com/x']:
            db.add_watcher({'id': str(uuid.uuid4())[:8], 'email': 'c@d.com', 'url': u,
                            'keywords': 'k', 'unsubscribe_token': 't', 'active': True, 'created': now})
        n = db.count_recent_new_shop_watches('c@d.com', hours=24, known_domains={'knifejoy.com'})
        assert n == 1


# ═══════════════════════════════════════════════════════════════════════════════
# /api/watch — optional URL + maker + knife-gate (S54)
# ═══════════════════════════════════════════════════════════════════════════════

class TestWatchEndpointGlobal:
    @pytest.fixture
    def client(self, tmp_env):
        import importlib, paths, db
        importlib.reload(paths); db.DB_PATH = os.environ['DW_DB']
        if 'watcher_signup' in sys.modules: del sys.modules['watcher_signup']
        with patch.dict(os.environ, {'RESEND_API_KEY': 'test-key'}):
            import watcher_signup; importlib.reload(watcher_signup)
            watcher_signup.app.config['TESTING'] = True
            with watcher_signup.app.test_client() as c:
                yield c, watcher_signup

    @patch('watcher_signup.send_verification_email', return_value=True)
    def test_global_requires_maker(self, _e, client):
        c, _ws = client
        r = c.post('/api/watch', json={'url': '', 'keywords': 'damascus', 'email': 'g@h.com'})
        assert r.status_code == 400 and 'maker' in r.get_json()['error'].lower()

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.send_confirmation_email', return_value=True)
    def test_global_watch_created(self, _c, _e, client):
        c, _ws = client
        r = c.post('/api/watch', json={'url': '', 'maker': 'Chris Reeve', 'keywords': 'damascus', 'email': 'g@h.com'})
        assert r.status_code in (200, 201)
        import db
        ws = db.get_watchers_by_email('g@h.com')
        assert any((w['url'] or '') == '' and w['maker'] == 'Chris Reeve' for w in ws)

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.send_confirmation_email', return_value=True)
    def test_new_domain_not_knives_rejected(self, _c, _e, client):
        c, ws = client
        ws._fetch_page_text = lambda u: 'shoes and socks'
        # Test domains don't resolve — bypass the write-time SSRF guard so we exercise
        # the knife-gate, not DNS. (SSRF is covered in TestSignupSSRF.)
        with patch.object(ws, 'is_safe_url', return_value=(True, '')), \
             patch.object(ws, 'classify_dealer', return_value={'is_dealer': False, 'confidence': 0.9, 'category': 'apparel'}):
            r = c.post('/api/watch', json={'url': 'https://sneakers-xyz.com/x', 'keywords': 'jordan', 'email': 'g@h.com'})
        assert r.status_code == 400 and 'knives' in r.get_json()['error'].lower()

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.send_confirmation_email', return_value=True)
    def test_new_domain_knives_creates_and_queues(self, _c, _e, client):
        c, ws = client
        ws._fetch_page_text = lambda u: 'chris reeve sebenza knives in stock'
        with patch.object(ws, 'is_safe_url', return_value=(True, '')), \
             patch.object(ws, 'classify_dealer', return_value={'is_dealer': True, 'confidence': 0.95, 'category': 'knife dealer', 'brands': 'Chris Reeve'}):
            r = c.post('/api/watch', json={'url': 'https://newknives-xyz.com/crk', 'keywords': 'damascus', 'email': 'g@h.com'})
        assert r.status_code in (200, 201)
        import db
        assert db.get_dealer_candidate('newknives-xyz.com') is not None


# ═══════════════════════════════════════════════════════════════════════════════
# MAKER ALIAS EXPANSION (makers.py) — S54
# ═══════════════════════════════════════════════════════════════════════════════

class TestExpandMaker:
    def test_known_maker_expands_to_aliases(self):
        from makers import expand_maker
        terms = expand_maker('Chris Reeve')
        assert 'chris reeve' in terms and 'crk' in terms   # name + alias, lowercased

    def test_alias_input_resolves_same_maker(self):
        from makers import expand_maker
        assert set(expand_maker('crk')) == set(expand_maker('Chris Reeve'))

    def test_unknown_maker_returns_literal(self):
        from makers import expand_maker
        assert expand_maker('Acme Forge') == ['acme forge']

    def test_blank_returns_empty(self):
        from makers import expand_maker
        assert expand_maker('') == [] and expand_maker(None) == []


# ═══════════════════════════════════════════════════════════════════════════════
# WEB_WATCHER — skips global (empty-URL) watches (S54)
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebWatcherSkipsGlobal:
    def test_user_site_list_excludes_empty_url(self):
        import web_watcher  # agents/ is on sys.path via the module-level insert above
        watchers = [
            {'id': '1', 'url': 'https://shop.com/x', 'keywords': 'a', 'active': 1},
            {'id': '2', 'url': '',                  'keywords': 'a', 'maker': 'CRK', 'active': 1},
            {'id': '3', 'url': None,                'keywords': 'a', 'maker': 'CRK', 'active': 1},
        ]
        sites = web_watcher.user_watch_sites(watchers)
        urls = [s['url'] for s in sites]
        assert 'https://shop.com/x' in urls
        assert '' not in urls and None not in urls
        assert len(sites) == 1
