"""
TraceAPL - Browser MVP

Features:
- Assign a pre-existing QR code or barcode to a new sample
- Scan QR codes/barcodes from a phone/browser camera using html5-qrcode
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

import base64
import csv
import functools
import hmac
import io
import json
import os
import smtplib
import sqlite3
import urllib.request

import requests
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Optional

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, send_file, session, url_for

APP_DIR = Path(__file__).resolve().parent
DB_FILE = APP_DIR / "sample_tracker_web.db"
BACKUP_DIR = APP_DIR / "backups"
BACKUP_RETENTION_DAYS = int(os.environ.get("TRACEAPL_BACKUP_RETENTION_DAYS", "30"))
ADMIN_PASSWORD = os.environ.get("TRACEAPL_ADMIN_PASSWORD", "change-me")
TRACEAPL_BASE_URL = os.environ.get("TRACEAPL_BASE_URL", "")
TRACEAPL_EMAIL_ENABLED = os.environ.get("TRACEAPL_EMAIL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
TRACEAPL_SMTP_HOST = os.environ.get("TRACEAPL_SMTP_HOST", "")
TRACEAPL_SMTP_PORT = int(os.environ.get("TRACEAPL_SMTP_PORT", "587"))
TRACEAPL_SMTP_USERNAME = os.environ.get("TRACEAPL_SMTP_USERNAME", "")
TRACEAPL_SMTP_PASSWORD = os.environ.get("TRACEAPL_SMTP_PASSWORD", "")
TRACEAPL_EMAIL_FROM = os.environ.get("TRACEAPL_EMAIL_FROM", "").strip()
TRACEAPL_SMTP_FROM = os.environ.get("TRACEAPL_SMTP_FROM", TRACEAPL_EMAIL_FROM or TRACEAPL_SMTP_USERNAME or "traceapl@localhost")
TRACEAPL_SMTP_TLS = os.environ.get("TRACEAPL_SMTP_TLS", "1") != "0"
TRACEAPL_SMTP_USE_TLS = os.environ.get("TRACEAPL_SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}
TRACEAPL_EMAIL_NOTIFY_ON_ASSIGNMENT = os.environ.get("TRACEAPL_EMAIL_NOTIFY_ON_ASSIGNMENT", "true").strip().lower() in {"1", "true", "yes", "on"}
TRACEAPL_EMAIL_REMINDERS_ENABLED = os.environ.get("TRACEAPL_EMAIL_REMINDERS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
TRACEAPL_EMAIL_REMINDER_INTERVAL_DAYS = int(os.environ.get("TRACEAPL_EMAIL_REMINDER_INTERVAL_DAYS", "7"))
TRACEAPL_EMAIL_REMINDER_BATCH_LIMIT = int(os.environ.get("TRACEAPL_EMAIL_REMINDER_BATCH_LIMIT", "50"))
TRACEAPL_SLACK_WEBHOOK_URL = os.environ.get("TRACEAPL_SLACK_WEBHOOK_URL", "")

# Employee lookup configuration. Use mock mode for offline development and rest mode
# for Denodo-backed employee autocomplete. Credentials should always come from
# environment variables, never from committed code.
TRACEAPL_EMPLOYEE_LOOKUP_MODE = os.environ.get("TRACEAPL_EMPLOYEE_LOOKUP_MODE", "mock").strip().lower()
DENODO_EMPLOYEE_REST_URL = os.environ.get("DENODO_EMPLOYEE_REST_URL", "").strip()
DENODO_USERNAME = os.environ.get("DENODO_USERNAME", "").strip()
DENODO_PASSWORD = os.environ.get("DENODO_PASSWORD", "")
DENODO_TIMEOUT_SECONDS = int(os.environ.get("DENODO_TIMEOUT_SECONDS", "20"))
DENODO_VERIFY_SSL = os.environ.get("DENODO_VERIFY_SSL", "true").strip().lower() not in {"0", "false", "no", "off"}
DENODO_EMPLOYEE_USE_SERVER_FILTER = os.environ.get(
    "DENODO_EMPLOYEE_USE_SERVER_FILTER",
    "true",
).strip().lower() in {"1", "true", "yes", "on"}
DENODO_EMPLOYEE_NAME_FIELD = os.environ.get("DENODO_EMPLOYEE_NAME_FIELD", "preferred_full_name")
DENODO_EMPLOYEE_FALLBACK_NAME_FIELD = os.environ.get("DENODO_EMPLOYEE_FALLBACK_NAME_FIELD", "full_name")
DENODO_EMPLOYEE_EMAIL_FIELD = os.environ.get("DENODO_EMPLOYEE_EMAIL_FIELD", "email_id")
DENODO_EMPLOYEE_USER_FIELD = os.environ.get("DENODO_EMPLOYEE_USER_FIELD", "user_id")
DENODO_EMPLOYEE_ID_FIELD = os.environ.get("DENODO_EMPLOYEE_ID_FIELD", "person_num")
DENODO_EMPLOYEE_STATUS_FIELD = os.environ.get("DENODO_EMPLOYEE_STATUS_FIELD", "person_status_code")
DENODO_EMPLOYEE_ACTIVE_VALUE = os.environ.get("DENODO_EMPLOYEE_ACTIVE_VALUE", "A")
DENODO_EMPLOYEE_TEAM_FIELD = os.environ.get("DENODO_EMPLOYEE_TEAM_FIELD", "group_name")

# Denodo-backed form tag/autocomplete configuration. These use the same
# Denodo credentials as the employee lookup. Keep URLs configurable because
# localhost only works when TraceAPL is running on the same host/tunnel as Denodo.
DENODO_WORK_PROGRAM_REST_URL = os.environ.get(
    "DENODO_WORK_PROGRAM_REST_URL",
    "https://denodo.jhuapl.edu:9443/denodo-restfulws/addit/views/dim_work_program",
).strip()
DENODO_WORK_PROGRAM_SEARCH_FIELDS = [
    field.strip() for field in os.environ.get(
        "DENODO_WORK_PROGRAM_SEARCH_FIELDS",
        "work_program_name",
    ).split(",") if field.strip()
]
DENODO_WORK_PROGRAM_LABEL_FIELDS = [
    field.strip() for field in os.environ.get(
        "DENODO_WORK_PROGRAM_LABEL_FIELDS",
        "work_program_name",
    ).split(",") if field.strip()
]
DENODO_WORK_PROGRAM_FILTER_PREFIX = os.environ.get("DENODO_WORK_PROGRAM_FILTER_PREFIX", "").strip()

DENODO_LOCATION_REST_URL = os.environ.get(
    "DENODO_LOCATION_REST_URL",
    "https://denodo.jhuapl.edu:9443/denodo-restfulws/APL_Common/views/loc_room_locations",
).strip()
DENODO_LOCATION_SEARCH_FIELDS = [
    field.strip() for field in os.environ.get(
        "DENODO_LOCATION_SEARCH_FIELDS",
        "location_display_id",
    ).split(",") if field.strip()
]
DENODO_LOCATION_LABEL_FIELDS = [
    field.strip() for field in os.environ.get(
        "DENODO_LOCATION_LABEL_FIELDS",
        "location_display_id",
    ).split(",") if field.strip()
]
DENODO_LOCATION_FILTER_PREFIX = os.environ.get("DENODO_LOCATION_FILTER_PREFIX", "").strip()

MOCK_EMPLOYEES = [
    {"display_name": "Test User", "email": "test.user@example.org", "employee_id": "000000", "user_id": "testuser", "team": "Mock Team"},
    {"display_name": "Sample Assignee", "email": "sample.assignee@example.org", "employee_id": "000001", "user_id": "samplea", "team": "Mock Team"},
    {"display_name": "Alex Characterization", "email": "alex.characterization@example.org", "employee_id": "000002", "user_id": "alexc", "team": "Mock Team"},
]

_last_backup_check_date: str | None = None
_last_reminder_check_date: str | None = None

app = Flask(__name__)
app.secret_key = os.environ.get("TRACEAPL_SECRET_KEY", "dev-change-this-secret-key")


def is_admin() -> bool:
    return bool(session.get("traceapl_admin"))


def admin_required(view_func):
    @functools.wraps(view_func)
    def wrapped(*args, **kwargs):
        if not is_admin():
            flash("Admin login required for that action.", "error")
            return redirect(url_for("admin_login", next=request.url))
        return view_func(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_admin_state() -> dict[str, Any]:
    return {"is_admin": is_admin()}


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def admin_actor() -> str:
    return session.get("traceapl_admin_user") or "TraceAPL admin"


def log_audit_event(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: str,
    action: str,
    details: dict[str, Any] | str | None = None,
    actor: str | None = None,
) -> None:
    if isinstance(details, str):
        details_text = details
    elif details is None:
        details_text = ""
    else:
        details_text = json.dumps(details, default=str, sort_keys=True)
    conn.execute(
        """
        INSERT INTO audit_events (entity_type, entity_id, action, actor, timestamp, details)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (entity_type, entity_id, action, actor or admin_actor(), now_iso(), details_text),
    )



