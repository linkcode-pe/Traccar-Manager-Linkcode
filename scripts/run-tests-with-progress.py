#!/usr/bin/env python3
"""Run isolated tests and produce a deterministic, read-only progress event preview.

Never accepts a claimed test exit code. Does not update production by default.
"""
import argparse
import hashlib
import os
import json
import re
import subprocess
import sys
import importlib.util
import fcntl
from datetime import datetime, timezone
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--apply", action="store_true", help="Record event only after tests pass (non-root service account)")
    ap.add_argument("--skip-unchanged", action="store_true", help="Skip successful repeated runs of same source fingerprint")
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Z]{2,8}-[0-9]{3}", args.task):
        ap.error("invalid task")
    if not 30 <= args.timeout <= 600:
        ap.error("timeout out of bounds")
    if args.apply and args.task != "PROG-006":
        ap.error("automatic production writes currently restricted to PROG-006")
    if args.apply and os.geteuid() != 0:
        ap.error("production apply requires root-controlled execution")
    repo = Path(__file__).resolve().parent.parent
    revision = subprocess.check_output(["git", "-c", f"safe.directory={repo}", "-C", str(repo), "rev-parse", "--short=12", "HEAD"], text=True).strip()
    spec = importlib.util.spec_from_file_location("source_manifest", repo / "scripts/source-manifest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source_before = module.manifest(repo)
    state_dir = Path("/var/lib/traccar-manager-progress") if args.apply else Path("/tmp")
    lock_file = state_dir / "prog006-test-run.lock"
    lock = open(lock_file, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another PROG-006 test run is active", file=sys.stderr)
        return 8
    stamp = state_dir / "prog006-last-success.sha256"
    def status(result):
        if not args.apply:
            return
        payload = {"last_run": datetime.now(timezone.utc).isoformat(), "result": result,
                   "source_sha256": source_before["sha256"]}
        target = state_dir / "prog006-run-status.json"
        temporary = state_dir / f".prog006-run-status.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
        history = state_dir / "prog006-run-history.json"
        try:
            entries = json.loads(history.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                entries = []
        except (OSError, ValueError):
            entries = []
        entries = ([payload] + [item for item in entries if isinstance(item, dict)])[:20]
        history_tmp = state_dir / f".prog006-run-history.{os.getpid()}.tmp"
        history_tmp.write_text(json.dumps(entries, sort_keys=True), encoding="utf-8")
        os.chmod(history_tmp, 0o644)
        os.replace(history_tmp, history)
    if args.skip_unchanged and args.apply and stamp.is_file() and stamp.read_text().strip() == source_before["sha256"]:
        status("skipped_unchanged")
        print(json.dumps({"skipped": True, "reason": "unchanged_source", "source_sha256": source_before["sha256"]}))
        return 0
    command = ["bash", str(repo / "scripts/run-isolated-tests.sh"), "-q"]
    try:
        completed = subprocess.run(command, cwd=repo, text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, timeout=args.timeout, check=False)
        output = completed.stdout
        code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        code = 124
    source_after = module.manifest(repo)
    if source_after["sha256"] != source_before["sha256"]:
        status("source_changed")
        print("Source changed during tests; event refused", file=sys.stderr)
        return 7
    report_dir = repo / "docs" / "test-runs"
    report_dir.mkdir(parents=True, exist_ok=True)
    output_digest = hashlib.sha256(output.encode("utf-8", errors="replace")).hexdigest()
    name = f"{args.task}-{source_before['sha256'][:12]}-{output_digest[:12]}.md"
    report = report_dir / name
    report.write_text(
        "# Ejecución aislada de pruebas\n\n"
        f"- Fecha UTC: {datetime.now(timezone.utc).isoformat()}\n"
        f"- Tarea: {args.task}\n- Commit: {revision}\n"
        f"- Manifiesto de código SHA256: {source_before['sha256']} ({source_before['count']} archivos)\n"
        f"- Código de salida real: {code}\n"
        f"- SHA256 salida: {output_digest}\n"
        "\n## Salida de pruebas\n\n```text\n"
        + output[-12000:].replace("```", "` ` `") + "\n```\n", encoding="utf-8")
    print(json.dumps({"task": args.task, "revision": revision, "exit_code": code,
                      "report": str(report.relative_to(repo)), "output_sha256": output_digest, "source_sha256": source_before["sha256"]}, ensure_ascii=False))
    if code:
        status("tests_failed")
        print("Tests failed or timed out; no progress event generated", file=sys.stderr)
        return code if 1 <= code <= 125 else 1
    recorder = [sys.executable, str(repo / "scripts/progress-record-test-run.py"),
                "--task", args.task, "--report", str(report), "--revision", source_before["sha256"], "--exit-code", "0"]
    if args.apply:
        recorder.append("--apply")
        recorder = ["runuser", "-u", "traccar-manager-web", "--", "env",
                    f"PYTHONPATH={repo}", "PYTHONDONTWRITEBYTECODE=1", *recorder]
    result = subprocess.run(recorder, cwd=repo, check=False)
    if result.returncode == 0 and args.apply:
        stamp.write_text(source_before["sha256"] + "\n")
    status("passed" if result.returncode == 0 else "record_failed")
    return result.returncode

def record_unhandled_failure():
    """Best-effort status for crashes before normal status handling; never mask failure."""
    if "--apply" not in sys.argv or os.geteuid() != 0:
        return
    directory = Path("/var/lib/traccar-manager-progress")
    payload = {"last_run": datetime.now(timezone.utc).isoformat(), "result": "runner_failed", "source_sha256": None}
    for name, value in (("prog006-run-status.json", payload),):
        temp = directory / f".{name}.{os.getpid()}.tmp"
        temp.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        os.chmod(temp, 0o644)
        os.replace(temp, directory / name)
    history = directory / "prog006-run-history.json"
    try:
        entries = json.loads(history.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            entries = []
    except (OSError, ValueError):
        entries = []
    temp = directory / f".prog006-run-history.{os.getpid()}.tmp"
    temp.write_text(json.dumps(([payload] + [x for x in entries if isinstance(x, dict)])[:20]), encoding="utf-8")
    os.chmod(temp, 0o644)
    os.replace(temp, history)

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        try:
            record_unhandled_failure()
        except Exception:
            traceback.print_exc()
        raise SystemExit(1)
