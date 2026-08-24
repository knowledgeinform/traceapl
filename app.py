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
import hashlib
import io
import json
import html
import os
import smtplib
import sqlite3
import urllib.request
import secrets
import re

import requests
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Optional

from flask import Flask, Response, flash, jsonify, has_request_context, make_response, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

APP_DIR = Path(__file__).resolve().parent
DB_FILE = APP_DIR / "sample_tracker_web.db"
BACKUP_DIR = APP_DIR / "backups"
SAMPLE_UPLOAD_DIR = APP_DIR / "sample_uploads"
BACKUP_RETENTION_DAYS = int(os.environ.get("TRACEAPL_BACKUP_RETENTION_DAYS", "30"))
ADMIN_USERNAME = os.environ.get("TRACEAPL_ADMIN_USERNAME", "admin").strip().lower() or "admin"
ADMIN_PASSWORD = os.environ.get("TRACEAPL_ADMIN_PASSWORD", "change-me")
TRACEAPL_REMEMBER_DAYS = int(os.environ.get("TRACEAPL_REMEMBER_DAYS", "14"))
TRACEAPL_PASSWORD_MIN_LENGTH = int(os.environ.get("TRACEAPL_PASSWORD_MIN_LENGTH", "15"))
TRACEAPL_SAMPLE_PHOTO_MAX_MB = int(os.environ.get("TRACEAPL_SAMPLE_PHOTO_MAX_MB", "10"))
ALLOWED_SAMPLE_PHOTO_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
ALLOWED_SAMPLE_PHOTO_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
app_max_mb = int(os.environ.get("TRACEAPL_MAX_UPLOAD_MB", str(max(16, TRACEAPL_SAMPLE_PHOTO_MAX_MB + 4))))
TRACEAPL_SYSTEM_AUDIT_RETENTION_DAYS = int(os.environ.get("TRACEAPL_SYSTEM_AUDIT_RETENTION_DAYS", "730"))
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

