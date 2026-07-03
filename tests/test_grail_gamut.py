"""CRK grail gamut roster (S70) — the S+A tiers of Simon's CRK_grail_gamut.csv
folded into lunar_hunter.GRAILS as curated entries.

Covers: the new entries exist and match with the established scoped/unscoped
rules; specific entries outrank generic ones in roster order (the scan loop
stops at the first grail a product hits); the new entries carry NO ebay_query
(Sky owns eBay) and scan_ebay skips them; est_market shows in the alert email;
and the alert filter keeps LISTED (in_stock=None) finds while dropping
confirmed SOLD OUT ones."""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def lh(tmp_path, monkeypatch):
    monkeypatch.setenv('DW_LOG_DIR', str(tmp_path))
    import importlib
    import paths
    importlib.reload(paths)
    import lunar_hunter as _lh
    importlib.reload(_lh)
    return _lh


def _g(lh, key):
    return next(g for g in lh.GRAILS if g['key'] == key)


NEW_KEYS = ['jereboam', 'shadow_op', 'project', 'mk_series', 'aviator', 'sable',
            'd2_run', 'original_sebenza', 'regular_sebenza', 'sebenza_25',
            'unique_graphic', 'damascus', 'mammoth', 'ti_lock', 'impofu',
            'anniversary_21', 'prototype']


class TestRoster:
    def test_gamut_entries_present(self, lh):
        keys = [g['key'] for g in lh.GRAILS]
        for k in NEW_KEYS:
            assert k in keys, f"missing grail {k}"
        # The original pair still leads the roster (seen-state + email defaults).
        assert keys[0] == 'lunar' and keys[1] == 'crosshatch'

    def test_every_entry_has_display_fields(self, lh):
        for g in lh.GRAILS:
            assert g['display'] and g['emoji'] and g['subtitle']

    def test_new_entries_carry_est_market(self, lh):
        for k in NEW_KEYS:
            assert _g(lh, k).get('est_market'), f"{k} missing est_market"

    def test_specific_entries_before_generic(self, lh):
        keys = [g['key'] for g in lh.GRAILS]
        # A "Sebenza 25 Damascus" must resolve to the 25 (scarcer window),
        # an "Original Sebenza" must not be swallowed by regular_sebenza,
        # and prototype/d2 are catch-alls that go last.
        assert keys.index('sebenza_25') < keys.index('damascus')
        assert keys.index('original_sebenza') < keys.index('regular_sebenza')
        assert keys.index('regular_sebenza') < keys.index('damascus')
        assert keys.index('damascus') < keys.index('prototype')
        assert keys.index('damascus') < keys.index('d2_run')


