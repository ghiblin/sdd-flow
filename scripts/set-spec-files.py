#!/usr/bin/env python3
"""Rewrite the `**Spec files:**` line of an SDD main issue.

Usage:
  set-spec-files.py <issue-number> [--add] --spec-file <path> [--spec-file ...]

Without `--add` the line lists exactly the given paths; with `--add` they are
appended to the current list, skipping duplicates. Only that line changes
(UTF-8, never an empty body); no write happens when it would not change.
Re-reads the issue and exits non-zero if the body does not match. CRLF bodies
are read (and written back) as LF.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

SPEC_LINE_RE = re.compile(r"^\*\*Spec files:\*\*(.*)$", re.MULTILINE)


def run_gh(args: list[str], stdin: str | None = None) -> str:
    """Run `gh` with UTF-8 stdin/stdout; exit non-zero on failure."""
    result = subprocess.run(
        ["gh", *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(f"gh {' '.join(args[:2])} failed ({result.returncode})")
    return result.stdout.strip()


def read_body(number: str) -> str:
    body = json.loads(run_gh(["issue", "view", number, "--json", "body"]))["body"]
    return body.replace("\r\n", "\n")  # CRLF bodies (GitHub web UI) are read as LF


def set_spec_files(number: int, spec_files: list[str], add: bool = False) -> None:
    if not spec_files:
        raise SystemExit("refusing to write an empty **Spec files:** line")
    n = str(number)

    body = read_body(n)
    if not body.strip():
        raise SystemExit(f"issue #{n}: refusing to write an empty body — gh issue view likely failed")
    matches = SPEC_LINE_RE.findall(body)
    if len(matches) != 1:
        raise SystemExit(f"issue #{n}: expected exactly one **Spec files:** line in the body")

    files = [f.strip() for f in matches[0].split(",") if f.strip()] if add else []
    for f in spec_files:
        if f not in files:
            files.append(f)
    new_body = SPEC_LINE_RE.sub(lambda _: "**Spec files:** " + ", ".join(files), body)
    if new_body == body:
        return
    run_gh(["issue", "edit", n, "--body-file", "-"], stdin=new_body)

    if read_body(n).strip() != new_body.strip():
        raise SystemExit(f"issue #{n}: body read back does not match what was written")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("number", type=int)
    parser.add_argument("--add", action="store_true")
    parser.add_argument("--spec-file", action="append", required=True, dest="spec_files")
    args = parser.parse_args(argv)
    set_spec_files(args.number, args.spec_files, add=args.add)


if __name__ == "__main__":
    main()