# Daily Denodo work-authorization sync. The first production use case pulls
# work orders tagged with CHAR HAND OFF and creates TraceAPL sample records.
TRACEAPL_WORK_AUTH_SYNC_ENABLED = os.environ.get("TRACEAPL_WORK_AUTH_SYNC_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
TRACEAPL_WORK_AUTH_SYNC_DRY_RUN = os.environ.get("TRACEAPL_WORK_AUTH_SYNC_DRY_RUN", "true").strip().lower() in {"1", "true", "yes", "on"}
TRACEAPL_WORK_AUTH_SYNC_HOUR = int(os.environ.get("TRACEAPL_WORK_AUTH_SYNC_HOUR", "8"))
TRACEAPL_WORK_AUTH_NOTIFY_EMAIL = os.environ.get("TRACEAPL_WORK_AUTH_NOTIFY_EMAIL", "avi.bregman@jhuapl.edu").strip()
TRACEAPL_WORK_AUTH_DEFAULT_LOCATION = os.environ.get("TRACEAPL_WORK_AUTH_DEFAULT_LOCATION", "15-W114A").strip()
DENODO_WORK_AUTH_OPS_REST_URL = os.environ.get(
    "DENODO_WORK_AUTH_OPS_REST_URL",
    "https://denodo.jhuapl.edu:9443/denodo-restfulws/APL_Engineering/views/ve_wo_ops",
).strip()
DENODO_WORK_AUTH_WO_REST_URL = os.environ.get(
    "DENODO_WORK_AUTH_WO_REST_URL",
    "https://denodo.jhuapl.edu:9443/denodo-restfulws/APL_Engineering/views/ve_wo",
).strip()
DENODO_WORK_AUTH_OPERATION_FIELD = os.environ.get("DENODO_WORK_AUTH_OPERATION_FIELD", "OPERATION_TYPE").strip()
DENODO_WORK_AUTH_OPERATION_VALUE = os.environ.get("DENODO_WORK_AUTH_OPERATION_VALUE", "CHAR HAND OFF").strip()
DENODO_WORK_AUTH_OPS_BASE_ID_FIELD = os.environ.get("DENODO_WORK_AUTH_OPS_BASE_ID_FIELD", "WORKORDER_BASE_ID").strip()
DENODO_WORK_AUTH_WO_BASE_ID_FIELD = os.environ.get("DENODO_WORK_AUTH_WO_BASE_ID_FIELD", "BASE_ID").strip()
DENODO_WORK_AUTH_WAREHOUSE_FIELD = os.environ.get("DENODO_WORK_AUTH_WAREHOUSE_FIELD", "WAREHOUSE_ID").strip()
DENODO_WORK_AUTH_WBS_FIELD = os.environ.get("DENODO_WORK_AUTH_WBS_FIELD", "WBS_CODE").strip()
DENODO_WORK_AUTH_PROJECT_SEPARATOR = os.environ.get("DENODO_WORK_AUTH_PROJECT_SEPARATOR", "")


MOCK_EMPLOYEES = [
    {"display_name": "Test User", "email": "test.user@example.org", "employee_id": "000000", "user_id": "testuser", "team": "Mock Team"},
    {"display_name": "Sample Assignee", "email": "sample.assignee@example.org", "employee_id": "000001", "user_id": "samplea", "team": "Mock Team"},
    {"display_name": "Alex Characterization", "email": "alex.characterization@example.org", "employee_id": "000002", "user_id": "alexc", "team": "Mock Team"},
]

_last_backup_check_date: str | None = None
_last_reminder_check_date: str | None = None
_last_system_audit_cleanup_date: str | None = None
_last_work_auth_sync_check_date: str | None = None

app = Flask(__name__)
app.secret_key = os.environ.get("TRACEAPL_SECRET_KEY", "dev-change-this-secret-key")
app.config["MAX_CONTENT_LENGTH"] = app_max_mb * 1024 * 1024


def is_logged_in() -> bool:
    return bool(session.get("traceapl_user_id") or session.get("traceapl_builtin_admin"))


def current_username() -> str:
    return str(session.get("traceapl_username") or "")


def is_admin() -> bool:
    return bool(session.get("traceapl_builtin_admin") or session.get("traceapl_role") == "admin" or session.get("traceapl_admin"))


def admin_required(view_func):
    @functools.wraps(view_func)
    def wrapped(*args, **kwargs):
        if not is_logged_in():
            flash("Admin login is required for that action.", "error")
            return redirect(url_for("admin_login", next=request.url))
        if not is_admin():
            with get_db() as conn:
                log_system_audit_event(conn, "admin_access_denied", "failure", target_type="endpoint", target_id=request.endpoint or "", details={"path": request.path})
            flash("Admin privileges are required for that action.", "error")
            return redirect(url_for("home"))
        return view_func(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_user_state() -> dict[str, Any]:
    return {
        "is_logged_in": is_logged_in(),
        "current_username": current_username(),
        "is_admin": is_admin(),
    }


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
    return current_username() or session.get("traceapl_admin_user") or "TraceAPL admin"


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


def get_client_ip() -> str:
    """Return the best available client IP for audit records."""
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.remote_addr or ""


def log_system_audit_event(
    conn: sqlite3.Connection,
    event_type: str,
    outcome: str = "success",
    username: str | None = None,
    role: str | None = None,
    target_type: str = "",
    target_id: str = "",
    details: dict[str, Any] | str | None = None,
) -> None:
    """Create a security/system audit record. Admin-only retention is 2 years by default."""
    if isinstance(details, str):
        details_text = details
    elif details is None:
        details_text = ""
    else:
        details_text = json.dumps(details, default=str, sort_keys=True)
    conn.execute(
        """
        INSERT INTO system_audit_log (
            timestamp, username, role, event_type, outcome, target_type, target_id,
            ip_address, user_agent, method, path, details
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now_iso(),
            username if username is not None else (current_username() if has_request_context() else "system"),
            role if role is not None else (str(session.get("traceapl_role") or ("admin" if session.get("traceapl_builtin_admin") else "")) if has_request_context() else "system"),
            event_type,
            outcome,
            target_type,
            target_id,
            get_client_ip() if has_request_context() else "",
            request.headers.get("User-Agent", "") if has_request_context() else "",
            request.method if has_request_context() else "SYSTEM",
            request.path if has_request_context() else "",
            details_text,
        ),
    )


def cleanup_old_system_audit_events() -> None:
    """Retain system audit records for TRACEAPL_SYSTEM_AUDIT_RETENTION_DAYS, default 730 days."""
    if TRACEAPL_SYSTEM_AUDIT_RETENTION_DAYS <= 0:
        return
    cutoff = (datetime.now() - timedelta(days=TRACEAPL_SYSTEM_AUDIT_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        conn.execute("DELETE FROM system_audit_log WHERE timestamp < ?", (cutoff,))



USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def validate_username(username: str) -> str | None:
    if not username:
        return "Username is required."
    if not USERNAME_RE.match(username):
        return "Username must be 3-64 characters and may contain letters, numbers, dots, hyphens, and underscores."
    if username == ADMIN_USERNAME:
        return "That username is reserved. Choose a different username."
    return None


def validate_password(password: str, confirm_password: str | None = None, username: str | None = None) -> str | None:
    """Validate TraceAPL account passwords.

    Requirements:
    - Minimum 15 characters.
    - Must include at least 3 of 4 character types: lowercase, uppercase, number, special.
    - Must not contain the TraceAPL/JHU/APL username. TraceAPL self-registration does
      not collect first, middle, or last names; if those fields are added later, add
      them to this check as additional prohibited tokens.
    - Passwords do not expire by policy.
    """
    password = password or ""
    if confirm_password is not None and password != confirm_password:
        return "Passwords do not match."
    if len(password) < TRACEAPL_PASSWORD_MIN_LENGTH:
        return f"Password must be at least {TRACEAPL_PASSWORD_MIN_LENGTH} characters."

    character_type_count = sum([
        any(ch.islower() for ch in password),
        any(ch.isupper() for ch in password),
        any(ch.isdigit() for ch in password),
        any(not ch.isalnum() for ch in password),
    ])
    if character_type_count < 3:
        return "Password must include at least 3 of these 4 character types: lowercase letters, uppercase letters, numbers, and special characters."

    normalized_password = password.lower()
    normalized_username = normalize_username(username or "")
    if normalized_username and len(normalized_username) >= 3 and normalized_username in normalized_password:
        return "Password may not include your TraceAPL/JHU/APL username."
    return None

def fetch_user_by_username(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE username = ?", (normalize_username(username),)).fetchone()


def login_session_for_builtin_admin() -> None:
    session.clear()
    session["traceapl_builtin_admin"] = True
    session["traceapl_user_id"] = "builtin-admin"
    session["traceapl_username"] = ADMIN_USERNAME
    session["traceapl_role"] = "admin"
    session["traceapl_admin"] = True
    session["traceapl_admin_user"] = ADMIN_USERNAME


def login_session_for_user(user: sqlite3.Row) -> None:
    session.clear()
    session["traceapl_user_id"] = int(user["id"])
    session["traceapl_username"] = user["username"]
    session["traceapl_role"] = user["role"] or "user"
    if session["traceapl_role"] == "admin":
        session["traceapl_admin"] = True
        session["traceapl_admin_user"] = user["username"]


def clear_login_session() -> None:
    session.pop("traceapl_builtin_admin", None)
    session.pop("traceapl_user_id", None)
    session.pop("traceapl_username", None)
    session.pop("traceapl_role", None)
    session.pop("traceapl_admin", None)
    session.pop("traceapl_admin_user", None)


def create_remember_token(conn: sqlite3.Connection, user_id: int, response: Response) -> None:
    selector = secrets.token_urlsafe(18)
    token = secrets.token_urlsafe(36)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = (datetime.now() + timedelta(days=TRACEAPL_REMEMBER_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO remember_tokens (selector, user_id, token_hash, created_at, expires_at, last_used_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (selector, user_id, token_hash, now_iso(), expires_at, now_iso()),
    )
    response.set_cookie(
        "traceapl_remember",
        f"{selector}:{token}",
        max_age=TRACEAPL_REMEMBER_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=request.is_secure,
        samesite="Lax",
    )


def clear_remember_cookie(response: Response) -> Response:
    cookie_value = request.cookies.get("traceapl_remember", "")
    if ":" in cookie_value:
        selector = cookie_value.split(":", 1)[0]
        with get_db() as conn:
            conn.execute("DELETE FROM remember_tokens WHERE selector = ?", (selector,))
    response.delete_cookie("traceapl_remember")
    return response


def try_restore_remembered_user() -> bool:
    cookie_value = request.cookies.get("traceapl_remember", "")
    if ":" not in cookie_value:
        return False
    selector, token = cookie_value.split(":", 1)
    if not selector or not token:
        return False
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT rt.*, u.username, u.password_hash, u.role, u.is_active
            FROM remember_tokens rt
            JOIN users u ON u.id = rt.user_id
            WHERE rt.selector = ?
            """,
            (selector,),
        ).fetchone()
        if not row:
            return False
        try:
            expired = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S") < datetime.now()
        except Exception:
            expired = True
        if expired or not row["is_active"] or not hmac.compare_digest(row["token_hash"], token_hash):
            conn.execute("DELETE FROM remember_tokens WHERE selector = ?", (selector,))
            return False
        user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        if not user:
            return False
        login_session_for_user(user)
        conn.execute("UPDATE remember_tokens SET last_used_at = ? WHERE selector = ?", (now_iso(), selector))
    return True


def public_endpoint(endpoint: str | None) -> bool:
    """Return True for endpoints that do not require admin authentication.

    TraceAPL normal sample-tracking workflows are intentionally open to users who
    can reach the application through the approved network/SSO boundary. The
    built-in admin login is still required for admin-only endpoints by the
    @admin_required decorator.
    """
    if not endpoint:
        return True
    if endpoint == "static":
        return True
    return not endpoint.startswith("admin_")



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
def run_daily_maintenance_check() -> Response | None:
    # Normal TraceAPL pages do not require user login. Admin-only routes remain
    # protected by @admin_required.
    global _last_backup_check_date, _last_reminder_check_date, _last_system_audit_cleanup_date, _last_work_auth_sync_check_date
    today = datetime.now().strftime("%Y-%m-%d")

    if _last_backup_check_date != today:
        ensure_daily_backup()
        _last_backup_check_date = today

    if _last_system_audit_cleanup_date != today:
        try:
            cleanup_old_system_audit_events()
        except Exception as exc:
            print("TRACEAPL SYSTEM AUDIT CLEANUP ERROR:", repr(exc))
        _last_system_audit_cleanup_date = today

    if _last_reminder_check_date != today:
        try:
            send_due_characterization_reminders()
        except Exception as exc:
            # Reminders should never make the web app unavailable.
            print("TRACEAPL REMINDER CHECK ERROR:", repr(exc))
        _last_reminder_check_date = today

    work_auth_sync_check = globals().get("maybe_run_daily_work_auth_sync")
    if callable(work_auth_sync_check):
        try:
            work_auth_sync_check()
        except Exception as exc:
            # Denodo sync should never make the web app unavailable.
            print("TRACEAPL WORK AUTH SYNC CHECK ERROR:", repr(exc))


def init_db() -> None:
    SAMPLE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
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
            CREATE TABLE IF NOT EXISTS sample_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qr_code_value TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                original_filename TEXT,
                content_type TEXT,
                size_bytes INTEGER,
                caption TEXT,
                uploaded_by TEXT,
                uploaded_at TEXT NOT NULL,
                FOREIGN KEY (qr_code_value) REFERENCES samples(qr_code_value)
            )
            """
        )
        sample_photo_columns = {row[1] for row in conn.execute("PRAGMA table_info(sample_photos)").fetchall()}
        if "caption" not in sample_photo_columns:
            conn.execute("ALTER TABLE sample_photos ADD COLUMN caption TEXT")

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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                username TEXT,
                role TEXT,
                event_type TEXT NOT NULL,
                outcome TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                ip_address TEXT,
                user_agent TEXT,
                method TEXT,
                path TEXT,
                details TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_system_audit_log_timestamp ON system_audit_log(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_system_audit_log_event_type ON system_audit_log(event_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_system_audit_log_username ON system_audit_log(username)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS work_auth_sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                triggered_by TEXT,
                dry_run INTEGER NOT NULL DEFAULT 1,
                scanned INTEGER NOT NULL DEFAULT 0,
                created INTEGER NOT NULL DEFAULT 0,
                skipped_existing INTEGER NOT NULL DEFAULT 0,
                skipped_missing_project INTEGER NOT NULL DEFAULT 0,
                errors TEXT,
                created_samples TEXT,
                summary_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_work_auth_sync_runs_started_at ON work_auth_sync_runs(started_at)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT,
                last_password_change_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS remember_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                selector TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_used_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_remember_tokens_user_id ON remember_tokens(user_id)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
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

def manual_tracking_key(sample_id: str, work_program: str = "") -> str:
    """Create an internal lookup key for samples entered without a QR label.

    Manual entries do not have a preprinted QR/barcode value to guarantee uniqueness.
    Earlier versions used only the Sample ID, which made Sample IDs globally unique.
    The key now includes a deterministic hash of Sample ID + Work Program so the
    same Sample ID can be used in different work programs while remaining unique
    inside one work program.
    """
    cleaned_sample = sample_id.strip()
    cleaned_work_program = work_program.strip() or "UNASSIGNED"
    digest = hashlib.sha256(f"{cleaned_work_program.lower()}::{cleaned_sample.lower()}".encode("utf-8")).hexdigest()[:16]
    return f"MANUAL::{digest}::{cleaned_sample}"


def is_manual_tracking_key(qr_code_value: str) -> bool:
    return qr_code_value.startswith("MANUAL::")


def generated_tracking_key() -> str:
    """Create a TraceAPL-generated tracking value for samples created before a physical label exists."""
    return f"TRACEAPL-GENERATED::{secrets.token_urlsafe(18)}"


def generate_unique_tracking_key(conn: sqlite3.Connection) -> str:
    for _ in range(20):
        candidate = generated_tracking_key()
        if not conn.execute("SELECT 1 FROM samples WHERE qr_code_value = ?", (candidate,)).fetchone():
            return candidate
    raise RuntimeError("Unable to generate a unique TraceAPL tracking code.")


def is_generated_tracking_key(qr_code_value: str) -> bool:
    return qr_code_value.startswith("TRACEAPL-GENERATED::")


def allowed_sample_photo(filename: str, content_type: str) -> bool:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return extension in ALLOWED_SAMPLE_PHOTO_EXTENSIONS and content_type in ALLOWED_SAMPLE_PHOTO_CONTENT_TYPES


def save_sample_photo(conn: sqlite3.Connection, qr_code_value: str, file_storage, caption: str = "") -> int | None:
    """Save an optional sample photo and create a DB record. Returns the photo id, or None."""
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None

    original_filename = secure_filename(file_storage.filename or "")
    content_type = file_storage.mimetype or "application/octet-stream"
    if not original_filename:
        raise ValueError("Photo filename is empty.")
    if not allowed_sample_photo(original_filename, content_type):
        raise ValueError("Photo must be a JPG, PNG, GIF, or WEBP image.")

    # Read once so size limits are enforced before anything is written to disk.
    data = file_storage.read()
    max_bytes = TRACEAPL_SAMPLE_PHOTO_MAX_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise ValueError(f"Photo must be {TRACEAPL_SAMPLE_PHOTO_MAX_MB} MB or smaller.")

    extension = original_filename.rsplit(".", 1)[-1].lower()
    stored_filename = f"sample-photo-{secrets.token_urlsafe(18)}.{extension}"
    SAMPLE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (SAMPLE_UPLOAD_DIR / stored_filename).write_bytes(data)

    cursor = conn.execute(
        """
        INSERT INTO sample_photos (
            qr_code_value, stored_filename, original_filename, content_type,
            size_bytes, caption, uploaded_by, uploaded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (qr_code_value, stored_filename, original_filename, content_type, len(data), caption.strip(), current_username(), now_iso()),
    )
    log_audit_event(conn, "sample", qr_code_value, "sample_photo_uploaded", {"photo_id": cursor.lastrowid, "original_filename": original_filename})
    log_system_audit_event(conn, "sample_photo_uploaded", "success", target_type="sample", target_id=qr_code_value, details={"photo_id": cursor.lastrowid})
    return int(cursor.lastrowid)


def sample_id_exists_in_work_program(sample_id: str, work_program: str, exclude_qr_code_value: str = "") -> bool:
    """Return True when an active sample already uses this Sample ID in this Work Program."""
    normalized_sample_id = sample_id.strip()
    normalized_work_program = work_program.strip()
    sql = """
        SELECT 1
        FROM samples
        WHERE deleted_at IS NULL
          AND lower(TRIM(sample_id)) = lower(TRIM(?))
          AND lower(TRIM(COALESCE(work_program, ''))) = lower(TRIM(?))
    """
    params: list[str] = [normalized_sample_id, normalized_work_program]
    if exclude_qr_code_value:
        sql += " AND qr_code_value != ?"
        params.append(exclude_qr_code_value)
    sql += " LIMIT 1"
    with get_db() as conn:
        return conn.execute(sql, params).fetchone() is not None


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




def _denodo_rest_get(rest_url: str, params: dict[str, str] | None = None) -> Any:
    """Fetch a Denodo REST endpoint and return JSON data or response text.

    Some Denodo REST pages return HTML with a JavaScript ``var data = [...]`` block
    unless JSON is explicitly supported. The work-authorization sync handles both.
    """
    if not DENODO_USERNAME or not DENODO_PASSWORD:
        raise RuntimeError("DENODO_USERNAME and DENODO_PASSWORD must be configured for Denodo REST lookup.")
    response = requests.get(
        rest_url,
        params=params or {},
        auth=(DENODO_USERNAME, DENODO_PASSWORD),
        timeout=DENODO_TIMEOUT_SECONDS,
        verify=DENODO_VERIFY_SSL,
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").lower()
    if "json" in content_type:
        return response.json()
    text = response.text
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return response.json()
        except Exception:
            return text
    return text


def _extract_denodo_rows(payload: Any) -> list[dict[str, Any]]:
    """Extract rows from Denodo JSON or Denodo's HTML table page."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("elements", "data", "rows", "result", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        # Some Denodo responses wrap rows one level deeper.
        for value in payload.values():
            if isinstance(value, dict):
                nested = _extract_denodo_rows(value)
                if nested:
                    return nested
        return []
    if not isinstance(payload, str):
        return []

    # Denodo browser pages embed the returned records as JavaScript:
    #   var data = [{...}, {...}];
    match = re.search(r"var\s+data\s*=\s*(\[.*?\])\s*;", payload, flags=re.DOTALL)
    if not match:
        return []
    raw = html.unescape(match.group(1))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Keep this explicit so the admin sync page records a useful error.
        raise RuntimeError("Unable to parse Denodo HTML response: embedded var data block was not valid JSON.")
    return [row for row in data if isinstance(row, dict)]


def _fetch_denodo_view_rows(rest_url: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    payload = _denodo_rest_get(rest_url, params=params)
    return _extract_denodo_rows(payload)


def _first_nonempty(row: dict[str, Any], field_names: list[str]) -> str:
    for name in field_names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _work_auth_project_id(warehouse_id: str, wbs_code: str) -> str:
    warehouse_id = (warehouse_id or "").strip()
    wbs_code = (wbs_code or "").strip()
    if warehouse_id and wbs_code:
        return f"{warehouse_id}{DENODO_WORK_AUTH_PROJECT_SEPARATOR}{wbs_code}"
    return warehouse_id or wbs_code


def fetch_char_handoff_denodo_records() -> list[dict[str, str]]:
    """Return CHAR HAND OFF work orders with project/work-program data from Denodo."""
    ops_rows = _fetch_denodo_view_rows(
        DENODO_WORK_AUTH_OPS_REST_URL,
        params={DENODO_WORK_AUTH_OPERATION_FIELD: DENODO_WORK_AUTH_OPERATION_VALUE},
    )
    seen_base_ids: set[str] = set()
    records: list[dict[str, str]] = []
    for row in ops_rows:
        base_id = _first_nonempty(row, [DENODO_WORK_AUTH_OPS_BASE_ID_FIELD, "WORKORDER_BASE_ID", "BASE_ID"])
        if not base_id or base_id in seen_base_ids:
            continue
        seen_base_ids.add(base_id)
        records.append({"base_id": base_id, "operation_type": str(row.get(DENODO_WORK_AUTH_OPERATION_FIELD, DENODO_WORK_AUTH_OPERATION_VALUE) or "")})

    for record in records:
        base_id = record["base_id"]
        wo_rows: list[dict[str, Any]] = []
        # Try the base-id field configured for ve_wo, then common fallbacks.
        for field in [DENODO_WORK_AUTH_WO_BASE_ID_FIELD, "BASE_ID", "WORKORDER_BASE_ID", "WONUM"]:
            if not field:
                continue
            try:
                wo_rows = _fetch_denodo_view_rows(DENODO_WORK_AUTH_WO_REST_URL, params={field: base_id})
            except requests.HTTPError:
                wo_rows = []
            if wo_rows:
                break
        if not wo_rows:
            record.update({"warehouse_id": "", "wbs_code": "", "work_program": ""})
            continue
        wo = wo_rows[0]
        warehouse_id = _first_nonempty(wo, [DENODO_WORK_AUTH_WAREHOUSE_FIELD, "WAREHOUSE_ID"])
        wbs_code = _first_nonempty(wo, [DENODO_WORK_AUTH_WBS_FIELD, "WBS_CODE"])
        record.update({
            "warehouse_id": warehouse_id,
            "wbs_code": wbs_code,
            "work_program": _work_auth_project_id(warehouse_id, wbs_code),
        })
    return records


def _work_auth_duplicate_exists(conn: sqlite3.Connection, work_program: str, base_id: str) -> bool:
    return conn.execute(
        """
        SELECT 1 FROM samples
        WHERE COALESCE(deleted_at, '') = ''
          AND TRIM(COALESCE(work_program, '')) = ?
          AND TRIM(COALESCE(batch_lot, '')) = ?
        LIMIT 1
        """,
        (work_program.strip(), base_id.strip()),
    ).fetchone() is not None


def send_work_auth_sample_notification(sample_info: dict[str, str]) -> None:
    if not TRACEAPL_WORK_AUTH_NOTIFY_EMAIL:
        return
    subject = f"TraceAPL CHAR HAND OFF sample added: {sample_info.get('sample_id', '')}"
    body = (
        "TraceAPL created a sample from the Denodo CHAR HAND OFF sync.\n\n"
        f"Sample ID: {sample_info.get('sample_id', '')}\n"
        f"Batch/Lot: {sample_info.get('batch_lot', '')}\n"
        f"Work Program: {sample_info.get('work_program', '')}\n"
        f"Location: {sample_info.get('current_location', '')}\n"
        f"Tracking value: {sample_info.get('qr_code_value', '')}\n"
    )
    send_plain_email(TRACEAPL_WORK_AUTH_NOTIFY_EMAIL, subject, body)


def _record_work_auth_sync_run(summary: dict[str, Any]) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO work_auth_sync_runs (
                started_at, triggered_by, dry_run, scanned, created, skipped_existing,
                skipped_missing_project, errors, created_samples, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary.get("started_at", now_iso()),
                summary.get("triggered_by", ""),
                1 if summary.get("dry_run") else 0,
                int(summary.get("scanned", 0)),
                int(summary.get("created", 0)),
                int(summary.get("skipped_existing", 0)),
                int(summary.get("skipped_missing_project", 0)),
                json.dumps(summary.get("errors", []), default=str),
                json.dumps(summary.get("created_samples", []), default=str),
                json.dumps(summary, default=str, sort_keys=True),
            ),
        )
        log_system_audit_event(
            conn,
            "work_auth_sync_completed" if not summary.get("errors") else "work_auth_sync_error",
            "failure" if summary.get("errors") else "success",
            target_type="denodo_sync",
            target_id="CHAR HAND OFF",
            details=summary,
        )


def get_work_auth_sync_last_run() -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM work_auth_sync_runs ORDER BY started_at DESC, id DESC LIMIT 1").fetchone()
    if not row:
        return None
    result = dict(row)
    result["dry_run"] = bool(result.get("dry_run"))
    for key in ("errors", "created_samples"):
        try:
            result[key] = json.loads(result.get(key) or "[]")
        except Exception:
            result[key] = []
    return result


def run_work_auth_sync(dry_run: bool | None = None, triggered_by: str = "manual") -> dict[str, Any]:
    """Run the Denodo CHAR HAND OFF sync once.

    Dry run scans and reports what would be created, but does not write samples
    and does not send notification emails.
    """
    if dry_run is None:
        dry_run = TRACEAPL_WORK_AUTH_SYNC_DRY_RUN
    summary: dict[str, Any] = {
        "started_at": now_iso(),
        "triggered_by": triggered_by,
        "dry_run": bool(dry_run),
        "scanned": 0,
        "created": 0,
        "skipped_existing": 0,
        "skipped_missing_project": 0,
        "created_samples": [],
        "errors": [],
    }
    try:
        records = fetch_char_handoff_denodo_records()
        summary["scanned"] = len(records)
        with get_db() as conn:
            log_system_audit_event(conn, "work_auth_sync_started", "success", target_type="denodo_sync", target_id="CHAR HAND OFF", details={"dry_run": dry_run, "record_count": len(records)})
            for record in records:
                base_id = record.get("base_id", "").strip()
                work_program = record.get("work_program", "").strip()
                if not base_id or not work_program:
                    summary["skipped_missing_project"] += 1
                    continue
                if _work_auth_duplicate_exists(conn, work_program, base_id):
                    summary["skipped_existing"] += 1
                    continue
                qr_code_value = generate_unique_tracking_key(conn)
                sample_info = {
                    "qr_code_value": qr_code_value,
                    "sample_id": base_id,
                    "batch_lot": base_id,
                    "sample_type": DENODO_WORK_AUTH_OPERATION_VALUE,
                    "work_program": work_program,
                    "current_location": TRACEAPL_WORK_AUTH_DEFAULT_LOCATION,
                    "status": "Produced",
                }
                summary["created_samples"].append(sample_info)
                if dry_run:
                    continue
                conn.execute(
                    """
                    INSERT INTO samples (
                        qr_code_value, sample_id, sample_type, batch_lot, created_by,
                        created_at, current_owner, current_location, status, work_program, project, task, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        qr_code_value,
                        base_id,
                        DENODO_WORK_AUTH_OPERATION_VALUE,
                        base_id,
                        "Denodo CHAR HAND OFF sync",
                        now_iso(),
                        "",
                        TRACEAPL_WORK_AUTH_DEFAULT_LOCATION,
                        "Produced",
                        work_program,
                        work_program,
                        "",
                        f"Created automatically from Denodo {DENODO_WORK_AUTH_OPERATION_VALUE}. Warehouse={record.get('warehouse_id', '')}; WBS={record.get('wbs_code', '')}",
                    ),
                )
                log_audit_event(conn, "sample", qr_code_value, "created_from_denodo_char_handoff", sample_info, actor="system")
                log_system_audit_event(conn, "work_auth_sample_created", "success", target_type="sample", target_id=qr_code_value, details=sample_info)
                summary["created"] += 1
        if not dry_run and summary["created_samples"]:
            for sample_info in summary["created_samples"]:
                try:
                    send_work_auth_sample_notification(sample_info)
                except Exception as exc:
                    summary["errors"].append(f"Email notification failed for {sample_info.get('sample_id', '')}: {exc}")
    except Exception as exc:
        summary["errors"].append(str(exc))
    _record_work_auth_sync_run(summary)
    return summary


def maybe_run_daily_work_auth_sync() -> None:
    """Run the work-auth sync once per day after the configured hour."""
    global _last_work_auth_sync_check_date
    if not TRACEAPL_WORK_AUTH_SYNC_ENABLED:
        return
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    if _last_work_auth_sync_check_date == today:
        return
    if now.hour < TRACEAPL_WORK_AUTH_SYNC_HOUR:
        return
    run_work_auth_sync(dry_run=TRACEAPL_WORK_AUTH_SYNC_DRY_RUN, triggered_by="daily_app_check")
    _last_work_auth_sync_check_date = today


@app.route("/admin")
@admin_required
def admin_dashboard() -> str:
    return render_template("admin.html", backup_info=backup_summary())




@app.route("/admin/work-auth-sync")
@admin_required
def admin_work_auth_sync() -> str:
    return render_template(
        "work_auth_sync.html",
        last_run=get_work_auth_sync_last_run(),
        sync_enabled=TRACEAPL_WORK_AUTH_SYNC_ENABLED,
        dry_run=TRACEAPL_WORK_AUTH_SYNC_DRY_RUN,
        sync_hour=TRACEAPL_WORK_AUTH_SYNC_HOUR,
        notify_email=TRACEAPL_WORK_AUTH_NOTIFY_EMAIL,
        default_location=TRACEAPL_WORK_AUTH_DEFAULT_LOCATION,
        ops_url=DENODO_WORK_AUTH_OPS_REST_URL,
        wo_url=DENODO_WORK_AUTH_WO_REST_URL,
        operation_value=DENODO_WORK_AUTH_OPERATION_VALUE,
    )


@app.route("/admin/work-auth-sync/run", methods=["POST"])
@admin_required
def admin_run_work_auth_sync() -> Response:
    dry_run = request.form.get("dry_run", "") == "1"
    summary = run_work_auth_sync(dry_run=dry_run, triggered_by="admin_manual")
    if summary.get("errors"):
        flash(f"CHAR HAND OFF sync completed with errors: {'; '.join(summary['errors'])}", "error")
    elif dry_run:
        flash(f"Dry run complete. {summary['scanned']} Denodo record(s) scanned; {len(summary['created_samples'])} sample(s) would be created; {summary['skipped_existing']} duplicate(s) skipped.", "success")
    else:
        flash(f"Sync complete. {summary['created']} sample(s) created; {summary['skipped_existing']} duplicate(s) skipped.", "success")
    return redirect(url_for("admin_work_auth_sync"))


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


@app.route("/login", methods=["GET", "POST"])
def login() -> str | Response:
    """Built-in admin login only. Normal TraceAPL workflows are public."""
    next_url = request.values.get("next") or url_for("admin_dashboard")
    if request.method == "POST":
        username = normalize_username(request.form.get("username", ""))
        password = request.form.get("password", "")

        if username != ADMIN_USERNAME:
            with get_db() as conn:
                log_system_audit_event(conn, "admin_login_failed", "failure", username=username or "unknown", role="admin", target_type="user", target_id=username or "unknown", details={"reason": "not_builtin_admin"})
            flash("Use the built-in admin account for administrator access.", "error")
            return render_template("login.html", next_url=next_url, admin_only=True)

        admin_password_error = validate_password(ADMIN_PASSWORD, username=ADMIN_USERNAME)
        if admin_password_error:
            with get_db() as conn:
                log_system_audit_event(conn, "admin_login_blocked", "failure", username=ADMIN_USERNAME, role="admin", target_type="user", target_id=ADMIN_USERNAME, details={"reason": "admin_password_policy_not_met"})
            flash("Built-in admin password does not meet TraceAPL password policy. Set TRACEAPL_ADMIN_PASSWORD to a compliant value on the server.", "error")
            return render_template("login.html", next_url=next_url, admin_only=True)

        if hmac.compare_digest(password, ADMIN_PASSWORD):
            login_session_for_builtin_admin()
            with get_db() as conn:
                log_audit_event(conn, "auth", ADMIN_USERNAME, "admin_login", {"remember_device": False}, actor=ADMIN_USERNAME)
                log_system_audit_event(conn, "admin_login", "success", username=ADMIN_USERNAME, role="admin", target_type="user", target_id=ADMIN_USERNAME, details={"remember_device": False})
            flash("Logged in as admin.", "success")
            return redirect(next_url)

        with get_db() as conn:
            log_system_audit_event(conn, "admin_login_failed", "failure", username=ADMIN_USERNAME, role="admin", target_type="user", target_id=ADMIN_USERNAME, details={"reason": "bad_credentials"})
        flash("Incorrect admin password.", "error")

    return render_template("login.html", next_url=next_url, admin_only=True)


@app.route("/register", methods=["GET", "POST"])
def register() -> Response:
    flash("TraceAPL user self-registration is disabled. Normal TraceAPL workflows do not require a user account.", "info")
    return redirect(url_for("home"))


@app.route("/logout", methods=["POST"])
def logout() -> Response:
    username = current_username() or "admin"
    with get_db() as conn:
        log_audit_event(conn, "auth", username, "admin_logout", {"username": username}, actor=username)
        log_system_audit_event(conn, "admin_logout", "success", username=username, role="admin", target_type="user", target_id=username)
    clear_login_session()
    response = make_response(redirect(url_for("home")))
    clear_remember_cookie(response)
    flash("Logged out.", "success")
    return response


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login() -> str | Response:
    return redirect(url_for("login", next=request.values.get("next") or url_for("admin_dashboard")))


@app.route("/admin/logout", methods=["POST"])
def admin_logout() -> Response:
    return logout()


@app.route("/account/password", methods=["GET", "POST"])
def change_password() -> Response:
    flash("User password changes are disabled because normal TraceAPL access no longer uses user accounts. The built-in admin password is controlled by TRACEAPL_ADMIN_PASSWORD on the server.", "info")
    return redirect(url_for("home"))


@app.route("/admin/users")
@admin_required
def admin_users() -> str:
    with get_db() as conn:
        users = conn.execute("SELECT * FROM users ORDER BY created_at DESC, username ASC").fetchall()
    return render_template("admin_users.html", users=users, admin_username=ADMIN_USERNAME)


@app.route("/admin/users/<int:user_id>/reset-password", methods=["POST"])
@admin_required
def admin_reset_user_password(user_id: int) -> Response:
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            flash("User account not found.", "error")
            return redirect(url_for("admin_users"))
        password_error = validate_password(new_password, confirm_password, user["username"])
        if password_error:
            flash(password_error, "error")
            return redirect(url_for("admin_users"))
        conn.execute(
            "UPDATE users SET password_hash = ?, last_password_change_at = ? WHERE id = ?",
            (generate_password_hash(new_password), now_iso(), user_id),
        )
        conn.execute("DELETE FROM remember_tokens WHERE user_id = ?", (user_id,))
        log_audit_event(conn, "user", str(user_id), "admin_reset_password", {"username": user["username"]})
        log_system_audit_event(conn, "admin_reset_password", "success", target_type="user", target_id=str(user_id), details={"username": user["username"]})
    flash(f"Password reset for {user['username']}.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/toggle-active", methods=["POST"])
@admin_required
def admin_toggle_user_active(user_id: int) -> Response:
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            flash("User account not found.", "error")
            return redirect(url_for("admin_users"))
        new_active = 0 if user["is_active"] else 1
        conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_active, user_id))
        if not new_active:
            conn.execute("DELETE FROM remember_tokens WHERE user_id = ?", (user_id,))
        action = "user_enabled" if new_active else "user_disabled"
        log_audit_event(conn, "user", str(user_id), action, {"username": user["username"]})
        log_system_audit_event(conn, action, "success", target_type="user", target_id=str(user_id), details={"username": user["username"]})
    flash(f"User {user['username']} {'enabled' if new_active else 'disabled'}.", "success")
    return redirect(url_for("admin_users"))


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


