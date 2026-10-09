#!/usr/bin/env python3
"""Run isolated tests and produce a deterministic, read-only progress event preview.

Never accepts a claimed test exit code. Does not update production by default.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Z]{2,8}-[0-9]{3}", args.task):
        ap.error("invalid task")
    if not 30 <= args.timeout <= 600:
        ap.error("timeout out of bounds")
    repo = Path(__file__).resolve().parent.parent
    revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "--short=12", "HEAD"], text=True).strip()
    command = ["bash", str(repo / "scripts/run-isolated-tests.sh"), "-q"]
    try:
        completed = subprocess.run(command, cwd=repo, text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, timeout=args.timeout, check=False)
        output = completed.stdout
        code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        code = 124
    report_dir = repo / "docs" / "test-runs"
    report_dir.mkdir(parents=True, exist_ok=True)
    output_digest = hashlib.sha256(output.encode("utf-8", errors="replace")).hexdigest()
    name = f"{args.task}-{revision}-{output_digest[:12]}.md"
    report = report_dir / name
    report.write_text(
        "# Ejecución aislada de pruebas\n\n"
        f"- Fecha UTC: {datetime.now(timezone.utc).isoformat()}\n"
        f"- Tarea: {args.task}\n- Commit: {revision}\n"
        f"- Código de salida real: {code}\n"
        f"- SHA256 salida: {output_digest}\n"
        "\n## Salida de pruebas\n\n```text\n"
        + output[-12000:].replace("```", "` ` `") + "\n```\n", encoding="utf-8")
    print(json.dumps({"task": args.task, "revision": revision, "exit_code": code,
                      "report": str(report.relative_to(repo)), "output_sha256": output_digest}, ensure_ascii=False))
    if code:
        print("Tests failed or timed out; no progress event generated", file=sys.stderr)
        return code if 1 <= code <= 125 else 1
    result = subprocess.run(
        [sys.executable, str(repo / "scripts/progress-record-test-run.py"),
         "--task", args.task, "--report", str(report), "--revision", revision, "--exit-code", "0"],
        cwd=repo, check=False)
    return result.returncode

if __name__ == "__main__":
    raise SystemExit(main())
