#!/usr/bin/env python3
"""Record successful isolated test runs as traceable progress events.

This is a trusted server-side CLI, not an unauthenticated web endpoint.
It never marks a task verified. Default mode is a read-only preview.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--report", required=True, help="Existing UTF-8 test report in an approved docs directory")
    ap.add_argument("--revision", required=True, help="Full or short Git commit SHA")
    ap.add_argument("--exit-code", required=True, type=int)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Z]{2,8}-[0-9]{3}", args.task):
        ap.error("invalid task id")
    if not re.fullmatch(r"[a-fA-F0-9]{7,40}", args.revision):
        ap.error("invalid revision")
    if args.exit_code != 0:
        print("Tests did not pass: progress not updated", file=sys.stderr)
        return 2
    repo = Path(__file__).resolve().parent.parent
    docs = (repo / "docs").resolve()
    report = Path(args.report).resolve()
    if not report.is_relative_to(docs) or not report.is_file() or Path(args.report).is_symlink():
        ap.error("report must be an existing regular file under docs/")
    raw = report.read_bytes()
    if not raw or len(raw) > 200_000:
        ap.error("report size invalid")
    relative = report.relative_to(repo).as_posix()
    digest = hashlib.sha256(raw).hexdigest()
    key = hashlib.sha256(f"{args.task}|{args.revision}|{digest}".encode()).hexdigest()[:24]
    event = {
        "event_id": "test-run-" + key,
        "task_id": args.task,
        "source": "scripts/progress-record-test-run",
        "state": "in_testing",
        "doc_state": "in_review",
        "evidence": [f"{relative} (SHA256 {digest[:16]})", f"Commit {args.revision}; pruebas terminadas con código 0"],
    }
    if not args.apply:
        print(json.dumps({"preview": True, "event": event}, ensure_ascii=False))
        return 0
    if os.geteuid() == 0:
        print("Refusing to write progress database as root", file=sys.stderr)
        return 3
    from manager.auth.session_store import SessionPrincipal
    from manager.progress import ingest_event, connect
    with connect() as db:
        row = db.execute("SELECT state FROM tasks WHERE task_id=?", (args.task,)).fetchone()
        if row is None:
            print("Unknown task", file=sys.stderr)
            return 4
        if row["state"] == "verified":
            print("Verified task cannot be downgraded by test runner", file=sys.stderr)
            return 5
    principal = SessionPrincipal("system-ci-tests", "test-runner", ("development.progress.manage",), "2099-01-01T00:00:00Z")
    print(json.dumps(ingest_event(principal, event), ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
