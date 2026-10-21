"""Phase 4: deterministic synthetic lifecycle events into raw.lifecycle_events.

The account identity is real (from int_account_deduped); every event, timestamp,
and conversion is synthetic. The boundary is repeated in the table comment and
in the README.

Determinism:
* random.Random(42)
* uuid5 of dedup_key for account_id and of account_id + event_name for event_id
* fixed UTC anchor, no now()
* sorted populations before every sample

Conversion targets:
  35% of accounts enter; prospect->demo 40%; demo->won 30%; won->onboarded 85%;
  onboarded->first_order 80%; first_order->30_day_active 70%.
Messiness:
  5% of won are explicit handoff leaks (no onboarded);
  8% of 30_day_active get a support_ticket;
  4% of onboarded accounts without a first_order get a renewal_due.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from extract.db import get_conn, load_dataframe

SEED = 42
ANCHOR = datetime(2025, 4, 1, 9, 0, tzinfo=timezone.utc)
NAMESPACE = uuid.NAMESPACE_URL

EVENT_NAMES = [
    "prospect_created",
    "demo_booked",
    "closed_won",
    "onboarded",
    "first_order",
    "30_day_active",
    "support_ticket",
    "renewal_due",
]

DDL = """
CREATE TABLE IF NOT EXISTS raw.lifecycle_events (
    event_id         uuid PRIMARY KEY,
    account_id       uuid NOT NULL,
    event_name       text NOT NULL CHECK (
        event_name IN (
            'prospect_created', 'demo_booked', 'closed_won', 'onboarded',
            'first_order', '30_day_active', 'support_ticket', 'renewal_due'
        )
    ),
    event_timestamp  timestamptz NOT NULL,
    source_system    text NOT NULL DEFAULT 'synthetic'
        CHECK (source_system = 'synthetic'),
    event_properties jsonb
);

CREATE INDEX IF NOT EXISTS lifecycle_events_account_time_idx
    ON raw.lifecycle_events (account_id, event_timestamp);

COMMENT ON TABLE raw.lifecycle_events IS
    'HEAVILY SYNTHETIC. Funnel events generated with random.seed(42); the '
    'restaurant identity is real OSM data, every event and timestamp is not.';
COMMENT ON COLUMN raw.lifecycle_events.account_id IS
    'uuid5(dedup_key); deterministic account identity.';
COMMENT ON COLUMN raw.lifecycle_events.event_id IS
    'uuid5(account_id + event_name); deterministic and stable across rebuilds.';
COMMENT ON COLUMN raw.lifecycle_events.source_system IS
    'Always synthetic. This table is not real CRM history.';
