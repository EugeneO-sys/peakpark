"""
db.py - database access layer for SmartPark KE.

We use plain sqlite3 (standard library, zero extra dependencies) rather
than an ORM so the schema in schema.sql is the single, readable source
of truth for the "dynamic database" required by Task One.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "smartpark.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_connection():
    """Return a new sqlite3 connection with rows addressable by column name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(reset=False):
    """
    Create the schema if it does not exist, and seed it with a small,
    realistic starting dataset (zones, bays, default rate tiers) the
    first time the app runs. Safe to call on every startup.
    """
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = get_connection()
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())

    # Seed only if empty, so re-running the app never duplicates data.
    zone_count = conn.execute("SELECT COUNT(*) AS c FROM zones").fetchone()["c"]
    if zone_count == 0:
        _seed(conn)

    conn.commit()
    conn.close()


def _seed(conn):
    # Two zones, 10 bays each -- change/add zones any time via SQL/admin,
    # no code change required.
    zones = ["Zone A - Ground Floor", "Zone B - Basement"]
    zone_ids = []
    for name in zones:
        cur = conn.execute("INSERT INTO zones (name) VALUES (?)", (name,))
        zone_ids.append(cur.lastrowid)

    for zi, zone_id in enumerate(zone_ids):
        prefix = chr(ord("A") + zi)
        for n in range(1, 11):
            code = f"{prefix}-{n:02d}"
            conn.execute(
                "INSERT INTO bays (code, zone_id, status) VALUES (?, ?, 'FREE')",
                (code, zone_id),
            )

    # Default fee schedule, taken from the client's terms of reference.
    # Management can add/edit tiers later from the Admin > Rates screen
    # without touching this code.
    tiers = [
        ("Up to 30 minutes", 30, 0, 1),
        ("Up to 2 hours", 120, 50, 2),
        ("Up to 4 hours", 240, 100, 3),
        ("Up to 6 hours", 360, 300, 4),
        ("Over 6 hours", None, 500, 5),
    ]
    for label, max_minutes, amount, order in tiers:
        conn.execute(
            "INSERT INTO rate_tiers (label, max_minutes, amount_kshs, sort_order, active) "
            "VALUES (?, ?, ?, ?, 1)",
            (label, max_minutes, amount, order),
        )


def log_event(conn, session_id, event, details=""):
    """Append an immutable audit trail entry. Never update/delete these rows."""
    conn.execute(
        "INSERT INTO audit_log (session_id, event, details) VALUES (?, ?, ?)",
        (session_id, event, details),
    )
