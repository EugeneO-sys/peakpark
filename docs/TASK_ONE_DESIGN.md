# Task One: System Analysis, Algorithms, Data Structures and Dynamic Database Design

**Project:** SmartPark KE — A Modern Parking Management System
**Course:** Data Structures and Algorithms — Multimedia University of Kenya

---

## 1. Introduction

The client operates a car park in Kenya and wants to automate its operations end to
end: drivers must be able to see slot availability before entry, vehicles must be
recorded on arrival, the system must calculate duration and amount payable
automatically at exit, accept M-Pesa, card or cash payment, and open the barrier
only once payment is confirmed. Management must also be able to change parking
rates at any time without a software change, and the system must produce an
auditable record of every shilling collected for reconciliation and VAT.

This document analyses those terms of reference, proposes the modules needed to
satisfy them, gives an algorithm for each module, justifies the data structures
chosen, and designs a dynamic database that supports the whole system. It is
implemented as a working system in [`/app.py`](../app.py) and the rest of this
repository.

## 2. Analysis of the Client's Terms of Reference

| Client Requirement | System Implication |
|---|---|
| Show live slot availability on a display board and in a web/mobile view. | Need a single, always-current count of free/occupied bays per zone, exposed both to a physical display and an API/web page (Slot Monitoring & Display Module). |
| Record each vehicle on arrival, with plate, time of entry and allocated bay. | Need a Vehicle Entry Module that persists a timestamped session and hands off to a Slot Allocation Module. |
| Calculate duration and amount payable automatically at exit. | Need a Duration & Fee Computation Module driven by a rate table, not hard-coded prices. |
| Collect payment by M-Pesa, card or cash; open barrier only on confirmed payment. | Need a Payment Module with distinct "pending" and "confirmed" states, and a Barrier Control Module gated strictly on confirmation. |
| Let management change parking rates at any time without a software change. | Rates must be data (a database table), never a constant in source code; the fee algorithm must always read current, active rates. |
| Produce an auditable record of every shilling collected, for reconciliation and VAT. | Need an append-only Audit/Reporting Module: every payment and state change is logged with a timestamp and never overwritten. |

**Scope confirms this:** entry lane control, slot monitoring/display, slot
allocation, duration/fee computation, payment collection, exit barrier control,
exception handling and administrative reporting are in scope; online pre-booking,
valet operations, loyalty-scheme integration and automated number-plate
blacklisting are explicitly out of scope for this phase.

## 3. Proposed System Modules

- **Slot Monitoring & Display Module** — Maintains the live free/occupied state of every bay and exposes it to a physical board and a web/mobile view.
- **Vehicle Entry Module** — Captures plate number and entry time at the barrier/kiosk and starts a parking session.
- **Slot Allocation Module** — Assigns the entering vehicle to a specific free bay using a fast allocation algorithm.
- **Duration & Fee Computation Module** — At exit, computes minutes parked and looks up the amount payable from the current, editable rate schedule.
- **Payment Processing Module** — Accepts M-Pesa, card or cash, and only marks a session as paid once payment is confirmed.
- **Barrier Control Module** — Signals the physical exit barrier to open, strictly gated on a confirmed-payment event.
- **Rate Configuration Module** — Lets management add, edit or deactivate fee tiers at any time, with no code change.
- **Exception Handling Module** — Handles edge cases: full car park, unknown plate at exit, duplicate entry, failed/declined payment.
- **Administrative Reporting Module** — Produces an append-only, timestamped audit trail of every transaction for reconciliation and VAT.

## 4. Algorithms for Each Module

### 4.1 Slot Monitoring & Display Algorithm

```
FOR each zone in car park:
    free_count[zone] = COUNT(bays WHERE zone = zone AND status = FREE)
    total_count[zone] = COUNT(bays WHERE zone = zone)
DISPLAY free_count / total_count per zone on board and via /api/availability
REPEAT every few seconds OR whenever a bay's status changes (event-driven)
```

### 4.2 Vehicle Entry Algorithm

