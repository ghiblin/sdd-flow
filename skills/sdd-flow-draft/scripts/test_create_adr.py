"""Stdlib tests for create-adr.py; everything happens on a temp-dir filesystem, no network.

Run: python3 -m unittest discover -s skills/sdd-flow-draft/scripts -v
"""
import contextlib
import importlib.util
import io
import pathlib
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location(
    "create_adr", pathlib.Path(__file__).with_name("create-adr.py")
)
create_adr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(create_adr)


class CreateAdr(unittest.TestCase):
    def test_first_adr_in_a_repo_is_numbered_001(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_adr.create_adr(
                title="Use a router for dispatch",
                context="We need to pick between a DAG and a router.",
                decision="Use a router — simpler to reason about.",
                consequences="New handlers register with the router, not the DAG.",
                repo=tmp,
            )
        self.assertEqual(path.name, "ADR-001-use-a-router-for-dispatch.md")

    def test_adr_content_matches_the_template_with_the_given_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_adr.create_adr(
                title="Use a router",
                context="Context text.",
                decision="Decision text.",
                consequences="Consequence text.",
                status="Proposed",
                repo=tmp,
            )
            text = path.read_text(encoding="utf-8")
        self.assertEqual(
            text,
            "# ADR-001: Use a router\n\n"
            "**Status:** Proposed\n\n"
            "## Context\nContext text.\n\n"
            "## Decision\nDecision text.\n\n"
            "## Consequences\nConsequence text.\n",
        )

    def test_a_second_adr_takes_the_next_number_regardless_of_existing_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = pathlib.Path(tmp) / "docs" / "adr"
            adr_dir.mkdir(parents=True)
            (adr_dir / "ADR-005-something-old.md").write_text("old", encoding="utf-8")
            path = create_adr.create_adr(
                title="Something new", context="c", decision="d", consequences="e", repo=tmp,
            )
        self.assertEqual(path.name, "ADR-006-something-new.md")

    def test_readme_is_created_with_header_and_the_new_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            create_adr.create_adr(
                title="Use a router", context="c", decision="d", consequences="e", repo=tmp,
            )
            readme = (pathlib.Path(tmp) / "docs" / "adr" / "README.md").read_text(encoding="utf-8")
        self.assertIn("# Architecture Decision Records", readme)
        self.assertIn("| [ADR-001](ADR-001-use-a-router.md) | Use a router | Accepted |", readme)

    def test_readme_row_is_appended_to_an_existing_readme_without_losing_prior_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = pathlib.Path(tmp) / "docs" / "adr"
            adr_dir.mkdir(parents=True)
            (adr_dir / "README.md").write_text(
                "# Architecture Decision Records\n\n"
                "| ADR | Title | Status |\n|-----|-------|--------|\n"
                "| [ADR-001](ADR-001-old.md) | Old decision | Accepted |\n",
                encoding="utf-8",
            )
            (adr_dir / "ADR-001-old.md").write_text("old", encoding="utf-8")
            create_adr.create_adr(
                title="New decision", context="c", decision="d", consequences="e", repo=tmp,
            )
            readme = (adr_dir / "README.md").read_text(encoding="utf-8")
        self.assertIn("Old decision", readme)
        self.assertIn("| [ADR-002](ADR-002-new-decision.md) | New decision | Accepted |", readme)

    def test_a_blank_field_is_refused_before_any_file_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                create_adr.create_adr(
                    title="  ", context="c", decision="d", consequences="e", repo=tmp,
                )
            self.assertFalse((pathlib.Path(tmp) / "docs").exists())

    def test_a_multi_line_title_is_refused_before_any_file_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                create_adr.create_adr(
                    title="Line one\nLine two", context="c", decision="d", consequences="e", repo=tmp,
                )
            self.assertFalse((pathlib.Path(tmp) / "docs").exists())

    def test_a_title_with_no_word_characters_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                create_adr.create_adr(
                    title="---", context="c", decision="d", consequences="e", repo=tmp,
                )

class Cli(unittest.TestCase):
    def test_main_prints_the_adr_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                create_adr.main(
                    [
                        "--title", "Use a router",
                        "--context", "c",
                        "--decision", "d",
                        "--consequences", "e",
                        "--repo", tmp,
                    ]
                )
            self.assertEqual(
                out.getvalue().strip(), f"{tmp}/docs/adr/ADR-001-use-a-router.md"
            )


if __name__ == "__main__":
    unittest.main()
