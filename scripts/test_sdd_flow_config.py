"""Stdlib tests for sdd_flow_config.py.

Run: python3 -m unittest discover -s . -p "test_sdd_flow_config.py" -v
"""
import contextlib
import importlib.util
import io
import pathlib
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location(
    "sdd_flow_config", pathlib.Path(__file__).with_name("sdd_flow_config.py")
)
sdd_flow_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sdd_flow_config)


class NoConfigFile(unittest.TestCase):
    def test_defaults_apply_when_the_file_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = sdd_flow_config.load(tmp)
        self.assertEqual(cfg["state_backend"], "github-issues")
        self.assertEqual(cfg["tiers"]["classification"], "auto")
        self.assertFalse(cfg["notifications"]["desktop"])
        self.assertFalse(cfg["notifications"]["push"])
        self.assertTrue(cfg["worktree"]["enabled"])
        self.assertEqual(cfg["rules_file_glob"], "*/RULES.md")

    def test_default_tier_profiles_cover_all_three_tiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = sdd_flow_config.load(tmp)
        t0 = sdd_flow_config.tier_profile(cfg, 0)
        self.assertEqual(t0["spec_review_roles"], [])
        self.assertTrue(t0["batch_mode"])
        self.assertFalse(t0["refactor_step"])
        t1 = sdd_flow_config.tier_profile(cfg, 1)
        self.assertEqual(t1["spec_review_roles"], ["tech-lead"])
        t2 = sdd_flow_config.tier_profile(cfg, 2)
        self.assertEqual(t2["spec_review_roles"], ["pm", "tech-lead", "qa"])
        self.assertEqual(t2["code_review_rounds"], 2)


class ConfigFile(unittest.TestCase):
    def write(self, tmp, text):
        path = pathlib.Path(tmp) / ".claude"
        path.mkdir(parents=True, exist_ok=True)
        (path / "sdd-flow.local.md").write_text(text, encoding="utf-8")

    def test_an_overridden_scalar_wins_and_siblings_keep_their_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "---\nrules_file_glob: \"*/rules/*.md\"\n---\nbody\n")
            cfg = sdd_flow_config.load(tmp)
        self.assertEqual(cfg["rules_file_glob"], "*/rules/*.md")
        self.assertEqual(cfg["state_backend"], "github-issues")

    def test_a_nested_override_merges_instead_of_replacing_the_whole_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "---\nnotifications:\n  desktop: true\n---\n")
            cfg = sdd_flow_config.load(tmp)
        self.assertTrue(cfg["notifications"]["desktop"])
        self.assertFalse(cfg["notifications"]["push"])  # sibling default survives

    def test_an_overridden_tier_profile_field_merges_over_its_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(
                tmp,
                "---\ntiers:\n  profiles:\n    1: { code_review_rounds: 2 }\n---\n",
            )
            cfg = sdd_flow_config.load(tmp)
        t1 = sdd_flow_config.tier_profile(cfg, 1)
        self.assertEqual(t1["code_review_rounds"], 2)
        self.assertEqual(t1["spec_review_roles"], ["tech-lead"])  # untouched default

    def test_an_unimplemented_state_backend_is_a_hard_error_naming_the_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "---\nstate_backend: local-file\n---\n")
            with self.assertRaises(sdd_flow_config.ConfigError) as ctx:
                sdd_flow_config.load(tmp)
        self.assertIn("local-file", str(ctx.exception))
        self.assertIn("github.com/ghiblin/sdd-flow/issues/1", str(ctx.exception))

    def test_an_unrecognized_state_backend_is_also_a_hard_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "---\nstate_backend: s3\n---\n")
            with self.assertRaises(sdd_flow_config.ConfigError):
                sdd_flow_config.load(tmp)

    def test_missing_closing_frontmatter_fence_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "---\nstate_backend: github-issues\n")
            with self.assertRaises(sdd_flow_config.ConfigError):
                sdd_flow_config.load(tmp)


class Cli(unittest.TestCase):
    def test_get_prints_a_dotted_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = sdd_flow_config.main([tmp, "get", "notifications.desktop"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), "False")

    def test_get_tier_profile_prints_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = sdd_flow_config.main([tmp, "get-tier-profile", "0"])
        self.assertEqual(code, 0)
        self.assertIn('"batch_mode": true', out.getvalue())

    def test_an_unknown_key_exits_non_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = sdd_flow_config.main([tmp, "get", "no.such.key"])
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
