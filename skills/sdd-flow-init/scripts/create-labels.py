#!/usr/bin/env python3
"""Create or update the SDD label set and report which were created vs present.

Usage:
  create-labels.py

Idempotent: every label goes through `gh label create --force`, so a re-run
updates colours/descriptions in place. Re-reads the label list afterward and
exits non-zero if any SDD label is missing or does not match.
Prints one `created <name>` or `present <name>` line per label.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

LABELS = [
    ("sdd:feature", "1D76DB", "SDD: feature main issue"),
    ("sdd:task", "0E8A16", "SDD: feature development increment"),
    ("sdd:needs-spec", "D93F0B", "SDD: sub-issue whose behaviour the spec does not describe yet"),
    ("sdd:no-red-green", "C5DEF5", "SDD: sub-issue the user exempted from the red-green check"),
    ("sdd:follow-up", "BFD4F2", "SDD: reviewer finding deferred to a later issue"),
    ("sdd:stage:drafting-spec", "FBCA04", "SDD stage: drafting the spec"),
    ("sdd:stage:spec-approved", "FBCA04", "SDD stage: spec approved"),
    ("sdd:stage:implementing", "FBCA04", "SDD stage: implementing"),
    ("sdd:stage:complete", "FBCA04", "SDD stage: implementation complete"),
    ("sdd:stage:verified", "0E8A16", "SDD stage: PR-validated"),
]


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


def existing_labels() -> dict[str, tuple[str, str]]:
    rows = json.loads(
        run_gh(["label", "list", "--json", "name,color,description", "--limit", "1000"])
    )
    return {r["name"]: (r["color"].lower(), r.get("description") or "") for r in rows}


def create_labels() -> dict[str, str]:
    before = existing_labels()
    report = {}
    for name, color, description in LABELS:
        run_gh(
            ["label", "create", name, "--color", color, "--description", description, "--force"]
        )
        report[name] = "present" if name in before else "created"

    after = existing_labels()
    wrong = [
        name
        for name, color, description in LABELS
        if after.get(name) != (color.lower(), description)
    ]
    if wrong:
        raise SystemExit(f"labels missing or mismatched after create: {', '.join(wrong)}")
    return report


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    for name, status in create_labels().items():
        print(f"{status} {name}")


if __name__ == "__main__":
    main()
