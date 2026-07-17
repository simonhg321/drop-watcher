#!/usr/bin/env python3
"""
test_no_user_alerts.py — per-source user-alert suppression (user_alerts: false)

A source like chrisreeve.com is polled for intel (grail traffic) but the maker
does not ship direct — users must never receive alerts deep-linking there.
Run: python3 -m pytest tests/test_no_user_alerts.py -v
HGR
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestLoadNoUserAlertDomains:

    def test_flagged_source_domain_collected(self, tmp_path):
        from per_user_alerter import load_no_user_alert_domains
        yml = tmp_path / 'sources.yaml'
        yml.write_text(
            "websites:\n"
            "  - name: Chris Reeve Knives\n"
            "    url: https://www.chrisreeve.com\n"
            "    enabled: true\n"
            "    user_alerts: false\n"
            "  - name: KnifeJoy\n"
            "    url: https://knifejoy.com\n"
            "    enabled: true\n"
        )
        assert load_no_user_alert_domains(str(yml)) == {'chrisreeve.com'}

    def test_missing_file_returns_failsafe(self, tmp_path):
        # Loader must never take down the alerter over a config problem, but a
        # load failure returns the FAILSAFE set, not empty — a broken sources.yaml
        # must not silently disable the critical suppression (Corp directive 181).
        from per_user_alerter import load_no_user_alert_domains, FAILSAFE_NO_USER_ALERT_DOMAINS
        assert load_no_user_alert_domains(str(tmp_path / 'nope.yaml')) == FAILSAFE_NO_USER_ALERT_DOMAINS

    def test_production_config_suppresses_chrisreeve(self):
        # The actual sources.yaml must carry the flag — CRK does not ship direct
        from per_user_alerter import load_no_user_alert_domains
        assert 'chrisreeve.com' in load_no_user_alert_domains()


class TestSuppressedDomainNeverMatches:

    def test_url_watch_on_suppressed_domain_no_match(self, monkeypatch):
        import per_user_alerter as pua
        monkeypatch.setattr(pua, 'NO_USER_ALERT_DOMAINS', {'chrisreeve.com'})
        w = {'id': 'u1', 'url': 'https://www.chrisreeve.com', 'maker': '',
             'keywords': 'sebenza'}
        drop = {'source': 'Chris Reeve Knives', 'url': 'https://www.chrisreeve.com',
                'page_summary': 'New sebenza 31 in stock', 'notable_items': []}
        assert pua.matches_for_watcher_drop(w, drop) == []

    def test_global_watch_skips_suppressed_domain(self, monkeypatch):
        import per_user_alerter as pua
        monkeypatch.setattr(pua, 'NO_USER_ALERT_DOMAINS', {'chrisreeve.com'})
        w = {'id': 'g1', 'url': '', 'maker': 'Chris Reeve Knives',
             'keywords': 'sebenza'}
        drop = {'source': 'Chris Reeve Knives', 'url': 'https://www.chrisreeve.com/x',
                'page_summary': 'chris reeve sebenza drop', 'notable_items': []}
        assert pua.matches_for_watcher_drop(w, drop) == []

    def test_other_domains_unaffected(self, monkeypatch):
        import per_user_alerter as pua
        monkeypatch.setattr(pua, 'NO_USER_ALERT_DOMAINS', {'chrisreeve.com'})
        w = {'id': 'g1', 'url': '', 'maker': 'Chris Reeve Knives',
             'keywords': 'sebenza'}
        drop = {'source': 'DLT Trading — CRK', 'url': 'https://www.dlttrading.com/crk',
                'page_summary': 'chris reeve sebenza 31 restock', 'notable_items': []}
        assert pua.matches_for_watcher_drop(w, drop) == ['sebenza']
