# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""
sharp.py — outbound click attribution ("go_shankyou" links).

Alert emails wrap dealer-bound hrefs as
https://instockornot.club/go_shankyou/<token>; the route verifies the
token, logs the click to outbound_clicks, and 302s to the dealer. Gives
us per-user, per-dealer, per-drop click-through data — the referral
numbers behind dealer outreach and the partners channel.

Token is stateless (same scheme as nkd.py): HMAC-signed
(watcher_id, dest_url, source, ts). No DB write at email-build time —
a row only exists if someone actually clicks. The signature is the
open-redirect guard: we only ever redirect to URLs we signed.
HGR
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

import db

DATA_DIR = Path(os.environ.get("DW_DATA_DIR", "/var/lib/drop-watcher"))
SECRET_FILE = DATA_DIR / "sharp.secret"
BASE_URL = "https://instockornot.club/go_shankyou/"


def _load_secret() -> bytes:
    if SECRET_FILE.exists():
        return SECRET_FILE.read_bytes().strip()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = secrets.token_bytes(32)
    SECRET_FILE.write_bytes(raw)
    os.chmod(SECRET_FILE, 0o600)
    return raw


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_token(watcher_id: str, dest_url: str, source: str = "", ts: int | None = None) -> str:
    payload = json.dumps(
        {"w": watcher_id, "d": dest_url, "s": source[:40], "t": ts or int(time.time())},
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    sig = hmac.new(_load_secret(), payload, hashlib.sha256).digest()[:16]
    return f"{_b64url_encode(payload)}.{_b64url_encode(sig)}"


def make_link(watcher_id: str, dest_url: str, source: str = "") -> str:
    return BASE_URL + make_token(watcher_id, dest_url, source)


def verify_token(token: str) -> dict | None:
    """Returns {'w', 'd', 's', 't'} or None. No expiry: emails get clicked
    weeks later, and the HMAC alone is the open-redirect guard."""
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload = _b64url_decode(payload_b64)
        sig = _b64url_decode(sig_b64)
        expected = hmac.new(_load_secret(), payload, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(payload)
        if not all(k in data for k in ("w", "d", "t")):
            return None
        if not str(data["d"]).startswith(("http://", "https://")):
            return None
        return data
    except Exception:
        return None


def record_click(data: dict, user_agent: str = "") -> None:
    with db.get_db() as conn:
        conn.execute(
            """INSERT INTO outbound_clicks
               (watcher_id, dest_url, dest_domain, source, link_ts, clicked_at, user_agent)
               VALUES (?, ?, ?, ?, ?, datetime('now'), ?)""",
            (data["w"], data["d"],
             (data["d"].split("//", 1)[-1].split("/", 1)[0]).lower().removeprefix("www."),
             data.get("s", ""), int(data["t"]), user_agent[:200]),
        )
