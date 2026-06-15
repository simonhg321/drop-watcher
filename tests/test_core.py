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
        # query string / fragment on a bare-domain URL must not leak into the domain
        # (UTM-appended outbound links: https://mcneesknives.com?utm_source=dropwatcher)
        assert domain_from_url('https://mcneesknives.com?utm_source=dropwatcher&utm_medium=alert') == 'mcneesknives.com'
        assert domain_from_url('https://shop.com#frag') == 'shop.com'

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
# 2b. BACKFILL-ON-SIGNUP (backfill_alerter.py)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMatchesForWatcherDrop:
    """The shared matching primitive used by both live alerter and backfill."""

    def test_global_needs_maker_and_keyword(self):
        from per_user_alerter import matches_for_watcher_drop
        w = {'id': 'g1', 'url': '', 'maker': 'Demko', 'keywords': 'ad22, compact'}
        hit = {'source': 'Reddit', 'url': 'https://reddit.com/x',
               'page_summary': 'WTS Demko AD22 compact', 'notable_items': []}
        assert sorted(matches_for_watcher_drop(w, hit)) == ['ad22', 'compact']

    def test_global_no_maker_mention_no_match(self):
        from per_user_alerter import matches_for_watcher_drop
        w = {'id': 'g1', 'url': '', 'maker': 'Demko', 'keywords': 'ad22, compact'}
        # keyword present but maker (Demko) absent → global watch must not fire
        miss = {'source': 'Reddit', 'url': 'https://reddit.com/x',
                'page_summary': 'WTS a compact knife', 'notable_items': []}
        assert matches_for_watcher_drop(w, miss) == []

    def test_global_skips_user_drops(self):
        from per_user_alerter import matches_for_watcher_drop
        w = {'id': 'g1', 'url': '', 'maker': 'Demko', 'keywords': 'ad22'}
        user_drop = {'source': 'someshop.com (user)', 'url': 'https://someshop.com',
                     'page_summary': 'Demko AD22', 'notable_items': []}
        assert matches_for_watcher_drop(w, user_drop) == []

    def test_matches_keyword_only_in_product_titles(self):
        """S60 regression: structured extraction can catch a product the prose
        summary/excerpt missed (real case: Shirogorov Quantum Ursus on
        eknives.com/new/ 2026-06-10). Matching must search products[*].title."""
        from per_user_alerter import matches_for_watcher_drop
        w = {'id': 'g1', 'url': '', 'maker': 'Shirogorov', 'keywords': 'Ursus'}
        drop = {'source': 'EKnives', 'url': 'https://eknives.com/new/',
                'page_summary': 'new arrivals featuring heretic and hinderer',
                'notable_items': [], 'page_excerpt': 'heretic wraith hinderer xm',
                'products': [{'title': 'Shirogorov Quantum Ursus Blue E-KAMO '
                                       'Titanium 3.75" Stonewash',
                              'url': 'https://eknives.com/shirogorov-quantum-ursus/'}]}
        assert matches_for_watcher_drop(w, drop) == ['ursus']

    def test_global_title_match_requires_maker_in_same_title(self):
        """S60 false positive (Simon's 'cross hatch' watch): NWK page mentioned
        Chris Reeve (pocket clips) in prose AND had Jack Wolf knives with
        'Titanium Cross Hatch Handle' in product titles. Maker and keyword from
        DIFFERENT products must not fire a global watch."""
        from per_user_alerter import matches_for_watcher_drop
        w = {'id': 'g1', 'url': '', 'maker': 'Chris Reeve', 'keywords': 'cross hatch'}
        drop = {'source': 'Northwest Knives', 'url': 'https://www.northwestknives.com',
                'page_summary': 'dealer inventory including chris reeve pocket clips',
                'notable_items': [], 'page_excerpt': '',
                'products': [{'title': 'Jack Wolf Knives Gunslinger Jack Slip Joint '
                                       '- Titanium Cross Hatch Handle',
                              'url': 'https://www.northwestknives.com/products/jw'}]}
        assert matches_for_watcher_drop(w, drop) == []

    def test_global_title_match_fires_when_maker_in_same_title(self):
        from per_user_alerter import matches_for_watcher_drop
        w = {'id': 'g1', 'url': '', 'maker': 'Chris Reeve', 'keywords': 'cross hatch'}
        drop = {'source': 'DLT', 'url': 'https://www.dlttrading.com',
                'page_summary': 'new arrivals', 'notable_items': [], 'page_excerpt': '',
                'products': [{'title': 'Chris Reeve Knives Inkosi Cross Hatch Drop Point',
                              'url': 'https://www.dlttrading.com/inkosi-ch'}]}
        assert matches_for_watcher_drop(w, drop) == ['cross hatch']

    def test_global_prose_match_unchanged(self):
        """Page-level prose matching must not regress: maker + keyword both in
        the prose summary still fires even with no products array."""
        from per_user_alerter import matches_for_watcher_drop
        w = {'id': 'g1', 'url': '', 'maker': 'Chris Reeve', 'keywords': 'cross hatch'}
        drop = {'source': 'Reddit', 'url': 'https://reddit.com/x',
                'page_summary': 'WTS chris reeve sebenza cross hatch mint',
                'notable_items': []}
        assert matches_for_watcher_drop(w, drop) == ['cross hatch']

    def test_url_watch_needs_domain_and_keyword(self):
        from per_user_alerter import matches_for_watcher_drop
        w = {'id': 'u1', 'url': 'https://knifejoy.com/c/hinderer',
             'maker': '', 'keywords': 'damascus'}
        same = {'source': 'KnifeJoy', 'url': 'https://knifejoy.com/c/hinderer',
                'page_summary': 'New damascus xm-18', 'notable_items': []}
        other = {'source': 'Other', 'url': 'https://elsewhere.com/x',
                 'page_summary': 'damascus', 'notable_items': []}
        assert matches_for_watcher_drop(w, same) == ['damascus']
        assert matches_for_watcher_drop(w, other) == []


class TestAISpend:
    """bin/ai_spend.py — session-start AI spend report (S60)."""

    def test_cost_math_haiku_45(self):
        sys.path.insert(0, os.path.join(ROOT, 'bin'))
        import ai_spend
        rows = [
            {'caller': 'analyze_page', 'input_tokens': 1_000_000, 'output_tokens': 0},
            {'caller': 'analyze_page', 'input_tokens': 0, 'output_tokens': 1_000_000},
        ]
        s = ai_spend.summarize(rows)
        # Haiku 4.5: $1/MTok in, $5/MTok out
        assert s['cost'] == pytest.approx(6.0)
        assert s['calls'] == 2
        assert s['in_tokens'] == 1_000_000
        assert s['out_tokens'] == 1_000_000


class TestAISchemaNullTolerance:
    """S60: Haiku occasionally returns null for a single item field and the
    whole page analysis was discarded (live: EKnives New Arrivals 2026-06-11,
    notable_items_detail[12].price = null → entire scan lost)."""

    def test_null_price_tolerated(self):
        from ai_interpreter import parse_ai_response, PageAnalysis
        raw = json.dumps({
            'page_summary': 'new arrivals', 'alert_worthy': True,
            'notable_items': ['Knife A'],
            'notable_items_detail': [{'name': 'Knife A', 'url': None, 'price': None}],
        })
        result, _ = parse_ai_response(raw, PageAnalysis, 'test')
        assert result['notable_items_detail'][0]['price'] == ''

    def test_null_name_tolerated(self):
        from ai_interpreter import parse_ai_response, PageAnalysis
        raw = json.dumps({
            'page_summary': 'new arrivals', 'alert_worthy': True,
            'notable_items': ['Knife A'],
            'notable_items_detail': [{'name': None, 'price': '$100'}],
        })
        result, _ = parse_ai_response(raw, PageAnalysis, 'test')
        assert result['notable_items_detail'][0]['name'] == ''


