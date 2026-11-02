"""Stdlib unit tests for sdd_route. Run: python3 -m unittest scripts.test_sdd_route -v"""
import contextlib
import importlib.util
import io
import json
import pathlib
import unittest
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "sdd_route", pathlib.Path(__file__).with_name("sdd_route.py")
)
sdd_route = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sdd_route)

APPROVE = "Approve the spec section? (draft {k})"
BRANCH = "**Branch:** sdd/7-demo\n"


def body(*lines, branch=BRANCH, block=True, eol="\n"):
    text = "<!-- sdd:begin -->\n**Stage:** x\n" + branch
    if block:
        text += "## Open decisions\n" + "\n".join(lines or ("- [ ] _none_",)) + "\n"
    text += "<!-- sdd:end -->\n\n## Problem\n"
    return text.replace("\n", eol)


class Run(unittest.TestCase):
    """Calls main() with gh and the helper scripts replaced by fakes."""

    def route(self, *lines, stage="implementing", argv=("7",), labels=None, state="OPEN",
              open_subs=(), needs=(), prs=None, gh_fail=False, gh_raw=None, **body_kw):
        if labels is None:
            labels = ["sdd:feature"] + ([f"sdd:stage:{stage}"] if stage else [])
        issue = {"state": state, "labels": [{"name": n} for n in labels],
                 "body": body(*lines, **body_kw)}

        def gh(args):
            if gh_fail:
                raise sdd_route.ToolError("gh failed")
            if gh_raw is not None:
                return gh_raw
            if args[:2] == ["issue", "view"]:
                return json.dumps(issue)
            if args[:2] == ["pr", "list"]:
                return json.dumps(prs or [])
            raise AssertionError(args)

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sdd_route, "run_gh", gh), \
                mock.patch.object(sdd_route, "run_open_sub_issues", lambda n: list(open_subs)), \
                mock.patch.object(sdd_route, "run_needs_spec", lambda n: list(needs)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sdd_route.main(list(argv))
        return code, out.getvalue()

    def assertRoute(self, expected, *args, **kw):
        self.assertEqual(self.route(*args, **kw), (0, expected + "\n"))


class Stops(Run):
    def test_not_sdd_stops(self):
        self.assertRoute("route: stop   reason: not-sdd", labels=["sdd:stage:implementing"])

    def test_closed_stops(self):
        self.assertRoute("route: stop   reason: closed", state="CLOSED")

    def test_not_sdd_beats_closed(self):
        self.assertRoute("route: stop   reason: not-sdd", state="CLOSED", labels=[])

    def test_stage_label_count_stops(self):
        self.assertRoute("route: stop   reason: stage-label", stage=None)
        self.assertRoute("route: stop   reason: stage-label",
                         labels=["sdd:feature", "sdd:stage:complete", "sdd:stage:implementing"])

    def test_verified_with_pr_stops(self):
        prs = [{"url": "u1", "state": "MERGED", "createdAt": "2026-01-01T00:00:00Z"},
               {"url": "u2", "state": "OPEN", "createdAt": "2026-02-01T00:00:00Z"},
               {"url": "u3", "state": "CLOSED", "createdAt": "2026-03-01T00:00:00Z"}]
        self.assertRoute("route: stop   reason: pr-exists   url: u2", stage="verified", prs=prs)

    def test_verified_skips_decisions(self):
        self.assertRoute("route: pr-only", "- [ ] a real question", stage="verified")

    def test_verified_without_pr(self):
        self.assertRoute("route: pr-only", stage="verified",
                         prs=[{"url": "u", "state": "CLOSED", "createdAt": "2026-01-01T00:00:00Z"}])

    def test_bad_branch_line_exits_2(self):
        for branch in ("", "**Branch:** other/7-demo\n", BRANCH + BRANCH):
            self.assertEqual(self.route(stage="verified", branch=branch)[0], 2)

    def test_stops_do_not_read_block(self):
        self.assertRoute("route: stop   reason: closed", state="CLOSED", block=False)
        self.assertRoute("route: stop   reason: stage-label", stage=None, block=False)
        self.assertRoute("route: stop   reason: stage-label", stage="foo", block=False)
        self.assertRoute("route: pr-only", stage="verified", block=False)


class Decisions(Run):
    def test_open_decisions_route_first(self):
        self.assertRoute(
            "route: decisions   count: 2",
            "- [ ] _none_", "- [x] done", "- [ ] first", "- [ ] second",
            APPROVE.format(k=1).join(["- [ ] ", ""]), stage="drafting-spec")

    def test_after_sweep_skips_decisions(self):
        self.assertRoute("route: stage-3   sub-issue: none", "- [ ] first",
                         stage="spec-approved", argv=("7", "--after-sweep"))

    def test_checked_lines_are_ignored(self):
        self.assertRoute("route: stage-2", "- [x] " + APPROVE.format(k=1), "- [x] q",
                         stage="drafting-spec")

    def test_crlf_and_uppercase_x_are_read(self):
        self.assertRoute("route: checkpoint-b", "- [X] q", "- [ ] _none_", stage="complete",
                         eol="\r\n")
        self.assertRoute("route: decisions   count: 1", "- [X] q", "- [ ] open", stage="complete",
                         eol="\r\n")

    def test_indented_line_is_read(self):
        self.assertRoute("route: decisions   count: 1", "  - [ ] Pick a crate?", stage="complete")

    def test_heading_on_last_line_is_the_block(self):
        issue = {"state": "OPEN", "labels": [{"name": "sdd:feature"}, {"name": "sdd:stage:complete"}],
                 "body": "**Stage:** x\n## Open decisions"}
        self.assertRoute("route: checkpoint-b", stage="complete", gh_raw=json.dumps(issue))

    def test_non_numeric_k_is_a_decision(self):
        self.assertRoute("route: decisions   count: 1", "- [ ] Approve the spec section? (draft x)",
                         stage="drafting-spec")

    def test_missing_block_exits_2(self):
        for argv in (("7",), ("7", "--after-sweep")):
            self.assertEqual(self.route(stage="implementing", block=False, argv=argv)[0], 2)


class Stages(Run):
    def test_checkpoint_a_uses_highest_unchecked_k(self):
        self.assertRoute("route: checkpoint-a   draft: 10",
                         "- [ ] " + APPROVE.format(k=9), "- [ ] " + APPROVE.format(k=10),
                         "- [x] " + APPROVE.format(k=11), stage="drafting-spec",
                         argv=("7", "--after-sweep"))

    def test_needs_spec_beats_approval_line(self):
        self.assertRoute("route: scoped-draft   sub-issues: 5,12", "- [ ] " + APPROVE.format(k=1),
                         stage="drafting-spec", needs=[12, 5], open_subs=[12, 5, 20])

    def test_drafting_without_approval_line(self):
        self.assertRoute("route: stage-2   sub-issues: 4,9", stage="drafting-spec", open_subs=[9, 4])

    def test_stage_2_without_sub_issues(self):
        self.assertRoute("route: stage-2", stage="drafting-spec")

    def test_spec_approved_routes_to_stage_3(self):
        self.assertRoute("route: stage-3   sub-issue: 3", stage="spec-approved", open_subs=[8, 3])

    def test_spec_approved_without_sub_issue(self):
        self.assertRoute("route: stage-3   sub-issue: none", stage="spec-approved")

    def test_implementing_with_open_sub_issue(self):
        self.assertRoute("route: stage-3   sub-issue: 3", open_subs=[8, 3])

    def test_implementing_without_sub_issue(self):
        self.assertRoute("route: reconcile-first")

    def test_complete_routes_to_checkpoint_b(self):
        self.assertRoute("route: checkpoint-b", stage="complete", open_subs=[3])


class Errors(Run):
    def test_usage_errors_exit_2(self):
        for argv in ((), ("x",), ("7", "--bogus"), ("--help",), ("7", "8")):
            self.assertEqual(self.route(argv=argv)[0], 2, argv)

    def test_tool_errors_exit_2(self):
        self.assertEqual(self.route(gh_fail=True)[0], 2)
        self.assertEqual(self.route(gh_raw="not json")[0], 2)
        self.assertEqual(self.route(gh_raw="[]")[0], 2)
        self.assertEqual(self.route(gh_raw='{"state": "OPEN"}')[0], 2)
        with mock.patch.object(sdd_route, "SKILL_SCRIPTS", pathlib.Path("/nonexistent")):
            self.assertEqual(self.route()[0], 2)


if __name__ == "__main__":
    unittest.main()