def create_database_backup(reason: str = "manual") -> Path | None:
    """Create a point-in-time SQLite backup file and return its path."""
    if not DB_FILE.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_reason = "".join(ch for ch in reason.lower() if ch.isalnum() or ch in {"_", "-"}) or "backup"
    backup_path = BACKUP_DIR / f"traceapl_{safe_reason}_{timestamp}.db"

    source = sqlite3.connect(DB_FILE)
    try:
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()

    cleanup_old_backups()
    return backup_path


def cleanup_old_backups() -> None:
    """Remove TraceAPL backup files older than the configured retention window."""
    if BACKUP_RETENTION_DAYS <= 0 or not BACKUP_DIR.exists():
        return

    cutoff = datetime.now() - timedelta(days=BACKUP_RETENTION_DAYS)
    for path in BACKUP_DIR.glob("traceapl_*.db"):
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        if modified < cutoff:
            try:
                path.unlink()
            except OSError:
                pass


def ensure_daily_backup() -> Path | None:
    """Create one automatic backup per calendar day while the app is running."""
    today = datetime.now().strftime("%Y%m%d")
    if BACKUP_DIR.exists() and any(BACKUP_DIR.glob(f"traceapl_daily_{today}_*.db")):
        cleanup_old_backups()
        return None
    return create_database_backup("daily")


