#!/usr/bin/env python3
"""Verify the state that an SDD stage must leave behind.

Usage:
  sdd_check_state.py --issue <n> --stage <intent|draft|tdd|reconcile|pr-validate>
      [--worktree <dir>] [--child <c>] [--stopped]
      [--main-checkout <dir> --status-file <file> --main-sha <sha>]

Exit 0 when every check passes (no output), 1 when one fails (a `FAIL <check>: expected <x>,
found <y>` line each), 2 on a usage or tool error. Stdlib only.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sdd_script_tools import Parser, ToolError, run_checked  # noqa: E402

STAGES = ("intent", "draft", "tdd", "reconcile", "pr-validate")
REPO = Path(__file__).resolve().parent.parent
NEEDS_SPEC = Path(__file__).resolve().parent / "needs-spec.py"  # sdd-flow ships one shared scripts/ dir
# The `**Stage:**` line pattern of set-stage.py. A unit test pins it to that script's
# STAGE_LINE_RE, so the checker does not run the writer script to read one constant.
STAGE_LINE_RE = re.compile(r"^\*\*Stage:\*\* .*$", re.MULTILINE)


def run_gh(args: list[str]) -> str:
    return run_checked(["gh", *args], REPO)


def run_git(directory: str, *args: str) -> str:
    return run_checked(["git", "-C", directory, *args]).strip()


def run_needs_spec(issue: str) -> list[str]:
    out = run_checked([sys.executable, str(NEEDS_SPEC), issue], REPO)
    return [line for line in out.splitlines() if line.strip()]


def _json(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ToolError(f"cannot parse gh output: {exc}") from exc
    if not isinstance(data, dict):
        raise ToolError("cannot parse gh output: not an object")
    return data


def _allowed(stage: str, stopped: bool, needs_spec: bool) -> set[str]:
    if stage == "intent":
        return {"drafting-spec"}
    if stage == "draft":
        return {"spec-approved"}
    if stage == "tdd":
        return {"implementing"}
    if stage == "reconcile":
        return {"implementing", "complete"} | ({"drafting-spec"} if needs_spec else set())
    return {"complete"} if stopped else {"verified"}


def check(args: argparse.Namespace) -> list[str]:
    fails: list[str] = []
    issue = str(args.issue)
    data = _json(run_gh(["issue", "view", issue, "--json", "state,labels,body"]))
    try:
        names = [label["name"] for label in data["labels"]]
        body = data["body"]
        state = data["state"]
    except (KeyError, TypeError) as exc:
        raise ToolError(f"cannot parse gh output: {exc}") from exc
    stages = [n[len("sdd:stage:"):] for n in names if n.startswith("sdd:stage:")]

    if state != "OPEN":
        fails.append(f"FAIL issue-state: expected OPEN, found {state}")

    branch = None
    if args.worktree:
        m = re.search(r"^\*\*Branch:\*\*\s*(\S+)\s*$", body, re.M)
        if m and re.fullmatch(rf"sdd/{re.escape(issue)}-[\w.-]+", m.group(1)):
            branch = m.group(1)
        elif not fails:
            # A closed issue already fails; only an open one makes a bad Branch line a tool error.
            raise ToolError("no valid **Branch:** line in the issue body")

    if len(stages) != 1:
        fails.append(f"FAIL label-count: expected 1 sdd:stage:* label, found {len(stages)} ({', '.join(stages) or 'none'})")
    else:
        needs = bool(run_needs_spec(issue)) if args.stage in ("draft", "reconcile") else False
        label = stages[0]
        allowed = _allowed(args.stage, args.stopped, needs)
        if args.stage == "draft" and needs:
            fails.append("FAIL needs-spec: expected no open sdd:needs-spec sub-issue, found one")
        elif args.stage == "reconcile" and label == "drafting-spec" and not needs:
            fails.append("FAIL needs-spec: expected an open sdd:needs-spec sub-issue for drafting-spec, found none")
        elif label not in allowed:
            fails.append(f"FAIL stage-label: expected {' or '.join(sorted(allowed))}, found {label}")
        lines = STAGE_LINE_RE.findall(body.replace("\r\n", "\n"))
        if len(lines) != 1:
            fails.append(f"FAIL stage-line: expected one **Stage:** line, found {len(lines)}")
        elif (found_line := lines[0][len("**Stage:**"):].strip()) != label:
            fails.append(f"FAIL stage-line: expected **Stage:** {label}, found {found_line}")

    if branch is not None:
        found = run_git(args.worktree, "branch", "--show-current")
        if found != branch:
            fails.append(f"FAIL branch: expected {branch}, found {found}")

    if args.main_checkout:
        recorded = Path(args.status_file).read_text(encoding="utf-8").strip()
        status = run_git(args.main_checkout, "status", "--porcelain")
        if status.strip() != recorded:
            fails.append(f"FAIL main-status: expected {recorded!r}, found {status.strip()!r}")
        sha = run_git(args.main_checkout, "rev-parse", "main")
        if sha != args.main_sha:
            fails.append(f"FAIL main-sha: expected {args.main_sha}, found {sha}")

    if args.child:
        child_state = _json(run_gh(["issue", "view", str(args.child), "--json", "state"])).get("state")
        if child_state != "CLOSED":
            fails.append(f"FAIL child-state: expected CLOSED, found {child_state}")
    return fails


def main(argv: list[str] | None = None) -> int:
    parser = Parser(prog="sdd_check_state.py")
    parser.add_argument("--issue", required=True)
    parser.add_argument("--stage", required=True, choices=STAGES)
    parser.add_argument("--worktree")
    parser.add_argument("--child")
    parser.add_argument("--stopped", action="store_true")
    parser.add_argument("--main-checkout")
    parser.add_argument("--status-file")
    parser.add_argument("--main-sha")
    try:
        args = parser.parse_args(argv)
        if args.stopped and args.stage != "pr-validate":
            raise ToolError("--stopped is valid only with --stage pr-validate")
        group = [args.main_checkout, args.status_file, args.main_sha]
        if any(group) and not all(group):
            raise ToolError("--main-checkout, --status-file and --main-sha go together")
        fails = check(args)
    except ToolError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    except OSError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    for line in fails:
        print(line)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
