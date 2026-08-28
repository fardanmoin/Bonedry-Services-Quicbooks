"""Neon PostgreSQL state.

The Render free tier wipes the disk on every deploy, so every piece of state
that has to outlive a request lives here.
"""

import os
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")

SCHEMA = """
CREATE TABLE IF NOT EXISTS synced_leaves (
    unique_id     BIGINT PRIMARY KEY,
    employee_id   TEXT NOT NULL,
    local_date    DATE NOT NULL,
    jobcode       TEXT NOT NULL,
    leavetype_id  TEXT NOT NULL,
    leave_id      TEXT,
    status        INTEGER NOT NULL DEFAULT 0,
    is_hourly     BOOLEAN NOT NULL DEFAULT FALSE,
    start_time    TEXT,
    end_time      TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS employee_mappings (
    source_key   TEXT PRIMARY KEY,
    employee_id  TEXT NOT NULL,
    label        TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS leavetype_mappings (
    jobcode      TEXT PRIMARY KEY,
    leavetype_id TEXT NOT NULL,
    label        TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def available():
    return bool(DATABASE_URL)


def connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set on this service.")
    return psycopg2.connect(DATABASE_URL)


def init():
    if not available():
        return False
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
    return True


def load_employee_overrides():
    if not available():
        return {}
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT source_key, employee_id FROM employee_mappings")
            return {row[0]: row[1] for row in cur.fetchall()}


def save_employee_mapping(source_key, employee_id, label=None):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO employee_mappings (source_key, employee_id, label)
                VALUES (%s, %s, %s)
                ON CONFLICT (source_key) DO UPDATE
                SET employee_id = EXCLUDED.employee_id,
                    label = EXCLUDED.label,
                    updated_at = NOW()
                """,
                (source_key.strip().lower(), str(employee_id), label),
            )


def load_leavetype_map():
    if not available():
        return {}
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT jobcode, leavetype_id FROM leavetype_mappings")
            return {row[0]: row[1] for row in cur.fetchall()}


def save_leavetype_mapping(jobcode, leavetype_id, label=None):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO leavetype_mappings (jobcode, leavetype_id, label)
                VALUES (%s, %s, %s)
                ON CONFLICT (jobcode) DO UPDATE
                SET leavetype_id = EXCLUDED.leavetype_id,
                    label = EXCLUDED.label,
                    updated_at = NOW()
                """,
                (jobcode.strip().lower(), str(leavetype_id), label),
            )


def get_synced(unique_ids):
    if not available() or not unique_ids:
        return {}
    with connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM synced_leaves WHERE unique_id = ANY(%s)",
                (list(unique_ids),),
            )
            return {int(row["unique_id"]): dict(row) for row in cur.fetchall()}


def record_sync(item, leave_id):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO synced_leaves
                    (unique_id, employee_id, local_date, jobcode, leavetype_id,
                     leave_id, status, is_hourly, start_time, end_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (unique_id) DO UPDATE
                SET leave_id = EXCLUDED.leave_id,
                    status = EXCLUDED.status,
                    is_hourly = EXCLUDED.is_hourly,
                    start_time = EXCLUDED.start_time,
                    end_time = EXCLUDED.end_time,
                    updated_at = NOW()
                """,
                (
                    item["unique_id"],
                    item["employee_id"],
                    item["local_date"],
                    item["jobcode"],
                    item["leavetype_id"],
                    leave_id,
                    item["status"],
                    item["is_hourly"],
                    item["start_time"],
                    item["end_time"],
                ),
            )


def recent(limit=100):
    if not available():
        return []
    with connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM synced_leaves ORDER BY updated_at DESC LIMIT %s", (limit,)
            )
            rows = []
            for row in cur.fetchall():
                item = dict(row)
                item["local_date"] = str(item["local_date"])
                item["updated_at"] = str(item["updated_at"])
                item["unique_id"] = int(item["unique_id"])
                rows.append(item)
            return rows
