"""
SmartPark KE - a modern, web-based parking management system.

Multimedia University of Kenya - Data Structures & Algorithms
Task Two: Actual System Development (Python / Flask).

Modules implemented (mirrors the Task One design document):
  1. Slot Monitoring & Display        -> "/" and "/api/availability"
  2. Vehicle Entry                    -> "/entry"
  3. Slot Allocation                  -> algorithms.AvailabilityManager
  4. Duration & Fee Computation       -> algorithms.compute_duration_minutes/compute_fee
  5. Payment Collection & Barrier     -> "/exit", "/pay/<id>"
  6. Rate Configuration (dynamic)     -> "/admin/rates"
  7. Auditable Reporting              -> "/reports"

Run:
    pip install -r requirements.txt
    python app.py
Then open http://127.0.0.1:5000/
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, date

import db
import algorithms

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-in-production"  # needed for flash messages

# One shared, in-memory allocator (Module 3). Loaded from the database
# at start-up; kept in sync on every allocate/release so it never needs
# a full table scan while the app is running.
availability = algorithms.AvailabilityManager()


def get_zone_lookup(conn):
    rows = conn.execute("SELECT id, name FROM zones ORDER BY id").fetchall()
    return {row["id"]: row["name"] for row in rows}


# ---------------------------------------------------------------------
# Module 1: Slot Monitoring & Display
# ---------------------------------------------------------------------
@app.route("/")
def display_board():
    conn = db.get_connection()
    zones = get_zone_lookup(conn)
    totals = conn.execute(
        "SELECT zone_id, COUNT(*) AS total FROM bays GROUP BY zone_id"
    ).fetchall()
    total_by_zone = {row["zone_id"]: row["total"] for row in totals}
    free_by_zone = availability.counts_by_zone()

    board = []
    for zone_id, name in zones.items():
        board.append({
            "zone_id": zone_id,
            "name": name,
            "free": free_by_zone.get(zone_id, 0),
            "total": total_by_zone.get(zone_id, 0),
        })
    conn.close()
    return render_template("index.html", board=board)


@app.route("/api/availability")
def api_availability():
    """JSON feed so the same live data can drive a web/mobile view or an
    external physical display board, per the client's requirement."""
    conn = db.get_connection()
    zones = get_zone_lookup(conn)
    totals = conn.execute(
        "SELECT zone_id, COUNT(*) AS total FROM bays GROUP BY zone_id"
    ).fetchall()
    total_by_zone = {row["zone_id"]: row["total"] for row in totals}
    free_by_zone = availability.counts_by_zone()
    conn.close()

    data = [
        {
            "zone": zones[zid],
            "free": free_by_zone.get(zid, 0),
            "total": total_by_zone.get(zid, 0),
        }
        for zid in zones
    ]
    return jsonify({"generated_at": datetime.now().isoformat(), "zones": data})


# ---------------------------------------------------------------------
# Module 2 + 3: Vehicle Entry & Slot Allocation
# ---------------------------------------------------------------------
@app.route("/entry", methods=["GET", "POST"])
def entry():
    conn = db.get_connection()
    zones = get_zone_lookup(conn)

    if request.method == "POST":
        plate = request.form.get("plate_number", "").strip().upper()
        zone_id = int(request.form.get("zone_id"))

        if not plate:
            flash("Please enter a number plate.", "error")
            return redirect(url_for("entry"))

        # Exception handling: a plate already parked cannot re-enter.
        existing = conn.execute(
            "SELECT id FROM sessions WHERE plate_number = ? AND status = 'PARKED'",
            (plate,),
        ).fetchone()
        if existing:
            flash(f"{plate} is already recorded as parked (session #{existing['id']}).", "error")
            conn.close()
            return redirect(url_for("entry"))

        bay_code = availability.allocate(zone_id)
        if bay_code is None:
            flash("Sorry, this zone is full. No bays available.", "error")
            conn.close()
            return redirect(url_for("entry"))

        bay_id, _ = availability._bay_index[bay_code]
        conn.execute("UPDATE bays SET status = 'OCCUPIED' WHERE id = ?", (bay_id,))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            "INSERT INTO sessions (plate_number, bay_id, entry_time, status) "
            "VALUES (?, ?, ?, 'PARKED')",
            (plate, bay_id, now),
        )
        session_id = cur.lastrowid
        db.log_event(conn, session_id, "ENTRY", f"Bay {bay_code} allocated to {plate}")
        conn.commit()
        conn.close()

        flash(f"Vehicle {plate} recorded. Allocated bay: {bay_code}.", "success")
        return redirect(url_for("entry"))

    conn.close()
    return render_template("entry.html", zones=zones)


