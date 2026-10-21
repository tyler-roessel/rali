"""Supabase/Postgres connection and bulk-load helpers for RALI.

Design notes
------------
* Connections use the Supabase **session pooler** (port 5432). The transaction
  pooler (6543) is deliberately not supported because it breaks the prepared
  statements and DDL that dbt relies on.
* Bulk loads use ``COPY ... FROM STDIN`` rather than ``executemany``. Row-by-row
  inserts over a pooler are slow enough to time out on a free-tier project.
* ``mode="replace"`` is a truncate-then-COPY inside one transaction. If the COPY
  fails, the truncate rolls back too.
* ``mode="upsert"`` stages the frame in a temp table and then runs
  ``INSERT ... ON CONFLICT``. COPY itself cannot express ON CONFLICT.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

REQUIRED_ENV = ("SUPABASE_HOST", "SUPABASE_USER", "SUPABASE_DB_PASSWORD")


def get_conn():
    """Open a connection to the Supabase session pooler.

    Reads ``.env`` from the repository root. Environment variables that are
    already set win over the file, which makes CI/one-off overrides possible.
    """
    load_dotenv(ENV_PATH, override=False)
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            "Missing Supabase credentials: "
            + ", ".join(missing)
            + f". Copy .env.example to {ENV_PATH.name} and fill in the session "
            "pooler values (Project Settings -> Database -> Connection string)."
        )

    return psycopg2.connect(
        host=os.environ["SUPABASE_HOST"],
        port=int(os.environ.get("SUPABASE_PORT", "5432")),
        user=os.environ["SUPABASE_USER"],
        password=os.environ["SUPABASE_DB_PASSWORD"],
        dbname=os.environ.get("SUPABASE_DB_NAME", "postgres"),
        sslmode=os.environ.get("SUPABASE_SSLMODE", "require"),
        connect_timeout=int(os.environ.get("SUPABASE_CONNECT_TIMEOUT", "15")),
        application_name="rali",
    )


def ensure_schema(conn, name: str) -> None:
    """Create a schema if it does not exist. Identifier is quoted, never f-stringed."""
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(name)))


def _as_pg_array(value) -> str | None:
    """Encode a Python sequence as a Postgres array literal for COPY.

    Values are always double-quoted so commas, braces, and empty strings survive
    the CSV/COPY round trip.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    if isinstance(value, (list, tuple, set)):
        items = []
        for item in value:
            text = str(item).replace("\\", "\\\\").replace('"', '\\"')
            items.append(f'"{text}"')
        return "{" + ",".join(items) + "}"
    return None


def _prepare_frame(df: pd.DataFrame, columns: Sequence[str] | None) -> pd.DataFrame:
    frame = df.copy()
    if columns is not None:
        missing = [c for c in columns if c not in frame.columns]
        if missing:
            raise ValueError(f"DataFrame is missing columns: {missing}")
        frame = frame.loc[:, list(columns)]

    # psycopg2/COPY has no native list encoder; turn list columns into text[]
    # literals before serialising to CSV.
    for col in frame.columns:
        if frame[col].dtype == object:
            frame[col] = frame[col].map(
                lambda v: _as_pg_array(v) if isinstance(v, (list, tuple, set)) else v
            )
    return frame


def _copy_sql(conn, schema: str, table: str, columns: Sequence[str]) -> str:
    # pg_temp is a special alias, not a normal identifier: quote the table but
    # leave pg_temp unquoted so Postgres resolves the session's temp schema.
    if schema == "pg_temp":
        target = sql.SQL("pg_temp.{}").format(sql.Identifier(table))
    else:
        target = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))
    return sql.SQL(
        "COPY {} ({}) FROM STDIN WITH (FORMAT csv, NULL '', HEADER false)"
    ).format(
        target,
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
    ).as_string(conn)


def _target_exists(conn, schema: str, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"{schema}.{table}",))
        return bool(cur.fetchone()[0])


