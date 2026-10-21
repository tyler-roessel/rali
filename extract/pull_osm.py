"""Phase 1: pull Chicago full-service restaurants from Overpass into raw.osm_restaurants.

Scope decisions (approved 2026-10-20):
* ``amenity=restaurant`` only. ``fast_food`` is excluded so the account universe
  is independent full-service operators, not quick-service chains.
* Chain outlets are filtered in Python on the presence of ``brand`` or
  ``brand:wikidata``. The curated alias seed is a secondary check in Phase 2,
  not the primary chain filter.
* One request. On 429/504/timeout, wait 60 seconds and retry once, then stop.
* If the bbox returns more than 2,000 records, stop and report. Do not truncate.
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from extract.db import PROJECT_ROOT, get_conn, load_dataframe

OVERPASS_URL = os.environ.get(
    "OVERPASS_URL", "https://overpass-api.de/api/interpreter"
)
USER_AGENT = "RALI-portfolio/1.0 (restaurant account lifecycle modeling; one-shot extract)"

BBOX = "41.64,-87.94,42.03,-87.52"  # south,west,north,east

QUERY = f"""
[out:json][timeout:60];
(
  node["amenity"="restaurant"]["name"]({BBOX});
  way["amenity"="restaurant"]["name"]({BBOX});
);
out center;
""".strip()

RAW_DIR = PROJECT_ROOT / "data" / "raw"

TEXT_COLUMNS = [
    "osm_uid",
    "osm_type",
    "name",
    "cuisine",
    "addr_street",
    "addr_housenumber",
    "addr_city",
    "addr_postcode",
    "phone",
    "website",
    "opening_hours",
    "brand",
    "operator",
]

DDL = """
CREATE TABLE IF NOT EXISTS raw.osm_restaurants (
    osm_uid         text PRIMARY KEY,
    osm_id          bigint NOT NULL,
    osm_type        text NOT NULL CHECK (osm_type IN ('node', 'way')),
    name            text NOT NULL,
    cuisine         text,
    addr_street     text,
    addr_housenumber text,
    addr_city       text,
    addr_postcode   text,
    phone           text,
    website         text,
    opening_hours   text,
    brand           text,
    operator        text,
    lat             double precision,
    lon             double precision,
    loaded_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (osm_type, osm_id)
);

CREATE INDEX IF NOT EXISTS osm_restaurants_city_idx
    ON raw.osm_restaurants (lower(addr_city));
CREATE INDEX IF NOT EXISTS osm_restaurants_name_idx
    ON raw.osm_restaurants (lower(name));

COMMENT ON TABLE raw.osm_restaurants IS
    'Real OpenStreetMap restaurant records (amenity=restaurant), Chicago bbox. '
    'Chain-tagged outlets excluded in Python. Source: Overpass API, ODbL.';
COMMENT ON COLUMN raw.osm_restaurants.osm_uid IS
    'Synthetic stable key: osm_type || '':'' || osm_id. OSM ids are only unique per element type.';
COMMENT ON COLUMN raw.osm_restaurants.loaded_at IS
    'Load timestamp for this snapshot; full refresh, not an event time.';
"""


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _truthy_tag(value: Any) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() not in {"", "no", "none", "false", "0"}


def _parse_end_date(value: str) -> date | None:
    """Parse the common OSM end_date forms. Unparseable values are not treated
    as past, so a data-quality quirk cannot silently drop a live restaurant."""
    match = re.match(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", str(value).strip())
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2)) if match.group(2) else None
    day = int(match.group(3)) if match.group(3) else None
    try:
        if day and month:
            return date(year, month, day)
        if month:
            return date(year, month, calendar.monthrange(year, month)[1])
        return date(year, 12, 31)
    except ValueError:
        return None


def fetch_overpass(url: str = OVERPASS_URL) -> dict[str, Any]:
    """One POST, with the spec's single 60-second retry on 429/504/timeout."""
    last_error: str | None = None
    for attempt in (1, 2):
        try:
            response = requests.post(
                url,
                data={"data": QUERY},
                headers={"User-Agent": USER_AGENT},
                timeout=(15, 180),
            )
            if response.status_code in (429, 504):
                last_error = f"HTTP {response.status_code}"
                if attempt == 1:
                    print(f"Overpass returned {last_error}; waiting 60s before one retry.")
                    time.sleep(60)
                    continue
                break
            response.raise_for_status()
            payload = response.json()
            remark = str(payload.get("remark", ""))
            if "runtime error" in remark.lower() or "timed out" in remark.lower():
                raise RuntimeError(f"Overpass runtime error: {remark}")
            return payload
        except requests.Timeout:
            last_error = "timeout"
            if attempt == 1:
                print("Overpass timed out; waiting 60s before one retry.")
                time.sleep(60)
                continue
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            break
    raise RuntimeError(
        f"Overpass extract failed after retry ({last_error}). "
        f"Endpoint: {url}. No records were loaded."
    )


