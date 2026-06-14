"""record_index.py — per-source in-stock product index for FTS5 matching.

Rebuild-per-source-per-scan: a source's rows are replaced each scan. Only
in-stock records are indexed.

FTS5 variant: standalone (not external-content). product_records_fts stores its
own copies of (source_url, title, vendor, tags) so we can do a plain
  DELETE FROM product_records_fts WHERE source_url = ?
using FTS5's rowid-based delete (the FTS5 spec allows DELETE on a standalone table
via a normal WHERE — the engine rewrites it through the shadow tables). This avoids
the rowid-sync complexity of external-content tables and keeps the two invariants
(in-stock only; rebuild-per-source) easy to enforce at our scale.
"""
from datetime import datetime, timezone

import db


def index_scan(source_url: str, products: list) -> None:
    """Replace this source's index with current in-stock products.

    Existing rows for source_url are deleted from both product_records and the
    FTS table, then only products with available=True are re-inserted.
    """
    now = datetime.now(timezone.utc).isoformat()
    instock = [p for p in (products or []) if p.get("available")]

    with db.get_db() as conn:
        # Pull old rowids so we can remove them from the FTS table by rowid.
        old_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM product_records WHERE source_url=?", (source_url,)
            ).fetchall()
        ]
        # Delete old FTS rows by rowid (standalone FTS5 supports this).
        for rid in old_ids:
            conn.execute(
                "DELETE FROM product_records_fts WHERE rowid=?", (rid,)
            )
        conn.execute(
            "DELETE FROM product_records WHERE source_url=?", (source_url,)
        )

        for p in instock:
            tags = (
                ", ".join(p.get("tags") or [])
                if isinstance(p.get("tags"), list)
                else (p.get("tags") or "")
            )
            cur = conn.execute(
                "INSERT INTO product_records"
                "  (source_url, title, vendor, tags, url, price, available, scanned_at)"
                "  VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (
                    source_url,
                    p.get("title", ""),
                    p.get("vendor", ""),
                    tags,
                    p.get("url", ""),
                    str(p.get("price", "")),
                    now,
                ),
            )
            new_id = cur.lastrowid
            conn.execute(
                "INSERT INTO product_records_fts (rowid, source_url, title, vendor, tags)"
                "  VALUES (?, ?, ?, ?, ?)",
                (new_id, source_url, p.get("title", ""), p.get("vendor", ""), tags),
            )


def search_source(source_url: str, fts_query: str) -> list:
    """Return product_records rows for source_url matching fts_query.

    Joins product_records to the FTS table on rowid so we get the full
    structured record back, scoped to this source.
    """
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT pr.* FROM product_records pr"
            " JOIN product_records_fts f ON f.rowid = pr.id"
            " WHERE f.source_url=? AND product_records_fts MATCH ?",
            (source_url, fts_query),
        ).fetchall()
        return [dict(r) for r in rows]
