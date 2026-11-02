"""Stdlib tests for tier_classifier.py.

Run: python3 -m unittest discover -s . -p "test_tier_classifier.py" -v
"""
import contextlib
import importlib.util
import io
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "tier_classifier", pathlib.Path(__file__).with_name("tier_classifier.py")
)
tier_classifier = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tier_classifier)


class Classify(unittest.TestCase):
    def test_a_mechanical_file_split_with_a_green_gate_is_tier_0(self):
        # This is literally the diet-pal #491 incident's intent text.
        tier, rationale, question = tier_classifier.classify(
            "Split long files: chat.rs is over the file-length limit, extract its "
            "submodules with no behavior change.",
            build_gate_green_before=True,
        )
        self.assertEqual(tier, 0)
        self.assertIn("mechanical", rationale)
        self.assertIn("Tier 0", question)

    def test_a_rename_with_a_dirty_gate_before_is_not_automatically_tier_0(self):
        tier, _, _ = tier_classifier.classify(
            "Rename the PatientStorage trait to PatientRepository.",
            build_gate_green_before=False,
        )
        self.assertNotEqual(tier, 0)

    def test_a_known_narrow_bug_is_tier_1(self):
        tier, rationale, _ = tier_classifier.classify(
            "Fix the crash when a patient has no diet plan yet: the handler "
            "dereferences a None without checking."
        )
        self.assertEqual(tier, 1)
        self.assertIn("bugfix", rationale)

    def test_a_new_feature_is_tier_2(self):
        tier, rationale, _ = tier_classifier.classify(
            "Add a landing page that greets a logged-in user and links a guest to sign up."
        )
        self.assertEqual(tier, 2)
        self.assertIn("feature", rationale)

    def test_an_explicit_design_question_overrides_mechanical_wording_to_tier_2(self):
        tier, _, _ = tier_classifier.classify(
            "Refactor the storage layer — not sure yet whether to keep the trait "
            "boundary where it is or move it, need to decide the approach."
        )
        self.assertEqual(tier, 2)

    def test_a_refactor_that_also_claims_a_behavior_change_is_not_tier_0(self):
        tier, _, _ = tier_classifier.classify(
            "Refactor the chat loop and fix the bug where it drops the last message."
        )
        self.assertNotEqual(tier, 0)

    def test_the_question_always_lists_all_three_tiers(self):
        _, _, question = tier_classifier.classify("Bump the serde dependency to 1.0.200.")
        for marker in ("Tier 0", "Tier 1", "Tier 2"):
            self.assertIn(marker, question)


class Cli(unittest.TestCase):
    def test_main_prints_tier_and_rationale(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = tier_classifier.main(["Split chat.rs into submodules, no behavior change."])
        self.assertEqual(code, 0)
        self.assertIn("tier: 0", out.getvalue())
        self.assertIn("rationale:", out.getvalue())


if __name__ == "__main__":
    unittest.main()
