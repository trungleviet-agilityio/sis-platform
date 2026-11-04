"""Tests for the workflow closure (ADR 0002, L2, AA4, H6): scripts/platform/closure.py and
scripts/release/closure.txt. Standard library only, Python 3.9 or later:

    python3 -m unittest discover -s scripts/release/tests
"""

from __future__ import annotations

import json
import shutil
import subprocess  # noqa: S404  (the guard and the validator are run as a workflow would)
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Set

import helpers
from helpers import REPO_ROOT, Repo

# isort: split
import closure  # noqa: E402  (sys.path is set by helpers)


class ClosureComputation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = Repo(self.tmp / "platform")
        self.first = self.repo.seed()
        self.specs = closure.parse_specs(helpers.CLOSURE)

    def sha(self) -> str:
        return closure.workflow_sha(str(self.repo.path), "HEAD", self.specs)

    def test_comments_and_blank_lines_are_not_pathspecs(self) -> None:
        self.assertEqual(closure.parse_specs("# c\n\n  :(glob)a/**  \n"), [":(glob)a/**"])

    def test_workflow_sha_is_the_last_commit_that_touched_the_closure(self) -> None:
        self.assertEqual(self.sha(), self.first)

    def test_a_file_outside_the_closure_does_not_move_it(self) -> None:
        self.repo.write("docs/readme.md", "changed\n")
        self.repo.write("scripts/tf/test_policy.py", "# changed test\n")  # AA4: tests stay out
        self.repo.commit("docs and tests")
        self.assertEqual(self.sha(), self.first)

    def test_a_glob_covered_file_moves_it(self) -> None:
        self.repo.write("scripts/platform/tool.py", "print('changed')\n")
        moved = self.repo.commit("tool")
        self.assertEqual(self.sha(), moved)

    def test_exact_runtime_file_moves_it(self) -> None:
        self.repo.write("scripts/tf/policy.py", "# policy v2\n")
        self.assertEqual(self.repo.commit("policy"), self.sha())

    def test_glob_star_does_not_cross_directories_for_workflows(self) -> None:
        self.repo.write(".github/workflows/ci.yml", "name: ci\n")  # not reusable-*
        self.repo.commit("ci")
        self.assertEqual(self.sha(), self.first)
        self.repo.write(".github/workflows/reusable-new.yml", "name: new\n")
        self.assertEqual(self.repo.commit("reusable"), self.sha())

    def test_a_file_sourced_by_a_closure_script_is_in_the_closure(self) -> None:
        self.repo.write("scripts/platform/run.sh", 'source "$(dirname "$0")/../aws/helper.sh"\n')
        self.repo.commit("run.sh")
        self.repo.write("scripts/aws/helper.sh", "# helper v2\n")
        self.assertEqual(self.repo.commit("helper"), self.sha())

    def test_a_rename_moves_it_and_lists_both_paths(self) -> None:
        before = self.repo.head()
        self.repo.move("scripts/platform/tool.py", "scripts/platform/renamed.py")
        moved = self.repo.commit("rename")
        self.assertEqual(self.sha(), moved)
        changed = closure.changed_paths(str(self.repo.path), before, "HEAD", self.specs)
        self.assertEqual(changed, ["scripts/platform/renamed.py", "scripts/platform/tool.py"])

    def test_a_rename_out_of_the_closure_still_moves_it(self) -> None:
        self.repo.move("scripts/platform/tool.py", "docs/tool.py")
        self.assertEqual(self.repo.commit("move out"), self.sha())

    def test_no_matching_commit_is_an_error(self) -> None:
        with self.assertRaises(closure.ClosureError) as ctx:
            closure.workflow_sha(str(self.repo.path), "HEAD", [":(glob)nothing/**"])
        self.assertIn("no commit touches the closure pathspecs", str(ctx.exception))

    def test_unknown_ref_is_an_error(self) -> None:
        with self.assertRaises(closure.ClosureError) as ctx:
            closure.workflow_sha(str(self.repo.path), "v9.9.9", self.specs)
        self.assertIn("git log failed", str(ctx.exception))


