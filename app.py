"""
Sample QR Tracker - Browser MVP

Features:
- Assign a pre-existing QR code to a new sample
- Scan QR codes from a phone/browser camera using html5-qrcode
- Support handheld scanners as keyboard input
- Look up existing samples
- Record handoffs
- Track required characterization work
- View sample history
- Export CSV files

Run:
    pip install -r requirements.txt
    python app.py

Then open:
    http://127.0.0.1:5000

To test from a phone on the same Wi-Fi, run with host=0.0.0.0 and open:
    http://<your-computer-ip>:5000

Note: mobile browsers usually require HTTPS for camera access unless using localhost.
For phone testing, use HTTPS via a trusted internal server, a dev tunnel, or deploy behind HTTPS.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, flash, redirect, render_template, request, send_file, url_for

APP_DIR = Path(__file__).resolve().parent
DB_FILE = APP_DIR / "sample_tracker_web.db"

app = Flask(__name__)
app.secret_key = "dev-change-this-secret-key"


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qr_code_value TEXT NOT NULL UNIQUE,
                sample_id TEXT NOT NULL,
                sample_type TEXT,
                batch_lot TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                current_owner TEXT,
                current_location TEXT,
                status TEXT,
                project TEXT,
                task TEXT,
                notes TEXT
            )
            """
        )
        # Lightweight migrations for databases created by earlier versions.
        sample_columns = {row[1] for row in conn.execute("PRAGMA table_info(samples)").fetchall()}
        if "project" not in sample_columns:
            conn.execute("ALTER TABLE samples ADD COLUMN project TEXT")
        if "task" not in sample_columns:
            conn.execute("ALTER TABLE samples ADD COLUMN task TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS handoffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qr_code_value TEXT NOT NULL,
                from_person TEXT,
                to_person TEXT,
                from_location TEXT,
                to_location TEXT,
                timestamp TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY (qr_code_value) REFERENCES samples(qr_code_value)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qr_code_value TEXT NOT NULL,
                scan_type TEXT NOT NULL,
                scanned_by TEXT,
                timestamp TEXT NOT NULL,
                result TEXT,
                notes TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS characterizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qr_code_value TEXT NOT NULL,
                characterization_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                completed_by TEXT,
                data_location TEXT,
                notes TEXT,
                FOREIGN KEY (qr_code_value) REFERENCES samples(qr_code_value)
            )
            """
        )
        characterization_columns = {row[1] for row in conn.execute("PRAGMA table_info(characterizations)").fetchall()}
        if "data_location" not in characterization_columns:
            conn.execute("ALTER TABLE characterizations ADD COLUMN data_location TEXT")


def fetch_sample(qr_code_value: str) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM samples WHERE qr_code_value = ?",
            (qr_code_value.strip(),),
        ).fetchone()


def log_scan(qr_code_value: str, scan_type: str, result: str, scanned_by: str = "", notes: str = "") -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO scan_events (qr_code_value, scan_type, scanned_by, timestamp, result, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (qr_code_value.strip(), scan_type, scanned_by.strip(), now_iso(), result, notes.strip()),
        )


@app.route("/")
def home() -> str:
    with get_db() as conn:
        recent_samples = conn.execute(
            "SELECT * FROM samples ORDER BY created_at DESC LIMIT 8"
        ).fetchall()
        recent_handoffs = conn.execute(
            "SELECT * FROM handoffs ORDER BY timestamp DESC, id DESC LIMIT 8"
        ).fetchall()
    return render_template("home.html", recent_samples=recent_samples, recent_handoffs=recent_handoffs)


@app.route("/scan")
def scan() -> str:
    mode = request.args.get("mode", "lookup")
    if mode not in {"lookup", "assign"}:
        mode = "lookup"
    return render_template("scan.html", mode=mode)


@app.route("/scan/submit", methods=["POST"])
def submit_scan() -> Response | str:
    qr_code_value = request.form.get("qr_code_value", "").strip()
    mode = request.form.get("mode", "lookup")
    scanned_by = request.form.get("scanned_by", "").strip()

    if not qr_code_value:
        flash("Scan or enter a QR code first.", "error")
        return redirect(url_for("scan", mode=mode))

    sample = fetch_sample(qr_code_value)
    if sample:
        log_scan(qr_code_value, mode, "existing_sample_found", scanned_by)
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))

    log_scan(qr_code_value, mode, "unassigned_code", scanned_by)
    return redirect(url_for("new_sample", qr_code_value=qr_code_value))


@app.route("/sample/new")
def new_sample() -> str:
    qr_code_value = request.args.get("qr_code_value", "").strip()
    if not qr_code_value:
        flash("Scan an unused QR code before creating a sample.", "error")
        return redirect(url_for("scan", mode="assign"))
    existing = fetch_sample(qr_code_value)
    if existing:
        flash("That QR code is already assigned.", "error")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))
    return render_template("new_sample.html", qr_code_value=qr_code_value)


@app.route("/sample/create", methods=["POST"])
def create_sample() -> Response:
    qr_code_value = request.form.get("qr_code_value", "").strip()
    sample_id = request.form.get("sample_id", "").strip()

    if not qr_code_value or not sample_id:
        flash("QR code and Sample ID are required.", "error")
        return redirect(url_for("new_sample", qr_code_value=qr_code_value))

    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO samples (
                    qr_code_value, sample_id, sample_type, batch_lot, created_by,
                    created_at, current_owner, current_location, status, project, task, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    qr_code_value,
                    sample_id,
                    request.form.get("sample_type", "").strip(),
                    request.form.get("batch_lot", "").strip(),
                    request.form.get("created_by", "").strip(),
                    now_iso(),
                    request.form.get("current_owner", "").strip(),
                    request.form.get("current_location", "").strip(),
                    request.form.get("status", "Produced").strip() or "Produced",
                    request.form.get("project", "").strip(),
                    request.form.get("task", "").strip(),
                    request.form.get("notes", "").strip(),
                ),
            )
            characterization_values = request.form.getlist("characterization_type")
            for value in characterization_values:
                value = value.strip()
                if value:
                    conn.execute(
                        """
                        INSERT INTO characterizations (
                            qr_code_value, characterization_type, created_at, notes
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (qr_code_value, value, now_iso(), ""),
                    )
        log_scan(qr_code_value, "assign", "sample_created", request.form.get("created_by", ""))
        flash("Sample created and QR code assigned.", "success")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))
    except sqlite3.IntegrityError:
        flash("That QR code is already assigned to another sample.", "error")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))