@app.route("/sample/generated/new")
def generated_sample() -> str:
    return render_template("new_sample.html", qr_code_value=generated_tracking_key(), manual_entry=False, generated_entry=True)


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
    return render_template("new_sample.html", qr_code_value=qr_code_value, manual_entry=False, generated_entry=False)


@app.route("/sample/create", methods=["POST"])
def create_sample() -> Response:
    entry_mode = request.form.get("entry_mode", "qr").strip()
    qr_code_value = normalize_code_value(request.form.get("qr_code_value", ""))
    sample_id = request.form.get("sample_id", "").strip()
    work_program = request.form.get("work_program", request.form.get("project", "")).strip()

    if not sample_id:
        flash("Sample ID is required.", "error")
        return redirect(url_for("manual_sample") if entry_mode == "manual" else url_for("new_sample", qr_code_value=qr_code_value))

    if sample_id_exists_in_work_program(sample_id, work_program):
        flash("That Sample ID already exists in this Work Program. Use a unique Sample ID within the Work Program, or choose a different Work Program.", "error")
        return redirect(url_for("manual_sample") if entry_mode == "manual" else url_for("new_sample", qr_code_value=qr_code_value))

    if entry_mode == "manual":
        qr_code_value = manual_tracking_key(sample_id, work_program)
    elif entry_mode == "generated":
        # If the form already has a generated value, use it; otherwise create one at submit time.
        qr_code_value = qr_code_value or generated_tracking_key()
    elif not qr_code_value:
        flash("A QR code or barcode is required for code-based sample creation.", "error")
        return redirect(url_for("new_sample", qr_code_value=qr_code_value))

    try:
        with get_db() as conn:
            if entry_mode == "generated" and conn.execute("SELECT 1 FROM samples WHERE qr_code_value = ?", (qr_code_value,)).fetchone():
                qr_code_value = generate_unique_tracking_key(conn)
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
                    work_program,
                    work_program,
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
            try:
                save_sample_photo(conn, qr_code_value, request.files.get("sample_photo"), request.form.get("sample_photo_caption", ""))
            except ValueError as exc:
                flash(str(exc), "error")
                raise
        log_scan(qr_code_value, "assign", "sample_created", request.form.get("created_by", ""))
        if entry_mode == "manual":
            flash("Manual sample record created.", "success")
        elif entry_mode == "generated":
            flash("Sample created with a TraceAPL-generated QR value. You can print the custom QR code from the sample page.", "success")
        else:
            flash("Sample created and code assigned.", "success")
        for assigned_to, value, notes in notification_queue:
            notify_assignment_flash(assigned_to, sample_id, qr_code_value, value, notes)
        return redirect(url_for("sample_detail", qr_code_value=qr_code_value))
    except ValueError:
        return redirect(url_for("manual_sample") if entry_mode == "manual" else (url_for("generated_sample") if entry_mode == "generated" else url_for("new_sample", qr_code_value=qr_code_value)))
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
        photos = conn.execute(
            "SELECT * FROM sample_photos WHERE qr_code_value = ? ORDER BY uploaded_at DESC, id DESC",
            (qr_code_value,),
        ).fetchall()
    return render_template(
        "sample_detail.html",
        sample=sample,
        handoffs=handoffs,
        scans=scans,
        characterizations=characterizations,
        photos=photos,
        is_manual_sample=is_manual_tracking_key(qr_code_value),
        is_generated_sample=is_generated_tracking_key(qr_code_value),
    )


