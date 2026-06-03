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
import json
import logging
import yaml
from datetime import datetime, timezone
from dotenv import load_dotenv
import anthropic

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
  "notable_items": ["list of specific interesting items spotted"],
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


def analyze_page(site_name, url, page_text, makers_list):
    truncated = page_text[:CURATED_CHAR_LIMIT] if len(page_text) > CURATED_CHAR_LIMIT else page_text
    makers_formatted = '\n'.join([f"- {m}" for m in makers_list])
    makers_config = load_makers_config()
    priority_intel = build_priority_intel(makers_config)

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
            max_tokens=1536,
            messages=[{"role": "user", "content": prompt}]
        )

        log_api_usage('analyze_page', site_name, message)
        raw = first_text(message, site_name)
        result = clean_ai_json(raw)
        result['timestamp'] = datetime.now(timezone.utc).isoformat()
        result['site'] = site_name
        result['url'] = url
        result['model'] = MODEL

        log.info(f"{site_name} — AI analysis complete. Alert worthy: {result.get('alert_worthy', False)} Priority: {result.get('priority', 'medium')} Tokens: {message.usage.input_tokens}in/{message.usage.output_tokens}out")
        log_ai_call('analyze_page', site_name, url, truncated, result)
        return result

    except json.JSONDecodeError as e:
        log.error(f"AI returned invalid JSON for {site_name}: {e}")
        return None
    except anthropic.APIError as e:
        log.error(f"Anthropic API error for {site_name}: {e}")
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
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        result = json.loads(raw)
        result['timestamp'] = datetime.now(timezone.utc).isoformat()
        return result
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
        result = clean_ai_json(first_text(message, site_name))
        log_ai_call('classify_dealer', site_name, url, truncated[:500], result)
        return result
    except json.JSONDecodeError as e:
        log.error(f"classify_dealer invalid JSON for {site_name}: {e}")
        return None
    except anthropic.APIError as e:
        log.error(f"classify_dealer API error for {site_name}: {e}")
        return None
    except Exception as e:
        log.error(f"classify_dealer unexpected error for {site_name}: {e}")
        return None


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
            max_tokens=1536,
            messages=[{"role": "user", "content": prompt}]
        )

        log_api_usage('analyze_user_page', site_name, message)
        raw = first_text(message, site_name)
        result = clean_ai_json(raw)
        result['timestamp'] = datetime.now(timezone.utc).isoformat()
        result['site'] = site_name
        result['url'] = url
        result['model'] = MODEL

        log.info(f"{site_name} — user page analysis complete. Alert worthy: {result.get('alert_worthy', False)} Priority: {result.get('priority', 'medium')} Tokens: {message.usage.input_tokens}in/{message.usage.output_tokens}out")
        log_ai_call('analyze_user_page', site_name, url, f"keywords: {keywords_formatted}\n{truncated}", result)
        return result

    except json.JSONDecodeError as e:
        log.error(f"AI returned invalid JSON for user page {site_name}: {e}")
        return None
    except anthropic.APIError as e:
        log.error(f"Anthropic API error for user page {site_name}: {e}")
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
