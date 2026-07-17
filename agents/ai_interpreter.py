# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
ai_interpreter.py
Drop Watcher — AI Interpretation Layer
Two modes:
  1. Curated analysis (analyze_page) — knife/EDC expert prompt with maker priority rules
  2. User watch analysis (analyze_user_page) — generic stock-status prompt for any product/URL
Uses Claude Haiku for all analysis.
HGR
"""

import os
import re
import json
import logging
import yaml
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv
import anthropic
from pydantic import BaseModel, Field, field_validator


# ── Error classes ────────────────────────────────────────────────────────────
class AIError(Exception):
    """Base for all AI interpreter failures."""
    def __init__(self, message, site=None, url=None, raw=None):
        self.site = site
        self.url = url
        self.raw = raw
        super().__init__(message)

class AIParseError(AIError):
    """Haiku returned text that isn't valid JSON."""

class AISchemaError(AIError):
    """Haiku returned valid JSON that doesn't match the expected schema."""

class AIEmptyResponseError(AIError):
    """Haiku returned no text content."""

class AIRateLimitError(AIError):
    """Hit Anthropic rate limit."""

class AIOverloadError(AIError):
    """Anthropic API overloaded."""


# ── Pydantic response schemas ───────────────────────────────────────────────
class DropAnnouncement(BaseModel):
    detected: bool = False
    maker: Optional[str] = None
    description: Optional[str] = None
    timing: Optional[str] = None
    confidence: str = 'low'

class NotableItemDetail(BaseModel):
    name: str
    url: Optional[str] = None
    price: str = ''

    @field_validator('name', 'price', mode='before')
    @classmethod
    def null_to_empty(cls, v):
        # The AI sometimes emits null for a missing field; one null must not
        # invalidate the entire page analysis (S60: lost scans).
        return '' if v is None else v

class PageAnalysis(BaseModel):
    makers_found: list[str] = Field(default_factory=list)
    in_stock: dict[str, int] = Field(default_factory=dict)
    out_of_stock: dict[str, int] = Field(default_factory=dict)
    drop_announcement: DropAnnouncement = Field(default_factory=DropAnnouncement)
    notable_items: list[str] = Field(default_factory=list)
    notable_items_detail: list[NotableItemDetail] = Field(default_factory=list)
    page_summary: str = ''
    priority: str = 'medium'
    alert_worthy: bool = False

    @field_validator('priority')
    @classmethod
    def valid_priority(cls, v):
        if v not in ('critical', 'high', 'medium', 'low'):
            return 'medium'
        return v

class DropAnnouncementAnalysis(BaseModel):
    is_real_drop: bool = False
    maker: Optional[str] = None
    what: str = ''
    when: Optional[str] = None
    where: str = ''
    confidence: str = 'low'
    raw_quote: str = ''

class DealerClassification(BaseModel):
    is_dealer: bool = False
    category: str = ''
    brands: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    reason: str = ''

class UserPageAnalysis(BaseModel):
    keywords_found: list[str] = Field(default_factory=list)
    notable_items: list[str] = Field(default_factory=list)
    page_summary: str = ''
    priority: str = 'medium'
    alert_worthy: bool = False

    @field_validator('priority')
    @classmethod
    def valid_priority(cls, v):
        if v not in ('critical', 'high', 'medium', 'low'):
            return 'medium'
        return v

class KeywordQualityAssessment(BaseModel):
    quality: str = 'unknown'
    reason: str = ''
    suggestions: list[str] = Field(default_factory=list)
    generic_keywords: list[str] = Field(default_factory=list)
    corrected_keywords: list[str] = Field(default_factory=list)

    @field_validator('quality')
    @classmethod
    def valid_quality(cls, v):
        if v not in ('good', 'needs_work', 'bad', 'unknown'):
            return 'needs_work'
        return v