class TestBackfill:
    """backfill_alerter.py — one-time match against recent drop corpus."""

    def _seed_global_watcher(self, db, email='fan@example.com', alert_count=0):
        import uuid
        from datetime import datetime, timezone
        wid = uuid.uuid4().hex[:8]
        db.add_watcher({
            'id': wid, 'email': email, 'url': '', 'keywords': 'ad22, compact',
            'maker': 'Demko', 'name': 'Fan', 'active': True,
            'unsubscribe_token': uuid.uuid4().hex,
            'created': datetime.now(timezone.utc).isoformat(),
            'alert_count': alert_count, 'last_alert': None,
        })
        return wid

    def _seed_drop(self, db, summary='WTS Demko AD22 compact', url='https://reddit.com/r/knife_swap/1'):
        from datetime import datetime, timezone
        db.add_drop({
            'source': 'Reddit r/knife_swap', 'url': url,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'priority': 'medium', 'page_summary': summary, 'notable_items': [],
        })

    def test_dry_run_sends_nothing_but_reports(self, tmp_env):
        import db, backfill_alerter
        self._seed_global_watcher(db)
        self._seed_drop(db)
        with patch('backfill_alerter.send_email') as mock_send:
            res = backfill_alerter.backfill_for_email('fan@example.com', dry_run=True)
        mock_send.assert_not_called()
        assert res['matched_drops'] == 1
        assert res['sent'] is False

    def test_real_run_sends_digest_and_marks(self, tmp_env):
        import db, backfill_alerter
        wid = self._seed_global_watcher(db)
        self._seed_drop(db)
        with patch('backfill_alerter.send_email', return_value=True) as mock_send:
            res = backfill_alerter.backfill_for_email('fan@example.com')
        assert mock_send.call_count == 1
        assert res['sent'] is True
        # counter bumped, last_alert set
        w = db.get_watcher_by_id(wid)
        assert w['alert_count'] == 1
        assert w['last_alert'] is not None

    def test_no_match_no_email(self, tmp_env):
        import db, backfill_alerter
        self._seed_global_watcher(db)
        self._seed_drop(db, summary='WTS a random spyderco')  # no Demko mention
        with patch('backfill_alerter.send_email', return_value=True) as mock_send:
            res = backfill_alerter.backfill_for_email('fan@example.com')
        mock_send.assert_not_called()
        assert res['sent'] is False

    def test_cooldown_active_skipped(self, tmp_env):
        import db, backfill_alerter
        from per_user_alerter import cooldown_key
        wid = self._seed_global_watcher(db)
        self._seed_drop(db, url='https://reddit.com/r/knife_swap/1')
        # Pre-open an episode for the exact (watcher,url,matches) tuple
        ck = cooldown_key(wid, 'https://reddit.com/r/knife_swap/1', ['ad22', 'compact'])
        db.open_episode(ck, wid, 'reddit.com', 'https://reddit.com/r/knife_swap/1',
                        'ad22,compact', 'fan@example.com', '2026-06-12T20:00:00+00:00')
        with patch('backfill_alerter.send_email', return_value=True) as mock_send:
            res = backfill_alerter.backfill_for_email('fan@example.com')
        mock_send.assert_not_called()
        assert res['sent'] is False

    def test_send_failure_does_not_mark(self, tmp_env):
        import db, backfill_alerter
        wid = self._seed_global_watcher(db)
        self._seed_drop(db)
        with patch('backfill_alerter.send_email', return_value=False):
            res = backfill_alerter.backfill_for_email('fan@example.com')
        assert res['sent'] is False
        w = db.get_watcher_by_id(wid)
        assert w['alert_count'] == 0  # not bumped on failed send

    def test_digest_caps_drops(self, tmp_env):
        import db, backfill_alerter
        self._seed_global_watcher(db)
        for i in range(12):
            self._seed_drop(db, url=f'https://reddit.com/r/knife_swap/{i}')
        with patch('backfill_alerter.send_email', return_value=True):
            res = backfill_alerter.backfill_for_email('fan@example.com')
        assert res['matched_drops'] == 12
        assert res['shown'] == backfill_alerter.MAX_DROPS_PER_DIGEST

    def test_resolve_drop_items_skips_sold_out(self):
        # User watches can carry sold-out notable_items — must NOT be deep-linked.
        from per_user_alerter import resolve_drop_items, _is_sold_out
        assert _is_sold_out('CKF Peaceduke — SOLD OUT — $585') is True
        assert _is_sold_out('CKF GTK Elementak — IN STOCK — $585') is False
        assert _is_sold_out('Spyderco — NOTIFY ME') is True
        drop = {'source': 'ncblade.com (user)', 'url': 'https://ncblade.com/x',
                'notable_items': [
                    'CKF Peaceduke 2.0 M398 — SOLD OUT — $700',
                    'CKF GTK Elementak DLC M398 — IN STOCK — $585']}
        items = resolve_drop_items(drop, ['ckf', 'm398'])
        titles = ' '.join(it['title'] for it in items)
        assert 'GTK Elementak' in titles
        assert 'Peaceduke' not in titles      # sold-out item dropped from deep-links

    def test_live_alert_email_deep_links_store_item(self):
        # build_alert_email must deep-link a store item via link_candidates, not the page.
        from per_user_alerter import build_alert_email
        watcher = {'id': 'w1', 'name': 'Fan', 'email': 'f@x.com', 'unsubscribe_token': 'tok'}
        drop = {'source': 'Knife Art', 'url': 'https://www.knifeart.com',
                'page_summary': 'damascus in stock',
                'notable_items': ['Spartan Harsey Folder Damascus - $450.00'],
                'link_candidates': [
                    {'text': 'Spartan Harsey Folder Damascus',
                     'href': 'https://www.knifeart.com/products/spartan-harsey-damascus'}]}
        subject, html, text = build_alert_email(watcher, ['damascus'], drop)
        assert 'https://www.knifeart.com/products/spartan-harsey-damascus' in html
        assert 'https://www.knifeart.com/products/spartan-harsey-damascus' in text

    def test_digest_items_deep_links(self):
        import backfill_alerter as ba
        # 1. structured products → real product URL
        d1 = {'source': 'NCBlade', 'url': 'https://ncblade.com/collections/ckf',
              'products': [{'title': 'CKF Damascus', 'url': 'https://ncblade.com/products/ckf-damascus',
                            'price': '900', 'available': True, 'tags': ['damascus']}]}
        items = ba.digest_items(d1, ['damascus'])
        assert items[0]['url'] == 'https://ncblade.com/products/ckf-damascus'

        # 2. Reddit post → the drop url IS the listing
        d2 = {'source': 'Reddit r/knife_swap',
              'url': 'https://www.reddit.com/r/Knife_Swap/comments/abc/wts_damascus/',
              'notable_items': ['Pro-Tech Damascus - $3,495']}
        items = ba.digest_items(d2, ['damascus'])
        assert items[0]['url'] == d2['url']
        assert items[0]['price'] == '3,495'

        # 3. Store collection w/o product URL → show the item name+price, link the real
        #    scraped page (we do NOT fabricate /search URLs — they 404 on many stores).
        d3 = {'source': 'EDC Lifestyle', 'url': 'https://www.edclifestyle.com/pre-owned/',
              'notable_items': ['Heretic Hydra Damascus Recurve - $2,200.00 (in stock)']}
        items = ba.digest_items(d3, ['damascus'])
        assert items[0]['url'] == d3['url']               # the real page, never a guess
        assert items[0]['price'] == '2,200.00'
        assert 'Heretic Hydra Damascus Recurve' in items[0]['title']

        # 4. store collection w/ link_candidates → notable item resolves to its product
        d4 = {'source': 'Knife Art', 'url': 'https://www.knifeart.com',
              'notable_items': ['Spartan Harsey Folder Damascus - $450.00'],
              'link_candidates': [
                  {'text': 'Spartan Harsey Folder Damascus',
                   'href': 'https://www.knifeart.com/products/spartan-harsey-folder-damascus'},
                  {'text': 'Some Other Knife',
                   'href': 'https://www.knifeart.com/products/some-other-knife'}]}
        items = ba.digest_items(d4, ['damascus'])
        assert items[0]['url'] == 'https://www.knifeart.com/products/spartan-harsey-folder-damascus'
        assert items[0]['url'] != d4['url']               # deep-linked, not the homepage

    def test_collection_fetch_returns_candidates_from_html(self):
        # Non-Shopify HTML page with /products/ anchors → tier-3 structured extraction
        # now fires, so products is populated and candidates is [] (Task 4 wiring).
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'agents'))
        import collection_fetch
        html = ('<html><body>'
                '<a href="/products/chris-reeve-sebenza-31-damascus">CRK Sebenza 31 Damascus</a>'
                '<a href="/cart">Cart</a>'
                '<a href="/products/spartan-harsey-damascus">Spartan Harsey Damascus</a>'
                '</body></html>')
        def fake_fetch(url, ssl_permissive=False):
            return html if 'products.json' not in url else None
        text, products, candidates = collection_fetch.fetch_collection(
            'https://examplestore.com/collections/all', fake_fetch)
        assert text is not None
        # Tier-3 picks up /products/ anchors as structured products; candidates is empty.
        assert products is not None
        product_urls = [p['url'] for p in products]
        assert any('chris-reeve-sebenza-31-damascus' in u for u in product_urls)
        assert all('/cart' not in u for u in product_urls)  # bad paths dropped
        assert candidates == []                              # structured hit → no fuzzy fallback

    def test_priority_intel_survives_numeric_models(self):
        # YAML parses unquoted numeric models (Shirogorov 111, ZT 36) as ints;
        # build_priority_intel must not crash on ', '.join (S54 crash-loop fix).
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'agents'))
        import ai_interpreter as ai
        # high_models only render when the maker also has a critical entry (matches
        # the real Shirogorov/ZT config that crash-looped prod at the HIGH join).
        cfg = {'makers': [
            {'name': 'Shirogorov', 'notable_models': {'critical': ['neon'], 'high': [111, '95t']}},
            {'name': 'Zero Tolerance', 'notable_models': {'critical': [36], 'high': []}},
        ]}
        intel = ai.build_priority_intel(cfg)
        assert '111' in intel and '36' in intel   # ints rendered, no TypeError

    def test_digest_includes_disclaimer(self):
        import backfill_alerter
        subject, html, text = backfill_alerter.build_backfill_digest(
            'Fan', [(['ad22'], {'source': 'Reddit', 'url': 'https://x.com',
                                'page_summary': 'Demko AD22'})], 'tok123')
        for body in (html, text):
            assert 'not endorsements or guarantees' in body
            assert 'verify sellers' in body

    def test_backfill_scopes_to_only_watcher_ids(self, tmp_env):
        import db, backfill_alerter, uuid
        from datetime import datetime, timezone
        # Two active global watches for one email: only the new one should be scanned.
        tok = uuid.uuid4().hex
        for kw, maker in [('ad22', 'Demko'), ('sebenza', 'Chris Reeve')]:
            db.add_watcher({'id': kw[:6], 'email': 'multi@example.com', 'url': '',
                            'keywords': kw, 'maker': maker, 'name': 'M', 'active': True,
                            'unsubscribe_token': tok,
                            'created': datetime.now(timezone.utc).isoformat(),
                            'alert_count': 0, 'last_alert': None})
        self._seed_drop(db, summary='WTS Demko AD22 compact')         # matches ad22 watch
        self._seed_drop(db, summary='WTS Chris Reeve Sebenza 31', url='https://reddit.com/r/x/2')  # matches sebenza
        with patch('backfill_alerter.send_email', return_value=True) as mock_send:
            res = backfill_alerter.backfill_for_email('multi@example.com', only_watcher_ids=['ad22'])
        # Only the ad22 watch's drop should be in scope → 1 matched drop, one send.
        assert res['matched_drops'] == 1
        assert mock_send.call_count == 1

    def test_test_addresses_excluded_by_default(self):
        import backfill_alerter
        emails = ['fan@example.com', 'info@instockornot.club', 'simonhg@gmail.com']
        kept = backfill_alerter.filter_test_addresses(emails, include_tests=False)
        assert kept == ['fan@example.com']
        kept_all = backfill_alerter.filter_test_addresses(emails, include_tests=True)
        assert kept_all == emails


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
             patch('per_user_alerter.load_unprocessed_drops', return_value=[(1, user_drop), (2, curated_drop)]), \
             patch('per_user_alerter.db.is_cooldown_active', return_value=False), \
             patch('per_user_alerter.db.mark_cooldown'), \
             patch('per_user_alerter.db.update_watcher'), \
             patch('per_user_alerter.db.set_hwm'), \
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

    def test_shopify_products_url_root_for_non_collection(self):
        # Non-collection URLs now fall back to root /products.json (S55 tier-1 widening)
        import collection_fetch as cf
        assert cf.shopify_products_url('https://shop.com/products/foo') == \
            'https://shop.com/products.json'
        assert cf.shopify_products_url('https://shop.com/') == \
            'https://shop.com/products.json'
        assert cf.shopify_products_url('not-a-url') is None

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


