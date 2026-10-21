#!/usr/bin/env python3
"""Resolve warehouse accounts to mock CRM accounts with a confidence waterfall.

Waterfall:
  1. exact domain
  2. exact phone + exact normalized address
  3. fuzzy name + geo proximity

Every candidate match below --min-confidence (default 95) is written with
needs_human_review = true. Unmatched accounts are kept in the mapping with a
null crm_account_id and match_method = 'unmatched'; they are not review cases
because there is no candidate link to review.

The output is `seeds/crm_identity_resolution.csv`, which the dbt model
`marts.crm_identity_map` reads and joins back to dim_account and the mock CRM.
The script makes no network calls and does not modify the CRM.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extract.db import get_conn  # noqa: E402

DEFAULT_OUTPUT = ROOT / "seeds" / "crm_identity_resolution.csv"
DEFAULT_MOCK = ROOT / "seeds" / "mock_crm_accounts.csv"
LEGAL_TOKENS = {"restaurant", "the", "llc", "inc", "cafe"}


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_domain(value: str | None) -> str | None:
    text = clean(value)
    if not text:
        return None
    text = re.sub(r"^https?://", "", text.lower())
    text = text.split("/")[0].split(":")[0].strip(".")
    if text.startswith("www."):
        text = text[4:]
    return text or None


def normalize_phone(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return None
    return digits[-10:] if len(digits) >= 10 else digits


def normalize_name(value: str | None) -> str | None:
    text = clean(value)
    if not text:
        return None
    text = text.lower().replace("’", "'").replace("'", "")
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [t for t in text.split() if t not in LEGAL_TOKENS]
    return " ".join(tokens) or None


def normalize_address(value: str | None) -> str | None:
    text = clean(value)
    if not text:
        return None
    text = text.lower().replace("’", "'").replace("'", "").replace("&", " and ")
    text = re.sub(r"\b(suite|ste|unit|apt|apartment)\s*#?\s*[a-z0-9-]+", " ", text)
    text = re.sub(r"#\s*[a-z0-9-]+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    replacements = {
        "street": "st", "avenue": "ave", "boulevard": "blvd", "road": "rd",
        "drive": "dr", "lane": "ln", "court": "ct", "place": "pl",
        "north": "n", "south": "s", "east": "e", "west": "w",
    }
    tokens = [replacements.get(token, token) for token in text.split()]
    return " ".join(tokens) or None


def haversine_m(lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None) -> float | None:
    if None in (lat1, lon1, lat2, lon2):
        return None
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def name_similarity(left: str | None, right: str | None) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def load_accounts() -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                select account_id, name, website_domain, phone, normalized_address,
                       full_address, lat, lon, fit_score, territory
                from marts.dim_account
                order by name, account_id
                """
            )
            accounts = [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
    for account in accounts:
        account["account_id"] = str(account["account_id"])
        account["domain_norm"] = normalize_domain(account.get("website_domain"))
        account["phone_norm"] = normalize_phone(account.get("phone"))
        account["address_norm"] = normalize_address(account.get("normalized_address") or account.get("full_address"))
        account["name_norm"] = normalize_name(account.get("name"))
    return accounts


def load_crm(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Mock CRM seed not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["crm_account_id"] = str(row["crm_account_id"])
        row["domain_norm"] = normalize_domain(row.get("domain"))
        row["phone_norm"] = normalize_phone(row.get("phone"))
        row["address_norm"] = normalize_address(row.get("address"))
        row["name_norm"] = normalize_name(row.get("crm_name"))
        row["lat"] = float(row["lat"]) if clean(row.get("lat")) else None
        row["lon"] = float(row["lon"]) if clean(row.get("lon")) else None
    return rows


def candidate_distance(account: dict[str, Any], crm: dict[str, Any]) -> float | None:
    return haversine_m(account.get("lat"), account.get("lon"), crm.get("lat"), crm.get("lon"))


def assign(
    account: dict[str, Any],
    crm: dict[str, Any],
    method: str,
    confidence: float,
    evidence: str,
    assigned: dict[str, dict[str, Any]],
    used_crm: set[str],
    min_confidence: float,
    ambiguous: bool = False,
) -> None:
    assigned[account["account_id"]] = {
        "crm": crm,
        "match_method": method,
        "match_confidence": round(confidence, 2),
        "match_evidence": evidence,
        "needs_human_review": confidence < min_confidence or ambiguous,
        "ambiguous": ambiguous,
    }
    used_crm.add(crm["crm_account_id"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-crm", type=Path, default=DEFAULT_MOCK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-confidence", type=float, default=95.0)
    parser.add_argument("--fuzzy-name-threshold", type=float, default=0.55)
    parser.add_argument("--max-geo-meters", type=float, default=500.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    accounts = load_accounts()
    crm_records = load_crm(args.mock_crm)
    assigned: dict[str, dict[str, Any]] = {}
    used_crm: set[str] = set()

    # 1. Exact domain.
    for account in accounts:
        if not account["domain_norm"]:
            continue
        candidates = [
            crm for crm in crm_records
            if crm["domain_norm"] == account["domain_norm"] and crm["crm_account_id"] not in used_crm
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda c: name_similarity(account["name_norm"], c["name_norm"]), reverse=True)
        best = candidates[0]
        assign(
            account, best, "exact_domain", 100.0,
            f"domain={account['domain_norm']}",
            assigned, used_crm, args.min_confidence, ambiguous=len(candidates) > 1,
        )

    # 2. Exact phone + address.
    for account in accounts:
        if account["account_id"] in assigned:
            continue
        if not account["phone_norm"] or not account["address_norm"]:
            continue
        candidates = [
            crm for crm in crm_records
            if crm["phone_norm"] == account["phone_norm"]
            and crm["address_norm"] == account["address_norm"]
            and crm["crm_account_id"] not in used_crm
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda c: name_similarity(account["name_norm"], c["name_norm"]), reverse=True)
        best = candidates[0]
        assign(
            account, best, "exact_phone_address", 100.0,
            f"phone={account['phone_norm']}; address={account['address_norm']}",
            assigned, used_crm, args.min_confidence, ambiguous=len(candidates) > 1,
        )

    # 3. Fuzzy name + geo.
    fuzzy_candidates: list[tuple[float, float, float, dict[str, Any], dict[str, Any]]] = []
    for account in accounts:
        if account["account_id"] in assigned:
            continue
        for crm in crm_records:
            if crm["crm_account_id"] in used_crm:
                continue
            similarity = name_similarity(account["name_norm"], crm["name_norm"])
            distance = candidate_distance(account, crm)
            if similarity < args.fuzzy_name_threshold or distance is None or distance > args.max_geo_meters:
                continue
            geo_score = max(0.0, 1.0 - distance / args.max_geo_meters)
            confidence = 100.0 * (0.70 * similarity + 0.30 * geo_score)
            fuzzy_candidates.append((confidence, similarity, distance, account, crm))

    fuzzy_candidates.sort(key=lambda item: (-item[0], item[3]["account_id"], item[4]["crm_account_id"]))
    for confidence, similarity, distance, account, crm in fuzzy_candidates:
        if account["account_id"] in assigned or crm["crm_account_id"] in used_crm:
            continue
        assign(
            account, crm, "fuzzy_name_geo", confidence,
            f"name_similarity={similarity:.3f}; distance_m={distance:.1f}; "
            f"formula=0.70*name+0.30*geo",
            assigned, used_crm, args.min_confidence,
        )

    rows: list[dict[str, Any]] = []
    method_counts: dict[str, int] = {}
    review_count = 0
    for account in accounts:
        match = assigned.get(account["account_id"])
        if match is None:
            method = "unmatched"
            confidence = 0.0
            review = False
            crm = None
            evidence = "no_candidate"
        else:
            method = match["match_method"]
            confidence = match["match_confidence"]
            review = match["needs_human_review"]
            crm = match["crm"]
            evidence = match["match_evidence"]
        method_counts[method] = method_counts.get(method, 0) + 1
        review_count += int(review)
        rows.append({
            "account_id": account["account_id"],
            "account_name": account["name"],
            "warehouse_domain": account.get("website_domain"),
            "warehouse_phone": account.get("phone"),
            "warehouse_address": account.get("normalized_address") or account.get("full_address"),
            "crm_account_id": crm["crm_account_id"] if crm else "",
            "crm_name": crm["crm_name"] if crm else "",
            "crm_domain": crm.get("domain") if crm else "",
            "crm_phone": crm.get("phone") if crm else "",
            "crm_address": crm.get("address") if crm else "",
            "match_method": method,
            "match_confidence": f"{confidence:.2f}",
            "needs_human_review": "true" if review else "false",
            "match_evidence": evidence,
        })

    if not args.dry_run:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    crm_only = sorted({c["crm_account_id"] for c in crm_records} - used_crm)
    summary = {
        "dim_accounts": len(accounts),
        "mock_crm_accounts": len(crm_records),
        "mapping_rows": len(rows),
        "method_counts": method_counts,
        "needs_human_review": review_count,
        "crm_only": len(crm_only),
        "crm_only_ids": crm_only,
        "min_confidence": args.min_confidence,
        "output": str(args.output) if not args.dry_run else None,
    }
    print(json.dumps(summary, indent=2, sort_keys=True), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