KEYWORD_QUALITY_PROMPT = """You are a knife and EDC expert helping a user set up in-stock alerts.

The user wants to be alerted when these keywords appear on dealer pages:
  Keywords: {keywords}
  Maker: {maker}

Rate the keyword quality and suggest improvements.

Rules:
- Good keywords are specific product names or models: "Sebenza 31", "Umnumzaan", "Norseman", "SMF", "Inkosi Insingo"
- Bad keywords are generic material/finish/category terms that appear on almost every knife page: "damascus", "titanium", "limited", "dlc", "in stock"
- A keyword is OK if it identifies a specific product even without a maker (e.g. "Umnumzaan" is unambiguous)
- A generic term paired with a specific maker in the maker field is acceptable but not ideal (maker scoping reduces noise)

Respond in JSON:
{{
  "quality": "good" | "needs_work" | "bad",
  "reason": "one sentence explaining why",
  "suggestions": ["up to 3 better keyword alternatives"],
  "generic_keywords": ["which of their keywords are too generic"],
  "corrected_keywords": ["the keyword list you would actually watch with — the user's keywords cleaned up: junk/storefront terms removed, phrases split into product names/models. Empty list if their keywords are fine as-is or you can't infer real intent"]
}}"""

# ── Load environment ──────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, BASE_DIR)
import paths
import db as _db
load_dotenv(paths.ENV_FILE)

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger('ai_interpreter')

# ── Anthropic client ──────────────────────────────────────────────────────────
client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

MODEL = 'claude-haiku-4-5-20251001'

# ── Page-text limits ─────────────────────────────────────────────────────────
# The old hard 3000-char cut silently hid items lower on long collection pages
# (e.g. a Damascus listing in the bottom half of a Chris Reeve collection page).
USER_PAGE_CHAR_LIMIT = 8000
CURATED_CHAR_LIMIT   = 6000


# ── 'Read more' backstop ─────────────────────────────────────────────────────
# WooCommerce archive pages render a non-purchasable product with a 'Read more'
# button where 'Add to cart' would be. PAGE_ANALYSIS_PROMPT tells the model to
# exclude those, but it intermittently ignores the rule (2026-06-12: all 13
# 'Read more' items on the MSC catalog reported in stock — false alerts to 4
# users, each starting a 6h cooldown that would mask the real drop). The page
# text is the ground truth; this filter enforces the rule in code.
PURCHASABLE_MARKERS   = ('add to cart', 'add-to-cart', 'buy now')
UNPURCHASABLE_MARKER  = 'read more'
_MARKER_WINDOW        = 120  # chars after the item name where its button text lives


def _listing_status(page_text_lower, name):
    """'unpurchasable' | 'purchasable' | 'unknown' for one listed item.

    The item's button text follows its name (and price) in the flattened page
    text: 'Stub – Grandpa Finish $ 795.00 Read more'. Whitespace differs
    between what the model echoes back and the page ('( Custom' vs '(Custom'),
    so match the name with whitespace made optional everywhere.
    """
    chars = [c for c in name.lower() if not c.isspace()]
    if not chars:
        return 'unknown'
    pattern = r'\s*'.join(re.escape(c) for c in chars)
    # The name can appear several times (keyword header, nav, the listing
    # itself) — judge every occurrence. A purchase button at any occurrence
    # proves buyable; otherwise any 'Read more' occurrence means not.
    statuses = set()
    for m in re.finditer(pattern, page_text_lower):
        window = page_text_lower[m.end():m.end() + _MARKER_WINDOW]
        hits = [(window.find(mk), 'purchasable') for mk in PURCHASABLE_MARKERS]
        hits.append((window.find(UNPURCHASABLE_MARKER), 'unpurchasable'))
        hits = [(pos, status) for pos, status in hits if pos != -1]
        if hits:
            statuses.add(min(hits)[1])  # first marker after this occurrence
    if 'purchasable' in statuses:
        return 'purchasable'
    if 'unpurchasable' in statuses:
        return 'unpurchasable'
    return 'unknown'


def filter_unpurchasable(result, page_text):
    """Remove notable items whose listing shows 'Read more' instead of a
    purchase button. Mutates and returns result. Items not found in the page
    text are kept — truncation must not suppress a real drop."""
    items = result.get('notable_items') or []
    if not items:
        return result

    low = page_text.lower()
    removed = [i for i in items if _listing_status(low, i) == 'unpurchasable']
    if not removed:
        return result

    kept = [i for i in items if i not in removed]
    log.warning(f"{result.get('site', '?')}: dropped {len(removed)} 'Read more' "
                f"(not purchasable) items the AI marked in-stock: {removed}")
    result['notable_items'] = kept
    result['notable_items_detail'] = [
        d for d in (result.get('notable_items_detail') or [])
        if (d.get('name') if isinstance(d, dict) else d.name) in kept
    ]
    in_stock = result.get('in_stock') or {}
    if not kept:
        result['in_stock'] = {}
        announced = (result.get('drop_announcement') or {}).get('detected', False)
        result['alert_worthy'] = bool(announced)
        if not announced:
            result['priority'] = 'medium'
    elif len(in_stock) == 1:
        maker = next(iter(in_stock))
        result['in_stock'][maker] = min(in_stock[maker], len(kept))
    return result


