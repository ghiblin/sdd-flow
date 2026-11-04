#!/usr/bin/env python3
"""Print the next route of the `sdd` orchestrator for one SDD main issue.

Usage:
  sdd_route.py <n> [--after-sweep]

Prints one line `route: <name>` followed, for some routes, by `   <key>: <value>` fields,
and exits 0. Exit 2 on a usage or tool error. The script reads state and never writes it.
Stdlib only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sdd_script_tools import Parser, ToolError, load_open_decisions, parse_json, run_checked  # noqa: E402

SKILL_SCRIPTS = Path(__file__).resolve().parent  # sdd-flow ships one shared scripts/ dir
NEEDS_SPEC = SKILL_SCRIPTS / "needs-spec.py"
LIST_SUB_ISSUES = SKILL_SCRIPTS / "list-sub-issues.py"
APPROVE_RE = re.compile(r"^Approve the spec section\? \(draft (\d+)\)$")
BRANCH_PREFIX = "**Branch:**"
KNOWN_STAGES = ("verified", "drafting-spec", "spec-approved", "implementing", "complete")


def run_gh(args: list[str]) -> str:
    # No cwd override: gh must run in the caller's own working directory (the
    # user's project), never in this script's own location — that's the
    # plugin's install/cache directory once sdd-flow ships as a plugin, not a
    # git repo at all.
    return run_checked(["gh", *args])


def _numbers(out: str, what: str) -> list[int]:
    try:
        return [int(line.split("\t")[0]) for line in out.splitlines() if line.strip()]
    except ValueError as exc:
        raise ToolError(f"cannot parse {what} output: {exc}") from exc


def run_open_sub_issues(issue: str) -> list[int]:
    return _numbers(run_checked([sys.executable, str(LIST_SUB_ISSUES), issue, "--open"]),
                    "list-sub-issues")


def run_needs_spec(issue: str) -> list[int]:
    return _numbers(run_checked([sys.executable, str(NEEDS_SPEC), issue]), "needs-spec")


def _join(numbers: list[int]) -> str:
    """The one owner of the order of a printed sub-issue list: ascending."""
    return ",".join(str(n) for n in sorted(numbers))


def _branch(issue: str, body: str) -> str:
    lines = [ln for ln in body.replace("\r\n", "\n").split("\n") if ln.startswith(BRANCH_PREFIX)]
    if len(lines) != 1:
        raise ToolError("expected exactly one **Branch:** line in the issue body")
    branch = lines[0][len(BRANCH_PREFIX):].strip()
    if not re.fullmatch(rf"sdd/{re.escape(issue)}-[\w.-]+", branch):
        raise ToolError(f"the **Branch:** line is not sdd/{issue}-<slug>")
    return branch


def _pr_route(branch: str) -> str:
    prs = parse_json(run_gh(["pr", "list", "--head", branch, "--state", "all",
                             "--json", "url,state,createdAt"]), list)
    try:
        live = [pr for pr in prs if pr["state"] in ("OPEN", "MERGED")]
        newest = max(live, key=lambda pr: pr["createdAt"], default=None)
        return f"route: stop   reason: pr-exists   url: {newest['url']}" if newest else "route: pr-only"
    except (KeyError, TypeError) as exc:
        raise ToolError(f"cannot parse gh output: {exc}") from exc


def _unchecked(issue: str, body: str) -> tuple[list[str], list[int]]:
    """Return (decision lines, k of each unchecked approval line) of the open block."""
    od = load_open_decisions(SKILL_SCRIPTS / "open_decisions.py")
    body = od.normalize(body)
    if not body.endswith("\n"):
        body += "\n"  # a heading on the last line still counts as the block
    try:
        _, block, _ = od.split_block(issue, body)
    except SystemExit as exc:
        raise ToolError(str(exc)) from exc
    decisions: list[str] = []
    approvals: list[int] = []
    for line in block:
        state, text = od.parse(line.lstrip())  # an indented line (a web-UI edit) counts too
        if state != "open" or text == "_none_":
            continue
        match = APPROVE_RE.match(text)
        if match:
            approvals.append(int(match.group(1)))
        else:
            decisions.append(text)
    return decisions, approvals


def route(issue: str, after_sweep: bool) -> str:
    data = parse_json(run_gh(["issue", "view", issue, "--json", "state,labels,body"]), dict)
    try:
        names = [label["name"] for label in data["labels"]]
        body, state = data["body"], data["state"]
    except (KeyError, TypeError) as exc:
        raise ToolError(f"cannot parse gh output: {exc}") from exc
    if "sdd:feature" not in names:
        return "route: stop   reason: not-sdd"
    if state != "OPEN":
        return "route: stop   reason: closed"
    stages = [n[len("sdd:stage:"):] for n in names if n.startswith("sdd:stage:")]
    if len(stages) != 1 or stages[0] not in KNOWN_STAGES:
        return "route: stop   reason: stage-label"
    stage = stages[0]
    if stage == "verified":
        return _pr_route(_branch(issue, body))

    decisions, approvals = _unchecked(issue, body)
    if decisions and not after_sweep:
        return f"route: decisions   count: {len(decisions)}"

    if stage == "drafting-spec":
        needs = run_needs_spec(issue)
        if needs:
            return f"route: scoped-draft   sub-issues: {_join(needs)}"
        if approvals:
            return f"route: checkpoint-a   draft: {max(approvals)}"
        subs = run_open_sub_issues(issue)
        return f"route: stage-2   sub-issues: {_join(subs)}" if subs else "route: stage-2"
    if stage in ("spec-approved", "implementing"):
        subs = run_open_sub_issues(issue)
        if subs:
            return f"route: stage-3   sub-issue: {min(subs)}"
        return "route: stage-3   sub-issue: none" if stage == "spec-approved" else "route: reconcile-first"
    return "route: checkpoint-b"


def main(argv: list[str] | None = None) -> int:
    parser = Parser(prog="sdd_route.py", usage_text="usage: sdd_route.py <n> [--after-sweep]")
    parser.add_argument("issue")
    parser.add_argument("--after-sweep", action="store_true")
    try:
        args = parser.parse_args(argv)
        if not args.issue.isdecimal():
            raise ToolError("the issue number must be a decimal number")
        line = route(args.issue, args.after_sweep)
    except (ToolError, OSError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