```
INPUT plate_number, zone
IF an OPEN session already exists for plate_number:
    REJECT — vehicle already recorded as parked (see §4.7)
bay = SlotAllocation.allocate(zone)              // §4.3
IF bay is NULL:
    REJECT — zone is full (see §4.7)
CREATE session(plate_number, bay.id, entry_time = NOW(), status = PARKED)
SET bay.status = OCCUPIED
LOG audit event 'ENTRY'
```

### 4.3 Slot Allocation Algorithm

Each zone keeps a FIFO queue of its free bay codes, built once from the database
at start-up (implemented in [`algorithms.py`](../algorithms.py)).

```
ALLOCATE(zone):
    IF free_queue[zone] is empty:  RETURN NULL   // zone full
    bay_code = free_queue[zone].dequeue()          // O(1)
    RETURN bay_code

RELEASE(bay_code):
    zone = zone_of(bay_code)                        // O(1) via hash map
    free_queue[zone].enqueue(bay_code)               // O(1)
```

### 4.4 Duration & Fee Computation Algorithm

```
INPUT plate_number
session = FIND open session WHERE plate_number = plate_number
IF session not found: REJECT — unknown plate (see §4.7)
duration_minutes = (NOW() - session.entry_time) in whole minutes
tiers = SELECT * FROM rate_tiers WHERE active = TRUE ORDER BY sort_order ASC
FOR each tier in tiers:
    IF tier.max_minutes is NULL OR duration_minutes <= tier.max_minutes:
        amount_due = tier.amount
        BREAK
SET session.duration_minutes, session.amount_due, session.status = AWAITING_PAYMENT
```

### 4.5 Payment Processing & Barrier Control Algorithm

```
INPUT session_id, method ∈ {MPESA, CARD, CASH}, reference
CREATE payment(session_id, amount = session.amount_due, method, reference, confirmed = FALSE)
result = GATEWAY.charge(method, session.amount_due, reference)   // STK push / card / till
IF result != CONFIRMED:
    SET payment.confirmed = FALSE
    REJECT — payment not confirmed, barrier stays shut (see §4.7)
SET payment.confirmed = TRUE, session.status = PAID
SlotAllocation.release(session.bay_code)                          // §4.3
SET bay.status = FREE, session.status = EXITED
OPEN barrier
LOG audit events 'PAYMENT_CONFIRMED', 'BARRIER_OPENED'
```

### 4.6 Dynamic Rate Configuration Algorithm

```
ADD_TIER(label, max_minutes, amount):
    INSERT INTO rate_tiers(label, max_minutes, amount, sort_order = MAX(sort_order)+1, active = TRUE)

EDIT_TIER(tier_id, new_amount):
    UPDATE rate_tiers SET amount = new_amount WHERE id = tier_id
// No source file is touched — §4.4 always re-reads this table, so the
// change is live for the very next exit.
```

### 4.7 Exception Handling

- **Car park full:** allocation returns `NULL` → driver is informed before entering; no session is created.
- **Duplicate entry:** a plate with an already-OPEN session is rejected at the barrier to prevent double allocation.
- **Unknown plate at exit:** no matching open session → attendant is prompted to check the plate or handle manually.
- **Declined/failed payment:** session stays `AWAITING_PAYMENT` and the barrier stays shut; the attendant can retry with a different method.
- **System/database unavailable:** fail safe — barrier defaults to closed rather than opening on an unconfirmed state.

### 4.8 Administrative Reporting / Audit Algorithm

```
ON every state change (entry, exit-calculated, payment-confirmed, barrier-opened):
    APPEND-ONLY INSERT INTO audit_log(session_id, event, details, timestamp = NOW())

REPORT(date_range):
    total = SUM(payments.amount) WHERE confirmed = TRUE AND date BETWEEN range
    by_method = GROUP payments BY method, SUM(amount)
    vat = total * VAT_RATE / (1 + VAT_RATE)     // VAT_RATE = 0.16 in Kenya
    RETURN total, by_method, vat, full itemised list for reconciliation
```

## 5. Data Structures Used and Justification