@app.route("/sample/<path:qr_code_value>")
def sample_detail(qr_code_value: str) -> str | Response:
    sample = fetch_sample(qr_code_value)
    if not sample:
        flash("QR code is not assigned yet. Create a sample record first.", "error")
        return redirect(url_for("new_sample", qr_code_value=qr_code_value))

    with get_db() as conn:
        handoffs = conn.execute(
            "SELECT * FROM handoffs WHERE qr_code_value = ? ORDER BY timestamp DESC, id DESC",
            (qr_code_value,),
        ).fetchall()
        scans = conn.execute(
            "SELECT * FROM scan_events WHERE qr_code_value = ? ORDER BY timestamp DESC, id DESC LIMIT 20",
            (qr_code_value,),
        ).fetchall()
        characterizations = conn.execute(
            "SELECT * FROM characterizations WHERE qr_code_value = ? ORDER BY completed_at IS NOT NULL, created_at ASC, id ASC",
            (qr_code_value,),
        ).fetchall()
    return render_template(
        "sample_detail.html",
        sample=sample,
        handoffs=handoffs,
        scans=scans,
        characterizations=characterizations,
    )


@app.route("/sample/<path:qr_code_value>/characterization/add", methods=["POST"])
def add_characterization(qr_code_value: str) -> Response:
    sample = fetch_sample(qr_code_value)
    if not sample:
        flash("Cannot add characterization for an unassigned QR code.", "error")
        return redirect(url_for("scan", mode="lookup"))

    characterization_type = request.form.get("characterization_type", "").strip()
    if not characterization_type:
        flash("Enter a characterization type first.", "error")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO characterizations (qr_code_value, characterization_type, created_at, notes)
            VALUES (?, ?, ?, ?)
            """,
            (qr_code_value, characterization_type, now_iso(), request.form.get("notes", "").strip()),
        )
    flash("Characterization requirement added.", "success")
    return redirect(url_for("sample_detail", qr_code_value=qr_code_value))


@app.route("/sample/<path:qr_code_value>/characterization/<int:char_id>/complete", methods=["POST"])
def complete_characterization(qr_code_value: str, char_id: int) -> Response:
    completed_by = request.form.get("completed_by", "").strip()
    if not completed_by:
        flash("Enter who completed the characterization.", "error")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM characterizations WHERE id = ? AND qr_code_value = ?",
            (char_id, qr_code_value),
        ).fetchone()
        if not row:
            flash("Characterization item not found.", "error")
            return redirect(url_for("sample_detail", qr_code_value=qr_code_value))
        conn.execute(
            """
            UPDATE characterizations
            SET completed_at = ?, completed_by = ?, data_location = ?, notes = ?
            WHERE id = ? AND qr_code_value = ?
            """,
            (
                now_iso(),
                completed_by,
                request.form.get("data_location", "").strip(),
                request.form.get("completion_notes", "").strip() or row["notes"],
                char_id,
                qr_code_value,
            ),
        )
    flash("Characterization marked complete.", "success")
    return redirect(url_for("sample_detail", qr_code_value=qr_code_value))


@app.route("/sample/<path:qr_code_value>/handoff", methods=["POST"])
def create_handoff(qr_code_value: str) -> Response:
    sample = fetch_sample(qr_code_value)
    if not sample:
        flash("Cannot record a handoff for an unassigned QR code.", "error")
        return redirect(url_for("scan", mode="lookup"))

    to_person = request.form.get("to_person", "").strip()
    to_location = request.form.get("to_location", "").strip()
    status = request.form.get("status", "Transferred").strip() or "Transferred"

    if not to_person:
        flash("Hand off to person is required.", "error")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO handoffs (
                qr_code_value, from_person, to_person, from_location,
                to_location, timestamp, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                qr_code_value,
                sample["current_owner"] or "",
                to_person,
                sample["current_location"] or "",
                to_location,
                now_iso(),
                request.form.get("notes", "").strip(),
            ),
        )
        conn.execute(
            """
            UPDATE samples
            SET current_owner = ?, current_location = ?, status = ?
            WHERE qr_code_value = ?
            """,
            (to_person, to_location, status, qr_code_value),
        )
    log_scan(qr_code_value, "handoff", "handoff_recorded", to_person)
    flash("Handoff recorded.", "success")
    return redirect(url_for("sample_detail", qr_code_value=qr_code_value))


@app.route("/search")
def search() -> str:
    term = request.args.get("q", "").strip()
    rows: list[sqlite3.Row] = []
    if term:
        like = f"%{term}%"
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT * FROM samples
                WHERE qr_code_value LIKE ?
                   OR sample_id LIKE ?
                   OR sample_type LIKE ?
                   OR batch_lot LIKE ?
                   OR project LIKE ?
                   OR task LIKE ?
                   OR current_owner LIKE ?
                   OR current_location LIKE ?
                   OR status LIKE ?
                   OR EXISTS (
                       SELECT 1 FROM characterizations c
                       WHERE c.qr_code_value = samples.qr_code_value
                         AND c.characterization_type LIKE ?
                   )
                ORDER BY created_at DESC
                """,
                (like, like, like, like, like, like, like, like, like, like),
            ).fetchall()
    return render_template("search.html", term=term, rows=rows)


@app.route("/export/<kind>")
def export(kind: str) -> Response:
    if kind not in {"samples", "handoffs", "scans", "characterizations"}:
        flash("Unknown export type.", "error")
        return redirect(url_for("home"))

    output = io.StringIO()
    writer = csv.writer(output)

    with get_db() as conn:
        rows = conn.execute(f"SELECT * FROM {kind} ORDER BY id DESC").fetchall()

    if rows:
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow([row[key] for key in row.keys()])
    else:
        writer.writerow(["No records"])

    data = io.BytesIO(output.getvalue().encode("utf-8"))
    return send_file(
        data,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"{kind}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    )


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
