#!/usr/bin/env python3
"""Print the SDD main issue number from the current `sdd/<n>-<slug>` branch.

Usage:
  resolve-issue.py [--branch sdd/<n>-<slug>]

Exits non-zero (telling you to run sdd-intent) when the branch is not an SDD
feature branch.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

BRANCH_RE = re.compile(r"^sdd/([0-9]+)-.+$")


def run_git(args: list[str]) -> str:
    """Run `git`; exit non-zero on failure."""
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(f"git {' '.join(args[:2])} failed ({result.returncode})")
    return result.stdout.strip()


def resolve_issue(branch: str | None = None) -> int:
    if branch is None:
        branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    match = BRANCH_RE.match(branch)
    if not match:
        raise SystemExit(
            f"branch '{branch}' is not an sdd/<n>-<slug> branch: run sdd-intent "
            "or check out the feature branch"
        )
    return int(match.group(1))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--branch")
    args = parser.parse_args(argv)
    print(resolve_issue(args.branch))


if __name__ == "__main__":
    main()
