"""Phase 3: homepage-only website fingerprinting into raw.website_signals.

Rules:
* One request per normalized host (dedupe first), homepage only.
* 10 second timeout, at most 3 redirects, 2 second polite delay.
* Detection is fragment matching over the raw HTML, final URL, and title.
* Evidence stores the matched fragment strings, not page content.
* Third-party platform pages (Yelp, Facebook, OpenTable, delivery marketplaces)
  are not fetched. The row is still written with fetch_status='skipped_third_party'
  so the gap is visible rather than silently missing.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import warnings
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from extract.db import get_conn, load_dataframe

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

USER_AGENT = "RALI-portfolio/1.0 (restaurant website capability audit; one page per domain)"
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
DEFAULT_SLEEP = 2.0
BATCH_SIZE = 25

ORDERING = [
    ("toasttab.com", "toast"),
    ("bentobox", "bentobox"),
    ("square.site", "square"),
    ("olo.com", "olo"),
    ("chownow", "chownow"),
    ("order.online", "order.online"),
    ("slicelife", "slicelife"),
]

RESERVATIONS = [
    ("resy.com", "resy"),
    ("opentable.com", "opentable"),
    ("exploretock.com", "exploretock"),
    ("sevenrooms", "sevenrooms"),
    ("yelp.com/reservations", "yelp_reservations"),
]

DELIVERY = [
    ("doordash", "doordash"),
    ("ubereats", "ubereats"),
    ("grubhub", "grubhub"),
    ("postmates", "postmates"),
    ("caviar", "caviar"),
]

PLATFORMS = [
    ("wix", "wix"),
    ("squarespace", "squarespace"),
    ("wordpress", "wordpress"),
    ("shopify", "shopify"),
    ("webflow", "webflow"),
    ("godaddy", "godaddy"),
]

# Platform pages that are not the restaurant's own website. Fetching these would
# either produce no signal or pull data from a source whose terms restrict
# caching (Yelp, Google, reservation/delivery marketplaces).
THIRD_PARTY = {
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "youtube.com",
    "linkedin.com",
    "yelp.com",
    "foursquare.com",
    "google.com",
    "goo.gl",
    "tripadvisor.com",
    "doordash.com",
    "ubereats.com",
    "grubhub.com",
    "postmates.com",
    "caviar.com",
    "seamless.com",
    "opentable.com",
    "resy.com",
    "exploretock.com",
    "sevenrooms.com",
    "tock.com",
}

DDL = """
CREATE TABLE IF NOT EXISTS raw.website_signals (
    domain                 text PRIMARY KEY,
    has_website            boolean NOT NULL DEFAULT true,
    has_online_ordering    boolean NOT NULL DEFAULT false,
    online_ordering_vendor text,
    has_reservations       boolean NOT NULL DEFAULT false,
    reservation_vendor     text,
    delivery_marketplaces  text[] NOT NULL DEFAULT '{}',
    site_platform          text,
    signal_confidence      text,
    failure_class          text,
    fetch_status           text NOT NULL CHECK (
        fetch_status IN ('ok', 'timeout', 'http_error', 'dns_error', 'skipped_third_party')
    ),
    http_status             integer,
    final_url               text,
    page_title              text,
    evidence                text,
    error_detail            text,
    account_count           integer NOT NULL DEFAULT 1,
    fetched_at              timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS website_signals_status_idx
    ON raw.website_signals (fetch_status);

COMMENT ON TABLE raw.website_signals IS
    'Observed homepage fragments for restaurant domains. Real observed data; '
    'one row per domain, homepage only, no page content stored.';
COMMENT ON COLUMN raw.website_signals.evidence IS
    'Concatenated matched fragment strings (ordering/reservation/delivery/platform). '
    'Null when no matched fragment was found, including failed or skipped fetches.';
COMMENT ON COLUMN raw.website_signals.error_detail IS
    'Failure or skip detail for non-ok rows; null for ok rows.';
COMMENT ON COLUMN raw.website_signals.signal_confidence IS
    'confirmed = ok with at least one matched fragment; unknown_no_match = ok with no fragment; unknown_unreachable = failed or skipped. Page-level, not per-capability.';
COMMENT ON COLUMN raw.website_signals.failure_class IS
    'blocked, not_found, server_error, timeout, dns_error, connection_or_redirect, or skipped_third_party; null for ok.';
COMMENT ON COLUMN raw.website_signals.fetch_status IS
    'ok, timeout, http_error, dns_error, or skipped_third_party (not fetched).';
"""


def normalize_website(raw: str | None) -> tuple[str, str, bool] | None:
    """Return (domain, homepage_url, is_third_party), or None if unparseable."""
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = "https://" + value
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    scheme = parsed.scheme.lower() if parsed.scheme.lower() in {"http", "https"} else "https"
    return host, f"{scheme}://{host}/", host in THIRD_PARTY


def collect_domains() -> tuple[pd.DataFrame, dict[str, int]]:
    """Read account websites and dedupe to one row per domain. No network calls."""
    conn = get_conn()
    try:
        accounts = pd.read_sql(
            "select dedup_key, name, website from intermediate.int_account_deduped "
            "where website is not null",
            conn,
        )
    finally:
        conn.close()

    rows: list[dict[str, Any]] = []
    invalid = 0
    for _, account in accounts.iterrows():
        normalized = normalize_website(account["website"])
        if normalized is None:
            invalid += 1
            continue
        domain, homepage_url, third_party = normalized
        rows.append(
            {
                "domain": domain,
                "homepage_url": homepage_url,
                "is_third_party": third_party,
                "account_name": account["name"],
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, {"accounts": len(accounts), "invalid": invalid, "domains": 0}

    grouped = (
        frame.groupby("domain", as_index=False)
        .agg(
            homepage_url=("homepage_url", "first"),
            is_third_party=("is_third_party", "max"),
            account_count=("account_name", "count"),
            example_account=("account_name", "first"),
        )
        .sort_values("domain")
    )
    stats = {
        "accounts": len(accounts),
        "invalid": invalid,
        "domains": len(grouped),
        "third_party_domains": int(grouped["is_third_party"].sum()),
        "fetchable_domains": int((~grouped["is_third_party"]).sum()),
        "third_party_accounts": int(
            frame.loc[frame["is_third_party"], "account_name"].count()
        ),
    }
    return grouped, stats


def detect_signals(haystack: str) -> dict[str, Any]:
    evidence: list[str] = []
    ordering_vendor = None
    reservation_vendor = None
    delivery: list[str] = []
    platform = None

    for fragment, vendor in ORDERING:
        if fragment in haystack:
            evidence.append(f"ordering:{fragment}")
            ordering_vendor = ordering_vendor or vendor

    for fragment, vendor in RESERVATIONS:
        if fragment in haystack:
            evidence.append(f"reservation:{fragment}")
            reservation_vendor = reservation_vendor or vendor

    for fragment, vendor in DELIVERY:
        if fragment in haystack:
            evidence.append(f"delivery:{fragment}")
            delivery.append(vendor)

    for fragment, vendor in PLATFORMS:
        if fragment in haystack:
            evidence.append(f"platform:{fragment}")
            platform = platform or vendor

    return {
        "has_online_ordering": ordering_vendor is not None,
        "online_ordering_vendor": ordering_vendor,
        "has_reservations": reservation_vendor is not None,
        "reservation_vendor": reservation_vendor,
        "delivery_marketplaces": sorted(set(delivery)),
        "site_platform": platform,
        "evidence": "; ".join(evidence) if evidence else None,
    }


def _row_base(domain: str, account_count: int, third_party: bool) -> dict[str, Any]:
    return {
        "domain": domain,
        "has_website": True,
        "has_online_ordering": False,
        "online_ordering_vendor": None,
        "has_reservations": False,
        "reservation_vendor": None,
        "delivery_marketplaces": [],
        "site_platform": None,
        "signal_confidence": "unknown_unreachable",
        "failure_class": None,
        "fetch_status": "skipped_third_party" if third_party else "http_error",
        "http_status": None,
        "final_url": None,
        "page_title": None,
        "evidence": None,
        "error_detail": "not fetched: third-party platform page"
        if third_party
        else None,
        "account_count": account_count,
        "fetched_at": datetime.now(timezone.utc),
    }


def finalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Derive page-level signal confidence and a failure class.

    confirmed means the page loaded and at least one known fragment matched.
    It is page-level: it does not prove that a specific absent capability is
    absent. unknown_no_match means the page loaded but nothing matched;
    unknown_unreachable means we have no fingerprint (failure or skip).
    """
    status = row["fetch_status"]
    if status == "ok":
        row["signal_confidence"] = "confirmed" if row.get("evidence") else "unknown_no_match"
        row["failure_class"] = None
        return row

    row["signal_confidence"] = "unknown_unreachable"
    http_status = row.get("http_status")
    if status == "skipped_third_party":
        row["failure_class"] = "skipped_third_party"
    elif status == "timeout":
        row["failure_class"] = "timeout"
    elif status == "dns_error":
        row["failure_class"] = "dns_error"
    elif http_status in (401, 403, 429):
        row["failure_class"] = "blocked"
    elif http_status in (404, 410):
        row["failure_class"] = "not_found"
    elif http_status is not None and http_status >= 500:
        row["failure_class"] = "server_error"
    else:
        row["failure_class"] = "connection_or_redirect"
    return row


def fetch_one(session: requests.Session, domain: str, homepage_url: str, account_count: int) -> dict[str, Any]:
    row = _row_base(domain, account_count, third_party=False)
    try:
        response = session.get(homepage_url, timeout=10, allow_redirects=True)
        row["http_status"] = int(response.status_code)
        row["final_url"] = response.url[:1000]
        if response.status_code >= 400:
            row["fetch_status"] = "http_error"
            row["evidence"] = None
            row["error_detail"] = f"HTTP {response.status_code} {response.reason}"[:300]
            return row

        raw_html = response.text[:MAX_BYTES]
        try:
            soup = BeautifulSoup(raw_html, "lxml")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
        except Exception:
            title = ""
        row["page_title"] = title[:200] if title else None
        haystack = f"{raw_html} {response.url} {title}".lower()
        row["fetch_status"] = "ok"
        row.update(detect_signals(haystack))
        return row
    except requests.exceptions.TooManyRedirects as exc:
        row["fetch_status"] = "http_error"
        row["evidence"] = None
        row["error_detail"] = f"too_many_redirects: {exc}"[:300]
        return row
    except requests.exceptions.Timeout as exc:
        row["fetch_status"] = "timeout"
        row["evidence"] = None
        row["error_detail"] = f"timeout: {exc}"[:300]
        return row
    except requests.exceptions.ConnectionError as exc:
        text = str(exc).lower()
        dns = any(
            token in text
            for token in (
                "name or service not known",
                "nodename nor servname",
                "getaddrinfo",
                "name resolution",
                "temporary failure in name resolution",
            )
        )
        row["fetch_status"] = "dns_error" if dns else "http_error"
        row["evidence"] = None
        row["error_detail"] = f"{row['fetch_status']}: {exc}"[:300]
        return row
    except requests.exceptions.RequestException as exc:
        row["fetch_status"] = "http_error"
        row["evidence"] = None
        row["error_detail"] = f"request_exception: {exc}"[:300]
        return row
    except Exception as exc:  # parsing/encoding edge cases should not kill the run
        row["fetch_status"] = "http_error"
        row["evidence"] = None
        row["error_detail"] = f"unexpected: {type(exc).__name__}: {exc}"[:300]
        return row


def load_rows(conn, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    frame = pd.DataFrame(rows)
    frame["http_status"] = frame["http_status"].astype("Int64")
    load_dataframe(
        conn,
        frame,
        "raw",
        "website_signals",
        ddl=DDL,
        mode="upsert",
        conflict_key="domain",
    )


def existing_domains(conn) -> set[str]:
    try:
        with conn.cursor() as cur:
            cur.execute("select domain from raw.website_signals")
            return {r[0] for r in cur.fetchall()}
    except Exception:
        conn.rollback()
        return set()


def print_count_report(domains: pd.DataFrame, stats: dict[str, int]) -> None:
    print("Website domain accounting")
    print(f"  accounts with a website: {stats['accounts']}")
    print(f"  invalid/unparseable URLs: {stats['invalid']}")
    print(f"  unique domains: {stats['domains']}")
    print(f"  third-party domains (not fetched): {stats['third_party_domains']}")
    print(f"  first-party fetchable domains: {stats['fetchable_domains']}")
    print(f"  accounts behind third-party domains: {stats['third_party_accounts']}")
    if not domains.empty:
        top = domains.sort_values("account_count", ascending=False).head(10)
        print("  top domains by account count:")
        for _, row in top.iterrows():
            print(f"    {row['domain']}: {row['account_count']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count-only", action="store_true", help="Report domains; no fetches")
    parser.add_argument("--limit", type=int, default=None, help="Fetch at most N domains")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP, help="Delay between fetches")
    parser.add_argument("--refresh", action="store_true", help="Refetch domains already loaded")
    args = parser.parse_args()

    domains, stats = collect_domains()
    print_count_report(domains, stats)
    if stats["fetchable_domains"] > 2000:
        print(
            f"\nSTOP: {stats['fetchable_domains']} first-party domains exceeds the 2,000 cap. "
            "Nothing was fetched."
        )
        return 2
    if args.count_only:
        print("\nCount-only: no fetches made.")
        return 0

    conn = get_conn()
    done = set() if args.refresh else existing_domains(conn)
    todo = domains[~domains["domain"].isin(done)].copy()
    if args.limit is not None:
        todo = todo.head(args.limit)
    print(f"\nFetching {len(todo)} domains; {len(done)} already loaded; 2s delay between requests.")

    session = requests.Session()
    session.max_redirects = MAX_REDIRECTS
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    fetched = 0
    try:
        for _, item in todo.iterrows():
            domain = item["domain"]
            if item["is_third_party"]:
                row = _row_base(domain, int(item["account_count"]), third_party=True)
            else:
                row = fetch_one(session, domain, item["homepage_url"], int(item["account_count"]))
                time.sleep(max(0.0, args.sleep))
            row = finalize_row(row)
            rows.append(row)
            counts[row["fetch_status"]] = counts.get(row["fetch_status"], 0) + 1
            fetched += 1

            if len(rows) >= BATCH_SIZE:
                load_rows(conn, rows)
                rows = []
            if fetched % 25 == 0 or fetched == len(todo):
                print(f"  progress {fetched}/{len(todo)} statuses={counts}", flush=True)
    finally:
        try:
            load_rows(conn, rows)
        finally:
            conn.close()
            session.close()

    print("\nFetch status counts")
    for status, count in sorted(counts.items()):
        print(f"  {status}: {count}")
    attempted = sum(c for s, c in counts.items() if s != "skipped_third_party")
    ok = counts.get("ok", 0)
    if attempted:
        print(f"  success rate (ok / attempted): {ok}/{attempted} = {ok / attempted:.1%}")
    print(f"  success rate (ok / all domains): {ok}/{sum(counts.values())} = {ok / max(1, sum(counts.values())):.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
