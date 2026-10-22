#!/usr/bin/env python3
"""Generate the Dallas mock CRM payload for the reverse-ETL demo.

``scripts/sync_to_crm.py`` only compares priority rows (``fit_score >= 80``), so
the sample is drawn from that cohort: 50 of the 134 Dallas priority accounts.
The records deliberately cover every diff outcome:

* 30 exact snapshots        -> unchanged
* 20 stale snapshots        -> update (older fit score, rank, confidence)
* 1 CRM-only record         -> ignored (no destructive sync)

The JSON uses CRM-style display keys (``Id``, ``Name``, ``Website``); the sync
loader normalizes them to the internal field names. Output is
``mock_crm_records.json`` at the repo root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extract.db import get_conn  # noqa: E402

DEFAULT_OUTPUT = ROOT / "mock_crm_records.json"
DEFAULT_SEED = 42
SAMPLE_SIZE = 50
STALE_COUNT = 20
MIN_FIT_SCORE = 80


def crm_id_for(account_id: str) -> str:
    digest = hashlib.md5(account_id.encode("utf-8")).hexdigest()[:15].upper()
    return f"001{digest}"


def load_priority() -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                select account_id::text as account_id,
                       account_name,
                       rank as queue_rank,
                       fit_score,
                       territory,
                       observed_capability,
                       signal_confidence,
                       website
                from marts.mart_sales_queue
                where fit_score >= %s
                order by rank
                """,
                (MIN_FIT_SCORE,),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def record(row: dict[str, Any], stale: bool) -> dict[str, Any]:
    fit_score = int(row["fit_score"])
    queue_rank = int(row["queue_rank"])
    confidence = row["signal_confidence"]
    if stale:
        # A record last synced before the Dallas rebuild: older score, rank and
        # confidence all differ from the warehouse's current desired state.
        fit_score = max(50, fit_score - 10)
        queue_rank = queue_rank + 7
        confidence = "unknown_no_match"
    return {
        "Id": crm_id_for(row["account_id"]),
        "AccountId": row["account_id"],
        "Name": row["account_name"],
        "Website": row.get("website") or "",
        "FitScore": fit_score,
        "QueueRank": queue_rank,
        "Territory": row["territory"],
        "ObservedCapability": row["observed_capability"],
        "SignalConfidence": confidence,
        "LastSyncedAt": "2026-08-01T12:00:00Z" if stale else "2026-09-15T12:00:00Z",
    }


def build(seed: int = DEFAULT_SEED) -> dict[str, Any]:
    rows = load_priority()
    if len(rows) < SAMPLE_SIZE:
        raise SystemExit(f"Only {len(rows)} priority accounts; need {SAMPLE_SIZE}")
    rng = random.Random(seed)
    sample = sorted(rng.sample(rows, SAMPLE_SIZE), key=lambda r: r["queue_rank"])

    records = []
    for index, row in enumerate(sample):
        records.append(record(row, stale=index >= SAMPLE_SIZE - STALE_COUNT))

    # One CRM-only row proves the sync does not delete records it cannot match.
    records.append({
        "Id": "001000000000000CRM",
        "AccountId": "00000000-0000-0000-0000-000000000001",
        "Name": "Closed Location (CRM only)",
        "Website": "",
        "FitScore": 85,
        "QueueRank": 999,
        "Territory": "Unknown",
        "ObservedCapability": "website_not_recorded",
        "SignalConfidence": "unknown_unreachable",
        "LastSyncedAt": "2026-07-01T12:00:00Z",
    })
    return {
        "crm": "Mock CRM (Dallas)",
        "generated_at": "2026-10-22T00:00:00Z",
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    payload = build(args.seed)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(payload['records'])} CRM records to {args.output}")
    print(f"  exact snapshots: {SAMPLE_SIZE - STALE_COUNT}")
    print(f"  stale (update) snapshots: {STALE_COUNT}")
    print("  CRM-only records: 1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