def latest_backup() -> Path | None:
    if not BACKUP_DIR.exists():
        return None
    backups = sorted(BACKUP_DIR.glob("traceapl_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return backups[0] if backups else None


def backup_summary() -> dict[str, Any]:
    latest = latest_backup()
    count = len(list(BACKUP_DIR.glob("traceapl_*.db"))) if BACKUP_DIR.exists() else 0
    return {
        "count": count,
        "latest_name": latest.name if latest else "No backups yet",
        "latest_time": datetime.fromtimestamp(latest.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if latest else "—",
        "retention_days": BACKUP_RETENTION_DAYS,
    }


@app.before_request
def run_daily_maintenance_check() -> None:
    global _last_backup_check_date, _last_reminder_check_date
    today = datetime.now().strftime("%Y-%m-%d")

    if _last_backup_check_date != today:
        ensure_daily_backup()
        _last_backup_check_date = today

    if _last_reminder_check_date != today:
        try:
            send_due_characterization_reminders()
        except Exception as exc:
            # Reminders should never make the web app unavailable.
            print("TRACEAPL REMINDER CHECK ERROR:", repr(exc))
        _last_reminder_check_date = today


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
                work_program TEXT,
                project TEXT,
                task TEXT,
                notes TEXT
            )
            """
        )
        # Lightweight migrations for databases created by earlier versions.
        sample_columns = {row[1] for row in conn.execute("PRAGMA table_info(samples)").fetchall()}
        if "work_program" not in sample_columns:
            conn.execute("ALTER TABLE samples ADD COLUMN work_program TEXT")
            sample_columns.add("work_program")
        if "project" not in sample_columns:
            conn.execute("ALTER TABLE samples ADD COLUMN project TEXT")
            sample_columns.add("project")
        if "task" not in sample_columns:
            conn.execute("ALTER TABLE samples ADD COLUMN task TEXT")
            sample_columns.add("task")
        # Migrate older Project/Task values into the unified Work Program field.
        # This keeps existing databases compatible while the UI uses one Work Program field.
        project_expr = "COALESCE(NULLIF(TRIM(project), ''), '')"
        task_expr = "COALESCE(NULLIF(TRIM(task), ''), '')"
        conn.execute(
            f"""
            UPDATE samples
            SET work_program = CASE
                WHEN {project_expr} != '' AND {task_expr} != '' THEN {project_expr} || ' - ' || {task_expr}
                WHEN {project_expr} != '' THEN {project_expr}
                WHEN {task_expr} != '' THEN {task_expr}
                ELSE work_program
            END
            WHERE COALESCE(NULLIF(TRIM(work_program), ''), '') = ''
            """
        )
        if "deleted_at" not in sample_columns:
            conn.execute("ALTER TABLE samples ADD COLUMN deleted_at TEXT")
        if "deleted_by" not in sample_columns:
            conn.execute("ALTER TABLE samples ADD COLUMN deleted_by TEXT")
        if "delete_reason" not in sample_columns:
            conn.execute("ALTER TABLE samples ADD COLUMN delete_reason TEXT")
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
        if "assigned_to" not in characterization_columns:
            conn.execute("ALTER TABLE characterizations ADD COLUMN assigned_to TEXT")
        if "reminder_last_sent_at" not in characterization_columns:
            conn.execute("ALTER TABLE characterizations ADD COLUMN reminder_last_sent_at TEXT")
        if "reminder_count" not in characterization_columns:
            conn.execute("ALTER TABLE characterizations ADD COLUMN reminder_count INTEGER DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT,
                timestamp TEXT NOT NULL,
                details TEXT
            )
            """
        )


def normalize_code_value(code_value: str) -> str:
    """Normalize scanner input from QR codes, barcodes, and keyboard-wedge scanners."""
    return "".join(str(code_value or "").replace("\r", "").replace("\n", "").split("\t")).strip()


def fetch_sample(qr_code_value: str, include_deleted: bool = False) -> sqlite3.Row | None:
    where_deleted = "" if include_deleted else " AND deleted_at IS NULL"
    with get_db() as conn:
        return conn.execute(
            f"SELECT * FROM samples WHERE qr_code_value = ?{where_deleted}",
            (normalize_code_value(qr_code_value),),
        ).fetchone()


def log_scan(qr_code_value: str, scan_type: str, result: str, scanned_by: str = "", notes: str = "") -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO scan_events (qr_code_value, scan_type, scanned_by, timestamp, result, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (normalize_code_value(qr_code_value), scan_type, scanned_by.strip(), now_iso(), result, notes.strip()),
        )

def manual_tracking_key(sample_id: str) -> str:
    """Create an internal lookup key for samples entered without a QR label."""
    cleaned = sample_id.strip()
    return f"MANUAL::{cleaned}"


def is_manual_tracking_key(qr_code_value: str) -> bool:
    return qr_code_value.startswith("MANUAL::")


def sample_url(qr_code_value: str) -> str:
    if TRACEAPL_BASE_URL:
        return f"{TRACEAPL_BASE_URL.rstrip('/')}{url_for('sample_detail', qr_code_value=qr_code_value)}"
    return url_for('sample_detail', qr_code_value=qr_code_value, _external=True)


def extract_email_from_assignment(value: str) -> str:
    """Extract an email address from TraceAPL assignment text.

    Supports values such as:
        Name <person@example.org>
        person@example.org
    """
    value = (value or "").strip()
    if "<" in value and ">" in value:
        return value.split("<", 1)[1].split(">", 1)[0].strip()
    if "@" in value and " " not in value:
        return value
    if "@" in value:
        # Fallback for manually entered strings that include a name and email
        # without angle brackets. Return the first token that looks like email.
        for token in value.replace(",", " ").split():
            if "@" in token:
                return token.strip("<>;,.()[]{}")
    return ""


def send_plain_email(to_email: str, subject: str, body: str) -> None:
    """Send a plain-text TraceAPL email notification via configured SMTP."""
    if not TRACEAPL_EMAIL_ENABLED:
        return
    if not to_email:
        return
    if not TRACEAPL_SMTP_HOST:
        raise RuntimeError("TRACEAPL_SMTP_HOST is not configured.")

    from_email = TRACEAPL_SMTP_FROM or TRACEAPL_EMAIL_FROM or TRACEAPL_SMTP_USERNAME
    if not from_email:
        raise RuntimeError("TRACEAPL_EMAIL_FROM or TRACEAPL_SMTP_FROM is not configured.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(body)

    with smtplib.SMTP(TRACEAPL_SMTP_HOST, TRACEAPL_SMTP_PORT, timeout=20) as server:
        if TRACEAPL_SMTP_TLS and TRACEAPL_SMTP_USE_TLS:
            server.starttls()
        if TRACEAPL_SMTP_USERNAME and TRACEAPL_SMTP_PASSWORD:
            server.login(TRACEAPL_SMTP_USERNAME, TRACEAPL_SMTP_PASSWORD)
        server.send_message(msg)


def send_characterization_assignment_notification(
    assigned_to: str,
    sample_id: str,
    qr_code_value: str,
    characterization_type: str,
    notes: str = "",
) -> list[str]:
    """Send optional assignment notifications when a characterization is assigned."""
    assigned_to = (assigned_to or "").strip()
    if not assigned_to:
        return []

    messages: list[str] = []
    link = sample_url(qr_code_value)
    subject = f"TraceAPL characterization assigned: {characterization_type} for {sample_id}"
    body = (
        "You have been assigned a TraceAPL characterization task.\n\n"
        f"Sample: {sample_id}\n"
        f"Characterization: {characterization_type}\n"
        f"Assigned to: {assigned_to}\n"
        f"Sample record: {link}\n"
    )
    if notes:
        body += f"Notes: {notes}\n"

    assigned_email = extract_email_from_assignment(assigned_to)

    if TRACEAPL_EMAIL_ENABLED:
        if not assigned_email:
            messages.append(f"email not sent: no email address found in assignment value '{assigned_to}'")
        else:
            try:
                send_plain_email(assigned_email, subject, body)
                messages.append(f"email sent to {assigned_email}")
            except Exception as exc:  # Keep the app usable if notification delivery fails.
                messages.append(f"email not sent to {assigned_email}: {exc}")

    if TRACEAPL_SLACK_WEBHOOK_URL:
        try:
            payload = {
                "text": (
                    f"TraceAPL characterization assigned: *{characterization_type}* for sample *{sample_id}* "
                    f"to {assigned_to}. {link}"
                )
            }
            req = urllib.request.Request(
                TRACEAPL_SLACK_WEBHOOK_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                response.read()
            messages.append("Slack notification sent")
        except Exception as exc:
            messages.append(f"Slack notification not sent: {exc}")

    return messages

def notify_assignment_flash(assigned_to: str, sample_id: str, qr_code_value: str, characterization_type: str, notes: str = "") -> None:
    results = send_characterization_assignment_notification(assigned_to, sample_id, qr_code_value, characterization_type, notes)
    for result in results:
        category = "success" if "sent" in result and "not sent" not in result else "error"
        flash(result, category)


def send_characterization_reminder_notification(
    assigned_to: str,
    sample_id: str,
    qr_code_value: str,
    characterization_type: str,
    created_at: str,
    notes: str = "",
) -> str:
    """Send a weekly reminder email for an incomplete characterization task."""
    assigned_email = extract_email_from_assignment(assigned_to)
    if not assigned_email:
        return f"reminder not sent: no email address found in assignment value '{assigned_to}'"

    link = sample_url(qr_code_value)
    subject = f"TraceAPL reminder: {characterization_type} for {sample_id} is still pending"
    body = (
        "This is a TraceAPL reminder that a characterization task assigned to you "
        "has not yet been logged as completed.\n\n"
        f"Sample: {sample_id}\n"
        f"Characterization: {characterization_type}\n"
        f"Assigned to: {assigned_to}\n"
        f"Created: {created_at}\n"
        f"Sample record: {link}\n\n"
        "You will receive this reminder weekly until the task is marked complete in TraceAPL.\n"
    )
    if notes:
        body += f"\nNotes: {notes}\n"

    send_plain_email(assigned_email, subject, body)
    return f"reminder sent to {assigned_email}"


def send_due_characterization_reminders(limit: Optional[int] = None) -> list[str]:
    """Send reminders for assigned, incomplete characterizations due for weekly follow-up."""
    if not TRACEAPL_EMAIL_REMINDERS_ENABLED or not TRACEAPL_EMAIL_ENABLED:
        return []

    if TRACEAPL_EMAIL_REMINDER_INTERVAL_DAYS <= 0:
        return []

    batch_limit = limit or TRACEAPL_EMAIL_REMINDER_BATCH_LIMIT
    due_before = (datetime.now() - timedelta(days=TRACEAPL_EMAIL_REMINDER_INTERVAL_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    sent_at = now_iso()
    results: list[str] = []

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id AS characterization_id,
                c.qr_code_value,
                c.characterization_type,
                c.created_at,
                c.notes,
                c.assigned_to,
                COALESCE(c.reminder_count, 0) AS reminder_count,
                s.sample_id
            FROM characterizations c
            JOIN samples s ON s.qr_code_value = c.qr_code_value
            WHERE s.deleted_at IS NULL
              AND c.completed_at IS NULL
              AND c.assigned_to IS NOT NULL
              AND TRIM(c.assigned_to) <> ''
              AND c.created_at <= ?
              AND (c.reminder_last_sent_at IS NULL OR c.reminder_last_sent_at <= ?)
            ORDER BY c.created_at ASC, c.id ASC
            LIMIT ?
            """,
            (due_before, due_before, batch_limit),
        ).fetchall()

        for row in rows:
            try:
                result = send_characterization_reminder_notification(
                    assigned_to=row["assigned_to"] or "",
                    sample_id=row["sample_id"],
                    qr_code_value=row["qr_code_value"],
                    characterization_type=row["characterization_type"],
                    created_at=row["created_at"],
                    notes=row["notes"] or "",
                )
                conn.execute(
                    """
                    UPDATE characterizations
                    SET reminder_last_sent_at = ?, reminder_count = COALESCE(reminder_count, 0) + 1
                    WHERE id = ?
                    """,
                    (sent_at, row["characterization_id"]),
                )
                results.append(result)
            except Exception as exc:
                message = f"reminder not sent for characterization {row['characterization_id']}: {exc}"
                print("TRACEAPL REMINDER ERROR:", message)
                results.append(message)

    return results


def build_denodo_employee_filter(query: str) -> str:
    """Build a Denodo REST $filter expression using VQL WHERE syntax."""
    safe_query = (query or "").strip().lower().replace("'", "''")
    return (
        f"{DENODO_EMPLOYEE_STATUS_FIELD} = '{DENODO_EMPLOYEE_ACTIVE_VALUE}' "
        f"AND {DENODO_EMPLOYEE_EMAIL_FIELD} IS NOT NULL "
        "AND ("
        f"lower({DENODO_EMPLOYEE_NAME_FIELD}) LIKE '%{safe_query}%' OR "
        f"lower({DENODO_EMPLOYEE_FALLBACK_NAME_FIELD}) LIKE '%{safe_query}%' OR "
        f"lower({DENODO_EMPLOYEE_EMAIL_FIELD}) LIKE '%{safe_query}%' OR "
        f"lower({DENODO_EMPLOYEE_USER_FIELD}) LIKE '%{safe_query}%'"
        ")"
    )


def normalize_employee_record(record: dict[str, Any]) -> dict[str, str] | None:
    """Convert a Denodo employee record into the limited object used by the browser."""
    display_name = str(
        record.get(DENODO_EMPLOYEE_NAME_FIELD)
        or record.get(DENODO_EMPLOYEE_FALLBACK_NAME_FIELD)
        or ""
    ).strip()
    email = str(record.get(DENODO_EMPLOYEE_EMAIL_FIELD) or "").strip()
    user_id = str(record.get(DENODO_EMPLOYEE_USER_FIELD) or "").strip()
    employee_id = str(record.get(DENODO_EMPLOYEE_ID_FIELD) or "").strip()
    team = str(
        record.get(DENODO_EMPLOYEE_TEAM_FIELD)
        or record.get("org_name")
        or record.get("group_name")
        or ""
    ).strip()

    if not display_name or not email:
        return None

    value = f"{display_name} <{email}>"
    return {
        "display_name": display_name,
        "email": email,
        "employee_id": employee_id,
        "user_id": user_id,
        "team": team,
        "value": value,
        "label": value,
    }


def search_mock_employees(query: str, limit: Optional[int] = None) -> list[dict[str, str]]:
    normalized = (query or "").strip().lower()
    if len(normalized) < 2:
        return []
    if limit is None:
        limit = 10
    matches = []
    for record in MOCK_EMPLOYEES:
        searchable = " ".join(str(value) for value in record.values()).lower()
        if normalized in searchable:
            item = normalize_employee_record({
                DENODO_EMPLOYEE_NAME_FIELD: record["display_name"],
                DENODO_EMPLOYEE_EMAIL_FIELD: record["email"],
                DENODO_EMPLOYEE_ID_FIELD: record["employee_id"],
                DENODO_EMPLOYEE_USER_FIELD: record["user_id"],
                DENODO_EMPLOYEE_TEAM_FIELD: record["team"],
            })
            if item:
                matches.append(item)
        if len(matches) >= limit:
            break
    return matches


def search_denodo_rest_employees(query: str, limit: Optional[int] = None) -> list[dict[str, str]]:
    """Search Denodo REST for employees and return safe autocomplete objects."""
    normalized = (query or "").strip()
    if len(normalized) < 2:
        return []
    if limit is None:
        limit = 10
    if not DENODO_EMPLOYEE_REST_URL:
        raise RuntimeError("DENODO_EMPLOYEE_REST_URL is not configured.")
    if not DENODO_USERNAME or not DENODO_PASSWORD:
        raise RuntimeError("DENODO_USERNAME and DENODO_PASSWORD must be configured for Denodo REST lookup.")

    fetch_count = max(limit * 5, 50)
    params = {
        "$format": "json",
        "$count": str(fetch_count),
    }
    if DENODO_EMPLOYEE_USE_SERVER_FILTER:
        params["$filter"] = build_denodo_employee_filter(normalized)

    response = requests.get(
        DENODO_EMPLOYEE_REST_URL,
        params=params,
        auth=(DENODO_USERNAME, DENODO_PASSWORD),
        timeout=DENODO_TIMEOUT_SECONDS,
        verify=DENODO_VERIFY_SSL,
    )
    response.raise_for_status()

    data = response.json()
    elements = data.get("elements", []) if isinstance(data, dict) else []

    matches: list[dict[str, str]] = []
    normalized_lower = normalized.lower()
    for record in elements:
        if not isinstance(record, dict):
            continue
        if not DENODO_EMPLOYEE_USE_SERVER_FILTER:
            status = str(record.get(DENODO_EMPLOYEE_STATUS_FIELD, "")).strip()
            if status != DENODO_EMPLOYEE_ACTIVE_VALUE:
                continue
            searchable = " ".join([
                str(record.get(DENODO_EMPLOYEE_NAME_FIELD, "")),
                str(record.get(DENODO_EMPLOYEE_FALLBACK_NAME_FIELD, "")),
                str(record.get(DENODO_EMPLOYEE_EMAIL_FIELD, "")),
                str(record.get(DENODO_EMPLOYEE_USER_FIELD, "")),
                str(record.get("first_name", "")),
                str(record.get("last_name", "")),
                str(record.get("preferred_first_name", "")),
                str(record.get("preferred_last_name", "")),
            ]).lower()
            if normalized_lower not in searchable:
                continue
        item = normalize_employee_record(record)
        if item:
            matches.append(item)
        if len(matches) >= limit:
            break
    return matches


def search_employees(query: str, limit: Optional[int] = None) -> list[dict[str, str]]:
    if TRACEAPL_EMPLOYEE_LOOKUP_MODE == "rest":
        return search_denodo_rest_employees(query, limit)
    return search_mock_employees(query, limit)


def denodo_escape_literal(value: str) -> str:
    return (value or "").strip().lower().replace("'", "''")


def build_denodo_tag_filter(query: str, search_fields: list[str], filter_prefix: str = "") -> str:
    safe_query = denodo_escape_literal(query)
    clauses = [f"lower({field}) LIKE '%{safe_query}%'" for field in search_fields]
    search_expr = " OR ".join(clauses) if clauses else ""
    if filter_prefix and search_expr:
        return f"({filter_prefix}) AND ({search_expr})"
    if filter_prefix:
        return filter_prefix
    return f"({search_expr})" if search_expr else ""


def format_denodo_tag_value(record: dict[str, Any], label_fields: list[str], fallback_fields: list[str]) -> tuple[str, str]:
    parts: list[str] = []
    seen: set[str] = set()
    for field in label_fields + fallback_fields:
        value = str(record.get(field) or "").strip()
        if value and value.lower() not in seen:
            parts.append(value)
            seen.add(value.lower())
    value = " - ".join(parts[:3]).strip()
    if not value:
        return "", ""
    primary = parts[0]
    secondary = " - ".join(parts[1:3])
    return value, secondary


def search_denodo_tag_view(
    *,
    rest_url: str,
    query: str,
    search_fields: list[str],
    label_fields: list[str],
    filter_prefix: str = "",
    limit: Optional[int] = None,
) -> list[dict[str, str]]:
    normalized = (query or "").strip()
    if len(normalized) < 2:
        return []
    if limit is None:
        limit = 10
    if not rest_url:
        raise RuntimeError("Denodo REST URL is not configured for this lookup.")
    if not DENODO_USERNAME or not DENODO_PASSWORD:
        raise RuntimeError("DENODO_USERNAME and DENODO_PASSWORD must be configured for Denodo REST lookup.")

    fetch_count = max(limit * 5, 50)
    params = {
        "$format": "json",
        "$count": str(fetch_count),
    }
    filter_expr = build_denodo_tag_filter(normalized, search_fields, filter_prefix)
    if filter_expr:
        params["$filter"] = filter_expr

    try:
        response = requests.get(
            rest_url,
            params=params,
            auth=(DENODO_USERNAME, DENODO_PASSWORD),
            timeout=DENODO_TIMEOUT_SECONDS,
            verify=DENODO_VERIFY_SSL,
        )
        response.raise_for_status()
        data = response.json()
        elements = data.get("elements", []) if isinstance(data, dict) else []
    except requests.HTTPError as exc:
        # Some Denodo views reject a filter if even one field name is not searchable
        # or not present in the view. Fall back to one-field filters so valid fields
        # still work without breaking the whole autocomplete.
        status_code = getattr(exc.response, "status_code", None)
        if status_code != 400 or not filter_expr:
            raise
        elements = []
        seen_records: set[str] = set()
        for field in search_fields:
            single_filter = build_denodo_tag_filter(normalized, [field], filter_prefix)
            if not single_filter:
                continue
            single_params = {
                "$format": "json",
                "$count": str(fetch_count),
                "$filter": single_filter,
            }
            try:
                single_response = requests.get(
                    rest_url,
                    params=single_params,
                    auth=(DENODO_USERNAME, DENODO_PASSWORD),
                    timeout=DENODO_TIMEOUT_SECONDS,
                    verify=DENODO_VERIFY_SSL,
                )
                single_response.raise_for_status()
                single_data = single_response.json()
                single_elements = single_data.get("elements", []) if isinstance(single_data, dict) else []
            except requests.HTTPError as single_exc:
                if getattr(single_exc.response, "status_code", None) == 400:
                    continue
                raise
            for record in single_elements:
                if not isinstance(record, dict):
                    continue
                record_key = json.dumps(record, sort_keys=True, default=str)
                if record_key in seen_records:
                    continue
                seen_records.add(record_key)
                elements.append(record)
        if not elements:
            # Last-resort fallback: pull a small first page without a filter and let
            # local matching below decide. This keeps the endpoint available even
            # while the exact Denodo field mapping is being refined.
            fallback_response = requests.get(
                rest_url,
                params={"$format": "json", "$count": str(fetch_count)},
                auth=(DENODO_USERNAME, DENODO_PASSWORD),
                timeout=DENODO_TIMEOUT_SECONDS,
                verify=DENODO_VERIFY_SSL,
            )
            fallback_response.raise_for_status()
            fallback_data = fallback_response.json()
            elements = fallback_data.get("elements", []) if isinstance(fallback_data, dict) else []

    matches: list[dict[str, str]] = []
    normalized_lower = normalized.lower()
    for record in elements:
        if not isinstance(record, dict):
            continue
        value, secondary = format_denodo_tag_value(record, label_fields, search_fields)
        if not value:
            continue
        # Keep a local match guard in case a Denodo view ignores/relaxes the filter.
        searchable = " ".join(str(record.get(field, "")) for field in search_fields).lower()
        if normalized_lower not in searchable and normalized_lower not in value.lower():
            continue
        matches.append({
            "value": value,
            "label": value,
            "display_name": value,
            "secondary": secondary,
        })
        if len(matches) >= limit:
            break
    return matches


@app.route("/api/work-programs/search")
def api_work_program_search() -> Response:
    query = request.args.get("q", "").strip()
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        limit = 10
    limit = max(1, min(limit, 25))
    try:
        return jsonify(search_denodo_tag_view(
            rest_url=DENODO_WORK_PROGRAM_REST_URL,
            query=query,
            search_fields=DENODO_WORK_PROGRAM_SEARCH_FIELDS,
            label_fields=DENODO_WORK_PROGRAM_LABEL_FIELDS,
            filter_prefix=DENODO_WORK_PROGRAM_FILTER_PREFIX,
            limit=limit,
        ))
    except Exception as exc:
        print("WORK PROGRAM LOOKUP ERROR:", repr(exc))
        return jsonify({"error": "Work program lookup temporarily unavailable."}), 503


@app.route("/api/locations/search")
def api_location_search() -> Response:
    query = request.args.get("q", "").strip()
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        limit = 10
    limit = max(1, min(limit, 25))
    try:
        return jsonify(search_denodo_tag_view(
            rest_url=DENODO_LOCATION_REST_URL,
            query=query,
            search_fields=DENODO_LOCATION_SEARCH_FIELDS,
            label_fields=DENODO_LOCATION_LABEL_FIELDS,
            filter_prefix=DENODO_LOCATION_FILTER_PREFIX,
            limit=limit,
        ))
    except Exception as exc:
        print("LOCATION LOOKUP ERROR:", repr(exc))
        return jsonify({"error": "Location lookup temporarily unavailable."}), 503


@app.route("/api/employees/search")
def api_employee_search() -> Response:
    query = request.args.get("q", "").strip()
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        limit = 10
    limit = max(1, min(limit, 25))

    try:
        return jsonify(search_employees(query, limit))
    except Exception as exc:
        print("EMPLOYEE LOOKUP ERROR:", repr(exc))
        return jsonify({"error": "Employee lookup temporarily unavailable."}), 503


@app.route("/admin")
@admin_required
def admin_dashboard() -> str:
    return render_template("admin.html", backup_info=backup_summary())


@app.route("/admin/reminders/run", methods=["POST"])
@admin_required
def run_reminders_now() -> Response:
    results = send_due_characterization_reminders()
    sent_count = sum(1 for result in results if result.startswith("reminder sent"))
    if results:
        flash(f"Reminder check complete. {sent_count} reminder email(s) sent.", "success" if sent_count else "error")
    else:
        flash("Reminder check complete. No reminders were due.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login() -> str | Response:
    next_url = request.values.get("next") or url_for("admin_dashboard")
    if request.method == "POST":
        password = request.form.get("password", "")
        if hmac.compare_digest(password, ADMIN_PASSWORD):
            session["traceapl_admin"] = True
            session["traceapl_admin_user"] = request.form.get("admin_user", "").strip() or "TraceAPL admin"
            flash("Admin login successful.", "success")
            return redirect(next_url)
        flash("Incorrect admin password.", "error")
    return render_template("admin_login.html", next_url=next_url)


@app.route("/admin/logout", methods=["POST"])
def admin_logout() -> Response:
    session.pop("traceapl_admin", None)
    session.pop("traceapl_admin_user", None)
    flash("Admin logged out.", "success")
    return redirect(url_for("home"))


@app.route("/")
def home() -> str:
    week_start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        recent_samples = conn.execute(
            "SELECT * FROM samples WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT 8"
        ).fetchall()
        recent_week_samples = conn.execute(
            "SELECT * FROM samples WHERE deleted_at IS NULL AND created_at >= ? ORDER BY created_at DESC LIMIT 8",
            (week_start,),
        ).fetchall()
        recent_week_count = conn.execute(
            "SELECT COUNT(*) AS count FROM samples WHERE deleted_at IS NULL AND created_at >= ?",
            (week_start,),
        ).fetchone()["count"]
        completed_characterization_count = conn.execute(
            "SELECT COUNT(*) AS count FROM characterizations c JOIN samples s ON s.qr_code_value = c.qr_code_value WHERE s.deleted_at IS NULL AND c.completed_at IS NOT NULL"
        ).fetchone()["count"]
        pending_characterization_count = conn.execute(
            "SELECT COUNT(*) AS count FROM characterizations c JOIN samples s ON s.qr_code_value = c.qr_code_value WHERE s.deleted_at IS NULL AND c.completed_at IS NULL"
        ).fetchone()["count"]
        recent_handoffs = conn.execute(
            "SELECT h.* FROM handoffs h JOIN samples s ON s.qr_code_value = h.qr_code_value WHERE s.deleted_at IS NULL ORDER BY h.timestamp DESC, h.id DESC LIMIT 8"
        ).fetchall()
        work_program_portals = conn.execute(
            """
            SELECT
                COALESCE(NULLIF(TRIM(s.work_program), ''), 'Unassigned Work Program') AS work_program_name,
                COUNT(*) AS sample_count,
                MAX(s.created_at) AS latest_sample_at,
                SUM(CASE WHEN c.completed_at IS NULL AND c.id IS NOT NULL THEN 1 ELSE 0 END) AS pending_characterizations,
                SUM(CASE WHEN c.completed_at IS NOT NULL THEN 1 ELSE 0 END) AS completed_characterizations
            FROM samples s
            LEFT JOIN characterizations c ON c.qr_code_value = s.qr_code_value
            WHERE s.deleted_at IS NULL
            GROUP BY work_program_name
            ORDER BY latest_sample_at DESC
            """
        ).fetchall()
    return render_template(
        "home.html",
        recent_samples=recent_samples,
        recent_week_samples=recent_week_samples,
        recent_week_count=recent_week_count,
        completed_characterization_count=completed_characterization_count,
        pending_characterization_count=pending_characterization_count,
        recent_handoffs=recent_handoffs,
        work_program_portals=work_program_portals,
    )


@app.route("/sample/manual/new")
def manual_sample() -> str:
    return render_template("new_sample.html", qr_code_value="", manual_entry=True)


@app.route("/work-program/<path:work_program_name>")
def work_program_portal(work_program_name: str) -> str:
    normalized_work_program = work_program_name.strip()
    is_unassigned = normalized_work_program == "Unassigned Work Program"

    where_clause = "s.deleted_at IS NULL AND COALESCE(NULLIF(TRIM(s.work_program), ''), 'Unassigned Work Program') = ?"
    params = (normalized_work_program,)

    with get_db() as conn:
        samples = conn.execute(
            f"""
            SELECT s.* FROM samples s
            WHERE {where_clause}
            ORDER BY s.created_at DESC
            """,
            params,
        ).fetchall()
        sample_count = len(samples)
        completed_characterization_count = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM characterizations c
            JOIN samples s ON s.qr_code_value = c.qr_code_value
            WHERE {where_clause} AND c.completed_at IS NOT NULL
            """,
            params,
        ).fetchone()["count"]
        pending_characterization_count = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM characterizations c
            JOIN samples s ON s.qr_code_value = c.qr_code_value
            WHERE {where_clause} AND c.completed_at IS NULL
            """,
            params,
        ).fetchone()["count"]
        recent_handoffs = conn.execute(
            f"""
            SELECT h.*, s.sample_id
            FROM handoffs h
            JOIN samples s ON s.qr_code_value = h.qr_code_value
            WHERE {where_clause}
            ORDER BY h.timestamp DESC, h.id DESC
            LIMIT 8
            """,
            params,
        ).fetchall()

    return render_template(
        "project.html",
        work_program_name=normalized_work_program,
        is_unassigned=is_unassigned,
        samples=samples,
        sample_count=sample_count,
        completed_characterization_count=completed_characterization_count,
        pending_characterization_count=pending_characterization_count,
        recent_handoffs=recent_handoffs,
    )


@app.route("/project/<path:project_name>")
def project_portal(project_name: str) -> Response:
    # Backward-compatible redirect for old Project portal links.
    return redirect(url_for("work_program_portal", work_program_name=project_name))


@app.route("/scan")
def scan() -> str:
    mode = request.args.get("mode", "lookup")
    if mode not in {"lookup", "assign"}:
        mode = "lookup"
    return render_template("scan.html", mode=mode)


@app.route("/mobile/scan")
def mobile_scan() -> str:
    mode = request.args.get("mode", "lookup")
    if mode not in {"lookup", "assign"}:
        mode = "lookup"
    return render_template("mobile_scan.html", mode=mode)


@app.route("/scan/submit", methods=["POST"])
def submit_scan() -> Response | str:
    qr_code_value = normalize_code_value(request.form.get("qr_code_value", ""))
    mode = request.form.get("mode", "lookup")
    scanned_by = request.form.get("scanned_by", "").strip()

    if not qr_code_value:
        flash("Scan or enter a QR code or barcode first.", "error")
        return redirect(url_for("scan", mode=mode))

    sample = fetch_sample(qr_code_value)
    if sample:
        log_scan(qr_code_value, mode, "existing_sample_found", scanned_by)
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))

    log_scan(qr_code_value, mode, "unassigned_code", scanned_by)
    return redirect(url_for("new_sample", qr_code_value=qr_code_value))


@app.route("/sample/new")
def new_sample() -> str:
    qr_code_value = normalize_code_value(request.args.get("qr_code_value", ""))
    if not qr_code_value:
        flash("Scan an unused QR code or barcode before creating a sample.", "error")
        return redirect(url_for("scan", mode="assign"))
    existing = fetch_sample(qr_code_value)
    if existing:
        flash("That code is already assigned.", "error")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))
    return render_template("new_sample.html", qr_code_value=qr_code_value, manual_entry=False)


@app.route("/sample/create", methods=["POST"])
def create_sample() -> Response:
    entry_mode = request.form.get("entry_mode", "qr").strip()
    qr_code_value = normalize_code_value(request.form.get("qr_code_value", ""))
    sample_id = request.form.get("sample_id", "").strip()

    if not sample_id:
        flash("Sample ID is required.", "error")
        return redirect(url_for("manual_sample") if entry_mode == "manual" else url_for("new_sample", qr_code_value=qr_code_value))

    if entry_mode == "manual":
        qr_code_value = manual_tracking_key(sample_id)
        with get_db() as conn:
            existing_sample_id = conn.execute("SELECT 1 FROM samples WHERE sample_id = ?", (sample_id,)).fetchone()
        if existing_sample_id:
            flash("That Sample ID already exists. Choose a unique Sample ID for manual entry.", "error")
            return redirect(url_for("manual_sample"))
    elif not qr_code_value:
        flash("A QR code or barcode is required for code-based sample creation.", "error")
        return redirect(url_for("new_sample", qr_code_value=qr_code_value))

    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO samples (
                    qr_code_value, sample_id, sample_type, batch_lot, created_by,
                    created_at, current_owner, current_location, status, work_program, project, task, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    request.form.get("work_program", request.form.get("project", "")).strip(),
                    request.form.get("work_program", request.form.get("project", "")).strip(),
                    "",
                    request.form.get("notes", "").strip(),
                ),
            )
            characterization_values = request.form.getlist("characterization_type")
            assigned_values = request.form.getlist("characterization_assigned_to")
            notification_queue: list[tuple[str, str, str]] = []
            for index, value in enumerate(characterization_values):
                value = value.strip()
                assigned_to = assigned_values[index].strip() if index < len(assigned_values) else ""
                if value:
                    conn.execute(
                        """
                        INSERT INTO characterizations (
                            qr_code_value, characterization_type, created_at, assigned_to, notes
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (qr_code_value, value, now_iso(), assigned_to, ""),
                    )
                    if assigned_to:
                        notification_queue.append((assigned_to, value, ""))
        log_scan(qr_code_value, "assign", "sample_created", request.form.get("created_by", ""))
        if entry_mode == "manual":
            flash("Manual sample record created.", "success")
        else:
            flash("Sample created and code assigned.", "success")
        for assigned_to, value, notes in notification_queue:
            notify_assignment_flash(assigned_to, sample_id, qr_code_value, value, notes)
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))
    except sqlite3.IntegrityError:
        if entry_mode == "manual":
            flash("That manual Sample ID already exists.", "error")
            return redirect(url_for("manual_sample"))
        flash("That code is already assigned to another sample.", "error")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))


