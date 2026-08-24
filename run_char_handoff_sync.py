#!/usr/bin/env python3
"""Run the TraceAPL Denodo CHAR HAND OFF sync once.

Use this with Windows Task Scheduler for a reliable daily 8 AM run.
Set the same environment variables used for TraceAPL before running this script.
"""

from __future__ import annotations

import argparse
import json
import sys

import app as traceapl_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TraceAPL CHAR HAND OFF Denodo sync once.")
    parser.add_argument("--commit", action="store_true", help="Create samples. Default is dry run.")
    args = parser.parse_args()

    traceapl_app.init_db()
    summary = traceapl_app.run_work_auth_sync(dry_run=not args.commit, triggered_by="scheduled_script")
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 1 if summary.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