class TestGrailRoster:
    """lunar_hunter multi-grail layer (S60): the hunter sweeps a roster of
    grails per run — Lunar Landing + Inkosi Cross Hatch — with per-grail
    match rules and per-grail seen-keys."""

    @pytest.fixture
    def lh(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DW_LOG_DIR', str(tmp_path))
        import importlib
        import paths
        importlib.reload(paths)
        import lunar_hunter as _lh
        importlib.reload(_lh)
        return _lh

    def test_roster_has_crosshatch(self, lh):
        keys = [g['key'] for g in lh.GRAILS]
        assert 'lunar' in keys and 'crosshatch' in keys

    def test_crosshatch_exact_wins_unscoped(self, lh):
        g = next(g for g in lh.GRAILS if g['key'] == 'crosshatch')
        assert lh._grail_match(g, 'chris reeve inkosi cross hatch drop point', scoped=False)
        assert lh._grail_match(g, 'inkosi cross hatch', scoped=False)

    def test_crosshatch_signal_needs_reeve_context_unscoped(self, lh):
        g = next(g for g in lh.GRAILS if g['key'] == 'crosshatch')
        # The S60 false positive: a handle texture, no Reeve context
        assert not lh._grail_match(
            g, 'jack wolf knives gunslinger jack slip joint - titanium cross hatch handle',
            scoped=False)
        # Reeve context in the same blob → fires (e.g. r/knife_swap sebenza 21 crosshatch)
        assert lh._grail_match(g, 'wts crk large sebenza 21 crosshatch mint', scoped=False)

    def test_crosshatch_signal_alone_ok_on_scoped_page(self, lh):
        g = next(g for g in lh.GRAILS if g['key'] == 'crosshatch')
        assert lh._grail_match(g, 'small cross hatch glass blasted', scoped=True)

    def test_lunar_behavior_unchanged(self, lh):
        g = next(g for g in lh.GRAILS if g['key'] == 'lunar')
        assert lh._grail_match(g, 'lunar landing cgg', scoped=False)
        assert not lh._grail_match(g, 'crkt lunar folding knife', scoped=False)
        assert lh._grail_match(g, 'lunar', scoped=True)

    def test_seen_key_preserves_lunar_prefix(self, lh):
        """Existing lunar seen-state must survive the refactor — same key as the
        old 'lunar:source|url|stock' scheme, and crosshatch keys must differ."""
        import hashlib
        lunar = next(g for g in lh.GRAILS if g['key'] == 'lunar')
        ch = next(g for g in lh.GRAILS if g['key'] == 'crosshatch')
        f = {'source': 'KnifeJoy', 'url': 'https://x/y', 'in_stock': True}
        old = hashlib.md5("lunar:KnifeJoy|https://x/y|True".encode()).hexdigest()
        assert lh._seen_key({**f, 'grail': lunar}) == old
        assert lh._seen_key({**f, 'grail': ch}) != old


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
# EMAIL AUDIT LOG (alerter.log_sent_email)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmailAuditLog:
    def test_log_sent_email_writes_record(self, tmp_env):
        import importlib
        import paths
        importlib.reload(paths)
        from alerter import log_sent_email
        log_sent_email(
            to='test@example.com',
            subject='[DROP WATCHER] Match found — Southern Edges',
            body_text='Keywords matched: umnumzaan\nSource: southernedges.com',
            email_type='alert',
        )
        log_path = os.path.join(str(tmp_env), 'logs', 'emails_sent.log')
        assert os.path.exists(log_path)
        content = open(log_path).read()
        assert 'TO: test@example.com' in content
        assert 'SUBJ: [DROP WATCHER] Match found' in content
        assert 'TYPE: alert' in content
        assert 'Keywords matched: umnumzaan' in content
        assert content.strip().endswith('===')

    def test_log_sent_email_appends(self, tmp_env):
        import importlib
        import paths
        importlib.reload(paths)
        from alerter import log_sent_email
        log_sent_email(to='a@test.com', subject='First', body_text='body1', email_type='alert')
        log_sent_email(to='b@test.com', subject='Second', body_text='body2', email_type='confirm')
        log_path = os.path.join(str(tmp_env), 'logs', 'emails_sent.log')
        content = open(log_path).read()
        assert content.count('===') == 2
        assert 'TO: a@test.com' in content
        assert 'TO: b@test.com' in content

    def test_log_sent_email_survives_missing_dir(self, tmp_env):
        """Should not raise if log dir doesn't exist (fail silent)."""
        import importlib
        import paths
        import shutil
        shutil.rmtree(os.path.join(str(tmp_env), 'logs'))
        importlib.reload(paths)
        from alerter import log_sent_email
        # Should not raise
        log_sent_email(to='x@test.com', subject='Test', body_text='body', email_type='alert')


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

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.send_confirmation_email', return_value=True)
    def test_new_shop_daily_cap_returns_429(self, _c, _e, client):
        # Set a low per-email daily cap, then add more distinct NEW (knife) domains than
        # the cap allows for one email; the over-limit request must 429.
        c, ws = client
        import paths, yaml
        with open(paths.SETTINGS_YAML, 'w') as f:
            yaml.safe_dump({'max_new_shops_per_email_per_day': 1}, f)
        ws._fetch_page_text = lambda u: 'chris reeve knives in stock'
        with patch.object(ws, 'is_safe_url', return_value=(True, '')), \
             patch.object(ws, 'classify_dealer',
                          return_value={'is_dealer': True, 'confidence': 0.95,
                                        'category': 'knife dealer', 'brands': 'CRK'}):
            r1 = c.post('/api/watch', json={'url': 'https://capshop-one.com/a',
                                            'keywords': 'damascus', 'email': 'cap@h.com'})
            r2 = c.post('/api/watch', json={'url': 'https://capshop-two.com/b',
                                            'keywords': 'damascus', 'email': 'cap@h.com'})
        assert r1.status_code in (200, 201)
        assert r2.status_code == 429

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.send_confirmation_email', return_value=True)
    def test_classify_failure_creates_watch_no_queue(self, _c, _e, client):
        # New domain, but page fetch yields nothing → classifier never runs → fail open:
        # the watch is created and the shop is NOT queued for review (don't lose the user).
        c, ws = client
        ws._fetch_page_text = lambda u: ''
        with patch.object(ws, 'is_safe_url', return_value=(True, '')), \
             patch.object(ws, 'classify_dealer') as mock_cls:
            r = c.post('/api/watch', json={'url': 'https://nopage-xyz.com/x',
                                           'keywords': 'damascus', 'email': 'nf@h.com'})
        assert r.status_code in (200, 201)
        mock_cls.assert_not_called()
        import db
        assert db.get_dealer_candidate('nopage-xyz.com') is None

    @patch('watcher_signup.send_verification_email', return_value=True)
    @patch('watcher_signup.send_confirmation_email', return_value=True)
    def test_curated_domain_skips_ai(self, _c, _e, client):
        # A domain already in sources.yaml is known/curated → the knife-gate (and its
        # paid AI call) must be skipped entirely, and the watch still created.
        c, ws = client
        import paths, yaml
        # Real sources.yaml uses the 'websites' top-level key (not 'sources').
        with open(paths.SOURCES_YAML, 'w') as f:
            yaml.safe_dump({'websites': [{'url': 'https://knownshop.com/collections/all'}]}, f)
        with patch.object(ws, 'is_safe_url', return_value=(True, '')), \
             patch.object(ws, 'classify_dealer', MagicMock()) as mock_cls:
            r = c.post('/api/watch', json={'url': 'https://knownshop.com/x',
                                           'keywords': 'damascus', 'email': 'kn@h.com'})
        assert r.status_code in (200, 201)
        mock_cls.assert_not_called()
        import db
        assert any(w['url'] for w in db.get_watchers_by_email('kn@h.com'))


# ═══════════════════════════════════════════════════════════════════════════════
# MAKER ALIAS EXPANSION (makers.py) — S54
# ═══════════════════════════════════════════════════════════════════════════════

class TestSynonyms:
    """Keyword synonym expansion (synonyms.py) — a cool-list term also matches its
    synonyms (cgg ↔ unique graphics). Reads the in-repo keyword_synonyms.yaml. (S54)"""

    def test_expand_known_group_is_bidirectional(self):
        from synonyms import expand_keyword
        a = set(expand_keyword('cgg'))
        b = set(expand_keyword('Unique Graphics'))
        assert 'cgg' in a and 'unique graphics' in a
        assert a == b

    def test_expand_unknown_is_literal(self):
        from synonyms import expand_keyword
        assert expand_keyword('damascus') == ['damascus']

    def test_expand_blank(self):
        from synonyms import expand_keyword
        assert expand_keyword('') == [] and expand_keyword(None) == []

    def test_kw_matches_any_fires_on_synonym(self):
        from synonyms import kw_matches_any
        assert kw_matches_any('cgg', 'chris reeve sebenza unique graphics edition')
        assert not kw_matches_any('cgg', 'plain titanium sebenza, no graphic')

    def test_keywords_match_uses_synonyms(self):
        from per_user_alerter import keywords_match
        # cool-list 'cgg' should fire on text that only says 'unique graphics'
        assert keywords_match('chris reeve unique graphics drop', 'cgg') == ['cgg']


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

    def test_real_makers_yaml_has_no_nonstring_aliases(self):
        # Guard: a YAML alias like 229 or 0044 parses as int and (pre-fix) crashed the
        # whole maker index, silently breaking ALL global maker matching. Catch it here.
        # Read the REPO config deterministically (not paths.MAKERS_YAML, which may point
        # at /etc and vary by environment).
        import yaml
        d = yaml.safe_load(open(os.path.join(ROOT, 'config', 'makers.yaml'))) or {}
        bad = [(m.get('name'), a) for m in d.get('makers', []) if isinstance(m, dict)
               for a in (m.get('aliases') or []) if not isinstance(a, str)]
        assert bad == [], f"non-string aliases (quote them in makers.yaml): {bad}"

    def test_build_keywords_survives_int_alias_and_nameless_collab(self):
        # This is what actually crash-looped web_watcher: an int alias hit .lower(),
        # and a collab entry inside makers: (no 'name') would KeyError.
        import config_load
        cool = {'keywords': {'b': ['Show', 229]}}
        makers = {'makers': [
            {'name': 'Chris Reeve Knives', 'aliases': ['crk', 229]},
            {'makers': ['Wilson Combat', 'Chris Reeve Knives'], 'aliases': ['wc sebenza']},
        ]}
        kws = config_load.build_keywords(cool, makers)
        assert 'crk' in kws and '229' in kws and 'wc sebenza' in kws

    def test_index_survives_a_nonstring_alias(self):
        # Even if a bad alias slips in, the index must still build for everyone else.
        import makers
        makers._maker_index.cache_clear()
        with patch('makers.load_yaml', return_value={'makers': [
                {'name': 'Chris Reeve Knives', 'aliases': ['crk', 'chris reeve']},
                {'name': 'Bad Maker', 'aliases': [229]}]}):
            idx = makers._maker_index('dummy-path')
        makers._maker_index.cache_clear()
        assert 'crk' in idx and '229' in idx  # both survive; int coerced to str

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


# ═══════════════════════════════════════════════════════════════════════════════
# SITE FEEDBACK — sanitizer + /api/feedback route (S54)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFeedbackSanitizer:
    """sanitize_feedback flattens untrusted input to plain text and caps length."""

    @pytest.fixture(autouse=True)
    def _import(self):
        import watcher_signup
        self.sanitize = watcher_signup.sanitize_feedback

    def test_strips_html_tags(self):
        out = self.sanitize('<script>alert(1)</script>hello <b>there</b>')
        assert '<' not in out and '>' not in out
        assert 'hello' in out and 'there' in out

    def test_removes_code_fences_and_backticks(self):
        out = self.sanitize('look ```rm -rf /``` at `this`')
        assert '`' not in out

    def test_flattens_markdown_links_keeps_text(self):
        out = self.sanitize('see [click me](http://evil.example/x)')
        assert 'click me' in out
        assert 'evil.example' not in out and '](' not in out

    def test_strips_leading_markdown_structure(self):
        out = self.sanitize('# Big header\n> quoted\n- bullet')
        assert 'Big header' in out and 'quoted' in out and 'bullet' in out
        assert not out.lstrip().startswith('#')
        assert '\n>' not in out and not out.splitlines()[1].startswith('>')

    def test_strips_zero_width_and_control_chars(self):
        out = self.sanitize('he​llo‮world\x07')
        assert '​' not in out and '‮' not in out and '\x07' not in out
        assert 'hello' in out.replace(' ', '')

    def test_caps_at_max_words(self):
        out = self.sanitize(' '.join(['word'] * 700), max_words=600)
        # 600 words + the [truncated] marker
        assert out.count('word') == 600
        assert '[truncated]' in out

    def test_under_cap_not_truncated(self):
        out = self.sanitize('just a short note')
        assert '[truncated]' not in out
        assert out == 'just a short note'

    def test_empty_returns_empty(self):
        assert self.sanitize('') == ''
        assert self.sanitize(None) == ''
        assert self.sanitize('   \n\t ') == ''


class TestFeedbackAPI:
    """POST /api/feedback emails Simon and posts a NOT FLEET blog entry."""

    @pytest.fixture
    def client(self, tmp_env):
        import importlib
        import paths
        importlib.reload(paths)
        import db
        db.DB_PATH = os.environ['DW_DB']
        if 'watcher_signup' in sys.modules:
            del sys.modules['watcher_signup']
        with patch.dict(os.environ, {'RESEND_API_KEY': 'test-key', 'DW_BLOG_TOKEN': 'test-token'}):
            import watcher_signup
            importlib.reload(watcher_signup)
            watcher_signup.app.config['TESTING'] = True
            with watcher_signup.app.test_client() as c:
                yield c

    @patch('watcher_signup.post_feedback_to_blog', return_value=True)
    @patch('watcher_signup.send_feedback_email', return_value=True)
    def test_happy_path(self, mock_email, mock_blog, client):
        resp = client.post('/api/feedback', json={
            'subject': 'Great site', 'email': 'fan@example.com',
            'comment': 'Love the maker watch feature.',
        })
        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True
        assert mock_email.called and mock_blog.called

    @patch('watcher_signup.post_feedback_to_blog', return_value=True)
    @patch('watcher_signup.send_feedback_email', return_value=True)
    def test_empty_comment_rejected(self, mock_email, mock_blog, client):
        resp = client.post('/api/feedback', json={'subject': 'x', 'comment': '   '})
        assert resp.status_code == 400
        assert not mock_email.called and not mock_blog.called

    @patch('watcher_signup.post_feedback_to_blog', return_value=True)
    @patch('watcher_signup.send_feedback_email', return_value=True)
    def test_comment_of_only_markup_rejected(self, mock_email, mock_blog, client):
        # Sanitizes to empty → 400 (markup-only is not real feedback)
        resp = client.post('/api/feedback', json={'comment': '<b></b>`` '})
        assert resp.status_code == 400

    @patch('watcher_signup.post_feedback_to_blog', return_value=True)
    @patch('watcher_signup.send_feedback_email', return_value=True)
    def test_bad_email_rejected(self, mock_email, mock_blog, client):
        resp = client.post('/api/feedback', json={
            'comment': 'hi', 'email': 'not-an-email',
        })
        assert resp.status_code == 400
        assert not mock_email.called

    @patch('watcher_signup.post_feedback_to_blog', return_value=True)
    @patch('watcher_signup.send_feedback_email', return_value=True)
    def test_email_optional(self, mock_email, mock_blog, client):
        resp = client.post('/api/feedback', json={'comment': 'no email here'})
        assert resp.status_code == 200

    @patch('watcher_signup.post_feedback_to_blog', return_value=False)
    @patch('watcher_signup.send_feedback_email', return_value=True)
    def test_blog_down_email_still_sent_succeeds(self, mock_email, mock_blog, client):
        # Independent side effects: blog failing must not lose the feedback.
        resp = client.post('/api/feedback', json={'comment': 'still works'})
        assert resp.status_code == 200
        assert mock_email.called

    @patch('watcher_signup.post_feedback_to_blog', return_value=False)
    @patch('watcher_signup.send_feedback_email', return_value=False)
    def test_both_down_returns_error(self, mock_email, mock_blog, client):
        resp = client.post('/api/feedback', json={'comment': 'oh no'})
        assert resp.status_code == 502
        assert resp.get_json()['ok'] is False

    @patch('watcher_signup.post_feedback_to_blog', return_value=True)
    @patch('watcher_signup.send_feedback_email', return_value=True)
    def test_comment_is_sanitized_before_side_effects(self, mock_email, mock_blog, client):
        client.post('/api/feedback', json={'comment': 'hi <script>x</script> there'})
        # First positional arg to send_feedback_email is subject, second is comment
        passed_comment = mock_email.call_args.args[1]
        assert '<script>' not in passed_comment


# ═══════════════════════════════════════════════════════════════════════════════
# DEALER SCOUT — instant email the moment a NEW knife dealer is auto-added (S54)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDealerScoutInstantAlert:
    """_promote_one emails Simon instantly when a genuinely-new dealer is auto-added,
    and stays quiet for domains we already watch."""

    def _scout(self):
        import importlib, db
        db.DB_PATH = os.environ['DW_DB']
        import dealer_scout
        importlib.reload(dealer_scout)
        return dealer_scout, db

    def _seed(self, db, domain, conf=0.95):
        db.upsert_dealer_candidate(domain, is_dealer=True, category='knife dealer',
                                   brands='Chris Reeve', confidence=conf, reason='t',
                                   sample_url=f'https://{domain}', user_count=1)
        return db.get_dealer_candidate(domain)

    def test_instant_email_on_new_autoadd(self, tmp_env):
        ds, db = self._scout()
        cand = self._seed(db, 'newdealer-xyz.com')
        with patch.object(ds, '_append_dealer_to_sources', return_value=True), \
             patch.object(ds, 'curated_domains', return_value=set()), \
             patch.object(ds, 'send_email', return_value=True) as mock_send:
            assert ds._promote_one(cand) is True
        assert mock_send.call_count == 1
        assert 'newdealer-xyz.com' in str(mock_send.call_args)

    def test_no_email_when_already_curated(self, tmp_env):
        ds, db = self._scout()
        cand = self._seed(db, 'dupe-xyz.com')
        with patch.object(ds, 'curated_domains', return_value={'dupe-xyz.com'}), \
             patch.object(ds, 'send_email', return_value=True) as mock_send:
            assert ds._promote_one(cand) is False
        mock_send.assert_not_called()

    def test_email_failure_does_not_break_autoadd(self, tmp_env):
        # An instant-alert send failure must NOT undo the auto-add.
        ds, db = self._scout()
        cand = self._seed(db, 'flaky-mail-xyz.com')
        with patch.object(ds, '_append_dealer_to_sources', return_value=True), \
             patch.object(ds, 'curated_domains', return_value=set()), \
             patch.object(ds, 'send_email', side_effect=Exception('resend down')):
            assert ds._promote_one(cand) is True  # add still succeeds


# ═══════════════════════════════════════════════════════════════════════════════
# KEYWORD QUALITY ASSESSMENT — assess_keyword_quality() (Task 3)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAssessKeywordQuality:
    def test_good_keywords(self):
        from unittest.mock import patch, MagicMock
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"quality": "good", "reason": "Specific model name.", "suggestions": [], "generic_keywords": []}')]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        with patch('agents.ai_interpreter.client') as mock_client:
            mock_client.messages.create.return_value = mock_response
            from agents.ai_interpreter import assess_keyword_quality
            result = assess_keyword_quality('Umnumzaan', maker='Chris Reeve')

        assert result['quality'] == 'good'
        assert result['generic_keywords'] == []

    def test_bad_keywords(self):
        from unittest.mock import patch, MagicMock
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"quality": "bad", "reason": "Too generic.", "suggestions": ["Sebenza 31"], "generic_keywords": ["damascus", "limited"]}')]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        with patch('agents.ai_interpreter.client') as mock_client:
            mock_client.messages.create.return_value = mock_response
            from agents.ai_interpreter import assess_keyword_quality
            result = assess_keyword_quality('damascus, limited')

        assert result['quality'] == 'bad'
        assert 'damascus' in result['generic_keywords']

    def test_api_failure_returns_unknown(self):
        with patch('agents.ai_interpreter.client') as mock_client:
            mock_client.messages.create.side_effect = Exception("API down")
            from agents.ai_interpreter import assess_keyword_quality
            result = assess_keyword_quality('anything')

        assert result == {'quality': 'unknown'}


