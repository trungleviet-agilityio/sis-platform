"""Tests for scripts/release/check_release.py (ADR 0002, L4, L7). Standard library only,
Python 3.9 or later, local fixture git repos only:

    python3 -m unittest discover -s scripts/release/tests
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Tuple

import helpers
from helpers import Repo, run_main

# isort: split
import check_release  # noqa: E402  (sys.path is set by helpers)


class ReleaseCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = Repo(self.tmp / "platform")
        self.c1 = self.repo.seed("0.1.0")
        self.repo.tag("v0.1.0")

    def release(self, tag: str, *extra: str, sha: str = "HEAD") -> Tuple[int, str, str]:
        full = helpers.git(self.repo.path, "rev-parse", sha)
        return run_main(
            check_release, ["--repo", str(self.repo.path), "--tag", tag, "--sha", full, *extra]
        )

    def ship(self, version: str, change: str = "") -> str:
        """Commit a change (a path under the repo), bump every version, and return the commit."""
        if change:
            self.repo.write(change, f"change for {version}\n")
        self.repo.bump_versions(version)
        return self.repo.commit(f"release {version}")


class WorkflowShaMovement(ReleaseCase):
    def test_first_release_has_no_previous_tag(self) -> None:
        rc, out, err = self.release("v0.1.0", sha=self.c1)
        self.assertEqual((rc, err), (0, ""))
        self.assertIn(f"workflow_sha: {self.c1}", out)
        self.assertIn("previous tag: none (first release)", out)

    def test_patch_that_leaves_the_closure_alone_passes(self) -> None:
        self.ship("0.1.1", "docs/notes.md")
        rc, out, err = self.release("v0.1.1")
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("previous tag: v0.1.0", out)
        self.assertIn("workflow_sha moved: no", out)
        self.assertIn("closure paths changed: none", out)

    def test_patch_that_moves_the_closure_fails(self) -> None:
        self.ship("0.1.1", "scripts/platform/tool.py")
        rc, out, err = self.release("v0.1.1")
        self.assertEqual(rc, 1)
        self.assertIn("workflow_sha moved: yes", out)
        self.assertIn("  scripts/platform/tool.py", out)
        self.assertIn(
            "patch release v0.1.1 moves workflow_sha; a trust move needs a minor release (L7)", err
        )

    def test_a_patch_that_only_touches_tests_passes(self) -> None:
        self.ship("0.1.1", "scripts/tf/test_policy.py")  # AA4: tests are outside the closure
        rc, _out, err = self.release("v0.1.1")
        self.assertEqual((rc, err), (0, ""))

    def test_a_patch_that_touches_closure_txt_fails(self) -> None:
        self.repo.write("scripts/release/closure.txt", helpers.CLOSURE + ":(glob)extra/**\n")
        self.repo.bump_versions("0.1.1")
        self.repo.commit("closure")
        rc, out, err = self.release("v0.1.1")
        self.assertEqual(rc, 1)
        self.assertIn("  scripts/release/closure.txt", out)
        self.assertIn("moves workflow_sha", err)

    def test_minor_release_may_move_it(self) -> None:
        self.ship("0.2.0", "scripts/platform/tool.py")
        rc, out, err = self.release("v0.2.0")
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("workflow_sha moved: yes", out)

    def test_major_release_may_move_it(self) -> None:
        self.ship("1.0.0", "scripts/lib.sh")
        rc, _out, err = self.release("v1.0.0")
        self.assertEqual((rc, err), (0, ""))

    def test_a_rename_inside_the_closure_is_listed_with_both_paths(self) -> None:
        self.repo.move("scripts/platform/tool.py", "scripts/platform/renamed.py")
        self.repo.bump_versions("0.2.0")
        self.repo.commit("rename")
        rc, out, _err = self.release("v0.2.0")
        self.assertEqual(rc, 0)
        self.assertIn("  scripts/platform/renamed.py", out)
        self.assertIn("  scripts/platform/tool.py", out)

    def test_previous_tag_is_the_highest_lower_version(self) -> None:
        self.ship("0.1.1", "docs/a.md")
        self.repo.tag("v0.1.1")
        self.ship("0.1.10", "docs/b.md")
        self.repo.tag("v0.1.10")
        self.ship("0.1.2", "docs/c.md")
        rc, out, _err = self.release("v0.1.2")
        self.assertEqual(rc, 0)
        self.assertIn("previous tag: v0.1.1", out)

    def test_explicit_previous_ref(self) -> None:
        self.ship("0.2.0", "scripts/platform/tool.py")
        self.repo.tag("v0.2.0")
        self.ship("0.2.1", "docs/a.md")
        rc, out, err = self.release("v0.2.1", "--prev", "v0.1.0")
        self.assertEqual(rc, 1)
        self.assertIn("previous tag: v0.1.0", out)
        self.assertIn("moves workflow_sha", err)

    def test_previous_tag_without_a_closure_counts_as_moved(self) -> None:
        old = Repo(self.tmp / "older")
        old.write("README.md", "x\n")
        old.commit("init")
        old.tag("v0.0.9")
        old.seed("0.0.10")
        helpers.git(old.path, "tag", "v0.0.10")
        self.repo = old
        rc, out, err = self.release("v0.0.10")
        self.assertEqual(rc, 1)
        self.assertIn("previous tag v0.0.9 has no scripts/release/closure.txt", out)
        self.assertIn("moves workflow_sha", err)

    def test_unknown_previous_ref(self) -> None:
        rc, _out, err = self.release("v0.1.1", "--prev", "v9.9.9")
        self.assertEqual(rc, 2)
        self.assertIn("cannot resolve previous ref v9.9.9", err)


class VersionAgreement(ReleaseCase):
    def test_tag_shape(self) -> None:
        rc, _out, err = self.release("0.1.1")
        self.assertEqual(rc, 2)
        self.assertIn("tag must look like vX.Y.Z", err)

    def test_plugin_version_must_equal_the_tag(self) -> None:
        self.ship("0.1.1", "docs/a.md")
        self.repo.write(
            "plugins/sis-team/.claude-plugin/plugin.json", helpers.PLUGIN % ("sis-team", "0.1.0")
        )
        self.repo.commit("forgot sis-team")
        rc, _out, err = self.release("v0.1.1")
        self.assertEqual(rc, 1)
        self.assertIn(
            "plugin.json: version 0.1.0 does not match tag v0.1.1 (L4)",
            err,
        )

    def test_intake_version_constant_must_equal_the_tag(self) -> None:
        self.ship("0.1.1", "docs/a.md")
        self.repo.write("intake/sis_intake/__init__.py", helpers.INIT % "0.1.0")
        self.repo.commit("forgot __version__")
        rc, _out, err = self.release("v0.1.1")
        self.assertEqual(rc, 1)
        self.assertIn(
            "intake/sis_intake/__init__.py: __version__ 0.1.0 does not match tag v0.1.1 (L4)", err
        )

    def test_missing_version_constant(self) -> None:
        self.ship("0.1.1", "docs/a.md")
        self.repo.write("intake/sis_intake/__init__.py", '"""pkg."""\n')
        self.repo.commit("no constant")
        rc, _out, err = self.release("v0.1.1")
        self.assertEqual(rc, 1)
        self.assertIn("intake/sis_intake/__init__.py: no __version__ found", err)

    def test_plugin_json_without_a_version(self) -> None:
        self.ship("0.1.1", "docs/a.md")
        self.repo.write("plugins/sis-team/.claude-plugin/plugin.json", '{"name": "x"}\n')
        self.repo.commit("no version")
        rc, _out, err = self.release("v0.1.1")
        self.assertEqual(rc, 1)
        self.assertIn("plugins/sis-team/.claude-plugin/plugin.json: no version", err)

    def test_versions_are_read_from_the_commit_not_the_working_tree(self) -> None:
        self.ship("0.1.1", "docs/a.md")
        self.repo.write("intake/sis_intake/__init__.py", helpers.INIT % "9.9.9")  # uncommitted
        rc, _out, err = self.release("v0.1.1")
        self.assertEqual((rc, err), (0, ""))

    def test_no_plugin_json_at_all_is_an_error(self) -> None:
        bare = Repo(self.tmp / "bare")
        bare.write("scripts/release/closure.txt", helpers.CLOSURE)
        bare.commit("x")
        self.repo = bare
        rc, _out, err = self.release("v0.1.0")
        self.assertEqual(rc, 1)
        self.assertIn("no .claude-plugin/plugin.json found", err)


class Usage(ReleaseCase):
    def test_missing_arguments(self) -> None:
        rc, _out, err = run_main(check_release, ["--repo", str(self.repo.path)])
        self.assertEqual(rc, 2)
        self.assertIn("Usage:", err)

    def test_sha_that_is_not_a_commit(self) -> None:
        rc, _out, err = run_main(
            check_release, ["--repo", str(self.repo.path), "--tag", "v0.1.1", "--sha", "f" * 40]
        )
        self.assertEqual(rc, 2)
        self.assertIn("is not a commit", err)


if __name__ == "__main__":
    unittest.main()
