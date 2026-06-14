import os, tempfile, importlib
from datetime import datetime, timezone, timedelta


def _fresh_db():
    d = tempfile.mkdtemp()
    os.environ['DW_DB'] = os.path.join(d, 'test.db')
    import db; importlib.reload(db)
    import daily_cap; importlib.reload(daily_cap)
    return db, daily_cap


def test_under_cap_until_six():
    db, daily_cap = _fresh_db()
    r = "user@example.com"
    for _ in range(6):
        assert daily_cap.under_daily_cap(r) is True
        db.record_sent_alert(r, "email")
    assert daily_cap.under_daily_cap(r) is False   # 7th blocked


def test_old_sends_fall_out_of_window():
    db, daily_cap = _fresh_db()
    r = "user@example.com"
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    for _ in range(6):
        db.record_sent_alert(r, "email", ts=old)
    assert daily_cap.under_daily_cap(r) is True     # all outside 24h