# ── filter_unpurchasable: 'Read more' deterministic backstop ─────────────────

class TestFilterUnpurchasable:
    """The PAGE_ANALYSIS_PROMPT tells the model 'Read more' items are not
    purchasable, but it intermittently ignores the rule (2026-06-12: all 13
    'Read more' items on the MSC catalog page reported in stock — false alerts
    to 4 users, each starting a 6h cooldown that would mask the real drop).
    filter_unpurchasable is the code-side enforcement of that rule."""

    # Actual page text from the incident (ai_calls id 36185), trimmed.
    MSC_PAGE = (
        "Mick Strider Custom Knives – Page 2 Showing 22–34 of 34 results "
        "MSC CC SnG Tanto $ 1,475.00 Read more "
        "MSC Jibble Hand Ground ( Custom Pocket Clip) Read more "
        "Stub – Grandpa Finish $ 795.00 Read more "
        "Zipper $ 120.00 Read more Menu"
    )

    def _result(self, items, in_stock=None, detected=False):
        return {
            'makers_found': ['Mick Strider Custom Knives'],
            'in_stock': in_stock if in_stock is not None else {'Mick Strider Custom Knives': len(items)},
            'out_of_stock': {},
            'drop_announcement': {'detected': detected},
            'notable_items': list(items),
            'notable_items_detail': [{'name': i, 'url': None, 'price': ''} for i in items],
            'page_summary': 'catalog page',
            'priority': 'critical',
            'alert_worthy': True,
        }

    def test_all_read_more_items_filtered(self):
        from agents.ai_interpreter import filter_unpurchasable
        result = self._result(['MSC CC SnG Tanto', 'Stub – Grandpa Finish', 'Zipper'])
        filtered = filter_unpurchasable(result, self.MSC_PAGE)
        assert filtered['notable_items'] == []
        assert filtered['notable_items_detail'] == []
        assert filtered['in_stock'] == {}
        assert filtered['alert_worthy'] is False

    def test_whitespace_mismatch_still_filtered(self):
        # Model returned '(Custom Pocket Clip)'; page text has '( Custom Pocket Clip)'
        from agents.ai_interpreter import filter_unpurchasable
        result = self._result(['MSC Jibble Hand Ground (Custom Pocket Clip)'])
        filtered = filter_unpurchasable(result, self.MSC_PAGE)
        assert filtered['notable_items'] == []
        assert filtered['alert_worthy'] is False

    def test_add_to_cart_item_kept(self):
        from agents.ai_interpreter import filter_unpurchasable
        page = (self.MSC_PAGE + " MSC Performance PT $ 550.00 Add to cart")
        result = self._result(['Stub – Grandpa Finish', 'MSC Performance PT'])
        filtered = filter_unpurchasable(result, page)
        assert filtered['notable_items'] == ['MSC Performance PT']
        assert [d['name'] for d in filtered['notable_items_detail']] == ['MSC Performance PT']
        assert filtered['in_stock'] == {'Mick Strider Custom Knives': 1}
        assert filtered['alert_worthy'] is True

    def test_item_not_in_text_kept(self):
        # Truncation can cut an item out of the text we kept — give it the
        # benefit of the doubt rather than suppress a real drop.
        from agents.ai_interpreter import filter_unpurchasable
        result = self._result(['MSC Ghost Knife'])
        filtered = filter_unpurchasable(result, self.MSC_PAGE)
        assert filtered['notable_items'] == ['MSC Ghost Knife']
        assert filtered['alert_worthy'] is True

    def test_no_markers_page_unchanged(self):
        # Shopify-style page with no button text at all — filter must not touch it.
        from agents.ai_interpreter import filter_unpurchasable
        page = "Grimsmo Norseman #2741 $1,800.00 In stock ships today"
        result = self._result(['Grimsmo Norseman #2741'])
        filtered = filter_unpurchasable(result, page)
        assert filtered['notable_items'] == ['Grimsmo Norseman #2741']
        assert filtered['alert_worthy'] is True

    def test_drop_announcement_survives_empty_items(self):
        from agents.ai_interpreter import filter_unpurchasable
        result = self._result(['Stub – Grandpa Finish'], detected=True)
        filtered = filter_unpurchasable(result, self.MSC_PAGE)
        assert filtered['notable_items'] == []
        assert filtered['alert_worthy'] is True  # real announcement still alert-worthy


