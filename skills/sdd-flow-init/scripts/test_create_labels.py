"""Stdlib tests for create-labels.py; `gh` is faked, GitHub is never reached.

Run: python3 -m unittest discover -s .claude/skills/sdd-init/scripts -v
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "create_labels", pathlib.Path(__file__).with_name("create-labels.py")
)
create_labels = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(create_labels)

EXPECTED = {
    "sdd:feature": ("1D76DB", "SDD: feature main issue"),
    "sdd:task": ("0E8A16", "SDD: feature development increment"),
    "sdd:needs-spec": ("D93F0B", "SDD: sub-issue whose behaviour the spec does not describe yet"),
    "sdd:no-red-green": ("C5DEF5", "SDD: sub-issue the user exempted from the red-green check"),
    "sdd:follow-up": ("BFD4F2", "SDD: reviewer finding deferred to a later issue"),
    "sdd:stage:drafting-spec": ("FBCA04", "SDD stage: drafting the spec"),
    "sdd:stage:spec-approved": ("FBCA04", "SDD stage: spec approved"),
    "sdd:stage:implementing": ("FBCA04", "SDD stage: implementing"),
    "sdd:stage:complete": ("FBCA04", "SDD stage: implementation complete"),
    "sdd:stage:verified": ("0E8A16", "SDD stage: PR-validated"),
}


class FakeGh:
    """Plays GitHub's label store; records every `gh` call."""

    def __init__(self, existing=None, drop_on_create=None):
        # name -> (color lowercase as GitHub returns it, description)
        self.labels = dict(existing or {})
        self.drop_on_create = drop_on_create
        self.calls = []

    def __call__(self, args, stdin=None):
        self.calls.append(list(args))
        if args[:2] == ["label", "list"]:
            return json.dumps(
                [
                    {"name": n, "color": c, "description": d}
                    for n, (c, d) in self.labels.items()
                ]
            )
        if args[:2] == ["label", "create"]:
            name = args[2]
            assert "--force" in args, "label create must be idempotent"
            color = args[args.index("--color") + 1]
            desc = args[args.index("--description") + 1]
            if name != self.drop_on_create:
                self.labels[name] = (color.lower(), desc)
            return ""
        raise AssertionError(f"unexpected gh call: {args}")


class CreateLabels(unittest.TestCase):
    def test_given_a_fresh_repo_when_run_then_every_sdd_label_is_created(self):
        gh = FakeGh()
        create_labels.run_gh = gh
        report = create_labels.create_labels()
        self.assertEqual(report, {name: "created" for name in EXPECTED})
        for name, (color, desc) in EXPECTED.items():
            self.assertEqual(gh.labels[name], (color.lower(), desc))

    def test_given_some_labels_exist_then_they_are_reported_as_present(self):
        gh = FakeGh(existing={"sdd:feature": ("ffffff", "old"), "bug": ("d73a4a", "")})
        create_labels.run_gh = gh
        report = create_labels.create_labels()
        self.assertEqual(report["sdd:feature"], "present")
        self.assertEqual(report["sdd:task"], "created")
        self.assertNotIn("bug", report)
        # --force still updated the stale colour/description
        self.assertEqual(gh.labels["sdd:feature"], ("1d76db", "SDD: feature main issue"))

    def test_creates_spec_approved_label(self):
        gh = FakeGh()
        create_labels.run_gh = gh
        create_labels.create_labels()
        self.assertEqual(gh.labels["sdd:stage:spec-approved"], ("fbca04", "SDD stage: spec approved"))

    def test_every_create_call_uses_force(self):
        gh = FakeGh()
        create_labels.run_gh = gh
        create_labels.create_labels()
        creates = [c for c in gh.calls if c[:2] == ["label", "create"]]
        self.assertEqual(len(creates), len(EXPECTED))
        self.assertTrue(all("--force" in c for c in creates))

    def test_given_a_label_does_not_land_then_it_exits_non_zero(self):
        gh = FakeGh(drop_on_create="sdd:stage:complete")
        create_labels.run_gh = gh
        with self.assertRaises(SystemExit) as ctx:
            create_labels.create_labels()
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertIn("sdd:stage:complete", str(ctx.exception.code))

    def test_main_prints_one_line_per_label(self):
        gh = FakeGh(existing={"sdd:task": ("0e8a16", "SDD: feature development increment")})
        create_labels.run_gh = gh
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            create_labels.main([])
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), len(EXPECTED))
        self.assertIn("present sdd:task", lines)
        self.assertIn("created sdd:feature", lines)


if __name__ == "__main__":
    unittest.main()
