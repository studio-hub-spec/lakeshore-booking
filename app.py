
import os
import sqlite3
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, jsonify
from werkzeug.security import check_password_hash, generate_password_hash

TZ = ZoneInfo("America/Toronto")
DB_PATH = os.environ.get("DB_PATH", "database.db")
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "change-me-please")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

def get_db():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS studios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            size_sqft INTEGER,
            price_per_hour REAL NOT NULL,
            description TEXT,
            photo_url TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            studio_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'confirmed',
            notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (studio_id) REFERENCES studios(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    conn.commit()

    cur.execute("SELECT COUNT(*) as c FROM admins")
    if cur.fetchone()["c"] == 0:
        cur.execute("INSERT INTO admins (username, password_hash) VALUES (?,?)",
                    (ADMIN_USER, generate_password_hash(ADMIN_PASSWORD)))
        conn.commit()

    cur.execute("SELECT COUNT(*) as c FROM studios")
    if cur.fetchone()["c"] == 0:
        studios = [
            ("Room A — Budget", 300, 40.0, "Cozy studio ideal for solo dance, headshots, or small rehearsals.", ""),
            ("Room B — Mid", 650, 60.0, "Mirrors, Marley flooring, speakers — perfect for classes and shoots.", ""),
            ("Room C — Premium", 1000, 90.0, "Spacious premium room, AV, optional backdrops/cyclorama.", ""),
        ]
        cur.executemany("INSERT INTO studios (name, size_sqft, price_per_hour, description, photo_url) VALUES (?,?,?,?,?)", studios)
        conn.commit()
    conn.close()

def parse_hm(s): return datetime.strptime(s, "%H:%M").time()
def overlap(a_start, a_end, b_start, b_end): return max(a_start, b_start) < min(a_end, b_end)

@app.template_filter("money")
def money(v): return f"${v:,.2f}"

@app.context_processor
def inject_now(): return {"now": datetime.now(TZ)}

@app.route("/")
def index():
    conn = get_db()
    studios = conn.execute("SELECT * FROM studios ORDER BY id").fetchall()
    conn.close()
    return render_template("index.html", studios=studios)

@app.route("/studio/<int:studio_id>")
def studio(studio_id):
    conn = get_db()
    s = conn.execute("SELECT * FROM studios WHERE id=?", (studio_id,)).fetchone()
    if not s:
        flash("Studio not found.", "error")
        return redirect(url_for("index"))
    selected = request.args.get("date")
    if selected:
        try:
            selected_date = datetime.strptime(selected, "%Y-%m-%d").date()
        except ValueError:
            selected_date = date.today()
    else:
        selected_date = date.today()
    bookings = conn.execute("""
        SELECT * FROM bookings
        WHERE studio_id=? AND date=? AND status!='cancelled'
        ORDER BY start_time
    """, (studio_id, selected_date.isoformat())).fetchall()
    conn.close()
    return render_template("studio.html", studio=s, selected_date=selected_date, bookings=bookings)

@app.route("/book/<int:studio_id>", methods=["POST"])
def book(studio_id):
    full_name = request.form.get("full_name","").strip()
    email = request.form.get("email","").strip()
    phone = request.form.get("phone","").strip()
    date_str = request.form.get("date")
    start_time_str = request.form.get("start_time")
    duration_minutes = int(request.form.get("duration", "60"))
    notes = request.form.get("notes","").strip()

    if not (full_name and email and date_str and start_time_str):
        flash("Please fill in all required fields.", "error")
        return redirect(url_for("studio", studio_id=studio_id, date=date_str))

    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        start_t = parse_hm(start_time_str)
        end_dt = (datetime.combine(selected_date, start_t) + timedelta(minutes=duration_minutes))
        end_t = end_dt.time()
    except Exception:
        flash("Invalid date or time.", "error")
        return redirect(url_for("studio", studio_id=studio_id, date=date_str))

    open_t, close_t = time(8,0), time(22,0)
    if not (open_t <= start_t < close_t and open_t < end_t <= close_t and start_t < end_t):
        flash("Please book between 08:00 and 22:00.", "error")
        return redirect(url_for("studio", studio_id=studio_id, date=date_str))

    conn = get_db()
    existing = conn.execute("""
        SELECT start_time, end_time FROM bookings
        WHERE studio_id=? AND date=? AND status!='cancelled'
    """, (studio_id, selected_date.isoformat())).fetchall()
    for row in existing:
        if overlap(parse_hm(row["start_time"]), parse_hm(row["end_time"]), start_t, end_t):
            flash(f"Selected time overlaps with an existing booking: {row['start_time']}–{row['end_time']}.", "error")
            conn.close()
            return redirect(url_for("studio", studio_id=studio_id, date=date_str))

    created_at = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO bookings (studio_id, full_name, email, phone, date, start_time, end_time, status, notes, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (studio_id, full_name, email, phone, selected_date.isoformat(), start_time_str, end_t.strftime("%H:%M"), "confirmed", notes, created_at))
    booking_id = cur.lastrowid
    conn.commit()
    conn.close()

    return redirect(url_for("success", booking_id=booking_id, pay="0", checkout=""))

@app.route("/success/<int:booking_id>")
def success(booking_id):
    pay = request.args.get("pay") == "1"
    checkout_url = request.args.get("checkout") or None
    conn = get_db()
    b = conn.execute("""
        SELECT b.*, s.name as studio_name, s.price_per_hour as pph
        FROM bookings b JOIN studios s ON b.studio_id = s.id
        WHERE b.id=?
    """, (booking_id,)).fetchone()
    conn.close()
    if not b:
        flash("Booking not found.", "error")
        return redirect(url_for("index"))
    return render_template("success.html", b=b, pay=pay, checkout_url=checkout_url)

@app.route("/ics/<int:booking_id>")
def ics(booking_id):
    conn = get_db()
    b = conn.execute("""
        SELECT b.*, s.name as studio_name
        FROM bookings b JOIN studios s ON b.studio_id = s.id
        WHERE b.id=?
    """, (booking_id,)).fetchone()
    conn.close()
    if not b:
        flash("Booking not found.", "error")
        return redirect(url_for("index"))
    dt_start = datetime.strptime(b["date"] + " " + b["start_time"], "%Y-%m-%d %H:%M")
    dt_end = datetime.strptime(b["date"] + " " + b["end_time"], "%Y-%m-%d %H:%M")
    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Lakeshore Creative Studios//Booking//EN
BEGIN:VEVENT
UID:{booking_id}@lakeshore
DTSTAMP:{datetime.now(TZ).strftime("%Y%m%dT%H%M%S")}
DTSTART:{dt_start.strftime("%Y%m%dT%H%M%S")}
DTEND:{dt_end.strftime("%Y%m%dT%H%M%S")}
SUMMARY:Studio Booking - {b['studio_name']}
DESCRIPTION:Booking for {b['full_name']} ({b['email']})
END:VEVENT
END:VCALENDAR
"""
    path = f"/tmp/booking_{booking_id}.ics"
    with open(path, "w", encoding="utf-8") as f:
        f.write(ics_content)
    return send_file(path, as_attachment=True, download_name=f"booking_{booking_id}.ics")

def require_admin():
    if not session.get("admin"):
        flash("Please log in as admin.", "error")
        return False
    return True

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        conn = get_db()
        row = conn.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        conn.close()
        if row and check_password_hash(row["password_hash"], password):
            session["admin"] = username
            flash("Logged in.", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid credentials.", "error")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    flash("Logged out.", "success")
    return redirect(url_for("index"))

@app.route("/admin")
def admin_dashboard():
    if not require_admin():
        return redirect(url_for("admin_login"))
    conn = get_db()
    upcoming = conn.execute("""
        SELECT b.*, s.name as studio_name
        FROM bookings b JOIN studios s ON b.studio_id=s.id
        WHERE status!='cancelled' AND date >= ?
        ORDER BY date, start_time
        LIMIT 200
    """, (date.today().isoformat(),)).fetchall()
    studios = conn.execute("SELECT * FROM studios ORDER BY id").fetchall()
    conn.close()
    return render_template("admin.html", upcoming=upcoming, studios=studios)

@app.route("/admin/studios/new", methods=["GET","POST"])
def admin_new_studio():
    if not require_admin():
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        name = request.form.get("name","").strip()
        size = int(request.form.get("size","0") or 0)
        price = float(request.form.get("price","0") or 0)
        desc = request.form.get("description","").strip()
        photo = request.form.get("photo_url","").strip()
        if not name or price <= 0:
            flash("Name and positive price are required.", "error")
            return redirect(url_for("admin_new_studio"))
        conn = get_db()
        conn.execute("INSERT INTO studios (name,size_sqft,price_per_hour,description,photo_url) VALUES (?,?,?,?,?)",
                     (name, size, price, desc, photo))
        conn.commit()
        conn.close()
        flash("Studio created.", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_studio_new.html")

@app.route("/admin/bookings/<int:booking_id>/cancel", methods=["POST"])
def admin_cancel_booking(booking_id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    conn = get_db()
    conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
    conn.commit()
    conn.close()
    flash("Booking cancelled.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/api/availability/<int:studio_id>")
def api_availability(studio_id):
    qdate = request.args.get("date")
    try:
        _ = datetime.strptime(qdate, "%Y-%m-%d").date()
    except Exception:
        return jsonify({"error":"invalid date"}), 400
    conn = get_db()
    rows = conn.execute("""
        SELECT start_time, end_time FROM bookings
        WHERE studio_id=? AND date=? AND status!='cancelled'
        ORDER BY start_time
    """, (studio_id, qdate)).fetchall()
    conn.close()
    return jsonify({"studio_id": studio_id, "date": qdate, "booked": [{"start": r["start_time"], "end": r["end_time"]} for r in rows]})

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
