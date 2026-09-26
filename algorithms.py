"""
algorithms.py - the algorithmic core of SmartPark KE.

Implements, in code, the modules designed on paper in the Task One
report:

  1. Slot Allocation Algorithm   -> AvailabilityManager (queue per zone)
  2. Duration & Fee Algorithm    -> compute_duration_minutes / compute_fee
"""

from collections import deque
from datetime import datetime


class AvailabilityManager:
    """
    Keeps one in-memory FIFO queue of free bay codes per zone.

    Why a queue (collections.deque)?
      - allocate() and release() are both O(1), which matters because
        both fire on the hot path (every single arrival/departure).
      - FIFO order spreads wear/usage evenly across bays and is
        predictable for staff walking the aisles, unlike scanning the
        whole bay table for the first FREE row every time (O(n)).
      - The database (bays.status) remains the durable source of truth
        that survives a restart; this queue is a fast cache rebuilt
        from the database at start-up, so the two can never drift for
        long even if the process is restarted.
    """

    def __init__(self):
        # zone_id -> deque[bay_code]
        self._free_bays = {}
        # bay_code -> (bay_id, zone_id)   for O(1) lookup on release
        self._bay_index = {}

    def load_from_db(self, conn):
        self._free_bays.clear()
        self._bay_index.clear()
        rows = conn.execute(
            "SELECT id, code, zone_id, status FROM bays ORDER BY code"
        ).fetchall()
        for row in rows:
            self._bay_index[row["code"]] = (row["id"], row["zone_id"])
            self._free_bays.setdefault(row["zone_id"], deque())
            if row["status"] == "FREE":
                self._free_bays[row["zone_id"]].append(row["code"])

    def counts_by_zone(self):
        """Return {zone_id: free_count} for the live display board."""
        return {zid: len(q) for zid, q in self._free_bays.items()}

    def allocate(self, zone_id):
        """Pop the next free bay in this zone. O(1). Returns bay_code or None."""
        q = self._free_bays.get(zone_id)
        if not q:
            return None
        return q.popleft()

    def release(self, bay_code):
        """Return a bay to the free pool for its zone. O(1)."""
        _, zone_id = self._bay_index[bay_code]
        self._free_bays[zone_id].append(bay_code)


def compute_duration_minutes(entry_time_str, exit_time_str=None):
    """
    Duration Algorithm.
    entry_time_str / exit_time_str: 'YYYY-MM-DD HH:MM:SS' (as stored by sqlite3).
    Uses "now" when exit_time_str is not supplied (i.e. exit in progress).
    """
    fmt = "%Y-%m-%d %H:%M:%S"
    entry = datetime.strptime(entry_time_str, fmt)
    exit_ = datetime.strptime(exit_time_str, fmt) if exit_time_str else datetime.now()
    delta = exit_ - entry
    return max(0, int(delta.total_seconds() // 60))


def compute_fee(conn, duration_minutes):
    """
    Fee Algorithm.

    Reads the ACTIVE rate tiers from the database, ordered by
    sort_order (a small, sorted list of typically <10 tiers), and
    returns the amount for the first tier the duration fits into.
    A tier with max_minutes = NULL is treated as "infinity" (catch-all
    top tier), so this always terminates with a match.

    Because tiers live in the database, management can insert, edit or
    deactivate a tier at any time -- this function needs no code change
    to reflect a new price list, satisfying the "dynamic rates"
    objective in the terms of reference.
    """
    tiers = conn.execute(
        "SELECT max_minutes, amount_kshs FROM rate_tiers "
        "WHERE active = 1 ORDER BY sort_order ASC"
    ).fetchall()

    for tier in tiers:
        if tier["max_minutes"] is None or duration_minutes <= tier["max_minutes"]:
            return tier["amount_kshs"]

    # Should not happen if an open-ended tier exists, but fail safe.
    return tiers[-1]["amount_kshs"] if tiers else 0
