#!/usr/bin/env python3
"""Print an SDD main issue's sub-issue completion as `<completed> <total>`.

Usage:
  sub-issues-summary.py <main-issue-number>

Reads the GraphQL `subIssuesSummary`; read-only. `0 0` means no sub-issues.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

SUMMARY = (
    "query($id:ID!){ node(id:$id){ ... on Issue {"
    " subIssuesSummary{ total completed } } } }"
)


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


def sub_issues_summary(parent: int) -> tuple[int, int]:
    p = str(parent)
    parent_id = json.loads(run_gh(["issue", "view", p, "--json", "id"]))["id"]
    data = json.loads(
        run_gh(["api", "graphql", "-f", f"query={SUMMARY}", "-f", f"id={parent_id}"])
    )
    summary = data["data"]["node"]["subIssuesSummary"]
    return int(summary["completed"]), int(summary["total"])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("parent", type=int)
    args = parser.parse_args(argv)
    completed, total = sub_issues_summary(args.parent)
    print(f"{completed} {total}")


if __name__ == "__main__":
    main()
