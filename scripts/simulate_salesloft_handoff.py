#!/usr/bin/env python3
"""Simulate a Salesloft cadence handoff for one researched account.

This is the execution edge of the warehouse, kept deliberately inert:

* It reads one row from ``marts.mart_rep_research_queue``. The default pick is
  the highest-ranked row whose identity has been resolved against the demo CRM
  (``demo_crm_review_state = 'matched_in_demo_crm'``); if none exists it falls
  back to the top-ranked row.
* It builds a Salesloft-style ``cadence_membership`` payload with a mock
  ``person_id`` and ``cadence_id``.
* It checks ``outreach_ready``. Every row is currently false, so the default
  run prints a HOLD and exits without staging anything.
* ``--human-approved`` simulates a rep having reviewed the account. The payload
  is then printed as staged, but still nothing is sent: there are no network
  calls, credentials, or automatic sends in this script.

Exit codes are 0 for both HOLD and STAGED because both are valid outcomes of
the simulation; the printed line is the contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extract.db import get_conn  # noqa: E402

DEFAULT_CADENCE_ID = 424242
CADENCE_NAME = "Dallas Research Queue - Rep Send"
HOLD_MESSAGE = "HOLD: Account not yet cleared for outreach. Salesloft enrollment blocked."

QUERY = """
select account_id::text as account_id,
       account_name,
       territory,
       queue_rank,
       demo_fit_score,
       demo_fit_band,
       observed_capability,
       signal_confidence,
       possible_multi_location_group,
       demo_crm_review_state,
       use_case_hypothesis,
       next_research_step,
       outreach_ready,
       website
from marts.mart_rep_research_queue
where (%(account_id)s is null or account_id::text = %(account_id)s)
order by
    case demo_crm_review_state
        when 'matched_in_demo_crm' then 0
        when 'not_matched_in_demo_crm' then 1
        else 2
    end,
    queue_rank
limit 1
"""


def load_row(account_id: str | None) -> dict[str, Any]:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(QUERY, {"account_id": account_id})
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise SystemExit(
            "No research-queue row found"
            + (f" for account_id={account_id}" if account_id else "")
            + "."
        )
    return dict(row)


def stable_int(seed: str, floor: int, span: int) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return floor + int(digest, 16) % span


def build_payload(row: dict[str, Any], cadence_id: int, human_approved: bool) -> dict[str, Any]:
    payload = {
        "person_id": stable_int(f"person:{row['account_id']}", 100000, 899999),
        "cadence_id": cadence_id,
        "cadence_name": CADENCE_NAME,
        "account_id": row["account_id"],
        "account_name": row["account_name"],
        "territory": row["territory"],
        "queue_rank": row["queue_rank"],
        "demo_fit_score": row["demo_fit_score"],
        "demo_fit_band": row["demo_fit_band"],
        "observed_capability": row["observed_capability"],
        "signal_confidence": row["signal_confidence"],
        "possible_multi_location_group": bool(row["possible_multi_location_group"]),
        "use_case_hypothesis": row["use_case_hypothesis"],
        "next_research_step": row["next_research_step"],
        "outreach_ready": bool(row["outreach_ready"]),
        "human_approved": human_approved,
        "mode": "simulation_only",
        "idempotency_key": hashlib.sha256(
            f"salesloft:{row['account_id']}:{cadence_id}".encode("utf-8")
        ).hexdigest(),
        "request": {
            "method": "POST",
            "endpoint": "/v2/cadence_memberships",
            "sent": False,
        },
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--account-id",
        default=None,
        help="Target a specific research-queue account_id instead of the default pick",
    )
    parser.add_argument(
        "--cadence-id",
        type=int,
        default=DEFAULT_CADENCE_ID,
        help=f"Mock Salesloft cadence id (default {DEFAULT_CADENCE_ID})",
    )
    parser.add_argument(
        "--human-approved",
        action="store_true",
        help="Simulate a human review approval; stages the payload but still sends nothing",
    )
    args = parser.parse_args()

    row = load_row(args.account_id)
    payload = build_payload(row, args.cadence_id, args.human_approved)

    print(
        f"Selected: rank {row['queue_rank']} | {row['account_name']} | "
        f"{row['territory']} | demo_crm_review_state={row['demo_crm_review_state']} | "
        f"outreach_ready={bool(row['outreach_ready'])}"
    )

    if not row["outreach_ready"] and not args.human_approved:
        print(HOLD_MESSAGE)
        print("Pass --human-approved to simulate the human review that would unblock staging.")
        return 0

    print(f"STAGED FOR SALESLOFT: {json.dumps(payload)} - Awaiting rep send.")
    print("No network call was made; a rep must still send from Salesloft.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
