# Copyright (c) 2026 Simon HGR — instockornot.club — ELv2 License
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
import yaml
from datetime import datetime, timezone
from dotenv import load_dotenv
import anthropic

# ── Load environment ──────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, BASE_DIR)
import paths
load_dotenv(paths.ENV_FILE)

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger('ai_interpreter')

# ── Anthropic client ──────────────────────────────────────────────────────────
client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

MODEL = 'claude-haiku-4-5-20251001'

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

nano +87 /home/shg/drop-watcher/agents/ai_interpreter.py
```

Replace the entire PRIORITY RULES block (lines 87-100) with this:
```
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
- Damascus on any CRK is always CRITICAL
- CRK x Wilson Combat collab is CRITICAL — all other CRK drops/specials are HIGH, not CRITICAL
- CRK x Wilson Combat collab is CRITICAL — all other CRK drops/specials are HIGH, not CRITICAL
- Wood, brass, copper, walnut handles on Hinderer are always HIGH (not CRITICAL)
- Standard production Arno Bernard models (Rinkhals, iMamba, Turaco) without damascus are MEDIUM priority — this OVERRIDES the notable_item HIGH rule. Do not set these to high or critical unless damascus or mammoth inlay is explicitly mentioned.
- Demko AD20.5 is a common production knife — always MEDIUM priority unless a rare sprint/collab variant is explicitly mentioned
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
    truncated = page_text[:3000] if len(page_text) > 3000 else page_text
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
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = message.content[0].text.strip()

        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]

        result = json.loads(raw)
        result['timestamp'] = datetime.now(timezone.utc).isoformat()
        result['site'] = site_name
        result['url'] = url
        result['model'] = MODEL

        log.info(f"{site_name} — AI analysis complete. Alert worthy: {result.get('alert_worthy', False)} Priority: {result.get('priority', 'medium')}")
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
