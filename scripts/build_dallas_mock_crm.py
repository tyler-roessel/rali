#!/usr/bin/env python3
"""Generate a Dallas mock CRM seed from the live dim_account table.

The seed is 50 distinct Dallas accounts, deliberately split across the three
branches of ``scripts/resolve_identities.py`` so the identity-resolution demo
exercises every path rather than only exact-domain matches:

* 20 keep the warehouse domain            -> ``exact_domain``
* 15 get a new domain but keep phone/address -> ``exact_phone_address``
* 15 drop domain and phone                -> ``fuzzy_name_geo``

Names are lightly altered ("LLC", "Inc", "Group", "Co") and some phone numbers
are reformatted, so the rows read like a separate CRM rather than copies of the
warehouse. Legal suffixes are stripped by the resolver's name normalizer, so
the fuzzy branch still matches cleanly.

Reproducible: accounts are sampled with ``random.Random(seed)`` after sorting
by ``account_id``. The output is ``seeds/mock_crm_accounts.csv``.
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extract.db import PROJECT_ROOT, get_conn  # noqa: E402

DEFAULT_OUTPUT = PROJECT_ROOT / "seeds" / "mock_crm_accounts.csv"
DEFAULT_SEED = 42
COUNTS = {"exact_domain": 20, "exact_phone_address": 15, "fuzzy_name_geo": 15}

SUFFIXES = {
    "exact_domain": [" LLC", " Inc", " Group", " Co"],
    # "LLC" and "Inc" are removed by the resolver's legal-token normalizer, so
    # the fuzzy branch sees the same name and scores 100.
    "fuzzy_name_geo": [" LLC", " Inc"],
}

DOMAIN_CANDIDATES = ["com", "net"]


def digits(value: Any) -> str | None:
    text = re.sub(r"\D", "", str(value or ""))
    return text[-10:] if len(text) >= 10 else (text or None)


def address_for(row: dict[str, Any]) -> str | None:
    return row.get("normalized_address") or row.get("full_address") or None


def alt_phone(value: str) -> str:
    d = digits(value) or ""
    if len(d) != 10:
        return value
    return f"({d[:3]}) {d[3:6]}-{d[6:]}"


def slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return (text[:40].rstrip("-") or "account")


def mutate_domain(name: str, index: int, taken: set[str]) -> str:
    base = f"{slug(name)}-dallas"
    for tld in DOMAIN_CANDIDATES:
        candidate = f"{base}.{tld}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    candidate = f"{base}-{index}.com"
    taken.add(candidate)
    return candidate


def load_accounts() -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                select account_id::text as account_id,
                       name,
                       website_domain,
                       phone,
                       normalized_address,
                       full_address,
                       coalesce(addr_city, '') as city,
                       coalesce(addr_postcode, '') as postcode,
                       lat,
                       lon
                from marts.dim_account
                where not is_chain
                  and name is not null
                  and lat is not null
                  and lon is not null
                order by account_id
                """
            )
            rows = [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
    for row in rows:
        row["address"] = address_for(row)
        row["phone_digits"] = digits(row.get("phone"))
    return rows


def pick(rows: list[dict[str, Any]], count: int, rng: random.Random) -> list[dict[str, Any]]:
    chosen = rng.sample(rows, count)
    return sorted(chosen, key=lambda r: r["account_id"])


def build(seed: int = DEFAULT_SEED) -> list[dict[str, str]]:
    accounts = load_accounts()
    rng = random.Random(seed)

    domain_counts = Counter(
        row["website_domain"] for row in accounts if row.get("website_domain")
    )
    pair_counts = Counter(
        (row["phone_digits"], row["address"])
        for row in accounts
        if row.get("phone_digits") and row.get("address")
    )

    domain_pool = [
        row for row in accounts
        if row.get("website_domain")
        and domain_counts[row["website_domain"]] == 1
        and row.get("address")
    ]
    domain_ids = {row["account_id"] for row in domain_pool}
    phone_pool = [
        row for row in accounts
        if row.get("phone_digits") and row.get("address")
        and pair_counts[(row["phone_digits"], row["address"])] == 1
        and row["account_id"] not in domain_ids
    ]
    used_ids = domain_ids | {row["account_id"] for row in phone_pool}
    fuzzy_pool = [row for row in accounts if row["account_id"] not in used_ids]

    for label, pool, needed in (
        ("exact_domain", domain_pool, COUNTS["exact_domain"]),
        ("exact_phone_address", phone_pool, COUNTS["exact_phone_address"]),
        ("fuzzy_name_geo", fuzzy_pool, COUNTS["fuzzy_name_geo"]),
    ):
        if len(pool) < needed:
            raise SystemExit(f"Not enough candidates for {label}: {len(pool)} < {needed}")

    cohort_domain = pick(domain_pool, COUNTS["exact_domain"], rng)
    cohort_phone = pick(phone_pool, COUNTS["exact_phone_address"], rng)
    cohort_fuzzy = pick(fuzzy_pool, COUNTS["fuzzy_name_geo"], rng)

    taken_domains = set(domain_counts)
    records: list[dict[str, str]] = []

    def emit(row: dict[str, Any], cohort: str, index: int) -> None:
        suffixes = SUFFIXES.get(cohort, [" LLC", " Inc", " Group", " Co"])
        crm_name = f"{row['name']}{rng.choice(suffixes)}"
        if cohort == "exact_domain":
            domain = row["website_domain"]
            phone = row.get("phone") or ""
        elif cohort == "exact_phone_address":
            domain = mutate_domain(row["name"], index, taken_domains)
            phone = alt_phone(row["phone"]) if index % 2 else row["phone"]
        else:
            domain = ""
            phone = ""
        records.append({
            "crm_account_id": f"crm-dal-{index:03d}",
            "crm_name": crm_name,
            "domain": domain or "",
            "phone": phone or "",
            "address": row.get("address") or "",
            "city": row.get("city") or "",
            "postcode": row.get("postcode") or "",
            "lat": f"{row['lat']:.6f}",
            "lon": f"{row['lon']:.6f}",
        })

    index = 1
    for cohort, rows in (
        ("exact_domain", cohort_domain),
        ("exact_phone_address", cohort_phone),
        ("fuzzy_name_geo", cohort_fuzzy),
    ):
        for row in rows:
            emit(row, cohort, index)
            index += 1
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    records = build(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)

    print(f"wrote {len(records)} mock CRM rows to {args.output}")
    print(f"  exact_domain cohort: {COUNTS['exact_domain']}")
    print(f"  exact_phone_address cohort: {COUNTS['exact_phone_address']}")
    print(f"  fuzzy_name_geo cohort: {COUNTS['fuzzy_name_geo']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