def _row_from_element(element: dict[str, Any]) -> dict[str, Any] | None:
    tags = element.get("tags") or {}
    name = _clean(tags.get("name"))
    if not name:
        return None

    osm_type = element.get("type")
    if osm_type not in {"node", "way"}:
        return None

    if osm_type == "node":
        lat, lon = element.get("lat"), element.get("lon")
    else:
        center = element.get("center") or {}
        lat, lon = center.get("lat"), center.get("lon")

    return {
        "osm_uid": f"{osm_type}:{element['id']}",
        "osm_id": int(element["id"]),
        "osm_type": osm_type,
        "name": name,
        "cuisine": _clean(tags.get("cuisine")),
        "addr_street": _clean(tags.get("addr:street")),
        "addr_housenumber": _clean(tags.get("addr:housenumber")),
        "addr_city": _clean(tags.get("addr:city")),
        "addr_postcode": _clean(tags.get("addr:postcode")),
        "phone": _clean(tags.get("phone") or tags.get("contact:phone")),
        "website": _clean(tags.get("website") or tags.get("contact:website")),
        "opening_hours": _clean(tags.get("opening_hours")),
        "brand": _clean(tags.get("brand")),
        "operator": _clean(tags.get("operator")),
        "lat": float(lat) if lat is not None else None,
        "lon": float(lon) if lon is not None else None,
    }


def build_frame(payload: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, int]]:
    elements = payload.get("elements") or []
    stats = {
        "elements_returned": len(elements),
        "excluded_missing_name": 0,
        "excluded_disused_or_abandoned": 0,
        "excluded_past_end_date": 0,
        "excluded_chain_tagged": 0,
        "final": 0,
    }
    rows: list[dict[str, Any]] = []
    today = date.today()

    for element in elements:
        tags = element.get("tags") or {}
        if not _clean(tags.get("name")):
            stats["excluded_missing_name"] += 1
            continue
        if _truthy_tag(tags.get("disused")) or _truthy_tag(tags.get("abandoned")):
            stats["excluded_disused_or_abandoned"] += 1
            continue
        end_date = tags.get("end_date")
        if end_date and (_parse_end_date(end_date) or date.max) < today:
            stats["excluded_past_end_date"] += 1
            continue
        if _clean(tags.get("brand")) or _clean(tags.get("brand:wikidata")):
            stats["excluded_chain_tagged"] += 1
            continue

        row = _row_from_element(element)
        if row is not None:
            rows.append(row)

    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=TEXT_COLUMNS + ["osm_id", "lat", "lon"])
    else:
        frame = frame[TEXT_COLUMNS + ["osm_id", "lat", "lon"]]
        frame["osm_id"] = frame["osm_id"].astype("int64")
        frame["lat"] = pd.to_numeric(frame["lat"], errors="coerce")
        frame["lon"] = pd.to_numeric(frame["lon"], errors="coerce")
    stats["final"] = len(frame)
    return frame, stats


def null_rates(frame: pd.DataFrame) -> dict[str, float]:
    return {
        col: round(float(frame[col].isna().mean()) if len(frame) else 0.0, 4)
        for col in ("name", "website", "phone", "cuisine")
    }


def save_raw(payload: dict[str, Any]) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RAW_DIR / f"overpass_restaurants_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def print_sample(frame: pd.DataFrame, n: int = 10) -> None:
    cols = ["osm_uid", "name", "cuisine", "addr_city", "website", "phone", "lat", "lon"]
    print(frame[cols].head(n).to_string(index=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=2000, help="Stop above this count")
    parser.add_argument(
        "--from-file",
        type=Path,
        help="Load a previously saved Overpass JSON payload instead of fetching",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and filter, do not load")
    args = parser.parse_args()

    if args.from_file:
        print(f"Payload: {args.from_file} (no network request)")
        payload = json.loads(args.from_file.read_text(encoding="utf-8"))
        raw_path = args.from_file
    else:
        print(f"Overpass endpoint: {OVERPASS_URL}")
        print(f"Bbox: {BBOX}")
        payload = fetch_overpass()
        raw_path = save_raw(payload)
    frame, stats = build_frame(payload)

    print("\nExtract accounting")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print(f"  raw_payload: {raw_path}")

    if stats["elements_returned"] > args.limit:
        print(
            f"\nSTOP: bbox returned {stats['elements_returned']} elements, above the "
            f"{args.limit} cap. Nothing was loaded. Do not truncate randomly."
        )
        return 2
    if stats["final"] < 1200:
        print(
            f"\nWARNING: final count {stats['final']} is below the 1,200 target. "
            "The exact bbox was supplied by the reviewer; not expanding it silently."
        )

    print("\nNull rates")
    for col, rate in null_rates(frame).items():
        print(f"  {col}: {rate:.1%}")

    print("\n10-row sample")
    print_sample(frame)

    if args.dry_run:
        print("\nDry run: no rows loaded.")
        return 0

    conn = get_conn()
    try:
        loaded = load_dataframe(
            conn,
            frame,
            "raw",
            "osm_restaurants",
            ddl=DDL,
            mode="replace",
        )
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM raw.osm_restaurants")
            db_count = cur.fetchone()[0]
    finally:
        conn.close()

    print(f"\nLoaded {loaded} rows into raw.osm_restaurants; table count = {db_count}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