@app.route("/sample/<path:qr_code_value>/photo/upload", methods=["POST"])
def upload_sample_photo(qr_code_value: str) -> Response:
    sample = fetch_sample(qr_code_value)
    if not sample:
        flash("Sample entry was not found.", "error")
        return redirect(url_for("search"))
    try:
        with get_db() as conn:
            photo_id = save_sample_photo(conn, qr_code_value, request.files.get("sample_photo"), request.form.get("sample_photo_caption", ""))
            if photo_id:
                flash("Sample photo uploaded.", "success")
            else:
                flash("Choose a photo before uploading.", "error")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("sample_detail", qr_code_value=qr_code_value))


@app.route("/sample-photo/<int:photo_id>")
def sample_photo_file(photo_id: int) -> Response:
    with get_db() as conn:
        photo = conn.execute("SELECT * FROM sample_photos WHERE id = ?", (photo_id,)).fetchone()
    if not photo:
        flash("Sample photo was not found.", "error")
        return redirect(url_for("search"))
    path = SAMPLE_UPLOAD_DIR / photo["stored_filename"]
    if not path.exists():
        flash("Sample photo file is missing from sample_uploads/.", "error")
        return redirect(url_for("sample_detail", qr_code_value=photo["qr_code_value"]))
    return send_file(path, mimetype=photo["content_type"] or "application/octet-stream", download_name=photo["original_filename"] or photo["stored_filename"])