# ---------------------------------------------------------------------
# Module 4: Duration & Fee Computation (exit, step 1)
# ---------------------------------------------------------------------
@app.route("/exit", methods=["GET", "POST"])
def exit_vehicle():
    conn = db.get_connection()
    session_row = None

    if request.method == "POST":
        plate = request.form.get("plate_number", "").strip().upper()
        session_row = conn.execute(
            "SELECT * FROM sessions WHERE plate_number = ? AND status = 'PARKED'",
            (plate,),
        ).fetchone()

        if not session_row:
            flash(f"No parked vehicle found for plate {plate}.", "error")
            conn.close()
            return redirect(url_for("exit_vehicle"))

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        duration = algorithms.compute_duration_minutes(session_row["entry_time"], now)
        fee = algorithms.compute_fee(conn, duration)

        conn.execute(
            "UPDATE sessions SET exit_time = ?, duration_minutes = ?, "
            "amount_due_kshs = ?, status = 'AWAITING_PAYMENT' WHERE id = ?",
            (now, duration, fee, session_row["id"]),
        )
        db.log_event(conn, session_row["id"], "EXIT_CALCULATED",
                     f"duration={duration}min amount={fee}")
        conn.commit()

        bay_code = conn.execute(
            "SELECT code FROM bays WHERE id = ?", (session_row["bay_id"],)
        ).fetchone()["code"]
        conn.close()

        return render_template(
            "exit.html", session_row=None, result={
                "session_id": session_row["id"],
                "plate": plate,
                "bay_code": bay_code,
                "duration": duration,
                "fee": fee,
            }
        )

    conn.close()
    return render_template("exit.html", session_row=None, result=None)


# ---------------------------------------------------------------------
# Module 5: Payment Collection & Barrier Control
# ---------------------------------------------------------------------
@app.route("/pay/<int:session_id>", methods=["GET", "POST"])
def pay(session_id):
    conn = db.get_connection()
    session_row = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()

    if session_row is None or session_row["status"] != "AWAITING_PAYMENT":
        flash("This session is not awaiting payment.", "error")
        conn.close()
        return redirect(url_for("exit_vehicle"))

    if request.method == "POST":
        method = request.form.get("method")
        reference = request.form.get("reference", "").strip()

        # In production this branches to a real gateway (M-Pesa STK push /
        # card processor webhook / till). For this coursework build we
        # simulate an immediate, confirmed payment, which is the trigger
        # the client's terms of reference require before the barrier
        # opens: "open the barrier only on confirmed payment."
        conn.execute(
            "INSERT INTO payments (session_id, amount_kshs, method, reference, confirmed) "
            "VALUES (?, ?, ?, ?, 1)",
            (session_id, session_row["amount_due_kshs"], method, reference),
        )
        conn.execute(
            "UPDATE sessions SET status = 'EXITED' WHERE id = ?", (session_id,)
        )
        db.log_event(conn, session_id, "PAYMENT_CONFIRMED", f"{method} ref={reference}")
        db.log_event(conn, session_id, "BARRIER_OPENED", "Exit barrier opened")

        bay_code = conn.execute(
            "SELECT code FROM bays WHERE id = ?", (session_row["bay_id"],)
        ).fetchone()["code"]
        availability.release(bay_code)
        conn.execute(
            "UPDATE bays SET status = 'FREE' WHERE id = ?", (session_row["bay_id"],)
        )
        conn.commit()
        conn.close()

        return render_template("exit.html", session_row=None, result=None,
                                barrier_open=True, receipt={
                                    "plate": session_row["plate_number"],
                                    "bay_code": bay_code,
                                    "amount": session_row["amount_due_kshs"],
                                    "method": method,
                                })

    conn.close()
    return render_template("pay.html", session_row=session_row)


