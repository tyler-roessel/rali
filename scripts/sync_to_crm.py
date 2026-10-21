#!/usr/bin/env python3
"""Simulate a reverse-ETL sync from marts.mart_sales_queue to a CRM.

The script reads priority accounts from the warehouse, compares them with a
small local mock CRM file, and prints only the create/update payloads a real
CRM API would receive. It performs no network calls and never deletes CRM
records.

Diff rules:
* account_id is the natural key.
* A warehouse account missing from the mock CRM is a create.
* An existing account with a different fit_score is an update.
* Same fit_score is unchanged and emits no payload.
* CRM-only records are ignored (no destructive sync).

The idempotency_key is a deterministic hash of account_id + desired fields, so
retrying the same desired state produces the same key. sync_timestamp is the
only non-deterministic field; pass --sync-timestamp for reproducible output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extract.db import get_conn  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_warehouse(min_fit_score: int) -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                select account_id,
                       account_name,
                       rank as queue_rank,
                       fit_score,
                       territory,
                       intent_signal,
                       signal_confidence
                from marts.mart_sales_queue
                where fit_score >= %s
                order by rank
                """,
                (min_fit_score,),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def load_mock_crm(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(
            f"Mock CRM file not found: {path}. Run from the repo root or pass --mock-crm."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("Mock CRM must be a list or an object with a 'records' list")
    return records


def desired_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "account_name": row["account_name"],
        "fit_score": int(row["fit_score"]),
        "queue_rank": int(row["queue_rank"]),
        "territory": row["territory"],
        "intent_signal": row["intent_signal"],
        "signal_confidence": row["signal_confidence"],
    }


def build_payload(
    row: dict[str, Any],
    operation: str,
    sync_timestamp: str,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    account_id = str(row["account_id"])
    fields = desired_fields(row)
    key_material = json.dumps(
        {"account_id": account_id, "fields": fields},
        sort_keys=True,
        separators=(",", ":"),
    )
    payload = {
        "operation": operation,
        "crm_id": existing.get("crm_id") if existing else None,
        "account_id": account_id,
        "fields": fields,
        "sync_timestamp": sync_timestamp,
        "idempotency_key": hashlib.sha256(key_material.encode("utf-8")).hexdigest(),
    }
    if existing is not None:
        payload["change"] = {
            "previous_fit_score": existing.get("fit_score"),
            "new_fit_score": fields["fit_score"],
        }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mock-crm",
        type=Path,
        default=ROOT / "mock_crm_records.json",
        help="Path to the mock CRM JSON file",
    )
    parser.add_argument("--min-fit-score", type=int, default=80)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Emit at most N payloads (useful for a demo)",
    )
    parser.add_argument(
        "--sync-timestamp",
        default=None,
        help="Override the UTC timestamp, e.g. 2026-10-21T12:00:00Z",
    )
    args = parser.parse_args()

    sync_timestamp = args.sync_timestamp or utc_now()
    warehouse = load_warehouse(args.min_fit_score)
    crm_records = load_mock_crm(args.mock_crm)

    crm_by_id: dict[str, dict[str, Any]] = {}
    for record in crm_records:
        account_id = record.get("account_id")
        if not account_id:
            raise ValueError("Every mock CRM record must have an account_id")
        account_id = str(account_id)
        if account_id in crm_by_id:
            raise ValueError(f"Duplicate mock CRM account_id: {account_id}")
        crm_by_id[account_id] = record

    warehouse_ids = {str(row["account_id"]) for row in warehouse}
    crm_only = sorted(set(crm_by_id) - warehouse_ids)

    new_rows: list[dict[str, Any]] = []
    changed_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    unchanged = 0

    for row in warehouse:
        account_id = str(row["account_id"])
        existing = crm_by_id.get(account_id)
        if existing is None:
            new_rows.append(row)
        elif existing.get("fit_score") is None or float(existing["fit_score"]) != float(row["fit_score"]):
            changed_rows.append((row, existing))
        else:
            unchanged += 1

    payloads: list[dict[str, Any]] = []
    for row in new_rows:
        payloads.append(build_payload(row, "create", sync_timestamp))
    for row, existing in changed_rows:
        payloads.append(build_payload(row, "update", sync_timestamp, existing))

    truncated = False
    if args.limit is not None and len(payloads) > args.limit:
        payloads = payloads[: args.limit]
        truncated = True

    print(json.dumps(payloads, indent=2))

    summary = {
        "warehouse_priority_accounts": len(warehouse),
        "mock_crm_records": len(crm_records),
        "new": len(new_rows),
        "changed": len(changed_rows),
        "unchanged": unchanged,
        "crm_only_ignored": len(crm_only),
        "payloads_emitted": len(payloads),
        "truncated": truncated,
        "min_fit_score": args.min_fit_score,
        "sync_timestamp": sync_timestamp,
    }
    print(json.dumps(summary, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