class TestMatching:
    def test_jereboam(self, lh):
        g = _g(lh, 'jereboam')
        assert lh._grail_match(g, 'Jereboam MK II 9in clip point', scoped=True)
        # CRK spells it Jereboam (the wine bottle is jeroboam) → exact, fires anywhere
        assert lh._grail_match(g, 'wts jereboam sawback, serialized', scoped=False)

    def test_shadow_needs_reeve_context_unscoped(self, lh):
        g = _g(lh, 'shadow_op')
        assert lh._grail_match(g, 'Shadow I spearpoint', scoped=True)
        assert not lh._grail_match(g, 'crkt shadow folding knife', scoped=False)
        assert lh._grail_match(g, 'chris reeve shadow iv one piece', scoped=False)

    def test_sebenza_25_not_31(self, lh):
        g = _g(lh, 'sebenza_25')
        assert lh._grail_match(g, 'Large Sebenza 25 Micarta Inlay', scoped=True)
        assert not lh._grail_match(g, 'Small Sebenza 31 Tanto Box Elder', scoped=True)

    def test_regular_sebenza_variants(self, lh):
        g = _g(lh, 'regular_sebenza')
        assert lh._grail_match(g, 'Regular Sebenza large BG-42', scoped=True)
        assert not lh._grail_match(g, 'Sebenza 21 plain S35VN', scoped=True)

    def test_mk_series_word_boundaries(self, lh):
        g = _g(lh, 'mk_series')
        assert lh._grail_match(g, 'chris reeve mk iv sawback', scoped=False)
        # "mk vi" must not fire from inside "mk vii"-style tokens or bare "mk"
        assert not lh._grail_match(g, 'chris reeve mkultra thing', scoped=False)

    def test_damascus_context_gated(self, lh):
        g = _g(lh, 'damascus')
        assert lh._grail_match(g, 'Sebenza 21 Damascus ladder', scoped=False)
        assert not lh._grail_match(g, 'benchmade gold class damascus', scoped=False)
        # Current-production Damascus 31s/Inkosis are catalog stock, not grails.
        assert not lh._grail_match(
            g, 'Large Sebenza 31 Drop Point Boomerang Damascus', scoped=True)
        assert not lh._grail_match(g, 'Inkosi Raindrop Damascus', scoped=True)

    def test_prototype_scoped(self, lh):
        g = _g(lh, 'prototype')
        assert lh._grail_match(g, 'shop prototype umnumzaan, shop-marked', scoped=True)
        assert not lh._grail_match(g, 'spyderco prototype paramilitary', scoped=False)

    def test_unique_graphic_vetoes_current_production(self, lh):
        # CRK's CURRENT catalog sells "Night Sky Unique Graphic" Sebenza 31s —
        # 212 of them matched at KnifeJoy on the first live check. The grail is
        # the one-of-one hand graphics, so current-production terms veto.
        g = _g(lh, 'unique_graphic')
        assert not lh._grail_match(
            g, 'Chris Reeve Knives Large Sebenza 31 Magnacut Night Sky Unique Graphic',
            scoped=True)
        assert lh._grail_match(g, 'Sebenza 21 Unique Graphic tao one of a kind', scoped=True)
        assert lh._grail_match(g, 'crk regular sebenza cgg cabernet', scoped=False)

    def test_ti_lock_spellings(self, lh):
        g = _g(lh, 'ti_lock')
        for t in ('ti-lock hawk collab', 'ti lock', 'tilock'):
            assert lh._grail_match(g, t, scoped=True), t


class TestEbayExcluded:
    def test_new_entries_have_no_ebay_query(self, lh):
        for k in NEW_KEYS:
            assert not _g(lh, k).get('ebay_query'), f"{k} must not carry an ebay_query (Sky owns eBay)"

    def test_scan_ebay_skips_queryless_grails(self, lh, monkeypatch):
        monkeypatch.setenv('DW_EBAY_CLIENT_ID', 'x')
        monkeypatch.setenv('DW_EBAY_CLIENT_SECRET', 'y')
        monkeypatch.setattr(lh, '_ebay_token', lambda *a: 'tok')
        queries = []
        monkeypatch.setattr(lh, '_ebay_search', lambda tok, q: queries.append(q) or [])
        lh.scan_ebay()
        assert queries == ['chris reeve lunar landing', 'chris reeve cross hatch']


class TestAlerting:
    def _find(self, lh, key, in_stock, price=''):
        return {'source': 'KnifeJoy', 'title': 'x', 'url': 'https://x/y',
                'in_stock': in_stock, 'price': price, 'deep': True,
                'grail': _g(lh, key)}

    def test_est_market_in_email(self, lh):
        g = _g(lh, 'jereboam')
        _, html, txt = lh.build_find_email([self._find(lh, 'jereboam', True, '1200')], g)
        assert g['est_market'] in html
        assert g['est_market'] in txt

    def test_alert_filter_keeps_listed_drops_sold_out(self, lh):
        items = [(self._find(lh, 'jereboam', True), 'k1'),
                 (self._find(lh, 'jereboam', None), 'k2'),   # Reddit/text-scan LISTED
                 (self._find(lh, 'jereboam', False), 'k3')]
        kept = lh._alertable(items)
        assert [k for _, k in kept] == ['k1', 'k2']
