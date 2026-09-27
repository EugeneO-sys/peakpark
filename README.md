# PEAKPARK

A modern, web-based parking management system built for Task Two of the
Multimedia University of Kenya Data Structures & Algorithms coursework.
It implements every module identified in the Task One design document:
live slot display, vehicle entry, slot allocation, duration & fee
computation, payment collection, barrier control, dynamic rate
configuration, and auditable reporting.

## Features

- **Live slot availability** — a kiosk-style display board (`/`) and a
  JSON feed (`/api/availability`) for a mobile app or an external screen.
- **Vehicle entry** (`/entry`) — records plate, timestamp, and
  automatically allocates the next free bay.
- **Vehicle exit** (`/exit`) — automatically computes duration parked
  and the amount payable from the current rate schedule.
- **Payment & barrier control** (`/pay/<id>`) — collects M-Pesa, card or
  cash payment; the exit barrier only "opens" once payment is confirmed.
- **Dynamic rates** (`/admin/rates`) — management can add or edit fee
  tiers at any time; the fee algorithm reads this table live, so no
  code change or redeploy is ever needed to reprice the car park.
- **Reporting** (`/reports`) — an auditable trail of every shilling
  collected, totals by payment method, and a VAT breakdown for
  reconciliation.

## Default fee schedule (seeded, editable from Admin > Rates)

| Duration        | Fee (Kshs) |
|------------------|-----------:|
| Up to 30 minutes | Free       |
| Up to 2 hours    | 50         |
| Up to 4 hours    | 100        |
| Up to 6 hours    | 300        |
| Over 6 hours     | 500        |

## Project layout

```
smartpark-ke/
├── app.py                     # Flask routes (the 7 modules)
├── algorithms.py               # Slot allocation + duration/fee algorithms
├── db.py                        # sqlite3 connection helper + seed data
├── schema.sql                   # Dynamic database schema
├── templates/                    # Jinja2 HTML templates
├── static/style.css               # Styling
├── requirements.txt
└── docs/
    └── TASK_ONE_DESIGN.md          # Task One: TOR analysis, algorithms,
                                     # data structures & database design
```

See [`docs/TASK_ONE_DESIGN.md`](docs/TASK_ONE_DESIGN.md) for the full design
report: terms-of-reference analysis, pseudocode for every module, the data
structure rationale, and the entity-relationship breakdown of the schema
below.

## Data structures used, in brief

- **Queue (`collections.deque`) per zone** — O(1) slot allocation and
  release (`algorithms.AvailabilityManager`).
- **Hash map (`dict`)** — bay-code → (bay_id, zone_id) index for O(1)
  lookup on release; zone-id → name lookups.
- **Sorted list of rate tiers** — small, ordered table scanned once per
  exit to find the matching fee band.
- **Relational tables with indexes** (`schema.sql`) — durable storage
  and O(log n) lookups for plates, bay status and payment history.

See the accompanying Task One report for the full rationale and the
pseudocode for every module.

## Running locally

```bash
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000/ in your browser. The SQLite database
(`smartpark.db`) and its seed data (2 zones, 10 bays each, default
rates) are created automatically on first run.

## Notes

- Payment confirmation is simulated (instant `confirmed=1`) since no
  live M-Pesa/card gateway credentials are available in this
  coursework environment; `app.py`'s `pay()` view is where a real
  gateway callback would be wired in.
- `app.secret_key` is a development placeholder — replace it before any
  real deployment.