def filter_unpurchasable_user(result, page_text):
    """User-page variant of filter_unpurchasable (2026-06-12 23:47: the user-watch
    path lacked the backstop and re-shipped the morning's false positive, with
    SMS). UserPageAnalysis notable_items are 'Name — STATUS — price' strings;
    check the name part against the page's button text and kill the alert when
    nothing claimed purchasable actually has a purchase button."""
    items = result.get('notable_items') or []
    if not items or not result.get('alert_worthy'):
        return result

    low = page_text.lower()
    kept = []
    removed = []
    for item in items:
        # Split on em dash only — the 'Name — STATUS — price' separator the
        # prompt mandates. Names themselves contain en dashes/hyphens
        # ('Stub – Grandpa Finish'), which must stay intact.
        name = re.split(r'\s+—\s+', item)[0].strip()
        if name and _listing_status(low, name) == 'unpurchasable':
            removed.append(item)
        else:
            kept.append(item)
    if not removed:
        return result

    log.warning(f"{result.get('site', '?')} (user): dropped {len(removed)} 'Read more' "
                f"(not purchasable) items the AI marked available: {removed}")
    result['notable_items'] = kept
    if not kept:
        result['alert_worthy'] = False
    return result


def build_keyword_excerpt(page_text, keywords, limit=USER_PAGE_CHAR_LIMIT,
                          head=1500, window=400, max_hits_per_kw=5):
    """Build an excerpt that always includes context around the user's keywords.

    Guarantees that wherever a watched keyword appears — even near the end of a long
    page — the surrounding text reaches the AI, instead of being chopped off by a flat
    head-of-page truncation. Always keeps the page head for general context, then
    splices in windows around each keyword hit and merges overlaps.
    """
    if len(page_text) <= limit:
        return page_text

    low = page_text.lower()
    spans = [(0, head)]
    for kw in keywords:
        kw_l = (kw or '').lower().strip()
        if not kw_l:
            continue
        start, hits = 0, 0
        while hits < max_hits_per_kw:
            idx = low.find(kw_l, start)
            if idx == -1:
                break
            spans.append((max(0, idx - window), idx + len(kw_l) + window))
            start = idx + len(kw_l)
            hits += 1

    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    excerpt = ' … '.join(page_text[s:e] for s, e in merged)
    return excerpt[:limit]

# ── Token usage logging ────────────────────────────────────────────────────
def log_api_usage(caller, site_name, message):
    """Log token usage to SQLite after every Anthropic call."""
    try:
        _db.log_api_usage(caller, site_name, MODEL,
                          message.usage.input_tokens, message.usage.output_tokens)
    except Exception as e:
        log.warning(f"Could not log API usage: {e}")


def clean_ai_json(raw):
    """Extract valid JSON from AI response, handling markdown fences and preamble."""
    raw = raw.strip()
    if '```' in raw:
        parts = raw.split('```')
        for part in parts[1:]:
            cleaned = part.strip()
            if cleaned.startswith('json'):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith('{'):
                raw = cleaned
                break
    if not raw.startswith('{'):
        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end != -1:
            raw = raw[start:end+1]
    return json.loads(raw)


