#!/usr/bin/env python3
"""Create an SDD main issue from templates/main-issue.md and print its number.

Usage:
  create-issue.py --slug <kebab-slug> --intent "<one/two sentences>" \
      --spec-file docs/specs/<topic>/<file>.md [--spec-file ...] \
      [--decision "<question>" ...] [--tier {0,1,2}]

Creates the issue with the `sdd:feature` and `sdd:stage:drafting-spec` labels
(plus `sdd:tier:<n>` when `--tier` is given — the tier the user confirmed for
the sdd-flow tier_classifier.py proposal), then rewrites the whole body once
with the real number in `**Branch:**`.
Re-reads the issue and exits non-zero if the body or labels do not match; any
failure after the issue exists names it, so it is fixed rather than duplicated.
Intent, spec files and decisions must each be a single line.
"""
from __future__ import annotations

import argparse
import json
import re
import string
import subprocess
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "main-issue.md"
LABELS = ["sdd:feature", "sdd:stage:drafting-spec"]
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


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


def render(slug: str, intent: str, spec_files: list[str], decisions: list[str], number: str) -> str:
    lines = [f"- [ ] {d}" for d in decisions] or ["- [ ] _none_"]
    return string.Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        intent=intent,
        slug=slug,
        number=number,
        spec_files=", ".join(spec_files),
        decisions="\n".join(lines),
    )


def create_issue(
    slug: str, intent: str, spec_files: list[str], decisions: list[str], tier: int | None = None
) -> int:
    if not SLUG_RE.match(slug):
        raise SystemExit(f"slug '{slug}' is not kebab-case")
    if not intent.strip() or not spec_files:
        raise SystemExit("refusing to create an issue without an intent and spec files")
    for text in [intent, *spec_files, *decisions]:
        if not text.strip() or "\n" in text.strip():
            raise SystemExit(f"each intent, spec file and decision must be one non-empty line: {text!r}")
    intent = intent.strip()
    spec_files = [f.strip() for f in spec_files]
    decisions = [d.strip() for d in decisions]

    if tier is not None and tier not in (0, 1, 2):
        raise SystemExit(f"tier must be 0, 1 or 2, got {tier!r}")
    labels = [*LABELS, f"sdd:tier:{tier}"] if tier is not None else LABELS

    draft = render(slug, intent, spec_files, decisions, number="<issue-number>")
    label_args = [a for label in labels for a in ("--label", label)]
    url = run_gh(["issue", "create", "--title", slug, *label_args, "--body-file", "-"], stdin=draft)
    match = re.search(r"/issues/(\d+)\s*$", url)
    if not match:
        raise SystemExit(
            f"an issue was created but its number could not be read from gh output {url!r}: "
            "find and fix that issue instead of creating another"
        )
    number = match.group(1)

    body = render(slug, intent, spec_files, decisions, number=number)
    try:
        run_gh(["issue", "edit", number, "--body-file", "-"], stdin=body)
    except SystemExit as err:
        raise SystemExit(
            f"issue #{number} was created but its body was not finalized ({err.code}): "
            "fix that issue instead of creating another"
        )
    try:
        issue = json.loads(run_gh(["issue", "view", number, "--json", "body,labels"]))
        labels = {label["name"] for label in issue["labels"]}
        read_back = issue["body"]
    except (SystemExit, ValueError, KeyError, TypeError) as err:
        detail = err.code if isinstance(err, SystemExit) else repr(err)
        raise SystemExit(
            f"issue #{number} was created and its body written, but it could not be verified "
            f"({detail}): check that issue instead of creating another"
        )
    fix = "fix that issue instead of creating another"
    if read_back.strip() != body.strip():
        raise SystemExit(f"issue #{number}: body read back does not match what was written: {fix}")
    expected = {*LABELS, f"sdd:tier:{tier}"} if tier is not None else set(LABELS)
    if not expected <= labels:
        raise SystemExit(f"issue #{number}: labels {sorted(labels)} missing one of {sorted(expected)}: {fix}")
    return int(number)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slug", required=True)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--spec-file", action="append", required=True, dest="spec_files")
    parser.add_argument("--decision", action="append", default=[], dest="decisions")
    parser.add_argument("--tier", type=int, choices=[0, 1, 2], default=None)
    args = parser.parse_args(argv)
    print(create_issue(args.slug, args.intent, args.spec_files, args.decisions, args.tier))


if __name__ == "__main__":
    main()