# ---------------------------------------------------------------------
# Module 6: Dynamic Rate Configuration
# ---------------------------------------------------------------------
@app.route("/admin/rates", methods=["GET", "POST"])
def admin_rates():
    conn = db.get_connection()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update":
            tier_id = int(request.form["tier_id"])
            amount = int(request.form["amount_kshs"])
            conn.execute(
                "UPDATE rate_tiers SET amount_kshs = ? WHERE id = ?",
                (amount, tier_id),
            )
            flash("Rate updated. Takes effect immediately for all new exits.", "success")

        elif action == "add":
            label = request.form["label"].strip()
            max_minutes_raw = request.form.get("max_minutes", "").strip()
            max_minutes = int(max_minutes_raw) if max_minutes_raw else None
            amount = int(request.form["amount_kshs"])
            next_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM rate_tiers"
            ).fetchone()["n"]
            conn.execute(
                "INSERT INTO rate_tiers (label, max_minutes, amount_kshs, sort_order, active) "
                "VALUES (?, ?, ?, ?, 1)",
                (label, max_minutes, amount, next_order),
            )
            flash("New rate tier added.", "success")

        elif action == "toggle":
            tier_id = int(request.form["tier_id"])
            conn.execute(
                "UPDATE rate_tiers SET active = 1 - active WHERE id = ?", (tier_id,)
            )
            flash("Tier status toggled.", "success")

        conn.commit()

    tiers = conn.execute(
        "SELECT * FROM rate_tiers ORDER BY sort_order"
    ).fetchall()
    conn.close()
    return render_template("admin_rates.html", tiers=tiers)


# ---------------------------------------------------------------------
# Module 7: Auditable Reporting (reconciliation & VAT)
# ---------------------------------------------------------------------
@app.route("/reports")
def reports():
    conn = db.get_connection()
    today = date.today().isoformat()

    rows = conn.execute(
        "SELECT p.id, p.amount_kshs, p.method, p.reference, p.created_at, "
        "s.plate_number FROM payments p JOIN sessions s ON s.id = p.session_id "
        "WHERE p.confirmed = 1 ORDER BY p.created_at DESC LIMIT 200"
    ).fetchall()

    total_today = conn.execute(
        "SELECT COALESCE(SUM(amount_kshs), 0) AS t FROM payments "
        "WHERE confirmed = 1 AND date(created_at) = ?", (today,)
    ).fetchone()["t"]

    total_all = conn.execute(
        "SELECT COALESCE(SUM(amount_kshs), 0) AS t FROM payments WHERE confirmed = 1"
    ).fetchone()["t"]

    by_method = conn.execute(
        "SELECT method, COUNT(*) AS n, COALESCE(SUM(amount_kshs), 0) AS total "
        "FROM payments WHERE confirmed = 1 GROUP BY method"
    ).fetchall()

    VAT_RATE = 0.16  # Kenya standard VAT rate
    vat_all = round(total_all * VAT_RATE / (1 + VAT_RATE))

    conn.close()
    return render_template(
        "reports.html", rows=rows, total_today=total_today, total_all=total_all,
        by_method=by_method, vat_all=vat_all, vat_rate=int(VAT_RATE * 100),
    )


if __name__ == "__main__":
    db.init_db()
    conn = db.get_connection()
    availability.load_from_db(conn)
    conn.close()
    app.run(debug=True)