def parse_ai_response(raw, schema_cls, site_name='', url=''):
    """Extract JSON from AI text, validate against a Pydantic model.
    Returns (validated_dict, [warnings]).  Raises AIParseError / AISchemaError."""
    if not raw:
        raise AIEmptyResponseError(f"Empty AI response for {site_name}", site=site_name, url=url)
    try:
        data = clean_ai_json(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise AIParseError(f"Invalid JSON from AI for {site_name}: {e}",
                           site=site_name, url=url, raw=raw[:500])

    warnings = []
    try:
        validated = schema_cls.model_validate(data)
    except Exception as e:
        raise AISchemaError(f"Schema validation failed for {site_name}: {e}",
                            site=site_name, url=url, raw=str(data)[:500])

    result = validated.model_dump()

    if schema_cls is PageAnalysis:
        items = result.get('notable_items') or []
        detail = result.get('notable_items_detail') or []
        if len(items) > 0 and len(detail) == 0:
            warnings.append(f"notable_items has {len(items)} entries but notable_items_detail is empty")
        if len(items) > 0 and 0 < len(detail) < len(items):
            warnings.append(f"notable_items ({len(items)}) > notable_items_detail ({len(detail)}) — some items lack detail")

    return result, warnings


def first_text(message, label=''):
    """Safely pull the first text block from a Claude response.

    Guards against an empty content list or a non-text first block (e.g. a
    max_tokens stop with no text), which would otherwise raise
    IndexError/AttributeError. Logs the stop_reason so a truncated response is
    diagnosable instead of silently lost. Returns '' when there's no text.
    """
    for block in (message.content or []):
        text = getattr(block, 'text', None)
        if text:
            return text.strip()
    log.error(f"AI returned no text block for {label} (stop_reason={getattr(message, 'stop_reason', '?')})")
    return ''


def log_ai_call(caller, site_name, url, prompt_snippet, response_json):
    """Log full AI interaction to SQLite."""
    try:
        _db.log_ai_call(caller, site_name, url, prompt_snippet, response_json)
    except Exception as e:
        log.warning(f"Could not log AI call: {e}")

# ── Load makers config ────────────────────────────────────────────────────────
def load_makers_config():
    makers_path = paths.MAKERS_YAML
    try:
        with open(makers_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        log.warning(f"Could not load makers.yaml: {e}")
        return {}

def build_priority_intel(makers_config):
    lines = []
    lines.append("PRIORITY GUIDE — use this to set alert priority:")
    lines.append("")

    for maker in makers_config.get('makers', []):
        name = maker['name']
        notable_models = maker.get('notable_models', {})
        notable_materials = maker.get('notable_materials', {})

        critical_models = notable_models.get('critical', [])
        high_models = notable_models.get('high', [])
        critical_materials = notable_materials.get('critical', [])

        # Coerce to str — YAML parses an unquoted numeric model/year (e.g. 2026) as an
        # int, and ', '.join() raises TypeError on a non-str item. Hardened like
        # build_keywords (S54). Keeps the scraper from crash-looping on a config typo.
        critical_models    = [str(m) for m in critical_models]
        high_models        = [str(m) for m in high_models]
        critical_materials = [str(m) for m in critical_materials]

        if critical_models or critical_materials:
            lines.append(f"{name}:")
            if critical_models:
                if 'all' in critical_models:
                    lines.append(f"  CRITICAL: everything from {name}")
                else:
                    lines.append(f"  CRITICAL models: {', '.join(critical_models)}")
            if critical_materials:
                lines.append(f"  CRITICAL materials: {', '.join(critical_materials)}")
            if high_models:
                lines.append(f"  HIGH models: {', '.join(high_models)}")
            lines.append("")

    collabs = makers_config.get('collaborations', [])
    if collabs:
        lines.append("COLLABORATIONS — always CRITICAL:")
        for collab in collabs:
            aliases = collab.get('aliases', [])
            lines.append(f"  - {', '.join(aliases)}")
        lines.append("")

    return '\n'.join(lines)


PAGE_ANALYSIS_PROMPT = """You are an expert in the custom knife and EDC (everyday carry) gear market, 
specializing in mid-tech folders, Steel Flame jewelry, and high-end knife makers.

Analyze the following webpage content from {site_name} ({url}) and return a JSON response.

MAKERS WE CARE ABOUT:
{makers_list}

{priority_intel}

PRIORITY RULES:

OVERRIDE RULE — applies before anything else:
- If the page content contains recurring schedule language ("every Thursday", "daily at", "each weekday", "every week", "recurring", "every other") AND the drop does NOT contain a Hinderer x Steel Flame / CRK x Wilson Combat / Strider x Steel Flame collab or MSC knife — set priority to "medium" REGARDLESS of maker or model. Do not upgrade this.

After applying the override above, use these rules:
- "critical" = CRITICAL priority (rare, high value, drop everything)
- "high" = HIGH priority (worth checking immediately)
- "medium" = MEDIUM priority (interesting but not urgent)
- Only THESE specific collaborations are CRITICAL: Hinderer x Steel Flame, CRK x Wilson Combat, Strider x Steel Flame. All other collabs are medium.
- Any Mick Strider Custom Knife (MSC) available for purchase is always CRITICAL — these are extremely rare
- IMPORTANT: "Read more" buttons mean the item is NOT directly purchasable. Only "Add to cart" or "Buy now" buttons mean an item is truly in stock and available. Do not mark items as in_stock if they only show "Read more".
- Any drop announcement or DROP banner on McNees Knives is always HIGH priority
- Monkey Edge FRAG patterns or Monkey Edge Exclusives are always HIGH priority
- Prometheus Design Werx (PDW) folders/knives in their collections are always HIGH priority
- Damascus on any CRK is always CRITICAL
- CRK x Wilson Combat collab is CRITICAL — all other CRK drops/specials are HIGH, not CRITICAL
- Standard production Chris Reeve Sebenzas (plain titanium, wood inlays, bog oak, macassar ebony, box elder) at dealers are MEDIUM — these are regular restocks, not special drops. Only Damascus CRK, Wilson Combat collab, or genuinely rare/limited CRK variants are HIGH or CRITICAL.
- Standard production Hinderer XM-18, XM-24, Firetac in regular G-10/titanium at dealers are MEDIUM — these are common restocks. Only wood/walnut/brass/copper handles, DLT exclusives, or Steel Flame collabs are HIGH or CRITICAL.
- Standard production Heretic, Pro-Tech, WE Knife, Civivi, Kizer at dealers are MEDIUM unless a specific rare collab or limited run is mentioned.
- Standard production Arno Bernard models (Rinkhals, iMamba, Turaco) without damascus are MEDIUM priority — this OVERRIDES the notable_item HIGH rule. Do not set these to high or critical unless damascus or mammoth inlay is explicitly mentioned.
- Demko AD20.5 is a common production knife — always MEDIUM priority unless a rare sprint/collab variant is explicitly mentioned
- GENERAL RULE: Dealer "new arrivals" pages showing standard production knives from any maker = MEDIUM. Dealers restock constantly. Only flag HIGH if there is a genuinely special variant, limited edition, or collab.
WEBPAGE CONTENT (may be truncated; non-contiguous sections separated by " … "):
{page_content}

Return ONLY valid JSON in this exact format, no other text:
{{
  "makers_found": ["list of maker names found on this page"],
  "in_stock": {{"MakerName": 5}},
  "out_of_stock": {{"MakerName": 3}},
  "drop_announcement": {{
    "detected": true,
    "maker": "maker name or null",
    "description": "what is dropping",
    "timing": "when (specific day/time if mentioned, or null)",
    "confidence": "high/medium/low"
  }},
  "notable_items": ["EVERY in-stock item from tracked makers — list ALL, not just highlights"],
  "notable_items_detail": [{{"name": "item name", "url": "/relative-or-absolute-product-url", "price": "$NNN"}}],
  "page_summary": "one sentence summary of what this page is about",
  "priority": "critical/high/medium/low",
  "alert_worthy": true
}}

Rules:
- Only include makers from the list above
- drop_announcement.detected should only be true if there is a SPECIFIC upcoming drop mentioned
- alert_worthy should be true only if there are makers in stock OR a real drop announcement
- Use the priority guide above to set priority accurately
- Be conservative — false positives waste the owner's time
- NEVER include sold-out or unavailable items in notable_items — only include items that are actually in stock or genuinely dropping soon
- notable_items must list EVERY in-stock item from tracked makers, up to 30. Do NOT cherry-pick or summarize — users match keywords against this list and missing items cause missed alerts
- For each notable item, if you can see a direct product URL (<a href>) pointing to an individual product page (containing /products/, /product/, /p/, /dp/, or a slug path), include it in notable_items_detail. If no URL is visible, omit the url field for that item.
- notable_items_detail must have an entry for EVERY item in notable_items, even if the url field is omitted
- If no relevant content found return alert_worthy: false and empty arrays"""


DROP_ANNOUNCEMENT_PROMPT = """You are an expert in the custom knife and EDC gear market.

This content was flagged as a potential drop announcement on {site_name}.
Makers we follow: {makers_list}

FLAGGED CONTENT:
{content}

Is this a real, specific drop announcement for any of our makers? 
Return ONLY valid JSON:
{{
  "is_real_drop": true,
  "maker": "maker name or null",
  "what": "what is dropping",
  "when": "specific timing or null", 
  "where": "site name",
  "confidence": "high/medium/low",
  "raw_quote": "the exact text that triggered this"
}}"""


USER_PAGE_PROMPT = """You are analyzing a product or e-commerce page for a user who wants to know when specific items become available to purchase. This could be any type of product — knives, sneakers, electronics, concert tickets, collectibles, anything.

Page: {url}
The user is watching for these keywords: {keywords}

Look at the page content and determine:
1. Which of the user's keywords appear on the page
2. For each keyword match, what is the stock/availability status
3. Is anything the user wants actually purchasable right now

WEBPAGE CONTENT (may be truncated; non-contiguous sections separated by " … "):
{page_content}

Return ONLY valid JSON in this exact format, no other text:
{{
  "keywords_found": ["keywords from the user's list that appear on the page"],
  "notable_items": ["item name — STATUS — price if visible, e.g. 'Air Jordan 4 Retro — IN STOCK — $210' or 'RTX 5090 FE — SOLD OUT'"],
  "page_summary": "one sentence summarizing availability of the user's keywords on this page",
  "priority": "high/medium/low",
  "alert_worthy": true
}}

Rules:
- alert_worthy = true ONLY if at least one keyword-matching item can be purchased right now (Add to Cart, Buy Now, In Stock, Available)
- SOLD OUT, Out of Stock, Coming Soon, Notify Me, Waitlist, Unavailable = NOT alert worthy
- A "Read more" button instead of "Add to cart" means the item is NOT purchasable (WooCommerce shows "Read more" for items that cannot be bought) — NOT alert worthy
- Include ALL keyword-matching items in notable_items with their real status — even sold-out ones — but only set alert_worthy true for purchasable items
- page_summary MUST name the user's keywords and their stock status so downstream keyword matching works
- Be conservative — only alert on clear availability signals, false positives waste the user's time
- If none of the user's keywords appear on the page at all, return alert_worthy false and empty arrays
- Do not assume what the product is — read the page and report what you see"""


MORNING_BRIEFING_PROMPT = """You are a personal assistant to a knife and Steel Flame collector.

Here is a summary of what the Drop Watcher system found overnight:

SITES CHECKED: {sites_checked}
ALERTS GENERATED: {alert_count}
ALERT DETAILS:
{alerts_json}

Write a concise, friendly morning briefing in plain English. 
Lead with anything urgent (drops happening today, items in stock).
Be specific about makers and items where possible.
Keep it under 150 words.
End with HGR."""


_PRIORITY_INTEL = None  # built once from makers.yaml (static between restarts)

def get_priority_intel():
    """Cache the priority-intel string — makers.yaml is static between restarts, so
    re-reading + rebuilding it on every AI call was wasted disk I/O on the hot path."""
    global _PRIORITY_INTEL
    if _PRIORITY_INTEL is None:
        _PRIORITY_INTEL = build_priority_intel(load_makers_config())
    return _PRIORITY_INTEL


def analyze_page(site_name, url, page_text, makers_list):
    truncated = page_text[:CURATED_CHAR_LIMIT] if len(page_text) > CURATED_CHAR_LIMIT else page_text
    makers_formatted = '\n'.join([f"- {m}" for m in makers_list])
    priority_intel = get_priority_intel()

    prompt = PAGE_ANALYSIS_PROMPT.format(
        site_name=site_name,
        url=url,
        makers_list=makers_formatted,
        priority_intel=priority_intel,
        page_content=truncated
    )

    try:
        log.info(f"Sending {site_name} to AI interpreter...")
        message = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )

        log_api_usage('analyze_page', site_name, message)
        raw = first_text(message, site_name)
        result, warnings = parse_ai_response(raw, PageAnalysis, site_name, url)
        for w in warnings:
            log.warning(f"{site_name}: {w}")
        result['timestamp'] = datetime.now(timezone.utc).isoformat()
        result['site'] = site_name
        result['url'] = url
        result['model'] = MODEL
        filter_unpurchasable(result, truncated)

        log.info(f"{site_name} — AI analysis complete. Alert worthy: {result.get('alert_worthy', False)} Priority: {result.get('priority', 'medium')} Items: {len(result.get('notable_items', []))} Tokens: {message.usage.input_tokens}in/{message.usage.output_tokens}out")
        log_ai_call('analyze_page', site_name, url, truncated, result)
        return result

    except (AIParseError, AISchemaError, AIEmptyResponseError) as e:
        log.error(f"AI response error for {site_name}: {e}")
        return None
    except anthropic.RateLimitError as e:
        log.error(f"Rate limited for {site_name}: {e}")
        return None
    except anthropic.APIStatusError as e:
        log.error(f"Anthropic API error for {site_name}: {e.status_code} {e.message}")
        return None
    except Exception as e:
        log.error(f"Unexpected error in AI interpreter for {site_name}: {e}")
        return None


def analyze_drop_announcement(site_name, content, makers_list):
    makers_formatted = ', '.join(makers_list)
    prompt = DROP_ANNOUNCEMENT_PROMPT.format(
        site_name=site_name,
        makers_list=makers_formatted,
        content=content[:1500]
    )
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}]
        )
        log_api_usage('analyze_drop', site_name, message)
        raw = first_text(message, site_name)
        result, _ = parse_ai_response(raw, DropAnnouncementAnalysis, site_name, '')
        result['timestamp'] = datetime.now(timezone.utc).isoformat()
        return result
    except (AIParseError, AISchemaError, AIEmptyResponseError) as e:
        log.error(f"Drop announcement response error for {site_name}: {e}")
        return None
    except Exception as e:
        log.error(f"Drop announcement analysis failed for {site_name}: {e}")
        return None