| Data Structure | Used In | Why it was chosen |
|---|---|---|
| Queue (FIFO), one per zone | Slot Allocation Module (§4.3) | Allocation and release are both O(1); FIFO order spreads bay usage evenly and is predictable for staff, unlike an O(n) scan of every bay each time a car arrives. |
| Hash map (bay code → zone/id) | Slot Allocation, Display | O(1) lookup of a bay's zone when releasing it or aggregating live counts, instead of a linear search. |
| Sorted list of rate tiers | Duration & Fee Computation (§4.4) | The fee schedule is small (typically under 10 tiers) and naturally ordered by duration, so a single linear pass finds the matching tier; because it is read from the database it can be edited live (§4.6) with no code change. |
| Relational tables with indexes (B-tree, via SQLite/SQL engine) | All persistent state: bays, sessions, payments, audit_log | Durable storage that survives restarts; indexes on plate number and status give O(log n) lookup for "is this plate already parked?" and "find open session for plate" checks used in exception handling. |
| Append-only log (`audit_log` table) | Administrative Reporting (§4.8) | Rows are inserted, never updated or deleted, which is exactly the immutability an auditable financial trail for reconciliation and VAT requires. |

## 6. Dynamic Database Design

The database is "dynamic" in two senses required by the client: (1) **capacity can
grow** — adding a new zone or bay is a row insert, never a schema or code change;
and (2) **pricing can change** — rate tiers are rows, editable by management at
any time, and every algorithm that needs a price re-reads this table rather than
using a hard-coded constant. The full, runnable schema is in
[`schema.sql`](../schema.sql).

### 6.1 Entity Relationships

- A **Zone** has many **Bays** (1‑to‑many).
- A **Bay** has many **Sessions** over time, but at most one OPEN session at a time (1‑to‑many).
- A **Session** has many **Payment** attempts, but exactly one CONFIRMED payment when complete (1‑to‑many).
- A **Session** has many **Audit Log** entries, one per state change (1‑to‑many).
- **Rate Tiers** stand alone and are referenced logically (not by foreign key) by the fee algorithm at the moment of computation, so historical sessions keep the amount that was actually charged even if tiers change later.

```
zones (1) ───< bays (1) ───< sessions (1) ───< payments
                                  │
                                  └───< audit_log

rate_tiers  (read by the fee algorithm at exit time; not FK-linked)
```

### 6.2 Tables

| Table | Key Fields | Purpose |
|---|---|---|
| `zones` | id (PK), name | The physical areas of the car park; add a row to expand capacity. |
| `bays` | id (PK), code, zone_id (FK), status | One row per physical bay; status is the live truth behind the display board. |
| `rate_tiers` | id (PK), label, max_minutes, amount_kshs, sort_order, active, effective_from | The editable fee schedule; management changes prices here, never in code. |
| `sessions` | id (PK), plate_number, bay_id (FK), entry_time, exit_time, duration_minutes, amount_due_kshs, status | One row per parking visit, from entry to exit. |
| `payments` | id (PK), session_id (FK), amount_kshs, method, reference, confirmed, created_at | Every payment attempt; `confirmed = TRUE` is what is allowed to open the barrier. |
| `audit_log` | id (PK), session_id (FK), event, details, created_at | Append-only trail of every state change, for reconciliation and VAT. |

### 6.3 Why This Design Meets the Requirement

- **Adding a bay or a whole new zone:** `INSERT INTO zones / bays` — no code touched, no redeploy.
- **Changing a price:** `UPDATE rate_tiers.amount_kshs`, or `INSERT` a new tier — the fee algorithm (§4.4) always reads active tiers fresh from the database, so the change is live immediately.
- **Reconciliation and VAT:** `payments` and `audit_log` are never overwritten, so every shilling collected can be traced back to a specific session, method and timestamp.

## 7. Conclusion

Breaking the client's requirements into nine focused modules, backing the
hot-path Slot Allocation module with an O(1) queue/hash-map combination, and
pushing both capacity and pricing into a dynamic, editable database rather than
source code, gives a design that meets every stated objective — live display,
automatic duration/fee calculation, gated barrier control, and an auditable
financial trail — while remaining easy for management to reconfigure without
further software changes. This design is implemented as a working system,
**SmartPark KE**, in this repository.