@app.route("/sample-photo/<int:photo_id>/delete", methods=["POST"])
@admin_required
def delete_sample_photo(photo_id: int) -> Response:
    with get_db() as conn:
        photo = conn.execute("SELECT * FROM sample_photos WHERE id = ?", (photo_id,)).fetchone()
        if not photo:
            flash("Sample photo was not found.", "error")
            return redirect(url_for("search"))
        qr_code_value = photo["qr_code_value"]
        path = SAMPLE_UPLOAD_DIR / photo["stored_filename"]
        conn.execute("DELETE FROM sample_photos WHERE id = ?", (photo_id,))
        log_audit_event(conn, "sample", qr_code_value, "sample_photo_deleted", {"photo_id": photo_id, "original_filename": photo["original_filename"]})
        log_system_audit_event(conn, "sample_photo_deleted", "success", target_type="sample", target_id=qr_code_value, details={"photo_id": photo_id})
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        print("TRACEAPL PHOTO DELETE ERROR:", repr(exc))
    flash("Sample photo deleted.", "success")
    return redirect(url_for("sample_detail", qr_code_value=qr_code_value))


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

        if sample_id_exists_in_work_program(new_values["sample_id"], new_values["work_program"], exclude_qr_code_value=qr_code_value):
            flash("That Sample ID already exists in this Work Program. Use a unique Sample ID within the Work Program, or choose a different Work Program.", "error")
            return redirect(url_for("edit_sample", qr_code_value=qr_code_value))

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