DEALER_CLASSIFY_PROMPT = """You are classifying a website for a knife/EDC in-stock alert service.

URL: {url}

Decide whether this site is a DEDICATED knife / EDC (everyday-carry) retailer or a knife
maker's own store — the kind of specialty shop worth monitoring for knife drops.

Rules:
- is_dealer = true ONLY for knife/EDC specialty retailers (e.g. Blade HQ, KnifeCenter,
  DLT Trading) or a knife/tool maker's own storefront.
- is_dealer = false for GENERAL marketplaces and big-box stores (Amazon, eBay, Walmart,
  Target, Best Buy, Sam's Club, Academy), and for anything not centered on knives/EDC
  (jewelry, groceries, electronics, toys, etc.) — even if a knife happens to be listed.
- When unsure, prefer false with low confidence.

Return ONLY JSON:
{{
  "is_dealer": true/false,
  "category": "short label, e.g. 'knife/EDC retailer', 'knife maker store', 'general marketplace', 'non-knife retailer'",
  "brands": ["up to 5 knife/EDC brands you can see are carried"],
  "confidence": 0.0-1.0,
  "reason": "one sentence"
}}

PAGE CONTENT (may be truncated):
{page_content}
"""


def classify_dealer(url, page_text):
    """Classify whether a URL is a knife/EDC dealer worth curating. Returns dict or None.

    Used by dealer_scout.py to triage uncurated domains users have added. Does NOT
    decide anything about watching — it only fills the review queue.
    """
    site_name = url.lower().replace('https://', '').replace('http://', '').split('/')[0]
    truncated = page_text[:5000] if len(page_text) > 5000 else page_text
    prompt = DEALER_CLASSIFY_PROMPT.format(url=url, page_content=truncated)

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        log_api_usage('classify_dealer', site_name, message)
        raw = first_text(message, site_name)
        result, _ = parse_ai_response(raw, DealerClassification, site_name, url)
        log_ai_call('classify_dealer', site_name, url, truncated[:500], result)
        return result
    except (AIParseError, AISchemaError, AIEmptyResponseError) as e:
        log.error(f"classify_dealer response error for {site_name}: {e}")
        return None
    except anthropic.APIStatusError as e:
        log.error(f"classify_dealer API error for {site_name}: {e.status_code} {e.message}")
        return None
    except Exception as e:
        log.error(f"classify_dealer unexpected error for {site_name}: {e}")
        return None