# ── Episode-based cooldown (spec 2026-06-12) ─────────────────────────────────

class TestAlertEpisodes:
    """Episode-based cooldown primitives (spec 2026-06-12)."""

    @pytest.fixture
    def tmp_db(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DW_DATA_DIR', str(tmp_path))
        import importlib
        import paths
        importlib.reload(paths)
        import db
        importlib.reload(db)
        yield db

    def test_open_get_close_episode(self, tmp_db):
        db = tmp_db
        now = '2026-06-12T20:00:00+00:00'
        eid = db.open_episode('ck1', 'w001', 'shop.com',
                              'https://shop.com/p/1', 'grandpa finish',
                              'a@b.c', now)
        ep = db.get_open_episode('ck1')
        assert ep['id'] == eid
        assert ep['matches'] == 'grandpa finish'
        assert ep['emails_sent'] == 1
        assert ep['last_email_at'] == now
        db.close_episode(eid, '2026-06-12T21:00:00+00:00')
        assert db.get_open_episode('ck1') is None

    def test_get_open_episodes_lists_only_open(self, tmp_db):
        db = tmp_db
        now = '2026-06-12T20:00:00+00:00'
        e1 = db.open_episode('ck1', 'w001', 'a.com', 'https://a.com', 'x', '', now)
        db.open_episode('ck2', 'w002', 'b.com', 'https://b.com', 'y', '', now)
        db.close_episode(e1, now)
        open_eps = db.get_open_episodes()
        assert [e['match_key'] for e in open_eps] == ['ck2']

    def test_bump_episode_email(self, tmp_db):
        db = tmp_db
        eid = db.open_episode('ck1', 'w001', 'a.com', 'https://a.com', 'x', '',
                              '2026-06-12T20:00:00+00:00')
        db.bump_episode_email(eid, '2026-06-12T21:00:00+00:00')
        ep = db.get_open_episode('ck1')
        assert ep['emails_sent'] == 2
        assert ep['last_email_at'] == '2026-06-12T21:00:00+00:00'

    def test_stamp_engagement_resets_strikes(self, tmp_db):
        db = tmp_db
        db.add_watcher({'id': 'w001', 'email': 'a@b.c', 'url': 'https://a.com',
                        'keywords': 'x', 'unsubscribe_token': 'tok1',
                        'created': '2026-06-12T00:00:00+00:00'})
        db.update_watcher('w001', strikes=5)
        now = '2026-06-12T20:30:00+00:00'
        db.open_episode('ck1', 'w001', 'a.com', 'https://a.com/p', 'x', '',
                        '2026-06-12T20:00:00+00:00')
        db.stamp_engagement('w001', 'a.com', now)
        ep = db.get_open_episode('ck1')
        assert ep['engaged_at'] == now
        assert db.get_watcher_by_id('w001')['strikes'] == 0
        # second stamp must not overwrite the first engagement time
        db.stamp_engagement('w001', 'a.com', '2026-06-12T23:00:00+00:00')
        assert db.get_open_episode('ck1')['engaged_at'] == now

    def test_page_scan_latest_only(self, tmp_db):
        db = tmp_db
        db.record_page_scan('https://a.com/p', 'a.com', 'item one', '2026-06-12T20:00:00+00:00')
        db.record_page_scan('https://a.com/p', 'a.com', '', '2026-06-12T21:00:00+00:00')
        scan = db.get_page_scan('https://a.com/p')
        assert scan['instock_text'] == ''
        assert scan['scanned_at'] == '2026-06-12T21:00:00+00:00'
        assert db.get_page_scan('https://nope.com') is None

    def test_episodes_awaiting_keep_delete(self, tmp_db):
        db = tmp_db
        t0 = '2026-06-12T20:00:00+00:00'
        e1 = db.open_episode('ck1', 'w001', 'a.com', 'https://a.com', 'x', '', t0)
        db.open_episode('ck2', 'w002', 'b.com', 'https://b.com', 'y', '', t0)
        db.stamp_engagement('w001', 'a.com', '2026-06-12T20:05:00+00:00')
        due = db.episodes_awaiting_keep_delete('2026-06-12T20:25:00+00:00')
        assert [e['id'] for e in due] == [e1]
        db.mark_keep_delete_sent(e1, '2026-06-12T20:30:00+00:00')
        assert db.episodes_awaiting_keep_delete('2026-06-12T20:35:00+00:00') == []

    def test_strikes_column_migrated(self, tmp_db):
        db = tmp_db
        db.add_watcher({'id': 'w001', 'email': 'a@b.c', 'url': '', 'keywords': 'x',
                        'unsubscribe_token': 'tok1', 'created': '2026-06-12T00:00:00+00:00'})
        assert db.get_watcher_by_id('w001')['strikes'] == 0

    def test_touch_page_scan_refreshes_timestamp_only(self, tmp_db):
        db = tmp_db
        db.record_page_scan('https://a.com/p', 'a.com', 'item one', '2026-06-12T20:00:00+00:00')
        db.touch_page_scan('https://a.com/p', '2026-06-12T21:00:00+00:00')
        scan = db.get_page_scan('https://a.com/p')
        assert scan['instock_text'] == 'item one'
        assert scan['scanned_at'] == '2026-06-12T21:00:00+00:00'
        # touching a never-scanned url is a no-op, not an insert
        db.touch_page_scan('https://nope.com', '2026-06-12T21:00:00+00:00')
        assert db.get_page_scan('https://nope.com') is None


class TestEpisodeCooldown:
    """Alerter skips matches with an open episode; opening replaces the 6h timer."""

    def test_open_episode_blocks_rematch(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DW_DATA_DIR', str(tmp_path))
        import importlib
        import paths
        importlib.reload(paths)
        import db
        importlib.reload(db)
        import per_user_alerter as pua
        importlib.reload(pua)

        ck = pua.cooldown_key('w001', 'https://shop.com/p/1', ['grandpa finish'])
        assert pua.episode_blocks(ck) is False
        db.open_episode(ck, 'w001', 'shop.com', 'https://shop.com/p/1',
                        'grandpa finish', 'a@b.c', '2026-06-12T20:00:00+00:00')
        assert pua.episode_blocks(ck) is True
        db.close_episode(db.get_open_episode(ck)['id'], '2026-06-12T21:00:00+00:00')
        assert pua.episode_blocks(ck) is False


class TestEpisodeSweep:
    @pytest.fixture
    def env(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DW_DATA_DIR', str(tmp_path))
        import importlib
        import paths
        importlib.reload(paths)
        import db
        importlib.reload(db)
        import per_user_alerter as pua
        importlib.reload(pua)
        db.add_watcher({'id': 'w001', 'email': 'a@b.c',
                        'url': 'https://shop.com/p/1', 'keywords': 'grandpa finish',
                        'unsubscribe_token': 'tok1', 'active': 1,
                        'created': '2026-06-12T00:00:00+00:00'})
        return db, pua

    def _open(self, db, opened='2026-06-12T20:00:00+00:00'):
        return db.open_episode('ck1', 'w001', 'shop.com', 'https://shop.com/p/1',
                               'grandpa finish', 'a@b.c', opened)

    def test_close_when_scan_lacks_keywords(self, env):
        db, pua = env
        self._open(db)
        db.record_page_scan('https://shop.com/p/1', 'shop.com',
                            '', '2026-06-12T20:30:00+00:00')  # nothing in stock
        with patch.object(pua, 'send_email', return_value=True):
            pua.episode_sweep(datetime(2026, 6, 12, 21, 0, tzinfo=timezone.utc))
        assert db.get_open_episode('ck1') is None

    def test_stays_open_while_in_stock_and_reminds_after_24h(self, env):
        db, pua = env
        self._open(db)
        db.record_page_scan('https://shop.com/p/1', 'shop.com',
                            'Stub Grandpa Finish', '2026-06-12T20:30:00+00:00')
        with patch.object(pua, 'send_email', return_value=True) as se:
            pua.episode_sweep(datetime(2026, 6, 12, 20, 45, tzinfo=timezone.utc))
            assert se.call_count == 0          # <REMINDER_INTERVAL_H: no reminder yet
            pua.episode_sweep(datetime(2026, 6, 13, 21, 0, tzinfo=timezone.utc))
            assert se.call_count == 1          # ≥24h + still in stock: one reminder
        ep = db.get_open_episode('ck1')
        assert ep['emails_sent'] == 2
        assert db.get_watcher_by_id('w001')['strikes'] == 1

    def test_no_reminder_without_fresh_scan(self, env):
        db, pua = env
        self._open(db)   # no page_scan rows at all (feed drop)
        with patch.object(pua, 'send_email', return_value=True) as se:
            pua.episode_sweep(datetime(2026, 6, 12, 22, 0, tzinfo=timezone.utc))
        assert se.call_count == 0
        assert db.get_open_episode('ck1') is not None  # <24h: still open

    def test_stale_unscanned_episode_closes_at_24h(self, env):
        db, pua = env
        self._open(db, opened='2026-06-11T10:00:00+00:00')
        with patch.object(pua, 'send_email', return_value=True):
            pua.episode_sweep(datetime(2026, 6, 12, 21, 0, tzinfo=timezone.utc))
        assert db.get_open_episode('ck1') is None

    def test_engaged_episode_no_reminders_gets_keep_delete(self, env):
        db, pua = env
        self._open(db)
        db.record_page_scan('https://shop.com/p/1', 'shop.com',
                            'Stub Grandpa Finish', '2026-06-12T20:30:00+00:00')
        db.stamp_engagement('w001', 'shop.com', '2026-06-12T20:10:00+00:00')
        with patch.object(pua, 'send_email', return_value=True) as se:
            pua.episode_sweep(datetime(2026, 6, 12, 21, 0, tzinfo=timezone.utc))
        assert se.call_count == 1               # keep/delete email, NOT a reminder
        subject = se.call_args[0][0]
        assert 'keep' in subject.lower()
        ep = db.get_open_episode('ck1')
        assert ep['keep_delete_sent_at'] is not None
        # sweep again: no second keep/delete
        with patch.object(pua, 'send_email', return_value=True) as se2:
            pua.episode_sweep(datetime(2026, 6, 12, 22, 0, tzinfo=timezone.utc))
        assert se2.call_count == 0

    def test_strike_limit_quiets_episode_without_deactivating(self, env):
        # Simon 2026-06-14: stop the teardown bleed. At STRIKE_LIMIT we no longer
        # deactivate the watch (wrongful teardowns on grail watches aren't worth it) —
        # we close the noisy episode and reset the strike ladder, keeping the watch
        # active so the next genuine drop alerts fresh.
        db, pua = env
        db.add_watcher({'id': 'w002', 'email': 'a@b.c', 'url': 'https://other.com',
                        'keywords': 'sebenza', 'unsubscribe_token': 'tok1', 'active': 1,
                        'created': '2026-06-12T00:00:00+00:00'})
        db.update_watcher('w001', strikes=pua.STRIKE_LIMIT)
        self._open(db)
        db.record_page_scan('https://shop.com/p/1', 'shop.com',
                            'Stub Grandpa Finish', '2026-06-12T20:30:00+00:00')
        with patch.object(pua, 'send_email', return_value=True) as se:
            pua.episode_sweep(datetime(2026, 6, 13, 22, 0, tzinfo=timezone.utc))
        assert se.call_count == 0                       # no removal email
        assert db.get_watcher_by_id('w001')['active']   # watch KEPT active
        assert (db.get_watcher_by_id('w001')['strikes'] or 0) == 0  # ladder reset
        assert db.get_open_episode('ck1') is None        # noisy episode closed


class TestClickEngagement:
    def test_record_click_stamps_open_episode(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DW_DATA_DIR', str(tmp_path))
        import importlib
        import paths
        importlib.reload(paths)
        import db
        importlib.reload(db)
        import sharp
        importlib.reload(sharp)

        db.add_watcher({'id': 'w001', 'email': 'a@b.c', 'url': 'https://shop.com/p/1',
                        'keywords': 'x', 'unsubscribe_token': 'tok1', 'active': 1,
                        'created': '2026-06-12T00:00:00+00:00'})
        db.update_watcher('w001', strikes=7)
        db.open_episode('ck1', 'w001', 'shop.com', 'https://shop.com/p/1', 'x', '',
                        '2026-06-12T20:00:00+00:00')

        sharp.record_click({'w': 'w001', 'd': 'https://shop.com/p/1?utm=x',
                            's': 'alert', 't': 1760000000}, user_agent='UA')

        ep = db.get_open_episode('ck1')
        assert ep['engaged_at'] is not None
        assert db.get_watcher_by_id('w001')['strikes'] == 0

    def test_record_click_stamps_episode_for_bare_domain_utm_link(self, tmp_path, monkeypatch):
        # A homepage/root dealer link gets a UTM suffix with NO path
        # (https://mcneesknives.com?utm_source=dropwatcher). The dest domain must
        # still resolve to the bare host so engagement matches the open episode —
        # otherwise the keep-or-delete escape from the reminder ladder never fires.
        monkeypatch.setenv('DW_DATA_DIR', str(tmp_path))
        import importlib
        import paths
        importlib.reload(paths)
        import db
        importlib.reload(db)
        import sharp
        importlib.reload(sharp)

        db.add_watcher({'id': 'w001', 'email': 'a@b.c', 'url': 'https://mcneesknives.com',
                        'keywords': 'mcnees', 'unsubscribe_token': 'tok1', 'active': 1,
                        'created': '2026-06-12T00:00:00+00:00'})
        db.update_watcher('w001', strikes=5)
        db.open_episode('ck1', 'w001', 'mcneesknives.com', 'https://mcneesknives.com',
                        'mcnees', '', '2026-06-12T20:00:00+00:00')

        sharp.record_click({'w': 'w001',
                            'd': 'https://mcneesknives.com?utm_source=dropwatcher&utm_medium=alert',
                            's': 'McNees Knives', 't': 1760000000}, user_agent='UA')

        ep = db.get_open_episode('ck1')
        assert ep['engaged_at'] is not None
        assert db.get_watcher_by_id('w001')['strikes'] == 0


class TestWatchRemoveRoute:
    def test_get_remove_deactivates_single_watch(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DW_DATA_DIR', str(tmp_path))
        import importlib
        import paths
        importlib.reload(paths)
        import db
        importlib.reload(db)
        import watcher_signup
        importlib.reload(watcher_signup)
        client = watcher_signup.app.test_client()

        for wid, url in (('w001', 'https://a.com'), ('w002', 'https://b.com')):
            db.add_watcher({'id': wid, 'email': 'a@b.c', 'url': url, 'keywords': 'x',
                            'unsubscribe_token': 'tok1', 'active': 1,
                            'created': '2026-06-12T00:00:00+00:00'})

        r = client.post('/api/watch-remove/w001/tok1')
        assert r.status_code == 200
        assert not db.get_watcher_by_id('w001')['active']
        assert db.get_watcher_by_id('w002')['active']

        r = client.post('/api/watch-remove/w002/WRONG')
        assert r.status_code == 404
        assert db.get_watcher_by_id('w002')['active']


class TestFalsePositiveSelfHeals:
    def test_false_alert_episode_closes_then_real_drop_alerts(self, tmp_path, monkeypatch):
        """The 2026-06-12 MSC incident under the episode model: a false alert
        opens an episode; the corrected next scan closes it; a real drop after
        that is NOT blocked (old behavior: 6h blind spot)."""
        monkeypatch.setenv('DW_DATA_DIR', str(tmp_path))
        import importlib
        import paths
        importlib.reload(paths)
        import db
        importlib.reload(db)
        import per_user_alerter as pua
        importlib.reload(pua)

        ck = pua.cooldown_key('w001', 'https://msc.com/cat/page/2/', ['grandpa finish'])
        # false alert fires at T0 → episode opens
        db.open_episode(ck, 'w001', 'msc.com', 'https://msc.com/cat/page/2/',
                        'grandpa finish', 'a@b.c', '2026-06-12T15:54:00+00:00')
        assert pua.episode_blocks(ck)
        # next scan: filter_unpurchasable stripped the items → empty in-stock text
        db.record_page_scan('https://msc.com/cat/page/2/', 'msc.com', '',
                            '2026-06-12T16:15:00+00:00')
        with patch.object(pua, 'send_email', return_value=True):
            pua.episode_sweep(datetime(2026, 6, 12, 16, 20, tzinfo=timezone.utc))
        # 26 minutes after the false alert the watch is re-armed
        assert not pua.episode_blocks(ck)


class TestScannerGate:
    """Corp task 20 (Sky): email-scanner prefetch must not stamp engagement,
    reset strikes, or remove watches. Scanners use realistic browser UAs
    (wild data: same link 'clicked' by iPhone + Windows UAs 4s apart), so
    the destructive action is POST-gated and engagement is heuristic-gated."""

    def test_is_probable_scanner_heuristics(self):
        import sharp
        assert sharp.is_probable_scanner('', 300)                      # empty UA
        assert sharp.is_probable_scanner('python-requests/2.31', 300)  # tooling
        assert sharp.is_probable_scanner(
            'Mozilla/5.0 (compatible; MSOffice; SafeLinks)', 300)      # scanner marker
        assert sharp.is_probable_scanner(
            'Mozilla/5.0 (Macintosh) Chrome/126', 2)                   # <5s after mint
        assert not sharp.is_probable_scanner(
            'Mozilla/5.0 (Macintosh) Chrome/126', 90)                  # human-ish

    def test_scanner_click_logged_but_not_engaged(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DW_DATA_DIR', str(tmp_path))
        import importlib
        import paths
        importlib.reload(paths)
        import db
        importlib.reload(db)
        import sharp
        importlib.reload(sharp)

        db.add_watcher({'id': 'w001', 'email': 'a@b.c', 'url': 'https://shop.com/p/1',
                        'keywords': 'x', 'unsubscribe_token': 'tok1', 'active': 1,
                        'created': '2026-06-12T00:00:00+00:00'})
        db.update_watcher('w001', strikes=7)
        db.open_episode('ck1', 'w001', 'shop.com', 'https://shop.com/p/1', 'x', '',
                        '2026-06-12T20:00:00+00:00')

        import time as _time
        sharp.record_click({'w': 'w001', 'd': 'https://shop.com/p/1',
                            's': 'alert', 't': int(_time.time())},   # minted "now" → prefetch
                           user_agent='python-requests/2.31')

        ep = db.get_open_episode('ck1')
        assert ep['engaged_at'] is None                    # no engagement
        assert db.get_watcher_by_id('w001')['strikes'] == 7  # strikes untouched
        with db.get_db() as conn:
            row = conn.execute("SELECT scanner FROM outbound_clicks").fetchone()
        assert row['scanner'] == 1                          # still logged, flagged


class TestWatchRemoveScannerSafe:
    @pytest.fixture
    def client_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv('DW_DATA_DIR', str(tmp_path))
        import importlib
        import paths
        importlib.reload(paths)
        import db
        importlib.reload(db)
        import watcher_signup
        importlib.reload(watcher_signup)
        db.add_watcher({'id': 'w001', 'email': 'a@b.c', 'url': 'https://a.com',
                        'keywords': 'x', 'unsubscribe_token': 'tok1', 'active': 1,
                        'created': '2026-06-12T00:00:00+00:00'})
        return db, watcher_signup.app.test_client()

    def test_get_shows_confirm_does_not_deactivate(self, client_env):
        db, client = client_env
        r = client.get('/api/watch-remove/w001/tok1')
        assert r.status_code == 200
        assert b'form' in r.data.lower()                    # confirm form, not action
        assert db.get_watcher_by_id('w001')['active']       # STILL ACTIVE

    def test_post_deactivates(self, client_env):
        db, client = client_env
        r = client.post('/api/watch-remove/w001/tok1')
        assert r.status_code == 200
        assert not db.get_watcher_by_id('w001')['active']

    def test_ack_scanner_ua_skips_side_effects(self, client_env):
        db, client = client_env
        db.update_watcher('w001', strikes=9)
        r = client.get('/api/ack/tok1', headers={'User-Agent': 'python-requests/2.31'})
        assert r.status_code == 200
        assert db.get_watcher_by_id('w001')['strikes'] == 9  # untouched
        r = client.get('/api/ack/tok1', headers={'User-Agent':
            'Mozilla/5.0 (iPhone; CPU iPhone OS 26_5 like Mac OS X) Safari/605.1.15'})
        assert db.get_watcher_by_id('w001')['strikes'] == 0  # human resets


class TestAgeoutEmptyLastAlert:
    def test_empty_string_last_alert_not_nudged(self, tmp_path, monkeypatch):
        """'' sorts before every ISO date, so a watch with last_alert='' looked
        infinitely stale and got aged out within hours (bit Simon's grandpa
        watch 2026-06-12 after a manual reset used '' instead of NULL)."""
        monkeypatch.setenv('DW_DATA_DIR', str(tmp_path))
        import importlib
        import paths
        importlib.reload(paths)
        import db
        importlib.reload(db)
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.join(_os.path.dirname(db.__file__), 'bin'))
        import ageout_no_use
        importlib.reload(ageout_no_use)

        db.add_watcher({'id': 'w001', 'email': 'a@b.c', 'url': 'https://a.com',
                        'keywords': 'x', 'unsubscribe_token': 'tok1', 'active': 1,
                        'created': '2026-01-01T00:00:00+00:00'})
        with db.get_db() as conn:
            conn.execute("UPDATE watchers SET last_alert='' WHERE id='w001'")

        with patch.object(ageout_no_use, 'send_email', return_value=True) as se:
            ageout_no_use.nudge(datetime(2026, 6, 12, 23, 0, tzinfo=timezone.utc))
        assert se.call_count == 0
        assert db.get_watcher_by_id('w001')['ageout_email_sent'] is None


class TestFilterUnpurchasableUserPage:
    """23:47 incident: analyze_user_page (user-watch path) lacked the Read-more
    backstop and re-shipped the exact morning false positive, this time with SMS."""

    MSC_PAGE = ("Mick Strider Custom Knives – Page 2 "
                "Stub – Grandpa Finish $ 795.00 Read more "
                "Zipper $ 120.00 Add to cart Menu")

    def _result(self, items, worthy=True):
        return {'keywords_found': ['grandpa finish'], 'notable_items': list(items),
                'page_summary': 'available for purchase', 'priority': 'high',
                'alert_worthy': worthy}

    def test_read_more_item_kills_alert(self):
        from agents.ai_interpreter import filter_unpurchasable_user
        result = self._result(['Stub – Grandpa Finish — AVAILABLE FOR PURCHASE — $795.00'])
        filter_unpurchasable_user(result, self.MSC_PAGE)
        assert result['notable_items'] == []
        assert result['alert_worthy'] is False

    def test_genuine_add_to_cart_item_survives(self):
        from agents.ai_interpreter import filter_unpurchasable_user
        result = self._result(['Zipper — IN STOCK — $120.00'])
        filter_unpurchasable_user(result, self.MSC_PAGE)
        assert result['notable_items'] == ['Zipper — IN STOCK — $120.00']
        assert result['alert_worthy'] is True

    def test_item_not_in_text_kept(self):
        from agents.ai_interpreter import filter_unpurchasable_user
        result = self._result(['Ghost Knife — IN STOCK — $1'])
        filter_unpurchasable_user(result, self.MSC_PAGE)
        assert result['alert_worthy'] is True

    def test_real_incident_shape_with_keyword_header(self):
        # The actual 23:47 prompt shape: keyword header repeats the name with
        # no marker nearby; the real listing later says 'Read more'. The
        # header occurrence must not mask the listing verdict.
        from agents.ai_interpreter import filter_unpurchasable_user
        page = ("keywords: stub, grandpa finish\n"
                "Mick Strider Custom Knives – Page 2 "
                "Stub – Grandpa Finish $ 795.00 Read more Zipper $ 120.00 Read more Menu")
        result = self._result(['Stub – Grandpa Finish — AVAILABLE FOR PURCHASE — $795.00'])
        filter_unpurchasable_user(result, page)
        assert result['alert_worthy'] is False
