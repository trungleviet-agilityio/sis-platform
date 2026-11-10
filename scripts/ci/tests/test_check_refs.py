"""Tests for scripts/ci/check_refs.py. Standard library only, Python 3.9 or later, temp repos only:

python3 -m unittest discover -s scripts/ci/tests
"""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# isort: split
import check_refs  # noqa: E402  (sys.path is set above)

SKILL = "plugins/sis-team/skills/demo/SKILL.md"


class RefsCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.write("CLAUDE.md", "# repo\n")

    def write(self, rel: str, text: str = "") -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def run_check(self) -> Tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = check_refs.main(["--root", str(self.root)])
        return rc, out.getvalue(), err.getvalue()

    def assert_clean(self) -> None:
        rc, out, err = self.run_check()
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("every reference resolves", out)

    def assert_broken(self, where: str, token: str) -> None:
        rc, _, err = self.run_check()
        self.assertEqual(rc, 1)
        self.assertIn(f"{where}: reference `{token}` does not resolve", err)


class Failures(RefsCase):
    def test_reports_file_and_line(self) -> None:
        self.write("CLAUDE.md", "# repo\n\nSee `docs/missing.md` for more.\n")
        self.assert_broken("CLAUDE.md:3", "docs/missing.md")

    def test_scans_rules_agents_and_skills(self) -> None:
        self.write(".claude/rules/ci.md", "`gone/rule.md`\n")
        self.write("plugins/sis-team/agents/a.md", "`gone/agent.md`\n")
        self.write(SKILL, "`gone/skill.md`\n")
        rc, _, err = self.run_check()
        self.assertEqual(rc, 1)
        self.assertIn(".claude/rules/ci.md:1: reference `gone/rule.md`", err)
        self.assertIn("plugins/sis-team/agents/a.md:1: reference `gone/agent.md`", err)
        self.assertIn(f"{SKILL}:1: reference `gone/skill.md`", err)

    def test_bare_file_name_must_resolve(self) -> None:
        self.write("CLAUDE.md", "`nothing.py`\n")
        self.assert_broken("CLAUDE.md:1", "nothing.py")

    def test_trailing_slash_needs_a_directory(self) -> None:
        self.write("afile")
        self.write("CLAUDE.md", "`afile/`\n")
        self.assert_broken("CLAUDE.md:1", "afile/")

    def test_escape_from_the_repo_does_not_resolve(self) -> None:
        self.write("CLAUDE.md", f"`../{self.root.name}x/file.md`\n")
        (self.root.parent / f"{self.root.name}x").mkdir()
        self.addCleanup(shutil.rmtree, self.root.parent / f"{self.root.name}x", True)
        (self.root.parent / f"{self.root.name}x" / "file.md").write_text("", encoding="utf-8")
        self.assert_broken("CLAUDE.md:1", f"../{self.root.name}x/file.md")

    def test_empty_root_is_a_usage_error(self) -> None:
        (self.root / "CLAUDE.md").unlink()
        rc, _, err = self.run_check()
        self.assertEqual(rc, 2)
        self.assertIn("nothing to scan", err)


class Resolution(RefsCase):
    def test_every_base(self) -> None:
        self.write("at/root.md")
        self.write(".claude/rules/sibling.md")
        self.write("plugins/sis-team/skills/demo/references/deep.md")
        self.write("plugins/sis-team/hooks/hook.md")
        self.write("intake/tests/case.py")
        self.write("scripts/tf/policy.py")
        self.write(".claude/rules/ci.md", "`at/root.md` `sibling.md`\n")
        self.write(SKILL, "`references/deep.md` `hooks/hook.md` `tests/case.py` `policy.py`\n")
        self.assert_clean()

    def test_skill_directory_for_a_nested_skill_file(self) -> None:
        self.write("plugins/sis-team/skills/demo/references/deep.md")
        self.write("plugins/sis-team/skills/demo/sub/SKILL.md", "`references/deep.md`\n")
        self.assert_clean()

    def test_directory_with_trailing_slash(self) -> None:
        self.write("docs/adr/x.md")
        self.write("CLAUDE.md", "`docs/adr/`\n")
        self.assert_clean()


class NotPaths(RefsCase):
    def test_skipped_tokens(self) -> None:
        tokens = [
            "docs/adr/*.md",
            "modules/**",
            "docs/adr/NNNN-<slug>.md",
            "<topic>.png",
            "python3 scripts/gone.py",
            "https://example.com/a/b.md",
            "/bin/bash",
            "/sis-team:review",
            "--flag/value",
            "sis-team:e2e",
            "iam:PassRole",
            "sts.amazonaws.com",
            "v0.2.0",
            ".env",
            "make",
            "$ARGUMENTS",
        ]
        self.write("CLAUDE.md", "".join(f"`{token}`\n" for token in tokens))
        self.assert_clean()

    def test_fenced_blocks_are_skipped(self) -> None:
        self.write(
            "CLAUDE.md",
            "```bash\n`gone/one.md`\n```\n~~~\n`gone/two.md`\n~~~\n"
            "````\n```\n`gone/three.md`\n````\n",
        )
        self.assert_clean()

    def test_text_after_a_closed_fence_is_scanned(self) -> None:
        self.write("CLAUDE.md", "```\ncode\n```\n`gone/after.md`\n")
        self.assert_broken("CLAUDE.md:4", "gone/after.md")

    def test_worktrees_are_ignored(self) -> None:
        self.write(".claude/worktrees/w/CLAUDE.md", "`gone/in-worktree.md`\n")
        self.write(".claude/worktrees/w/.claude/rules/r.md", "`gone/in-worktree.md`\n")
        self.write("CLAUDE.md", "`.claude/worktrees/w/nope.md`\n")
        self.assert_clean()


class Allowlist(RefsCase):
    def test_allowlisted_token_passes_and_near_miss_fails(self) -> None:
        self.write("CLAUDE.md", "`CLAUDE.local.md`\n`CLAUDE.locals.md`\n")
        rc, _, err = self.run_check()
        self.assertEqual(rc, 1)
        self.assertNotIn("`CLAUDE.local.md`", err)
        self.assertIn("CLAUDE.md:2: reference `CLAUDE.locals.md`", err)

    def test_every_entry_has_a_reason(self) -> None:
        for token, reason in check_refs.ALLOWLIST.items():
            self.assertTrue(reason.strip(), token)


if __name__ == "__main__":
    unittest.main()