def assess_keyword_quality(keywords, maker=''):
    """Ask Haiku whether keywords are specific enough for good alerts.
    Returns dict with quality/reason/suggestions/generic_keywords.
    On any failure returns {'quality': 'unknown'} — never blocks signup."""
    prompt = KEYWORD_QUALITY_PROMPT.format(
        keywords=keywords,
        maker=maker or 'not specified',
    )
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        log_api_usage('assess_keyword_quality', 'keyword_check', message)
        raw = first_text(message, 'keyword_quality')
        result, _ = parse_ai_response(raw, KeywordQualityAssessment, 'keyword_check', '')
        log_ai_call('assess_keyword_quality', 'keyword_check', '', keywords[:200], result)
        return result
    except Exception as e:
        log.error(f"assess_keyword_quality failed: {e}")
        return {'quality': 'unknown'}


def analyze_user_page(url, page_text, user_keywords):
    """Analyze a page for a user's specific keywords — generic, not knife-market-specific."""
    truncated = build_keyword_excerpt(page_text, user_keywords)
    keywords_formatted = ', '.join(user_keywords)
    site_name = url.lower().replace('https://', '').replace('http://', '').split('/')[0]

    prompt = USER_PAGE_PROMPT.format(
        url=url,
        keywords=keywords_formatted,
        page_content=truncated
    )

    try:
        log.info(f"Sending user watch {site_name} to AI (keywords: {keywords_formatted})...")
        message = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )

        log_api_usage('analyze_user_page', site_name, message)
        raw = first_text(message, site_name)
        result, warnings = parse_ai_response(raw, UserPageAnalysis, site_name, url)
        for w in warnings:
            log.warning(f"{site_name} (user): {w}")
        result['timestamp'] = datetime.now(timezone.utc).isoformat()
        result['site'] = site_name
        result['url'] = url
        result['model'] = MODEL
        filter_unpurchasable_user(result, truncated)

        log.info(f"{site_name} — user page analysis complete. Alert worthy: {result.get('alert_worthy', False)} Priority: {result.get('priority', 'medium')} Tokens: {message.usage.input_tokens}in/{message.usage.output_tokens}out")
        log_ai_call('analyze_user_page', site_name, url, f"keywords: {keywords_formatted}\n{truncated}", result)
        return result

    except (AIParseError, AISchemaError, AIEmptyResponseError) as e:
        log.error(f"AI response error for user page {site_name}: {e}")
        return None
    except anthropic.RateLimitError as e:
        log.error(f"Rate limited for user page {site_name}: {e}")
        return None
    except anthropic.APIStatusError as e:
        log.error(f"Anthropic API error for user page {site_name}: {e.status_code} {e.message}")
        return None
    except Exception as e:
        log.error(f"Unexpected error analyzing user page {site_name}: {e}")
        return None


