"""daily_cap.py — hard ceiling: no recipient gets more than DAILY_CAP alerts per
rolling 24h, across all watches and both channels. Cutover circuit-breaker."""
import logging
from datetime import datetime, timezone, timedelta
import db

log = logging.getLogger(__name__)
DAILY_CAP = 6


def under_daily_cap(recipient):
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    n = db.count_sent_alerts(recipient, since)
    if n >= DAILY_CAP:
        log.warning(f"CAP_TRIPPED recipient={recipient} count={n} window=24h")
        return False
    return True
