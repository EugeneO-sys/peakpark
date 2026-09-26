-- =====================================================================
-- SmartPark KE - Dynamic Database Schema
-- Multimedia University of Kenya - DSA Task (Parking Management System)
--
-- "Dynamic" design notes:
--   * Parking capacity is data, not code: adding a zone or a bay is an
--     INSERT, never a code change (Objective: system scales to new sites).
--   * Rates are data, not code: rate_tiers can be edited/added by
--     management at any time via the /admin/rates screen; the fee
--     algorithm re-reads this table on every exit, so rate changes take
--     effect immediately with zero redeploys (Objective: "let management
--     change rates at any time without a software change").
--   * Every rate change and every payment is timestamped and kept
--     (never overwritten), so the system produces an auditable trail
--     of every shilling collected, for reconciliation and VAT.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- A physical area of the car park (e.g. "Ground Floor", "Zone A")
CREATE TABLE IF NOT EXISTS zones (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE
);

-- One parking bay. status is the live truth used by the display board.
CREATE TABLE IF NOT EXISTS bays (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    code     TEXT NOT NULL UNIQUE,               -- e.g. "A-01"
    zone_id  INTEGER NOT NULL REFERENCES zones(id),
    status   TEXT NOT NULL DEFAULT 'FREE'
             CHECK (status IN ('FREE', 'OCCUPIED'))
);

-- Fee schedule. Multiple tiers, ordered by sort_order, evaluated top to
-- bottom until duration_minutes <= max_minutes. A NULL max_minutes means
-- "this tier and beyond" (the open-ended top tier). Management edits
-- this table only -- no code change needed to re-price the car park.
CREATE TABLE IF NOT EXISTS rate_tiers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    label           TEXT NOT NULL,
    max_minutes     INTEGER,                     -- NULL = open ended
    amount_kshs     INTEGER NOT NULL,
    sort_order      INTEGER NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1,
    effective_from  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One parking visit: entry -> (optional) exit -> payment.
CREATE TABLE IF NOT EXISTS sessions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_number      TEXT NOT NULL,
    bay_id            INTEGER NOT NULL REFERENCES bays(id),
    entry_time        TEXT NOT NULL,
    exit_time         TEXT,
    duration_minutes  INTEGER,
    amount_due_kshs   INTEGER,
    status            TEXT NOT NULL DEFAULT 'PARKED'
                      CHECK (status IN ('PARKED','AWAITING_PAYMENT','PAID','EXITED'))
);

-- A payment attempt/record against a session. confirmed=1 is what
-- allows the barrier-open event to fire.
CREATE TABLE IF NOT EXISTS payments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER NOT NULL REFERENCES sessions(id),
    amount_kshs   INTEGER NOT NULL,
    method        TEXT NOT NULL CHECK (method IN ('MPESA','CARD','CASH')),
    reference     TEXT,                           -- M-Pesa code / card auth code
    confirmed     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Immutable event trail: every state change is appended here, never
-- edited, so it can be used for reconciliation and VAT audits.
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER REFERENCES sessions(id),
    event       TEXT NOT NULL,
    details     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bays_zone_status ON bays(zone_id, status);
CREATE INDEX IF NOT EXISTS idx_sessions_plate ON sessions(plate_number);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_payments_session ON payments(session_id);