def generate_morning_briefing(alerts, sites_checked):
    if not alerts:
        return "Nothing of interest overnight. All quiet on the drop front. HGR"
    prompt = MORNING_BRIEFING_PROMPT.format(
        sites_checked=sites_checked,
        alert_count=len(alerts),
        alerts_json=json.dumps(alerts, indent=2)[:3000]
    )
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}]
        )
        log_api_usage('morning_briefing', 'n/a', message)
        return first_text(message, 'morning_briefing')
    except Exception as e:
        log.error(f"Morning briefing generation failed: {e}")
        return f"Morning briefing unavailable ({e}). Check logs manually. HGR"


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    log.info("Testing AI interpreter with priority intel...")

    test_makers = [
        "Steel Flame", "Hinderer Knives", "Chris Reeve Knives",
        "Strider Knives", "McNees Knives", "Demko Knives"
    ]

    test_content = """
    New arrivals this week!
    Chris Reeve Knives Damascus Sebenza 31 — 1 unit in stock. 
    Hinderer XM-18 3.5 smooth walnut handle — only 1 left!
    Steel Flame pendants OUT OF STOCK — restock Friday.
    Strider SMF dropping this Saturday at noon.
    """

    result = analyze_page(
        site_name="Test Site",
        url="https://example.com",
        page_text=test_content,
        makers_list=test_makers
    )

    if result:
        print("\n✓ AI Interpreter working!\n")
        print(json.dumps(result, indent=2))
    else:
        print("\n✗ Something went wrong — check logs")
