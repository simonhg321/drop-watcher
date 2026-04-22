"""
NKD ("New Knife Day") — user conversion tracking.

Users who get a drop alert can click an "I scored!" button. Flow:
  1. Alerter embeds a stateless HMAC token in the email.
  2. User clicks -> lands on /nkd.html?t=<token>.
  3. Page POSTs note/image_url/show_on_wall to /api/nkd/<token>.
  4. Server verifies token, writes row to nkd_scores.
  5. Public wall (/wall.html) shows show_on_wall=1 entries.

Token is stateless — encodes (watcher_id, drop_url_hash, ts) and is
HMAC-signed with a secret at /var/lib/drop-watcher/nkd.secret.
No alert-time DB write required.
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
SECRET_FILE = DATA_DIR / "nkd.secret"
TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 60  # 60 days


def _load_secret() -> bytes:
    if SECRET_FILE.exists():
        return SECRET_FILE.read_bytes().strip()
    # First-run: generate, persist 600.
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


def _drop_url_hash(drop_url: str) -> str:
    return hashlib.sha256(drop_url.encode("utf-8")).hexdigest()[:16]


def make_token(watcher_id: str, drop_url: str, ts: int | None = None) -> str:
    """Stateless HMAC token encoding (watcher_id, drop_url, ts)."""
    ts = ts or int(time.time())
    payload = json.dumps(
        {"w": watcher_id, "u": drop_url, "t": ts},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    sig = hmac.new(_load_secret(), payload, hashlib.sha256).digest()[:16]
    return f"{_b64url_encode(payload)}.{_b64url_encode(sig)}"


def verify_token(token: str) -> dict | None:
    """Returns {'w': watcher_id, 'u': drop_url, 't': ts, 'd': drop_hash} or None."""
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload = _b64url_decode(payload_b64)
        sig = _b64url_decode(sig_b64)
        expected = hmac.new(_load_secret(), payload, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(payload)
        if not all(k in data for k in ("w", "u", "t")):
            return None
        if int(time.time()) - int(data["t"]) > TOKEN_MAX_AGE_SECONDS:
            return None
        data["d"] = _drop_url_hash(data["u"])
        return data
    except Exception:
        return None


# -------- DB helpers (table created by migrate_add_nkd.py) --------


def record_score(
    watcher_id: str,
    drop_url: str,
    note: str = "",
    image_url: str = "",
    show_on_wall: int = 0,
) -> int:
    with db.get_db() as conn:
        cur = conn.execute(
            """INSERT INTO nkd_scores
               (watcher_id, drop_url, scored_at, note, image_url, show_on_wall)
               VALUES (?, ?, datetime('now'), ?, ?, ?)""",
            (watcher_id, drop_url, note[:2000], image_url[:500], 1 if show_on_wall else 0),
        )
        return cur.lastrowid


def already_scored(watcher_id: str, drop_hash: str) -> bool:
    """Dedupe — has this watcher already scored this drop?"""
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT drop_url FROM nkd_scores WHERE watcher_id = ?",
            (watcher_id,),
        ).fetchall()
        return any(_drop_url_hash(r["drop_url"]) == drop_hash for r in rows)


def get_wall_entries(limit: int = 50) -> list[dict]:
    with db.get_db() as conn:
        rows = conn.execute(
            """SELECT s.id, s.scored_at, s.note, s.image_url, s.drop_url,
                      w.name
               FROM nkd_scores s
               LEFT JOIN watchers w ON w.id = s.watcher_id
               WHERE s.show_on_wall = 1
               ORDER BY s.scored_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "scored_at": r["scored_at"],
                "note": r["note"],
                "image_url": r["image_url"],
                "drop_url": r["drop_url"],
                "display_name": (r["name"] or "").strip() or "Anon",
            }
            for r in rows
        ]
