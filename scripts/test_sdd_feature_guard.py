"""Stdlib unit tests for the sdd_feature_guard PreToolUse hook.

Run: python3 -m unittest scripts.test_sdd_feature_guard -v
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HOOK = pathlib.Path(__file__).resolve().parent.parent / "hooks" / "scripts" / "sdd_feature_guard.py"

FEATURE = "app/tests/features/sample.feature"


def _load():
    spec = importlib.util.spec_from_file_location("sdd_feature_guard", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bash(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/nowhere"}


def tool(name, **tool_input):
    return {"tool_name": name, "tool_input": tool_input, "cwd": "/nowhere"}


def run_hook(data):
    """Run the hook as Claude Code does: JSON on stdin, decision on stdout."""
    result = subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(data), capture_output=True, text=True
    )
    return result.returncode, result.stdout


class FileTools(unittest.TestCase):
    def setUp(self):
        self.guard = _load()

    def test_given_edit_on_a_feature_file_when_checked_then_denied(self):
        data = tool("Edit", file_path=f"/repo/{FEATURE}", old_string="a", new_string="b")
        self.assertIsNotNone(self.guard.decide(data))

    def test_given_write_on_a_feature_file_when_checked_then_denied(self):
        self.assertIsNotNone(self.guard.decide(tool("Write", file_path=f"/repo/{FEATURE}", content="")))

    def test_given_notebook_edit_on_a_feature_path_when_checked_then_denied(self):
        self.assertIsNotNone(self.guard.decide(tool("NotebookEdit", notebook_path="/repo/x.feature")))

    def test_given_upper_case_extension_when_checked_then_denied(self):
        self.assertIsNotNone(self.guard.decide(tool("Write", file_path="/repo/X.FEATURE", content="")))

    def test_given_edit_on_a_rust_file_when_checked_then_allowed(self):
        data = tool("Edit", file_path="/repo/dietpal-core/src/lib.rs", old_string="a", new_string="b")
        self.assertIsNone(self.guard.decide(data))

    def test_given_write_on_a_feature_backup_when_checked_then_allowed(self):
        self.assertIsNone(self.guard.decide(tool("Write", file_path="/repo/x.feature.md", content="")))

    def test_given_read_of_a_feature_file_when_checked_then_allowed(self):
        self.assertIsNone(self.guard.decide(tool("Read", file_path=f"/repo/{FEATURE}")))


class BashWrites(unittest.TestCase):
    def setUp(self):
        self.guard = _load()

    def assertDenied(self, command):
        self.assertIsNotNone(self.guard.decide(bash(command)), command)

    def assertAllowed(self, command):
        self.assertIsNone(self.guard.decide(bash(command)), command)

    def test_given_redirect_into_a_feature_file_when_checked_then_denied(self):
        self.assertDenied(f"echo 'Feature: x' > {FEATURE}")

    def test_given_append_redirect_when_checked_then_denied(self):
        self.assertDenied(f"printf 'x' >> {FEATURE}")

    def test_given_glued_redirect_when_checked_then_denied(self):
        self.assertDenied(f"echo x >{FEATURE}")

    def test_given_heredoc_written_to_a_feature_file_when_checked_then_denied(self):
        self.assertDenied(f"cat > {FEATURE} <<'EOF'\nFeature: x\nEOF")

    def test_given_tee_when_checked_then_denied(self):
        self.assertDenied(f"echo x | tee -a {FEATURE}")

    def test_given_sed_in_place_when_checked_then_denied(self):
        self.assertDenied(f"sed -i '' 's/@wip//' {FEATURE}")

    def test_given_sed_in_place_with_suffix_when_checked_then_denied(self):
        self.assertDenied(f"sed -E -i.bak 's/a/b/' {FEATURE}")

    def test_given_perl_in_place_when_checked_then_denied(self):
        self.assertDenied(f"perl -pi -e 's/a/b/' {FEATURE}")

    def test_given_cp_onto_a_feature_file_when_checked_then_denied(self):
        self.assertDenied(f"cp /tmp/new.feature {FEATURE}")

    def test_given_mv_of_a_feature_file_when_checked_then_denied(self):
        self.assertDenied(f"mv {FEATURE} /tmp/old")

    def test_given_rm_of_feature_files_when_checked_then_denied(self):
        self.assertDenied("rm -f dietpal-core/tests/features/*.feature")

    def test_given_write_after_cd_when_checked_then_denied(self):
        self.assertDenied(f"cd /repo && echo x > {FEATURE}")

    def test_given_write_in_bash_c_when_checked_then_denied(self):
        self.assertDenied(f"bash -c 'echo x > {FEATURE}'")

    def test_given_write_in_substitution_when_checked_then_denied(self):
        self.assertDenied(f"x=$(sed -i '' 's/a/b/' {FEATURE})")

    def test_given_heredoc_fed_to_a_shell_when_checked_then_denied(self):
        self.assertDenied(f"bash <<'EOF'\nrm {FEATURE}\nEOF")

    def test_given_cat_of_a_feature_file_when_checked_then_allowed(self):
        self.assertAllowed(f"cat {FEATURE}")

    def test_given_grep_with_stderr_redirect_when_checked_then_allowed(self):
        self.assertAllowed(f"grep -n '@wip' {FEATURE} 2>/dev/null")

    def test_given_sed_print_without_in_place_when_checked_then_allowed(self):
        self.assertAllowed(f"sed -n '1,20p' {FEATURE}")

    def test_given_cp_from_a_feature_file_when_checked_then_allowed(self):
        self.assertAllowed(f"cp {FEATURE} /tmp/copy.txt")

    def test_given_remove_wip_helper_when_checked_then_allowed(self):
        cmd = f"python3 .claude/skills/sdd-tdd/scripts/remove-wip.py {FEATURE} --scenario 'Add a patient'"
        self.assertAllowed(cmd)

    def test_given_git_add_of_a_feature_file_when_checked_then_allowed(self):
        self.assertAllowed(f"git add {FEATURE} && git commit -m 'feat: x (#1)'")

    def test_given_rm_as_a_search_word_when_checked_then_allowed(self):
        self.assertAllowed(f"grep -n rm {FEATURE}")

    def test_given_write_to_another_file_when_checked_then_allowed(self):
        self.assertAllowed("echo x > notes.txt && rm -f /tmp/a.rs")

    def test_given_heredoc_body_that_names_a_write_when_checked_then_allowed(self):
        self.assertAllowed(f"cat <<'EOF'\nrm {FEATURE}\nEOF")


class WrappersAndMoreWrites(unittest.TestCase):
    """Wrapper commands, more write commands, and directories that hold feature files."""

    def setUp(self):
        self.guard = _load()
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name
        features = pathlib.Path(self.cwd, "tests", "features")
        features.mkdir(parents=True)
        (features / "a.feature").write_text("Feature: a\n", encoding="utf-8")
        pathlib.Path(self.cwd, "src").mkdir()
        (pathlib.Path(self.cwd, "src") / "lib.rs").write_text("", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def decide(self, command):
        return self.guard.decide({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": self.cwd})

    def test_given_a_write_behind_env_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide(f"env X=1 sed -i s/a/b/ {FEATURE}"))
        self.assertIsNotNone(self.decide(f"env -u HOME rm {FEATURE}"))

    def test_given_a_write_behind_sudo_or_nice_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide(f"sudo tee {FEATURE}"))
        self.assertIsNotNone(self.decide(f"sudo -u root rm {FEATURE}"))
        self.assertIsNotNone(self.decide(f"nice -n 5 truncate -s0 {FEATURE}"))

    def test_given_a_read_behind_env_when_checked_then_allowed(self):
        self.assertIsNone(self.decide(f"env LC_ALL=C grep -n @wip {FEATURE}"))

    def test_given_touch_truncate_ln_or_dd_on_a_feature_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide("touch new.feature"))
        self.assertIsNotNone(self.decide(f"truncate -s0 {FEATURE}"))
        self.assertIsNotNone(self.decide(f"ln -sf /dev/null {FEATURE}"))
        self.assertIsNotNone(self.decide(f"dd if=/dev/null of={FEATURE}"))

    def test_given_dd_that_reads_a_feature_when_checked_then_allowed(self):
        self.assertIsNone(self.decide(f"dd if={FEATURE} of=/dev/null"))

    def test_given_rm_r_of_a_directory_with_feature_files_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide("rm -rf tests/features"))
        self.assertIsNotNone(self.decide("rm -R tests"))
        self.assertIsNotNone(self.decide("rm -r tests/*"))

    def test_given_rm_r_of_a_directory_without_feature_files_when_checked_then_allowed(self):
        self.assertIsNone(self.decide("rm -rf src"))
        self.assertIsNone(self.decide("rm -rf missing-dir"))

    def test_given_a_glob_that_matches_a_feature_when_removed_then_denied(self):
        self.assertIsNotNone(self.decide("rm tests/features/*"))

    def test_given_mv_of_a_directory_with_feature_files_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide("mv tests/features old"))

    def test_given_cp_of_a_feature_into_a_directory_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide("cp other.feature tests/features/"))

    def test_given_cp_of_a_non_feature_into_a_feature_directory_when_checked_then_allowed(self):
        self.assertIsNone(self.decide("cp a.txt tests/features/"))

    def test_given_perl_module_or_include_flags_when_reading_then_allowed(self):
        self.assertIsNone(self.decide(f"perl -Mstrict -ne print {FEATURE}"))
        self.assertIsNone(self.decide(f"perl -Ilib -ne print {FEATURE}"))
        self.assertIsNone(self.decide(f"perl -e 'print 1' {FEATURE}"))

    def test_given_perl_in_place_clusters_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide(f"perl -i.bak -pe s/a/b/ {FEATURE}"))
        self.assertIsNotNone(self.decide(f"perl -lpi -e s/a/b/ {FEATURE}"))
        self.assertIsNotNone(self.decide(f"perl -0777 -pi -e s/a/b/ {FEATURE}"))

    def test_given_sed_with_an_expression_flag_when_reading_then_allowed(self):
        self.assertIsNone(self.decide(f"sed -n -e /wip/p {FEATURE}"))
        self.assertIsNotNone(self.decide(f"sed -Ei s/a/b/ {FEATURE}"))


class CdWrappersAndGitRepos(WrappersAndMoreWrites):
    """Round 2: `cd` moves the base of relative paths, more wrappers, `env -S`, `cp -r`, and git repos."""

    def test_given_cd_before_a_relative_rm_r_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide("cd tests && rm -rf features"))

    def test_given_cd_elsewhere_before_rm_r_when_checked_then_allowed(self):
        self.assertIsNone(self.decide("cd src && rm -rf build"))

    def test_given_timeout_stdbuf_command_or_exec_before_rm_when_checked_then_denied(self):
        for prefix in ("timeout 5", "timeout -s KILL 5", "stdbuf -o0", "stdbuf -o 0", "command -p", "exec -a x", "sudo -E", "nice -5"):
            with self.subTest(prefix=prefix):
                self.assertIsNotNone(self.decide(f"{prefix} rm {FEATURE}"))

    def test_given_env_split_string_with_a_write_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide(f"env -S 'rm {FEATURE}'"))
        self.assertIsNotNone(self.decide(f"env --split-string='rm {FEATURE}'"))

    def test_given_env_split_string_with_a_read_when_checked_then_allowed(self):
        self.assertIsNone(self.decide(f"env -S 'cat {FEATURE}'"))

    def test_given_cp_r_of_a_directory_with_feature_files_into_the_tree_when_checked_then_denied(self):
        pathlib.Path(self.cwd, "backup", "features").mkdir(parents=True)
        pathlib.Path(self.cwd, "backup", "features", "a.feature").write_text("", encoding="utf-8")
        self.assertIsNotNone(self.decide("cp -r backup/features tests/"))
        self.assertIsNotNone(self.decide("cp -a backup/features tests/"))

    def test_given_cp_r_of_feature_files_out_of_the_tree_when_checked_then_allowed(self):
        self.assertIsNone(self.decide("cp -r tests/features /tmp/feature-backup"))

    def test_given_a_git_repo_when_checked_then_ignored_directories_are_not_searched(self):
        subprocess.run(["git", "init", "-q", self.cwd], check=True)
        pathlib.Path(self.cwd, ".gitignore").write_text("target/\n", encoding="utf-8")
        pathlib.Path(self.cwd, "target", "x").mkdir(parents=True)
        pathlib.Path(self.cwd, "target", "x", "old.feature").write_text("", encoding="utf-8")
        self.assertIsNone(self.decide("rm -rf target"))
        self.assertIsNotNone(self.decide("rm -rf tests"))


class ShellContextAndFallbacks(unittest.TestCase):
    """Round 3: cd in subshells and pipelines, inner scripts per segment, env -S argv, mixed case, fallback walk."""

    def setUp(self):
        self.guard = _load()
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name
        features = pathlib.Path(self.cwd, "tests", "features")
        features.mkdir(parents=True)
        (features / "a.feature").write_text("Feature: a\n", encoding="utf-8")
        pathlib.Path(self.cwd, "docs").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def decide(self, command):
        return self.guard.decide({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": self.cwd})

    def test_given_a_cd_in_a_subshell_when_checked_then_the_next_path_keeps_the_start_directory(self):
        self.assertIsNotNone(self.decide("(cd docs) && rm -rf tests/features"))

    def test_given_a_cd_in_a_pipeline_when_checked_then_the_start_directory_is_still_checked(self):
        self.assertIsNotNone(self.decide("cd docs | true; rm -r tests"))

    def test_given_an_inner_script_before_a_cd_when_checked_then_it_runs_in_its_own_directory(self):
        self.assertIsNotNone(self.decide("bash -c 'rm -rf tests/features'; cd docs"))
        self.assertIsNotNone(self.decide("x=$(rm -rf tests/features); cd docs"))

    def test_given_env_split_string_with_more_arguments_when_checked_then_they_are_read(self):
        self.assertIsNotNone(self.decide(f"env -S 'rm -f' {FEATURE}"))

    def test_given_env_split_string_after_a_value_option_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide(f"env -u X -S 'rm {FEATURE}'"))
        self.assertIsNotNone(self.decide(f"env -C /tmp X=1 -S 'rm {FEATURE}'"))

    def test_given_a_mixed_case_feature_in_a_git_repo_when_its_directory_is_removed_then_denied(self):
        subprocess.run(["git", "init", "-q", self.cwd], check=True)
        pathlib.Path(self.cwd, "specs").mkdir()
        pathlib.Path(self.cwd, "specs", "Login.Feature").write_text("", encoding="utf-8")
        self.assertIsNotNone(self.decide("rm -r specs"))

    def test_given_cp_r_out_to_a_directory_outside_any_work_tree_when_checked_then_allowed(self):
        with tempfile.TemporaryDirectory() as outside:
            self.assertIsNone(self.decide(f"cp -r tests/features {outside}/backup"))

    def test_given_no_git_repo_when_walking_then_build_and_vcs_directories_are_skipped(self):
        for skipped in ("target", "node_modules", ".git"):
            with self.subTest(skipped=skipped):
                path = pathlib.Path(self.cwd, "out", skipped)
                path.mkdir(parents=True, exist_ok=True)
                (path / "x.feature").write_text("", encoding="utf-8")
                self.assertFalse(self.guard._walk_holds_feature(str(pathlib.Path(self.cwd, "out"))))

    def test_given_no_git_repo_when_the_walk_passes_the_limit_then_it_stops(self):
        # os.walk is top-down: the top directory (one file) is seen before its subdirectory
        big = pathlib.Path(self.cwd, "big")
        (big / "sub").mkdir(parents=True)
        (big / "top.txt").write_text("", encoding="utf-8")
        (big / "sub" / "late.feature").write_text("", encoding="utf-8")
        self.assertTrue(self.guard._walk_holds_feature(str(big)))
        old = self.guard.WALK_LIMIT
        self.guard.WALK_LIMIT = 0
        try:
            self.assertFalse(self.guard._walk_holds_feature(str(big)))
        finally:
            self.guard.WALK_LIMIT = old


class PipesHeredocsAndClusters(ShellContextAndFallbacks):
    """Round 4: a plain cd replaces the directory, a piped one adds a candidate; heredocs, pushd, env -iS."""

    def test_given_a_plain_cd_when_the_old_directory_holds_features_then_allowed(self):
        pathlib.Path(self.cwd, "src").mkdir()
        self.assertIsNone(self.decide("cd src && rm -rf tests"))

    def test_given_a_cd_in_a_subshell_when_only_its_target_holds_features_then_denied(self):
        # A cd in `( ... )` adds a candidate directory, so this over-denies on purpose.
        self.assertIsNotNone(self.decide("(cd tests) && rm -rf features"))

    def test_given_a_cd_in_the_background_when_only_its_target_holds_features_then_allowed(self):
        self.assertIsNone(self.decide("cd tests & rm -rf features"))

    def test_given_a_piped_cd_then_a_relative_cd_when_checked_then_every_candidate_is_moved(self):
        self.assertIsNotNone(self.decide("cd /tmp | true; cd tests; rm -r features"))

    def test_given_pushd_when_checked_then_it_moves_the_directory(self):
        self.assertIsNotNone(self.decide("pushd tests && rm -rf features"))

    def test_given_a_heredoc_script_after_a_cd_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide("cd tests && bash <<'EOF'\nrm -rf features\nEOF"))

    def test_given_env_split_string_in_a_short_cluster_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide(f"env -iS 'rm {FEATURE}'"))
        self.assertIsNotNone(self.decide(f"env -iS'rm {FEATURE}'"))

    def test_given_cp_r_into_another_git_worktree_when_checked_then_denied(self):
        with tempfile.TemporaryDirectory() as other:
            subprocess.run(["git", "init", "-q", other], check=True)
            self.assertIsNotNone(self.decide(f"cp -r tests/features {other}/copy"))


class ChdirTargetsAndReturns(ShellContextAndFallbacks):
    """Round 5: cd in a subshell, popd and cd -, env -C and sudo -D, and the -t target forms."""

    def test_given_a_cd_and_rm_in_one_subshell_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide("(cd tests && rm -r features)"))

    def test_given_mv_with_a_target_directory_option_when_the_source_holds_features_then_denied(self):
        self.assertIsNotNone(self.decide("mv -t ../elsewhere tests/features"))
        self.assertIsNotNone(self.decide("mv --target-directory ../elsewhere tests/features"))
        self.assertIsNotNone(self.decide("mv --target-directory=../x tests/features"))

    def test_given_mv_with_a_target_directory_option_when_the_source_holds_none_then_allowed(self):
        self.assertIsNone(self.decide("mv -t tests docs"))

    def test_given_popd_or_cd_dash_when_checked_then_the_earlier_directories_are_checked(self):
        self.assertIsNotNone(self.decide("pushd docs; popd; rm -r tests"))
        self.assertIsNotNone(self.decide("cd docs; cd -; rm -r tests"))

    def test_given_env_or_sudo_chdir_when_checked_then_the_command_runs_in_that_directory(self):
        for command in (
            "env -C tests rm -r features",
            "env --chdir tests rm -r features",
            "env --chdir=tests rm -r features",
            "sudo -D tests rm -r features",
            "sudo --chdir=tests rm -r features",
            "env -C tests -S 'rm -r features'",
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(self.decide(command))

    def test_given_env_chdir_elsewhere_when_checked_then_allowed(self):
        self.assertIsNone(self.decide("env -C docs rm -r features"))

    def test_given_cp_with_a_joined_target_directory_when_a_feature_is_copied_then_denied(self):
        self.assertIsNotNone(self.decide("cp --target-directory=tests/features x.feature"))


class ClustersStacksAndUnknownReturns(ShellContextAndFallbacks):
    """Round 6: option clusters, env -C heredocs, pushd -n and +N, and a return to an unknown directory."""

    def test_given_mv_with_t_in_a_cluster_or_with_an_attached_value_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide("mv -vt /tmp/x tests/features"))
        self.assertIsNotNone(self.decide("mv -t/tmp/x tests/features"))

    def test_given_mv_with_t_in_a_cluster_when_the_source_holds_none_then_allowed(self):
        self.assertIsNone(self.decide("mv -vt tests docs"))

    def test_given_cp_r_with_t_in_a_cluster_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide("cp -rt ./copy tests/features"))

    def test_given_env_chdir_in_a_cluster_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide("env -iC tests rm -r features"))
        self.assertIsNotNone(self.decide("env -iCtests rm -r features"))

    def test_given_a_wrapper_cluster_that_ends_in_a_value_letter_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide("sudo -nu root rm -r tests/features"))
        self.assertIsNotNone(self.decide("sudo -nD tests rm -r features"))

    def test_given_a_heredoc_fed_to_a_shell_behind_env_chdir_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide("env -C tests bash <<'X'\nrm -r features\nX"))

    def test_given_pushd_n_when_checked_then_the_directory_does_not_move(self):
        self.assertIsNotNone(self.decide("pushd -n docs; rm -r tests/features"))

    def test_given_a_stack_rotation_or_cd_dash_after_end_of_options_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide("pushd docs; pushd +1; rm -r tests/features"))
        self.assertIsNotNone(self.decide("cd docs; cd -- -; rm -r tests/features"))

    def test_given_a_return_before_any_move_when_a_write_follows_then_denied(self):
        for command in ("cd -; rm -r features", "popd; rm -r features", "pushd +1 && mv a b", "cd -; echo x > notes.txt"):
            with self.subTest(command=command):
                self.assertIsNotNone(self.decide(command))

    def test_given_a_return_before_any_move_when_only_reads_follow_then_allowed(self):
        for command in ("popd; ls", "cd -; cat x", "cd -; grep a b 2>/dev/null"):
            with self.subTest(command=command):
                self.assertIsNone(self.decide(command))


class RedirectsBsdEnvAndKnownAgain(ShellContextAndFallbacks):
    """Round 7: `>& file`, BSD env value options, an absolute cd after an unknown return, popd -n, the target rules."""

    def test_given_a_file_redirect_with_ampersand_after_an_unknown_return_when_checked_then_denied(self):
        self.assertIsNotNone(self.decide("cd -; echo x >& out.txt"))

    def test_given_an_fd_duplication_after_an_unknown_return_when_checked_then_allowed(self):
        self.assertIsNone(self.decide("cd -; ls 2>&1"))
        self.assertIsNone(self.decide("cd -; ls >&2"))
        self.assertIsNone(self.decide("cd -; ls >&3-"))
        self.assertIsNone(self.decide("cd -; ls >&-"))

    def test_given_bsd_env_value_options_when_checked_then_the_command_is_read(self):
        for command in (f"env -P /bin rm {FEATURE}", f"env -L root rm {FEATURE}", f"env -U root rm {FEATURE}"):
            with self.subTest(command=command):
                self.assertIsNotNone(self.decide(command))

    def test_given_any_cd_after_an_unknown_return_when_a_write_follows_then_denied(self):
        for command in (f"cd -; cd {self.cwd}/docs; touch x", "popd; pushd /tmp; popd; touch x",
                        "cd -; cd /tmp; cd -; touch x", "popd || cd /tmp; touch x", "cd -; (cd /tmp; touch x)"):
            with self.subTest(command=command):
                self.assertIsNotNone(self.decide(command))

    def test_given_a_relative_cd_after_an_unknown_return_when_a_write_follows_then_denied(self):
        self.assertIsNotNone(self.decide("cd -; cd docs; touch x"))

    def test_given_popd_n_when_checked_then_the_directory_does_not_move(self):
        # `popd -n` changes only the stack: the rm runs in docs, not back in the start directory.
        self.assertIsNone(self.decide("pushd docs; popd -n; rm -r tests"))
        self.assertIsNotNone(self.decide("pushd tests; popd -n; rm -r features"))

    def test_given_the_target_rules_when_checked_then_end_of_options_and_suffix_values_are_kept(self):
        # After `--`, `-t` is a file operand, not the target option.
        self.assertIsNotNone(self.decide("mv -- -t tests docs"))
        # `-S` takes the rest of its cluster as the suffix, so the `t` after it is no target option.
        self.assertIsNotNone(self.decide("mv -Stx tests docs"))

    def test_given_the_write_commands_after_an_unknown_return_when_checked_then_denied(self):
        for name in ("tee", "rm", "mv", "touch", "truncate", "cp", "ln", "dd", "rmdir", "mkdir", "install", "rsync"):
            with self.subTest(name=name):
                self.assertIsNotNone(self.decide(f"cd -; {name} x"))


class HookProtocol(unittest.TestCase):
    def test_given_a_denied_call_when_run_then_prints_a_deny_decision(self):
        code, out = run_hook(tool("Write", file_path=f"/repo/{FEATURE}", content=""))
        self.assertEqual(code, 0)
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(decision["hookEventName"], "PreToolUse")
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("remove-wip.py", decision["permissionDecisionReason"])
        self.assertIn("sdd-flow-spec-writer", decision["permissionDecisionReason"])

    def test_given_an_allowed_call_when_run_then_prints_nothing(self):
        code, out = run_hook(bash(f"cat {FEATURE}"))
        self.assertEqual((code, out), (0, ""))

    def test_given_invalid_json_when_run_then_prints_nothing(self):
        result = subprocess.run(
            [sys.executable, str(HOOK)], input="not json", capture_output=True, text=True
        )
        self.assertEqual((result.returncode, result.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
