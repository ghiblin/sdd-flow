#!/usr/bin/env python3
"""Prove a sub-issue's red-before-green order: a non-empty `test:` commit before a `feat:`/`fix:` commit.

Usage:
  verify_red_green.py <child> [--base main] [--repo .]

Reads the commits in `<base>...HEAD` that are on HEAD's side, oldest first, and keeps those whose
subject ends with `(#<child>)`. Passes (exit 0) only if a `test:` commit that changes at least one
file comes before a `feat:` or `fix:` commit. It checks only the order and that the red commit is
not empty, not which paths a commit touches. Stdlib only; importable (`verify`, `main`).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

TYPE = re.compile(r"^(?P<type>[a-z]+)(?:\([^)]*\))?!?: ")


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return result.stdout


def commits_for(child: int, repo: Path, base: str) -> list[tuple[str, str, str]]:
    """(sha, type, subject) of HEAD's commits in `base...HEAD` for `child`, oldest first."""
    log = git(repo, "log", "--reverse", "--right-only", "--format=%H%x09%s", f"{base}...HEAD")
    suffix = f"(#{child})"
    found = []
    for line in log.splitlines():
        sha, _, subject = line.partition("\t")
        match = TYPE.match(subject)
        if match and subject.rstrip().endswith(suffix):
            found.append((sha, match["type"], subject))
    return found


def is_empty(sha: str, repo: Path) -> bool:
    return not git(repo, "show", "--format=", "--name-only", sha).strip()


def verify(child: int, repo: Path | str = ".", base: str = "main") -> tuple[bool, str]:
    """Return (ok, message) for the red-green pair of sub-issue `child`."""
    repo = Path(repo)
    red_seen = False
    empty_red = False
    for sha, kind, _subject in commits_for(child, repo, base):
        if kind == "test":
            if is_empty(sha, repo):
                empty_red = True
            else:
                red_seen = True
        elif kind in ("feat", "fix") and red_seen:
            return True, f"#{child}: a test: commit comes before a {kind}: commit"
    if empty_red and not red_seen:
        return False, f"#{child}: the test: commit is empty; the red commit must change a file"
    return False, f"#{child}: no non-empty test: commit before a feat:/fix: commit in {base}...HEAD"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("child", type=int)
    parser.add_argument("--base", default="main")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    ok, message = verify(args.child, repo=args.repo, base=args.base)
    print(message, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