def load_dataframe(
    conn,
    df: pd.DataFrame,
    schema: str,
    table: str,
    *,
    ddl: str | None = None,
    columns: Sequence[str] | None = None,
    mode: str = "replace",
    conflict_key: str | Sequence[str] | None = None,
) -> int:
    """Load a DataFrame into ``schema.table`` with COPY.

    Parameters
    ----------
    ddl:
        Optional DDL run first, e.g. ``CREATE TABLE IF NOT EXISTS ...``.
    mode:
        ``replace`` truncates the target and reloads it; ``upsert`` stages rows
        in a temp table and merges on ``conflict_key``.
    conflict_key:
        Natural key column(s) for ``mode="upsert"``.
    """
    if mode not in {"replace", "upsert"}:
        raise ValueError("mode must be 'replace' or 'upsert'")
    if mode == "upsert" and not conflict_key:
        raise ValueError("mode='upsert' requires conflict_key")

    frame = _prepare_frame(df, columns)
    if frame.columns.empty:
        raise ValueError("Cannot load a DataFrame with no columns")

    keys: list[str] = []
    if conflict_key is not None:
        keys = [conflict_key] if isinstance(conflict_key, str) else list(conflict_key)

    buf = io.StringIO()
    frame.to_csv(
        buf,
        index=False,
        header=False,
        na_rep="",
        lineterminator="\n",
    )
    buf.seek(0)

    with conn:  # commit on success, roll back on failure
        ensure_schema(conn, schema)
        with conn.cursor() as cur:
            if ddl:
                cur.execute(ddl)

            if not _target_exists(conn, schema, table):
                raise RuntimeError(
                    f"Target {schema}.{table} does not exist and no ddl was supplied"
                )

            if mode == "replace":
                cur.execute(
                    sql.SQL("TRUNCATE TABLE {}.{}").format(
                        sql.Identifier(schema), sql.Identifier(table)
                    )
                )
                copy_target = (schema, table)
            else:
                tmp_name = f"_rali_load_{table}"
                cur.execute(
                    sql.SQL(
                        "CREATE TEMP TABLE {} (LIKE {}.{} INCLUDING DEFAULTS) "
                        "ON COMMIT DROP"
                    ).format(
                        sql.Identifier(tmp_name),
                        sql.Identifier(schema),
                        sql.Identifier(table),
                    )
                )
                copy_target = ("pg_temp", tmp_name)

            cur.copy_expert(
                _copy_sql(conn, copy_target[0], copy_target[1], list(frame.columns)),
                buf,
            )
            copied = len(frame)

            if mode == "upsert":
                update_cols = [c for c in frame.columns if c not in keys]
                conflict = sql.SQL(", ").join(sql.Identifier(k) for k in keys)
                insert_cols = sql.SQL(", ").join(sql.Identifier(c) for c in frame.columns)
                if update_cols:
                    action = sql.SQL("DO UPDATE SET ") + sql.SQL(", ").join(
                        sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(c))
                        for c in update_cols
                    )
                else:
                    action = sql.SQL("DO NOTHING")
                if copy_target[0] == "pg_temp":
                    source = sql.SQL("pg_temp.{}").format(sql.Identifier(copy_target[1]))
                else:
                    source = sql.SQL("{}.{}").format(
                        sql.Identifier(copy_target[0]), sql.Identifier(copy_target[1])
                    )
                cur.execute(
                    sql.SQL(
                        "INSERT INTO {}.{} ({}) SELECT {} FROM {} "
                        "ON CONFLICT ({}) {}"
                    ).format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        insert_cols,
                        insert_cols,
                        source,
                        conflict,
                        action,
                    )
                )

    return copied


def preview(conn, schema: str, table: str, limit: int = 10) -> pd.DataFrame:
    """Small helper for gate reports; read-only."""
    query = sql.SQL("SELECT * FROM {}.{} LIMIT %s").format(
        sql.Identifier(schema), sql.Identifier(table)
    )
    return pd.read_sql(query.as_string(conn), conn, params=(limit,))


if __name__ == "__main__":
    # Connectivity smoke test used by Phase 0's gate.
    with get_conn() as connection:
        with connection.cursor() as cursor:
            cursor.execute("select current_user, current_database(), version()")
            user, database, version = cursor.fetchone()
            print(f"connected as {user} to {database}")
            print(version.split(",")[0])
