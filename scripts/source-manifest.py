#!/usr/bin/env python3
"""Deterministic manifest of deployed application source, including untracked files."""
import argparse
import hashlib
import json
from pathlib import Path

ROOTS = ("manager", "api", "worker", "tests", "migrations", "runner", "web", "deploy", "deployment", "scripts")
SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".html", ".css", ".json", ".sql", ".yaml", ".yml"}
IGNORED = {"__pycache__", ".git", ".venv", "node_modules", ".pytest_cache", "dist", "build"}

def manifest(root):
    files = []
    for folder in ROOTS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if any(part in IGNORED for part in path.relative_to(root).parts):
                continue
            if path.is_symlink() or not path.is_file() or path.suffix not in SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            files.append({"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(payload).hexdigest(), "files": files, "count": len(files)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--output")
    args = parser.parse_args()
    data = manifest(Path(args.root).resolve())
    serialized = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")

if __name__ == "__main__":
    main()