@app.route("/admin/system-audit")
@admin_required
def admin_system_audit() -> str:
    event_type = request.args.get("event_type", "").strip()
    username = request.args.get("username", "").strip()
    outcome = request.args.get("outcome", "").strip()

    where = []
    params: list[Any] = []
    if event_type:
        where.append("event_type LIKE ?")
        params.append(f"%{event_type}%")
    if username:
        where.append("username LIKE ?")
        params.append(f"%{username}%")
    if outcome:
        where.append("outcome = ?")
        params.append(outcome)

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    with get_db() as conn:
        events = conn.execute(
            f"SELECT * FROM system_audit_log {where_sql} ORDER BY timestamp DESC, id DESC LIMIT 500",
            params,
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) AS count FROM system_audit_log").fetchone()["count"]
    return render_template(
        "system_audit.html",
        events=events,
        total=total,
        retention_days=TRACEAPL_SYSTEM_AUDIT_RETENTION_DAYS,
        event_type=event_type,
        username=username,
        outcome=outcome,
    )


@app.route("/admin/system-audit/export")
@admin_required
def export_system_audit() -> Response:
    output = io.StringIO()
    writer = csv.writer(output)
    with get_db() as conn:
        log_system_audit_event(conn, "system_audit_export", "success", target_type="system_audit_log", target_id="export")
        rows = conn.execute("SELECT * FROM system_audit_log ORDER BY timestamp DESC, id DESC").fetchall()
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
        download_name=f"system_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    )


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
    with get_db() as conn:
        log_system_audit_event(conn, "backup_create", "success" if backup_path else "failure", target_type="backup", target_id=backup_path.name if backup_path else "none")
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
        with get_db() as conn:
            log_system_audit_event(conn, "backup_download", "failure", target_type="backup", target_id="none", details={"reason": "no_backup_available"})
        flash("No backup is available yet.", "error")
        return redirect(url_for("home"))
    with get_db() as conn:
        log_system_audit_event(conn, "backup_download", "success", target_type="backup", target_id=backup_path.name)
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
        log_system_audit_event(conn, "data_export", "success", target_type="export", target_id=kind)
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
