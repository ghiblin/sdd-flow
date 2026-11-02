#!/usr/bin/env python3
"""Move an SDD main issue to a stage: swap the `sdd:stage:*` label and the `**Stage:**` line.

Usage:
  set-stage.py <issue-number> <drafting-spec|spec-approved|implementing|complete|verified>

`spec-approved` is allowed only from `drafting-spec` (or again from
`spec-approved`, a no-op re-run), and only when the highest
`Approve the spec section? (draft <k>)` line of `## Open decisions` is checked
with the resolution `yes` or `approved`. Only checklist lines of that block count,
up to the next heading or the sdd end marker, parsed with `open_decisions.py`. `implementing` is allowed only from
`spec-approved`, `implementing` or `complete`. A refusal exits 1 and keeps the label.

Rewrites only the body's `**Stage:**` line (UTF-8, never an empty body), then
removes every other `sdd:stage:*` label and adds `sdd:stage:<stage>` (skipped
when the labels already match). Re-reads the
issue and exits non-zero if the label or body does not match. CRLF bodies are
read (and written back) as LF.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from open_decisions import MARKER, SEP, parse, split_block  # noqa: E402

STAGES = ["drafting-spec", "spec-approved", "implementing", "complete", "verified"]
IMPLEMENTING_FROM = {"spec-approved", "implementing", "complete"}
SPEC_APPROVED_FROM = {"drafting-spec", "spec-approved"}
APPROVAL_RE = re.compile(
    r"^Approve the spec section\? \(draft (\d+)\)(?:" + re.escape(SEP.rstrip()) + r"(?: (.*))?)?$"
)
STAGE_PREFIX = "sdd:stage:"
STAGE_LINE_RE = re.compile(r"^\*\*Stage:\*\* .*$", re.MULTILINE)


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


def read_issue(number: str) -> tuple[str, set[str]]:
    issue = json.loads(run_gh(["issue", "view", number, "--json", "body,labels"]))
    # CRLF bodies (saved by the GitHub web UI) are read as LF.
    return issue["body"].replace("\r\n", "\n"), {label["name"] for label in issue["labels"]}


def decision_lines(number: str, body: str) -> list[str]:
    """Every line of the `## Open decisions` block, up to the next heading or `<!-- sdd:end -->`.

    It reads the block with `split_block`, as check-open-decision.py and
    add-open-decision.py do, so a checklist line after a gap still counts.
    """
    if MARKER not in body:
        return []
    return split_block(number, body)[1]


def approval_met(number: str, body: str) -> bool:
    """True when the highest-numbered approval line of `## Open decisions` is checked and resolved `yes` or `approved`."""
    items = decision_lines(number, body)
    lines = []
    for item in items:
        state, text = parse(item)
        match = APPROVAL_RE.match(text) if state else None
        if match:
            lines.append((int(match.group(1)), state == "checked", match.group(2) or ""))
    if not lines:
        raise SystemExit(
            f"issue #{number}: no `Approve the spec section? (draft <k>)` line in the "
            "`## Open decisions` block (the block ends at the next heading or `<!-- sdd:end -->`)"
        )
    _, checked, resolution = max(lines, key=lambda line: line[0])
    return checked and resolution.strip().lower().rstrip(".") in ("yes", "approved")


def check_transition(number: str, stage: str, body: str, labels: set[str]) -> None:
    """Exit 1 with the reason when the move to `stage` is not allowed."""
    current = {l[len(STAGE_PREFIX):] for l in labels if l.startswith(STAGE_PREFIX)}
    if stage == "spec-approved":
        if not current & SPEC_APPROVED_FROM:
            raise SystemExit(f"issue #{number}: spec-approved is allowed only from drafting-spec or spec-approved")
        if not approval_met(number, body):
            raise SystemExit(f"issue #{number}: the spec section is not approved")
    elif stage == "implementing" and not current & IMPLEMENTING_FROM:
        raise SystemExit(
            f"issue #{number}: implementing is allowed only from spec-approved, implementing or complete"
        )


def set_stage(number: int, stage: str) -> None:
    if stage not in STAGES:
        raise SystemExit(f"unknown stage '{stage}': expected one of {STAGES}")
    n = str(number)
    target = STAGE_PREFIX + stage

    body, labels = read_issue(n)
    if not body.strip():
        raise SystemExit(f"issue #{n}: refusing to write an empty body — gh issue view likely failed")
    if len(STAGE_LINE_RE.findall(body)) != 1:
        raise SystemExit(f"issue #{n}: expected exactly one **Stage:** line in the body")
    check_transition(n, stage, body, labels)
    new_body = STAGE_LINE_RE.sub(f"**Stage:** {stage}", body)

    # Body first: if a later step fails, the label (which merge tooling trusts)
    # still shows the old stage rather than claiming one the body never reached.
    if new_body != body:
        run_gh(["issue", "edit", n, "--body-file", "-"], stdin=new_body)
    stale = sorted(l for l in labels if l.startswith(STAGE_PREFIX) and l != target)
    if stale or target not in labels:
        label_args = ["--add-label", target]
        if stale:
            label_args += ["--remove-label", ",".join(stale)]
        run_gh(["issue", "edit", n, *label_args])

    body_back, labels_back = read_issue(n)
    if body_back.strip() != new_body.strip():
        raise SystemExit(f"issue #{n}: body read back does not match what was written")
    stage_labels = {l for l in labels_back if l.startswith(STAGE_PREFIX)}
    if stage_labels != {target}:
        raise SystemExit(f"issue #{n}: stage labels {sorted(stage_labels)}, expected ['{target}']")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("number", type=int)
    parser.add_argument("stage", choices=STAGES)
    args = parser.parse_args(argv)
    set_stage(args.number, args.stage)


if __name__ == "__main__":
    main()
