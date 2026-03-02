#!/usr/bin/env python3
"""
ai_interpreter.py
Drop Watcher — AI Interpretation Layer
Uses Claude to intelligently analyze page content for drops, stock, and announcements.
HGR
"""

import os
import json
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
import anthropic

# ── Load environment ──────────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger('ai_interpreter')

# ── Anthropic client ──────────────────────────────────────────────────────────
client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

MODEL = 'claude-haiku-4-5-20251001'  # Fast and cheap for high-frequency analysis

# ── Prompt templates ──────────────────────────────────────────────────────────

PAGE_ANALYSIS_PROMPT = """You are an expert in the custom knife and EDC (everyday carry) gear market, 
specializing in mid-tech folders, Steel Flame jewelry, and high-end knife makers.

Analyze the following webpage content from {site_name} ({url}) and return a JSON response.

MAKERS WE CARE ABOUT:
{makers_list}

WEBPAGE CONTENT (truncated to 3000 chars):
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
  "notable_items": ["list of specific interesting items spotted e.g. 'Hinderer XM-18 3.5 Magnacut in stock'"],
  "page_summary": "one sentence summary of what this page is about",
  "alert_worthy": true
}}

Rules:
- Only include makers from the list above
- drop_announcement.detected should only be true if there is a SPECIFIC upcoming drop mentioned, not generic "coming soon" copy
- alert_worthy should be true only if there are makers in stock OR a real drop announcement
- Be conservative — false positives waste the owner's time
- If no relevant content found, return alert_worthy: false and empty arrays"""


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


# ── Core analysis functions ───────────────────────────────────────────────────

def analyze_page(site_name, url, page_text, makers_list):
    """
    Send page content to Claude for intelligent analysis.
    Returns structured dict with makers found, stock status, drop announcements.
    Only called when web_watcher detects a page change.
    """
    # Truncate page text to keep API costs reasonable
    truncated = page_text[:3000] if len(page_text) > 3000 else page_text

    makers_formatted = '\n'.join([f"- {m}" for m in makers_list])

    prompt = PAGE_ANALYSIS_PROMPT.format(
        site_name=site_name,
        url=url,
        makers_list=makers_formatted,
        page_content=truncated
    )

    try:
        log.info(f"Sending {site_name} to AI interpreter...")
        message = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = message.content[0].text.strip()

        # Strip markdown code fences if present
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]

        result = json.loads(raw)
        result['timestamp'] = datetime.now(timezone.utc).isoformat()
        result['site'] = site_name
        result['url'] = url
        result['model'] = MODEL

        log.info(f"{site_name} — AI analysis complete. Alert worthy: {result.get('alert_worthy', False)}")
        return result

    except json.JSONDecodeError as e:
        log.error(f"AI returned invalid JSON for {site_name}: {e}")
        log.error(f"Raw response: {raw}")
        return None

    except anthropic.APIError as e:
        log.error(f"Anthropic API error for {site_name}: {e}")
        return None

    except Exception as e:
        log.error(f"Unexpected error in AI interpreter for {site_name}: {e}")
        return None


def analyze_drop_announcement(site_name, content, makers_list):
    """
    Deep analysis of potential drop announcement content.
    Called when web_watcher sees drop-language on a page.
    """
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

        raw = message.content[0].text.strip()
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


def generate_morning_briefing(alerts, sites_checked):
    """
    Generate a plain English morning briefing from overnight alerts.
    Run once daily.
    """
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
        return message.content[0].text.strip()

    except Exception as e:
        log.error(f"Morning briefing generation failed: {e}")
        return f"Morning briefing unavailable ({e}). Check logs manually. HGR"


# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    log.info("Testing AI interpreter...")

    test_makers = [
        "Steel Flame", "Hinderer", "Chris Reeve Knives",
        "Strider Knives", "McNees Knives", "Demko"
    ]

    test_content = """
    New arrivals this week! We just received a fresh shipment from Chris Reeve Knives.
    The Sebenza 31 is back in stock — we have 3 units available.
    Also in: Hinderer XM-18 3.5 in Magnacut — only 2 left!
    Steel Flame pendants are OUT OF STOCK but we expect a restock Friday.
    Mark your calendars — Strider SMF dropping this Saturday at noon.
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