class RealClosureFile(unittest.TestCase):
    """scripts/release/closure.txt of this repository."""

    def setUp(self) -> None:
        path = REPO_ROOT / "scripts" / "release" / "closure.txt"
        self.specs = closure.parse_specs(path.read_text(encoding="utf-8"))

    def covered(self) -> Set[str]:
        return closure.tracked_files(str(REPO_ROOT), self.specs)

    def test_every_pathspec_is_a_glob_pathspec(self) -> None:
        for spec in self.specs:
            self.assertTrue(spec.startswith(":(glob)"), spec)

    def test_closure_lists_itself(self) -> None:
        self.assertIn("scripts/release/closure.txt", self.covered())

    def test_aa4_exact_tf_runtime_files_only(self) -> None:
        covered = self.covered()
        for runtime in ("policy.py", "check.sh", "resolved-sources.sh"):
            self.assertIn(f"scripts/tf/{runtime}", covered)
        self.assertNotIn("scripts/tf/test_policy.py", covered)
        self.assertNotIn("scripts/tf/resolved-sources-selftest.sh", covered)
        self.assertFalse([p for p in self.specs if p.endswith("scripts/tf/**")])

    def test_runtime_scripts_and_validator_are_covered(self) -> None:
        covered = self.covered()
        for path in (
            "scripts/lib.sh",
            "scripts/platform/check_lock.py",
            "scripts/platform/closure.py",
            "intake/sis_intake/validate.py",
            "intake/schema/platform.schema.json",
            "intake/rules/rules.json",
            "intake/rules/compat.json",
            "intake/rules/defaults.json",
        ):
            self.assertIn(path, covered)

    def test_tests_docs_and_the_rule_table_are_outside(self) -> None:
        covered = self.covered()
        for path in (
            "README.md",
            "intake/README.md",
            "intake/tests/helpers.py",
            "intake/rules/questions.json",
            "scripts/release/check_release.py",
            "scripts/release/tests/test_closure.py",
            "scripts/ci/check_repo.py",
        ):
            self.assertNotIn(path, covered)

    def test_adapters_join_from_phase_2_not_before(self) -> None:
        # K: adapters/** joins in Phase 2 with the first adapter. Until then adapters/
        # holds only the contract and schemas, which no workflow runs.
        self.assertFalse([p for p in self.specs if "adapters" in p])

    def test_every_pathspec_matches_a_tracked_file_unless_it_is_a_future_path(self) -> None:
        future = {":(glob)scripts/aws/**", ":(glob).github/workflows/reusable-*.yml"}
        for spec in self.specs:
            if spec not in future:
                self.assertTrue(closure.tracked_files(str(REPO_ROOT), [spec]), spec)

    def test_validator_runs_from_the_closure_files_alone(self) -> None:
        """Copy only the closure into a clean directory and validate the example with it."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        for rel in self.covered():
            target = tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / rel, target)
        manifest = REPO_ROOT / "examples" / "consumer" / "platform.yaml"
        validate = tmp / "intake" / "sis_intake" / "validate.py"
        cmd = [sys.executable, "-I", str(validate), str(manifest)]
        done = subprocess.run(cmd, capture_output=True, check=False)  # noqa: S603
        self.assertEqual(done.returncode, 0, done.stderr.decode() + done.stdout.decode())
        emit = [*cmd, "--emit", "tfvars", "--env", "dev"]
        done = subprocess.run(emit, capture_output=True, check=False)  # noqa: S603
        self.assertEqual(done.returncode, 0, done.stderr.decode())
        self.assertIn("platform", json.loads(done.stdout.decode()))

    def test_guard_accepts_the_repository(self) -> None:
        guard = REPO_ROOT / "scripts" / "ci" / "check_repo.py"
        cmd = [sys.executable, str(guard), "repo", str(REPO_ROOT)]
        done = subprocess.run(cmd, capture_output=True, check=False)  # noqa: S603
        self.assertEqual(done.returncode, 0, done.stderr.decode())


if __name__ == "__main__":
    unittest.main()
