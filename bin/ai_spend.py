# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
#!/usr/bin/env python3
"""
ai_spend.py — AI spend report from the live SQLite api_usage table.
Printed at session start so we keep an eye on cost after the S60
max_tokens bump (1536 -> 4096). Replaces token_report.py, which reads
the dead api_usage.jsonl (last written 2026-04-01) with stale pricing.

Run: python3 bin/ai_spend.py          (today + yesterday + 7-day total)
     python3 bin/ai_spend.py 30       (last N days, daily table)
HGR
"""
import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths
from dotenv import load_dotenv
load_dotenv(paths.ENV_FILE, override=True)
import db

# Haiku 4.5 pricing per 1M tokens (verified 2026-06-11)
INPUT_COST_PER_M = 1.00
OUTPUT_COST_PER_M = 5.00

WEB_WATCHER_LOG = os.path.join(paths.LOG_DIR, 'web_watcher.log')


def summarize(rows):
    """Aggregate usage rows -> calls / tokens / dollar cost (Haiku 4.5)."""
    in_t = sum(r['input_tokens'] or 0 for r in rows)
    out_t = sum(r['output_tokens'] or 0 for r in rows)
    return {
        'calls': len(rows),
        'in_tokens': in_t,
        'out_tokens': out_t,
        'cost': in_t / 1e6 * INPUT_COST_PER_M + out_t / 1e6 * OUTPUT_COST_PER_M,
    }


def rows_between(conn, start_expr, end_expr=None):
    q = "SELECT caller, input_tokens, output_tokens FROM api_usage WHERE ts >= " + start_expr
    if end_expr:
        q += " AND ts < " + end_expr
    return [dict(r) for r in conn.execute(q)]


def ai_error_count(day_utc):
    """AI response errors in web_watcher.log for a YYYY-MM-DD day (lost scans)."""
    try:
        out = subprocess.run(
            ['grep', '-c', f'^{day_utc}.*AI response error', WEB_WATCHER_LOG],
            capture_output=True, text=True)
        return int(out.stdout.strip() or 0)
    except Exception:
        return -1


def main():
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)

    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        days = int(sys.argv[1])
        with db.get_db() as conn:
            print(f"AI spend, last {days} days (Haiku 4.5, ${INPUT_COST_PER_M}/"
                  f"${OUTPUT_COST_PER_M} per MTok):")
            for i in range(days - 1, -1, -1):
                day = (now - timedelta(days=i)).strftime('%Y-%m-%d')
                s = summarize(rows_between(conn, f"'{day}'", f"date('{day}', '+1 day')"))
                if s['calls']:
                    print(f"  {day}  {s['calls']:5d} calls  "
                          f"{s['in_tokens']/1000:8.0f}k in {s['out_tokens']/1000:7.0f}k out"
                          f"  ${s['cost']:.2f}")
        return

    today = now.strftime('%Y-%m-%d')
    yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    with db.get_db() as conn:
        t = summarize(rows_between(conn, f"'{today}'"))
        y = summarize(rows_between(conn, f"'{yesterday}'", f"'{today}'"))
        w = summarize(rows_between(conn, "datetime('now', '-7 days')"))

    err_today, err_yday = ai_error_count(today), ai_error_count(yesterday)
    print(f"AI SPEND (Haiku 4.5) — today: ${t['cost']:.2f} ({t['calls']} calls, "
          f"{t['out_tokens']/1000:.0f}k out) | yesterday: ${y['cost']:.2f} "
          f"({y['calls']} calls) | 7d: ${w['cost']:.2f}")
    print(f"AI JSON/schema errors (lost scans): today {err_today}, yesterday {err_yday}")


if __name__ == '__main__':
    main()