@app.route("/sample/<path:qr_code_value>")
def sample_detail(qr_code_value: str) -> str | Response:
    sample = fetch_sample(qr_code_value)
    if not sample:
        flash("Code is not assigned yet. Create a sample record first.", "error")
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
        is_manual_sample=is_manual_tracking_key(qr_code_value),
    )


@app.route("/sample/<path:qr_code_value>/label")
def sample_label(qr_code_value: str) -> str | Response:
    """Generate a printable QR label for the saved tracking code value."""
    sample = fetch_sample(qr_code_value)
    if not sample:
        flash("Sample entry was not found, so a label could not be generated.", "error")
        return redirect(url_for("scan", mode="lookup"))

    try:
        import qrcode
    except ImportError:
        flash("QR label generation requires the qrcode package. Run: pip install -r requirements.txt", "error")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    # Encode only the saved tracking value. Scanning this regenerated QR code
    # will behave the same as scanning the original label/barcode.
    qr.add_data(sample["qr_code_value"])
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_png_base64 = base64.b64encode(buffer.getvalue()).decode("ascii")

    return render_template(
        "label.html",
        sample=sample,
        qr_png_base64=qr_png_base64,
        is_manual_sample=is_manual_tracking_key(qr_code_value),
    )


@app.route("/sample/<path:qr_code_value>/characterization/add", methods=["POST"])
def add_characterization(qr_code_value: str) -> Response:
    sample = fetch_sample(qr_code_value)
    if not sample:
        flash("Cannot add characterization for an unassigned code.", "error")
        return redirect(url_for("scan", mode="lookup"))

    characterization_type = request.form.get("characterization_type", "").strip()
    assigned_to = request.form.get("assigned_to", "").strip()
    if not characterization_type:
        flash("Enter a characterization type first.", "error")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO characterizations (qr_code_value, characterization_type, created_at, assigned_to, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (qr_code_value, characterization_type, now_iso(), assigned_to, request.form.get("notes", "").strip()),
        )
    flash("Characterization requirement added.", "success")
    if assigned_to:
        notify_assignment_flash(assigned_to, sample["sample_id"], qr_code_value, characterization_type, request.form.get("notes", "").strip())
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
        flash("Cannot record a handoff for an unassigned code.", "error")
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
                WHERE deleted_at IS NULL
                  AND (qr_code_value LIKE ?
                   OR sample_id LIKE ?
                   OR sample_type LIKE ?
                   OR batch_lot LIKE ?
                   OR work_program LIKE ?
                   OR current_owner LIKE ?
                   OR current_location LIKE ?
                   OR status LIKE ?
                   OR EXISTS (
                       SELECT 1 FROM characterizations c
                       WHERE c.qr_code_value = samples.qr_code_value
                         AND (c.characterization_type LIKE ? OR c.assigned_to LIKE ?)
                   ))
                ORDER BY created_at DESC
                """,
                (like, like, like, like, like, like, like, like, like, like),
            ).fetchall()
    return render_template("search.html", term=term, rows=rows)



@app.route("/sample/<path:qr_code_value>/edit", methods=["GET", "POST"])
@admin_required
def edit_sample(qr_code_value: str) -> str | Response:
    sample = fetch_sample(qr_code_value)
    if not sample:
        flash("Sample entry was not found or is archived.", "error")
        return redirect(url_for("search"))

    if request.method == "POST":
        sample_id = request.form.get("sample_id", "").strip()
        if not sample_id:
            flash("Sample ID is required.", "error")
            return redirect(url_for("edit_sample", qr_code_value=qr_code_value))

        old_values = row_to_dict(sample)
        new_values = {
            "sample_id": sample_id,
            "sample_type": request.form.get("sample_type", "").strip(),
            "batch_lot": request.form.get("batch_lot", "").strip(),
            "current_owner": request.form.get("current_owner", "").strip(),
            "current_location": request.form.get("current_location", "").strip(),
            "status": request.form.get("status", "").strip(),
            "work_program": request.form.get("work_program", request.form.get("project", "")).strip(),
            "notes": request.form.get("notes", "").strip(),
        }

        with get_db() as conn:
            conn.execute(
                """
                UPDATE samples
                SET sample_id = ?, sample_type = ?, batch_lot = ?, current_owner = ?,
                    current_location = ?, status = ?, work_program = ?, project = ?, task = ?, notes = ?
                WHERE qr_code_value = ? AND deleted_at IS NULL
                """,
                (
                    new_values["sample_id"],
                    new_values["sample_type"],
                    new_values["batch_lot"],
                    new_values["current_owner"],
                    new_values["current_location"],
                    new_values["status"],
                    new_values["work_program"],
                    new_values["work_program"],
                    "",
                    new_values["notes"],
                    qr_code_value,
                ),
            )
            log_audit_event(
                conn,
                "sample",
                qr_code_value,
                "edit_sample",
                {"before": old_values, "after": new_values},
            )
        flash("Sample details updated.", "success")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))

    return render_template("edit_sample.html", sample=sample)


@app.route("/sample/<path:qr_code_value>/characterization/<int:char_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_characterization(qr_code_value: str, char_id: int) -> str | Response:
    sample = fetch_sample(qr_code_value)
    if not sample:
        flash("Sample entry was not found or is archived.", "error")
        return redirect(url_for("search"))

    with get_db() as conn:
        characterization = conn.execute(
            "SELECT * FROM characterizations WHERE id = ? AND qr_code_value = ?",
            (char_id, qr_code_value),
        ).fetchone()
    if not characterization:
        flash("Characterization item not found.", "error")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))

    if request.method == "POST":
        characterization_type = request.form.get("characterization_type", "").strip()
        if not characterization_type:
            flash("Characterization type is required.", "error")
            return redirect(url_for("edit_characterization", qr_code_value=qr_code_value, char_id=char_id))

        old_values = row_to_dict(characterization)
        assigned_to = request.form.get("assigned_to", "").strip()
        notes = request.form.get("notes", "").strip()
        data_location = request.form.get("data_location", "").strip()
        completion_status = request.form.get("completion_status", "pending")
        completed_by = request.form.get("completed_by", "").strip()
        completed_at = request.form.get("completed_at", "").strip()

        if completion_status == "complete":
            if not completed_by:
                completed_by = old_values.get("completed_by") or admin_actor()
            if not completed_at:
                completed_at = old_values.get("completed_at") or now_iso()
        else:
            completed_by = ""
            completed_at = None

        new_values = {
            "characterization_type": characterization_type,
            "assigned_to": assigned_to,
            "notes": notes,
            "data_location": data_location,
            "completed_by": completed_by,
            "completed_at": completed_at,
        }

        with get_db() as conn:
            conn.execute(
                """
                UPDATE characterizations
                SET characterization_type = ?, assigned_to = ?, notes = ?, data_location = ?,
                    completed_by = ?, completed_at = ?
                WHERE id = ? AND qr_code_value = ?
                """,
                (
                    characterization_type,
                    assigned_to,
                    notes,
                    data_location,
                    completed_by,
                    completed_at,
                    char_id,
                    qr_code_value,
                ),
            )
            log_audit_event(
                conn,
                "characterization",
                str(char_id),
                "edit_characterization",
                {"sample_qr_code_value": qr_code_value, "before": old_values, "after": new_values},
            )

        if assigned_to and assigned_to != (old_values.get("assigned_to") or "") and request.form.get("send_assignment_email"):
            notify_assignment_flash(assigned_to, sample["sample_id"], qr_code_value, characterization_type, notes)

        flash("Characterization item updated.", "success")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))

    return render_template("edit_characterization.html", sample=sample, characterization=characterization)


@app.route("/admin/deleted")
@admin_required
def admin_deleted_samples() -> str:
    with get_db() as conn:
        deleted_samples = conn.execute(
            "SELECT * FROM samples WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC"
        ).fetchall()
    return render_template("deleted_samples.html", deleted_samples=deleted_samples)


@app.route("/sample/<path:qr_code_value>/restore", methods=["POST"])
@admin_required
def restore_sample(qr_code_value: str) -> Response:
    sample = fetch_sample(qr_code_value, include_deleted=True)
    if not sample:
        flash("Sample entry was not found.", "error")
        return redirect(url_for("admin_deleted_samples"))
    if not sample["deleted_at"]:
        flash("Sample is already active.", "success")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))

    with get_db() as conn:
        conn.execute(
            "UPDATE samples SET deleted_at = NULL, deleted_by = NULL, delete_reason = NULL WHERE qr_code_value = ?",
            (qr_code_value,),
        )
        log_audit_event(conn, "sample", qr_code_value, "restore_sample", row_to_dict(sample))
    flash(f"Restored sample entry {sample['sample_id']}.", "success")
    return redirect(url_for("sample_detail", qr_code_value=qr_code_value))


@app.route("/admin/audit")
@admin_required
def admin_audit() -> str:
    with get_db() as conn:
        events = conn.execute(
            "SELECT * FROM audit_events ORDER BY timestamp DESC, id DESC LIMIT 250"
        ).fetchall()
    return render_template("audit.html", events=events)


@app.route("/sample/<path:qr_code_value>/delete", methods=["POST"])
@admin_required
def delete_sample(qr_code_value: str) -> Response:
    sample = fetch_sample(qr_code_value)
    if not sample:
        flash("Sample entry was not found or is already archived.", "error")
        return redirect(url_for("search"))

    confirmation = request.form.get("confirm_sample_id", "").strip()
    expected = sample["sample_id"]
    if confirmation != expected:
        flash(f"Archive was not completed. Type the exact Sample ID ({expected}) to confirm.", "error")
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))

    create_database_backup("prearchive")
    deleted_at = now_iso()
    delete_reason = request.form.get("delete_reason", "").strip()

    with get_db() as conn:
        conn.execute(
            """
            UPDATE samples
            SET deleted_at = ?, deleted_by = ?, delete_reason = ?
            WHERE qr_code_value = ? AND deleted_at IS NULL
            """,
            (deleted_at, admin_actor(), delete_reason, qr_code_value),
        )
        log_audit_event(
            conn,
            "sample",
            qr_code_value,
            "archive_sample",
            {"sample": row_to_dict(sample), "delete_reason": delete_reason},
        )

    flash(f"Archived sample entry {expected}. A pre-archive database backup was created first.", "success")
    return redirect(url_for("home"))


@app.route("/backup/create", methods=["POST"])
@admin_required
def create_backup_now() -> Response:
    backup_path = create_database_backup("manual")
    if backup_path:
        flash(f"Manual database backup created: {backup_path.name}", "success")
    else:
        flash("No database file exists yet, so there was nothing to back up.", "error")
    return redirect(request.referrer or url_for("home"))


@app.route("/backup/latest")
@admin_required
def download_latest_backup() -> Response:
    backup_path = latest_backup()
    if not backup_path:
        flash("No backup is available yet.", "error")
        return redirect(url_for("home"))
    return send_file(
        backup_path,
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=backup_path.name,
    )


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
    ensure_daily_backup()
    ssl_mode = os.environ.get("TRACEAPL_SSL", "").strip().lower()
    ssl_context = None
    if ssl_mode in {"1", "true", "adhoc", "self-signed"}:
        # Ad-hoc HTTPS is useful for phone-camera testing on a local network.
        # Browsers will show a certificate warning because this is not a trusted cert.
        ssl_context = "adhoc"
    elif ssl_mode and "," in ssl_mode:
        cert_file, key_file = [part.strip() for part in ssl_mode.split(",", 1)]
        ssl_context = (cert_file, key_file)

    app.run(
        host=os.environ.get("TRACEAPL_HOST", "127.0.0.1"),
        port=int(os.environ.get("TRACEAPL_PORT", "5000")),
        debug=os.environ.get("TRACEAPL_DEBUG", "1") != "0",
        ssl_context=ssl_context,
    )
