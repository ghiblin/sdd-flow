"""Stdlib unit tests for remove-wip.py. Run: python3 -m unittest discover -s <this folder>"""
import contextlib
import importlib.util
import io
import pathlib
import tempfile
import textwrap
import unittest

_spec = importlib.util.spec_from_file_location(
    "remove_wip", pathlib.Path(__file__).with_name("remove-wip.py")
)
remove_wip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remove_wip)


def feature(text):
    return textwrap.dedent(text).lstrip("\n")


class Tool(unittest.TestCase):
    """Given a feature file on disk, when remove-wip.py runs on it, then ..."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = pathlib.Path(self._tmp.name) / "a.feature"

    def run_tool(self, text, *names):
        self.path.write_bytes(text.encode("utf-8"))
        argv = [str(self.path)]
        for name in names:
            argv += ["--scenario", name]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = remove_wip.main(argv)
        return code, self.path.read_bytes().decode("utf-8"), err.getvalue()

    def assert_refused(self, text, *names, reason):
        code, after, err = self.run_tool(text, *names)
        self.assertNotEqual(code, 0)
        self.assertEqual(after, text, "a refused run must change nothing")
        self.assertIn(reason, err)


class RemovesOnlyTheWipTag(Tool):
    def test_deletes_a_tag_line_whose_only_tag_is_wip(self):
        before = feature(
            """
            Feature: F

              @wip
              Scenario: A
                Given a
            """
        )
        code, after, _ = self.run_tool(before, "A")
        self.assertEqual(code, 0)
        self.assertEqual(after, feature(
            """
            Feature: F

              Scenario: A
                Given a
            """
        ))

    def test_keeps_the_other_tags_on_the_line(self):
        for line, kept in [
            ("  @slow @wip @db", "  @slow @db"),
            ("  @wip @slow", "  @slow"),
            ("  @slow @wip", "  @slow"),
        ]:
            with self.subTest(line=line):
                before = f"Feature: F\n\n{line}\n  Scenario: A\n    Given a\n"
                code, after, _ = self.run_tool(before, "A")
                self.assertEqual(code, 0)
                self.assertEqual(after, f"Feature: F\n\n{kept}\n  Scenario: A\n    Given a\n")

    def test_does_not_touch_a_tag_that_only_starts_with_wip(self):
        before = "Feature: F\n\n  @wip @wipe\n  Scenario: A\n    Given a\n"
        code, after, _ = self.run_tool(before, "A")
        self.assertEqual(code, 0)
        self.assertEqual(after, "Feature: F\n\n  @wipe\n  Scenario: A\n    Given a\n")

    def test_removes_the_tag_from_the_outline_and_its_examples_blocks(self):
        before = feature(
            """
            Feature: F

              @wip
              Scenario Outline: A
                Given <x>

                @wip
                Examples: one
                  | x |
                  | 1 |

                @fast @wip
                Examples: two
                  | x |
                  | 2 |
            """
        )
        code, after, _ = self.run_tool(before, "A")
        self.assertEqual(code, 0)
        self.assertEqual(after, feature(
            """
            Feature: F

              Scenario Outline: A
                Given <x>

                Examples: one
                  | x |
                  | 1 |

                @fast
                Examples: two
                  | x |
                  | 2 |
            """
        ))

    def test_leaves_other_scenarios_and_crlf_endings_unchanged(self):
        before = (
            "Feature: F\r\n\r\n  @wip\r\n  Scenario: A\r\n    Given a\r\n\r\n"
            "  @wip\r\n  Scenario: B\r\n    Given b\r\n"
        )
        code, after, _ = self.run_tool(before, "B")
        self.assertEqual(code, 0)
        self.assertEqual(
            after,
            "Feature: F\r\n\r\n  @wip\r\n  Scenario: A\r\n    Given a\r\n\r\n"
            "  Scenario: B\r\n    Given b\r\n",
        )

    def test_handles_several_named_scenarios_and_non_ascii_text(self):
        before = feature(
            """
            Feature: Diät — café

              @wip
              Scenario: Prénom
                Given « a »

              @wip
              Example: Second
                Given b
            """
        )
        code, after, _ = self.run_tool(before, "Prénom", "Second")
        self.assertEqual(code, 0)
        self.assertNotIn("@wip", after)
        self.assertIn("Feature: Diät — café", after)
        self.assertIn("Given « a »", after)

    def test_ignores_lookalike_lines_inside_a_doc_string(self):
        before = feature(
            '''
            Feature: F

              @wip
              Scenario: A
                Given a text
                  """
                  @wip
                  Scenario: A
                  """
            '''
        )
        code, after, _ = self.run_tool(before, "A")
        self.assertEqual(code, 0)
        self.assertEqual(after.count("@wip"), 1)
        self.assertTrue(after.startswith("Feature: F\n\n  Scenario: A\n"))

    def test_a_blank_line_between_the_tag_and_the_scenario(self):
        before = "Feature: F\n\n  @wip\n\n  Scenario: A\n    Given a\n"
        code, after, _ = self.run_tool(before, "A")
        self.assertEqual(code, 0)
        self.assertEqual(after, "Feature: F\n\n\n  Scenario: A\n    Given a\n")

    def test_rules_scope_scenarios_but_keep_their_own_tags(self):
        before = feature(
            """
            Feature: F

              @slow
              Rule: R

                @wip
                Scenario: A
                  Given a
            """
        )
        code, after, _ = self.run_tool(before, "A")
        self.assertEqual(code, 0)
        self.assertIn("  @slow\n  Rule: R\n", after)
        self.assertNotIn("@wip", after)


class RefusesAndChangesNothing(Tool):
    def test_a_name_that_matches_no_scenario(self):
        before = "Feature: F\n\n  @wip\n  Scenario: A\n    Given a\n"
        self.assert_refused(before, "A", "Missing", reason="Missing")

    def test_a_name_that_matches_more_than_one_scenario(self):
        before = (
            "Feature: F\n\n  @wip\n  Scenario: A\n    Given a\n\n"
            "  @wip\n  Scenario: A\n    Given b\n"
        )
        self.assert_refused(before, "A", reason="more than one")

    def test_a_scenario_with_no_wip_tag(self):
        before = (
            "Feature: F\n\n  @wip\n  Scenario: A\n    Given a\n\n"
            "  @slow\n  Scenario: B\n    Given b\n"
        )
        self.assert_refused(before, "A", "B", reason="no @wip")

    def test_wip_on_the_feature(self):
        before = "@wip\nFeature: F\n\n  @wip\n  Scenario: A\n    Given a\n"
        self.assert_refused(before, "A", reason="Feature")

    def test_wip_on_the_rule_above_the_scenario(self):
        before = (
            "Feature: F\n\n  @wip\n  Rule: R\n\n    @wip\n    Scenario: A\n      Given a\n"
        )
        self.assert_refused(before, "A", reason="Rule")

    def test_a_file_that_is_not_utf8(self):
        before = "Feature: F\n\n  @wip\n  Scenario: Caf\u00e9\n    Given a\n".encode("latin-1")
        self.path.write_bytes(before)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = remove_wip.main([str(self.path), "--scenario", "A"])
        self.assertNotEqual(code, 0)
        self.assertIn("not UTF-8", err.getvalue())
        self.assertIn("nothing changed", err.getvalue())
        self.assertEqual(self.path.read_bytes(), before)

    def test_a_missing_file(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = remove_wip.main([str(self.path), "--scenario", "A"])
        self.assertNotEqual(code, 0)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
