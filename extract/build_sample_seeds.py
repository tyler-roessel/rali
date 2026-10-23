"""Build the committed 200-account offline sample seeds.

The sample is 200 clusters: every multi-record cluster plus enough deterministic
singletons to reach 200. It exports the raw OSM rows, the website signals for
those accounts' domains, and a deterministic synthetic lifecycle for the sample accounts.

Run from the repo root with live Supabase credentials.

Two passes are required because the sample lifecycle must use the account ids
produced by the sample dedup, not the live account table:
  1. python -m extract.build_sample_seeds
     writes raw/signal seeds from the live warehouse.
  2. dbt seed && dbt build --full-refresh --vars '{use_sample_data: true}'
     builds the sample staging/dedup layer.
  3. python -m extract.build_sample_seeds --lifecycle-only
     writes seeds/lifecycle_events_sample.csv from the sample dedup accounts.
  4. dbt seed --select lifecycle_events_sample && dbt build --full-refresh \
       --vars '{use_sample_data: true}'
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from extract.db import PROJECT_ROOT, get_conn
from extract.fingerprint_websites import normalize_website
from extract.generate_lifecycle import generate

SEED_COUNT = 200
SEEDS = PROJECT_ROOT / "seeds"


def md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


def pg_array(values) -> str:
    if not values:
        return "{}"
    return "{" + ",".join('"' + str(v).replace('"', '\\"') + '"' for v in values) + "}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lifecycle-only",
        action="store_true",
        help="Read the current sample deduped accounts and write the lifecycle seed",
    )
    args = parser.parse_args()

    if args.lifecycle_only:
        conn = get_conn()
        try:
            accounts = pd.read_sql(
                "select account_id, dedup_key, name, is_chain "
                "from intermediate.int_account_deduped order by dedup_key",
                conn,
            )
        finally:
            conn.close()
        events, summary = generate(accounts.to_dict("records"), seed=42)
        pd.DataFrame(events).to_csv(
            SEEDS / "lifecycle_events_sample.csv", index=False, na_rep=""
        )
        print(f"wrote {len(events)} sample lifecycle events")
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    conn = get_conn()
    try:
        accounts = pd.read_sql(
            "select account_id, dedup_key, name, is_chain from marts.dim_account",
            conn,
        )
        clusters = pd.read_sql(
            "select dedup_key, osm_uid from intermediate.int_account_clusters",
            conn,
        )
    finally:
        conn.close()

    accounts["h"] = accounts["dedup_key"].map(md5)
    # The account table has one row per key, so get cluster sizes from the cluster view.
    sizes = clusters.groupby("dedup_key").size()
    multi_keys = set(sizes[sizes > 1].index)
    merges = accounts[accounts["dedup_key"].isin(multi_keys)].sort_values("h")
    singles = accounts[~accounts["dedup_key"].isin(multi_keys)].sort_values("h").head(
        SEED_COUNT - len(merges)
    )
    sample = pd.concat([merges, singles]).sort_values("h")
    sample_keys = sorted(sample["dedup_key"].tolist())
    member_uids = sorted(clusters.loc[clusters["dedup_key"].isin(sample_keys), "osm_uid"].tolist())
    print(f"sample clusters: {len(sample_keys)}; raw rows: {len(member_uids)}")

    conn = get_conn()
    try:
        raw = pd.read_sql(
            "select osm_uid, osm_id, osm_type, name, cuisine, addr_street, "
            "addr_housenumber, addr_city, addr_postcode, phone, website, "
            "opening_hours, brand, operator, lat, lon, loaded_at "
            "from raw.osm_restaurants where osm_uid = any(%s) order by osm_uid",
            conn,
            params=(member_uids,),
        )
        domains = set()
        sample_websites = pd.read_sql(
            "select website from intermediate.int_account_deduped where dedup_key = any(%s)",
            conn,
            params=(sample_keys,),
        )
        for website in sample_websites["website"].dropna():
            normalized = normalize_website(website)
            if normalized:
                domains.add(normalized[0])
        signals = pd.read_sql(
            "select domain, has_website, has_online_ordering, online_ordering_vendor, "
            "has_reservations, reservation_vendor, delivery_marketplaces, site_platform, "
            "signal_confidence, failure_class, fetch_status, http_status, final_url, "
            "page_title, evidence, error_detail, account_count, fetched_at "
            "from raw.website_signals where domain = any(%s) order by domain",
            conn,
            params=(sorted(domains),),
        )
    finally:
        conn.close()

    raw.to_csv(SEEDS / "raw_accounts_sample.csv", index=False, na_rep="")
    signals = signals.copy()
    signals["http_status"] = signals["http_status"].astype("Int64")
    signals["delivery_marketplaces"] = signals["delivery_marketplaces"].map(pg_array)
    signals.to_csv(SEEDS / "website_signals_sample.csv", index=False, na_rep="")

    print(
        f"wrote {len(raw)} raw rows and {len(signals)} signal rows; "
        "run the sample build, then re-run with --lifecycle-only"
    )


if __name__ == "__main__":
    main()