"""


def round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def account_id_for(dedup_key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"rali:account:{dedup_key}"))


def event_id_for(account_id: str, event_name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"rali:event:{account_id}:{event_name}"))


def load_accounts() -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select dedup_key, name, is_chain "
                "from intermediate.int_account_deduped order by dedup_key"
            )
            accounts = [
                {"dedup_key": r[0], "name": r[1], "is_chain": bool(r[2])}
                for r in cur.fetchall()
            ]
    finally:
        conn.close()
    for account in accounts:
        account["account_id"] = account_id_for(account["dedup_key"])
    return accounts


def sample_stage(rng, population: list[dict[str, Any]], rate: float) -> list[dict[str, Any]]:
    count = round_half_up(len(population) * rate)
    chosen = rng.sample(population, count)
    chosen.sort(key=lambda a: a["account_id"])
    return chosen


def add_event(
    events: list[dict[str, Any]],
    account: dict[str, Any],
    event_name: str,
    timestamp: datetime,
    properties: dict[str, Any] | None = None,
) -> None:
    events.append(
        {
            "event_id": event_id_for(account["account_id"], event_name),
            "account_id": account["account_id"],
            "event_name": event_name,
            "event_timestamp": timestamp,
            "source_system": "synthetic",
            "event_properties": json.dumps(properties, sort_keys=True) if properties else None,
        }
    )


def generate(accounts: list[dict[str, Any]], seed: int = SEED) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(seed)

    # 35% of the account universe enters the funnel.
    entered = sample_stage(rng, accounts, 0.35)
    demo = sample_stage(rng, entered, 0.40)
    won = sample_stage(rng, demo, 0.30)
    onboarded = sample_stage(rng, won, 0.85)
    first_order = sample_stage(rng, onboarded, 0.80)
    thirty_day = sample_stage(rng, first_order, 0.70)
    support = sample_stage(rng, thirty_day, 0.08)

    onboarded_ids = {a["account_id"] for a in onboarded}
    first_order_ids = {a["account_id"] for a in first_order}
    won_ids = {a["account_id"] for a in won}

    # Explicit handoff leak: 5% of won, chosen only from accounts that did not
    # onboard. The 15% won->onboarded gap still exists; this labels a subset.
    not_onboarded = [a for a in won if a["account_id"] not in onboarded_ids]
    leak_count = round_half_up(0.05 * len(won))
    leaks = rng.sample(not_onboarded, min(leak_count, len(not_onboarded)))
    leak_ids = {a["account_id"] for a in leaks}

    # Renewal due with no first order: 4% of onboarded, only from the
    # onboarded-never-ordered population.
    never_ordered = [a for a in onboarded if a["account_id"] not in first_order_ids]
    renewal_count = round_half_up(0.04 * len(onboarded))
    renewals = rng.sample(never_ordered, min(renewal_count, len(never_ordered)))
    renewal_ids = {a["account_id"] for a in renewals}

    demo_ids = {a["account_id"] for a in demo}
    thirty_ids = {a["account_id"] for a in thirty_day}
    support_ids = {a["account_id"] for a in support}

    events: list[dict[str, Any]] = []
    for account in entered:
        aid = account["account_id"]
        prospect_at = ANCHOR + timedelta(
            days=rng.randint(0, 430),
            hours=rng.randint(0, 9),
            minutes=rng.randint(0, 59),
        )
        add_event(events, account, "prospect_created", prospect_at)

        if aid not in demo_ids:
            continue
        demo_at = prospect_at + timedelta(
            days=rng.randint(3, 14),
            hours=rng.randint(0, 7),
            minutes=rng.randint(0, 59),
        )
        add_event(events, account, "demo_booked", demo_at)

        if aid not in won_ids:
            continue
        closed_at = demo_at + timedelta(
            days=rng.randint(5, 30),
            hours=rng.randint(0, 7),
            minutes=rng.randint(0, 59),
        )
        add_event(
            events,
            account,
            "closed_won",
            closed_at,
            {"handoff_leak": True} if aid in leak_ids else None,
        )

        if aid not in onboarded_ids:
            continue
        onboarded_at = closed_at + timedelta(
            days=rng.randint(3, 14),
            hours=rng.randint(0, 7),
            minutes=rng.randint(0, 59),
        )
        add_event(events, account, "onboarded", onboarded_at)

        if aid not in first_order_ids:
            if aid in renewal_ids:
                renewal_at = onboarded_at + timedelta(
                    days=rng.randint(30, 40),
                    hours=rng.randint(0, 7),
                    minutes=rng.randint(0, 59),
                )
                add_event(
                    events,
                    account,
                    "renewal_due",
                    renewal_at,
                    {"no_first_order": True},
                )
            continue

        first_at = onboarded_at + timedelta(
            days=rng.randint(1, 5),
            hours=rng.randint(0, 7),
            minutes=rng.randint(0, 59),
        )
        add_event(events, account, "first_order", first_at)

        if aid not in thirty_ids:
            continue
        thirty_at = first_at + timedelta(days=30)
        add_event(events, account, "30_day_active", thirty_at)

        if aid in support_ids:
            support_at = thirty_at + timedelta(
                days=rng.randint(1, 10),
                hours=rng.randint(0, 7),
                minutes=rng.randint(0, 59),
            )
            add_event(events, account, "support_ticket", support_at)

    events.sort(key=lambda e: (e["account_id"], e["event_timestamp"], e["event_name"]))

    counts = Counter(e["event_name"] for e in events)

    def pct(numerator: str, denominator: str) -> float:
        return round(counts[numerator] / counts[denominator], 4) if counts[denominator] else 0.0

    funnel = {
        "prospect_created": counts["prospect_created"],
        "demo_booked": counts["demo_booked"],
        "closed_won": counts["closed_won"],
        "onboarded": counts["onboarded"],
        "first_order": counts["first_order"],
        "30_day_active": counts["30_day_active"],
    }
    conversions = {
        "account_to_prospect": round(counts["prospect_created"] / len(accounts), 4) if accounts else 0.0,
        "prospect_to_demo": pct("demo_booked", "prospect_created"),
        "demo_to_closed_won": pct("closed_won", "demo_booked"),
        "closed_won_to_onboarded": pct("onboarded", "closed_won"),
        "onboarded_to_first_order": pct("first_order", "onboarded"),
        "first_order_to_30_day": pct("30_day_active", "first_order"),
    }

    by_account: dict[str, dict[str, datetime]] = defaultdict(dict)
    for event in events:
        by_account[event["account_id"]][event["event_name"]] = event["event_timestamp"]

    order_pairs = [
        ("prospect_created", "demo_booked"),
        ("demo_booked", "closed_won"),
        ("closed_won", "onboarded"),
        ("onboarded", "first_order"),
        ("first_order", "30_day_active"),
        ("30_day_active", "support_ticket"),
        ("onboarded", "renewal_due"),
    ]
    violations = 0
    specific = {
        "onboarded_before_closed_won": 0,
        "first_order_before_onboarded": 0,
    }
    for timestamps in by_account.values():
        for earlier, later in order_pairs:
            if earlier in timestamps and later in timestamps and timestamps[later] < timestamps[earlier]:
                violations += 1
                if (earlier, later) == ("closed_won", "onboarded"):
                    specific["onboarded_before_closed_won"] += 1
                if (earlier, later) == ("onboarded", "first_order"):
                    specific["first_order_before_onboarded"] += 1

    digest_source = "\n".join(
        f"{e['event_id']}|{e['account_id']}|{e['event_name']}|{e['event_timestamp'].isoformat()}"
        for e in events
    )
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()

    summary = {
        "seed": seed,
        "anchor_utc": ANCHOR.isoformat(),
        "accounts": len(accounts),
        "entered": counts["prospect_created"],
        "event_counts": dict(sorted(counts.items())),
        "event_total": len(events),
        "funnel": funnel,
        "conversions": conversions,
        "messiness": {
            "handoff_leaks": len(leaks),
            "handoff_leak_share_of_won": round(len(leaks) / counts["closed_won"], 4)
            if counts["closed_won"]
            else 0.0,
            "support_tickets": counts["support_ticket"],
            "support_share_of_30_day": round(counts["support_ticket"] / counts["30_day_active"], 4)
            if counts["30_day_active"]
            else 0.0,
            "renewal_without_first_order": counts["renewal_due"],
            "renewal_share_of_onboarded": round(counts["renewal_due"] / counts["onboarded"], 4)
            if counts["onboarded"]
            else 0.0,
        },
        "stage_order_violations": violations,
        "specific_order_violations": specific,
        "event_id_sha256": digest,
    }
    return events, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--dry-run", action="store_true", help="Generate and report; do not load")
    parser.add_argument("--summary-json", type=Path, help="Write the run summary as JSON")
    args = parser.parse_args()

    accounts = load_accounts()
    events, summary = generate(accounts, args.seed)

    if not args.dry_run:
        frame = pd.DataFrame(events)
        conn = get_conn()
        try:
            load_dataframe(
                conn,
                frame,
                "raw",
                "lifecycle_events",
                ddl=DDL,
                mode="replace",
            )
            with conn.cursor() as cur:
                cur.execute("select count(*) from raw.lifecycle_events")
                summary["db_row_count"] = cur.fetchone()[0]
        finally:
            conn.close()
    else:
        summary["db_row_count"] = None

    if args.summary_json:
        args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
