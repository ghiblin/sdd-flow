#!/usr/bin/env python3
"""Squash-merge a feature PR, clean up its worktree/branch, and close the
feature's GitHub main issue (plus refuse if the main issue is not
sdd:stage:verified, or if any sdd:task sub-issue is still open).

The main issue number is taken from the branch name (sdd/<n>-<slug>).

Usage:
    scripts/merge_pr.py <worktree-name> [--dry-run] [--skip-ci-check] [--repo OWNER/REPO]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Matches git@<any-host>:owner/repo(.git), ssh://git@<any-host>/owner/repo(.git),
# and https://<any-host>/owner/repo(.git) — deliberately host-agnostic so a
# personal SSH alias (e.g. "github.me") doesn't need to match a known gh host.
REMOTE_URL_RE = re.compile(
    r"(?:git@[^:/]+[:/]|https?://[^/]+/)(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)

BRANCH_RE = re.compile(r"^sdd/(?P<number>\d+)-.+$")


def parse_owner_repo(remote_url: str) -> str:
    match = REMOTE_URL_RE.search(remote_url.strip())
    if not match:
        raise SystemExit(f"Could not parse owner/repo from remote URL: {remote_url}")
    return f"{match['owner']}/{match['repo']}"


def issue_number_from_branch(branch: str) -> int:
    match = BRANCH_RE.match(branch.strip())
    if not match:
        raise SystemExit(
            f"Branch '{branch}' is not an SDD feature branch (expected "
            f"'sdd/<issue-number>-<slug>'). Check out the feature branch first."
        )
    return int(match["number"])


def run(cmd: list[str], cwd: Path | None = None, dry_run: bool = False) -> str:
    prefix = "DRY-RUN $ " if dry_run else "$ "
    print(prefix + " ".join(cmd) + (f"  (cwd={cwd})" if cwd else ""))
    if dry_run:
        return ""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, end="", file=sys.stderr)
        raise SystemExit(f"Command failed ({result.returncode}): {' '.join(cmd)}")
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "worktree_name",
        help="Name of the worktree under .claude/worktrees/ to merge and remove "
        "(e.g. 'passwordless-auth')",
    )
    parser.add_argument(
        "--repo",
        help="[HOST/]OWNER/REPO to pass to gh via -R, bypassing gh's own "
        "remote-URL host detection (which fails against a personal SSH "
        "alias host). Default: parsed automatically from the worktree's "
        "'origin' remote URL, ignoring whatever hostname/alias it uses.",
    )
    parser.add_argument(
        "--skip-ci-check",
        action="store_true",
        help="Skip the 'gh pr checks' gate before merging",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the merge/teardown/close plan and exit without mutating anything.",
    )
    args = parser.parse_args()

    worktree_path = REPO_ROOT / ".claude" / "worktrees" / args.worktree_name
    if not worktree_path.exists():
        raise SystemExit(f"Worktree not found: {worktree_path}")

    branch = run(["git", "branch", "--show-current"], cwd=worktree_path)
    if not branch:
        raise SystemExit(f"Could not determine current branch in {worktree_path}")
    issue_number = issue_number_from_branch(branch)

    repo = args.repo
    if not repo:
        remote_url = run(["git", "remote", "get-url", "origin"], cwd=worktree_path)
        repo = parse_owner_repo(remote_url)
    gh_repo_flag = ["-R", repo]

    print(f"\nMerging PR for branch '{branch}' (worktree: {args.worktree_name})")
    print(f"Resolved gh repo: {repo}")
    print(f"Feature main issue: #{issue_number}")
    if args.dry_run:
        print("\n(--dry-run: the verified-stage and sub-issue gates run for real and report "
              "WOULD REFUSE if they'd block; no CI check, merge, teardown, or issue close will run)\n")

    # 0. Stage gate — refuse to merge unless the main issue has been through
    # sdd-flow-pr-validate and is labeled sdd:stage:verified.
    label_names = run(
        ["gh", "issue", "view", str(issue_number), *gh_repo_flag, "--json", "labels", "-q", ".labels[].name"],
        cwd=REPO_ROOT,
    ).splitlines()
    if "sdd:stage:verified" not in label_names:
        msg = f"Feature #{issue_number} is not sdd:stage:verified — run sdd-flow-pr-validate before merging."
        if args.dry_run:
            print(f"WOULD REFUSE: {msg}")
        else:
            raise SystemExit(msg)

    # 0b. Sub-issue gate — refuse to merge while any sdd:task sub-issue is
    # still open. Uses the GraphQL subIssues query (the reliable path; gh
    # issue list has no confirmed parent qualifier on 2.92).
    main_id = run(
        ["gh", "issue", "view", str(issue_number), *gh_repo_flag, "--json", "id", "-q", ".id"],
        cwd=REPO_ROOT,
    )
    raw = run(
        [
            "gh", "api", "graphql",
            "-f", "query=query($id:ID!){node(id:$id){... on Issue{"
            "subIssues(first:100){nodes{number title state}}}}}",
            "-f", f"id={main_id}",
        ],
        cwd=REPO_ROOT,
    )
    nodes = json.loads(raw)["data"]["node"]["subIssues"]["nodes"]
    still_open = [x for x in nodes if x["state"] == "OPEN"]
    if still_open:
        listing = "\n".join(f"  #{x['number']} {x['title']}" for x in still_open)
        msg = (
            f"Feature #{issue_number} still has open sub-issues — finish or close "
            f"them (via sdd-flow-reconcile) before merging:\n{listing}"
        )
        if args.dry_run:
            print(f"WOULD REFUSE: {msg}")
        else:
            raise SystemExit(msg)

    # 1. CI gate
    # gh requires an explicit PR selector (here: branch name) whenever -R is
    # passed — it won't infer "current branch" for an explicitly-named repo.
    # gh pr checks exits non-zero both when checks are failing/pending AND
    # when the PR simply has no checks configured at all — only the former
    # should block the merge.
    if not args.skip_ci_check:
        if args.dry_run:
            print(f"DRY-RUN $ gh pr checks {branch} {' '.join(gh_repo_flag)}  (cwd={worktree_path})")
        else:
            print(f"$ gh pr checks {branch} {' '.join(gh_repo_flag)}  (cwd={worktree_path})")
            result = subprocess.run(
                ["gh", "pr", "checks", branch, *gh_repo_flag],
                cwd=worktree_path,
                capture_output=True,
                text=True,
            )
            output = (result.stdout + result.stderr).strip()
            print(output)
            if "no checks reported" in output.lower():
                print("(no CI checks configured on this PR — nothing to gate on, proceeding)")
            elif result.returncode != 0:
                raise SystemExit(
                    "PR has failing or pending checks — resolve before merging:\n" + output
                )

    # 2. Squash-merge + delete remote branch
    run(
        ["gh", "pr", "merge", branch, *gh_repo_flag, "--squash", "--delete-branch"],
        cwd=worktree_path,
        dry_run=args.dry_run,
    )

    # 3. Remove local worktree (run from repo root, not from inside it)
    run(
        ["git", "worktree", "remove", str(worktree_path), "--force"],
        cwd=REPO_ROOT,
        dry_run=args.dry_run,
    )

    # 4. Delete local branch
    run(["git", "branch", "-D", branch], cwd=REPO_ROOT, dry_run=args.dry_run)

    # 5. Pull main
    run(["git", "checkout", "main"], cwd=REPO_ROOT, dry_run=args.dry_run)
    run(["git", "pull"], cwd=REPO_ROOT, dry_run=args.dry_run)
    latest_commit = run(["git", "log", "-1", "--oneline"], cwd=REPO_ROOT, dry_run=args.dry_run)

    # 6. Close the feature's main issue
    run(
        ["gh", "issue", "close", str(issue_number), *gh_repo_flag, "--reason", "completed"],
        cwd=REPO_ROOT,
        dry_run=args.dry_run,
    )

    print("\nDone.")
    print(f"Branch:  {branch} deleted (local + remote)")
    print(f"Worktree: {args.worktree_name} removed")
    print(f"Latest main commit: {latest_commit}")
    print(f"Closed feature main issue: #{issue_number}")


if __name__ == "__main__":
    main()
