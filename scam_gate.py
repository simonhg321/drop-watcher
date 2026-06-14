"""scam_gate.py — gate a candidate dealer at add-time. Fetch its catalog once,
score it with scam_source_filter, and return a Verdict. Used only by
dealer_scout._promote_one — never on the per-scan path."""
import logging
from urllib.parse import urlparse

import collection_fetch
import scam_source_filter
from scam_source_filter import Product, Verdict

log = logging.getLogger(__name__)

ALERT_EMAILS = ['simonhg@gmail.com', 'simon@instockornot.club']


def _to_float(v):
    try:
        return float(v) if v not in (None, '', '0', 0) else None
    except (TypeError, ValueError):
        return None


def to_products(records):
    out = []
    for r in records or []:
        out.append(Product(
            title=r.get('title', ''),
            original_price=_to_float(r.get('original_price')),
            sale_price=_to_float(r.get('price')),
            image_urls=list(r.get('image_urls') or []),
        ))
    return out


def _fetch_records(sample_url, fetch_page, log=None):
    """Fetch the candidate's catalog as structured records (Shopify/JSON-LD/card)."""
    _text, products, _cand = collection_fetch.fetch_collection(sample_url, fetch_page, log=log)
    return products or []


def evaluate(domain, sample_url, fetch_page, log=None):
    """Return a Verdict for a candidate dealer. ingest|review|quarantine.
    Fetch failure / empty catalog → ingest (fail-open: don't block a dealer on a
    transient fetch error; a real scam catalog scores high once actually fetched)."""
    records = _fetch_records(sample_url, fetch_page, log=log)
    if not records:
        return Verdict(action="ingest", score=0, reasons=["no records fetched (fail-open)"])
    return scam_source_filter.score_source(domain, to_products(records))


def notify_operator(domain, sample_url, verdict, send_email):
    subject = f"[SCAM GATE] blocked {domain} — {verdict.action} (score {verdict.score})"
    reasons = "\n".join(f"  - {r}" for r in verdict.reasons)
    body = (f"dealer_scout tried to add a source that the scam filter flagged.\n\n"
            f"Domain:  {domain}\nURL:     {sample_url}\n"
            f"Action:  {verdict.action}\nScore:   {verdict.score}\n\nReasons:\n{reasons}\n\n"
            f"It was NOT added to sources.yaml. If this is a false positive (e.g. a real "
            f"storewide sale), add the domain manually with: dealer_scout.py --approve {domain}")
    html = body.replace("\n", "<br>")
    for addr in ALERT_EMAILS:
        try:
            send_email(subject, html, body, to_addr=addr)
        except Exception as e:
            log.error(f"scam_gate: operator notify failed for {addr}: {e}")
