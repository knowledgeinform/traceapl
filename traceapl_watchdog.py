#!/usr/bin/env python3
"""Simple external TraceAPL watchdog.

Run from Windows Task Scheduler every 5-10 minutes. It sends an email if the
TraceAPL web endpoint is not reachable. Because this runs outside TraceAPL, it
can alert even when the Flask process or VM web service is down.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.request import Request, urlopen

TRACEAPL_WATCHDOG_URL = os.environ.get("TRACEAPL_WATCHDOG_URL", "https://localhost:5000/login")
TRACEAPL_WATCHDOG_NOTIFY_EMAIL = os.environ.get("TRACEAPL_WATCHDOG_NOTIFY_EMAIL", "avi.bregman@jhuapl.edu")
TRACEAPL_WATCHDOG_STATE_FILE = Path(os.environ.get("TRACEAPL_WATCHDOG_STATE_FILE", "traceapl_watchdog_state.json"))
TRACEAPL_WATCHDOG_TIMEOUT_SECONDS = int(os.environ.get("TRACEAPL_WATCHDOG_TIMEOUT_SECONDS", "20"))

SMTP_HOST = os.environ.get("TRACEAPL_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("TRACEAPL_SMTP_PORT", "587"))
SMTP_TLS = os.environ.get("TRACEAPL_SMTP_TLS", "1") != "0"
SMTP_USERNAME = os.environ.get("TRACEAPL_SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("TRACEAPL_SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("TRACEAPL_SMTP_FROM", os.environ.get("TRACEAPL_EMAIL_FROM", SMTP_USERNAME or "traceapl-watchdog@localhost"))


def load_state() -> dict:
    if not TRACEAPL_WATCHDOG_STATE_FILE.exists():
        return {}
    try:
        return json.loads(TRACEAPL_WATCHDOG_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    TRACEAPL_WATCHDOG_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def send_email(subject: str, body: str) -> None:
    if not SMTP_HOST or not SMTP_FROM or not TRACEAPL_WATCHDOG_NOTIFY_EMAIL:
        raise RuntimeError("SMTP host/from/notify email are not configured for watchdog alerting.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = TRACEAPL_WATCHDOG_NOTIFY_EMAIL
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        if SMTP_TLS:
            smtp.starttls(context=ssl.create_default_context())
        if SMTP_USERNAME and SMTP_PASSWORD:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(msg)


def is_traceapl_up() -> tuple[bool, str]:
    try:
        req = Request(TRACEAPL_WATCHDOG_URL, headers={"User-Agent": "TraceAPL-Watchdog/1.0"})
        with urlopen(req, timeout=TRACEAPL_WATCHDOG_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 500, f"HTTP {response.status}"
    except Exception as exc:
        return False, repr(exc)


def main() -> int:
    state = load_state()
    was_down = bool(state.get("is_down"))
    up, detail = is_traceapl_up()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if up:
        state.update({"is_down": False, "last_ok_at": now, "last_detail": detail})
        if was_down:
            try:
                send_email("TraceAPL is reachable again", f"TraceAPL recovered at {now}.\nURL: {TRACEAPL_WATCHDOG_URL}\nStatus: {detail}\n")
            except Exception as exc:
                print(f"Recovery email failed: {exc}", file=sys.stderr)
        save_state(state)
        print(f"TraceAPL OK: {detail}")
        return 0

    state.update({"is_down": True, "last_down_at": now, "last_detail": detail})
    save_state(state)
    print(f"TraceAPL DOWN: {detail}", file=sys.stderr)
    if not was_down:
        body = f"TraceAPL appears to be down or unreachable.\n\nTime: {now}\nURL: {TRACEAPL_WATCHDOG_URL}\nError/status: {detail}\n"
        send_email("TraceAPL is not reachable", body)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
