"""Plugin metadata, agent frontmatter, and the no-dash rule for everything under intake/."""

from __future__ import annotations

import json
import re
import unittest

import sis_intake

from .helpers import INTAKE_DIR

DASHES = (chr(0x2014), chr(0x2013))


class PluginMetadata(unittest.TestCase):
    def setUp(self) -> None:
        path = INTAKE_DIR / ".claude-plugin" / "plugin.json"
        self.plugin = json.loads(path.read_text("utf-8"))

    def test_version_matches_the_package(self) -> None:
        self.assertEqual(sis_intake.__version__, "0.2.0")
        self.assertEqual(self.plugin["version"], sis_intake.__version__)

    def test_author(self) -> None:
        self.assertEqual(self.plugin["author"]["name"], "trungleviet-agilityio")

    def test_name(self) -> None:
        self.assertEqual(self.plugin["name"], "sis-intake")


class AgentFrontmatter(unittest.TestCase):
    def frontmatter(self) -> dict[str, str]:
        text = (INTAKE_DIR / "agents" / "intake-interviewer.md").read_text("utf-8")
        match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        self.assertIsNotNone(match)
        assert match is not None
        out: dict[str, str] = {}
        for line in match.group(1).splitlines():
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
        return out

    def test_agent_has_read_only_tools_and_no_bash(self) -> None:
        tools = [t.strip() for t in self.frontmatter()["tools"].split(",")]
        self.assertEqual(tools, ["Read", "Grep", "Glob"])

    def test_skill_documents_the_validation_loop(self) -> None:
        skill = (INTAKE_DIR / "skills" / "intake" / "SKILL.md").read_text("utf-8")
        self.assertIn('validate.py" -', skill)
        self.assertIn("stdin", skill)
        self.assertIn("intake-interviewer", skill)
        self.assertNotIn("temp-file", skill)
        self.assertNotIn("temporary file", skill)

    def test_agent_body_runs_no_command(self) -> None:
        body = (INTAKE_DIR / "agents" / "intake-interviewer.md").read_text("utf-8")
        self.assertNotIn("Bash", body.split("---", 2)[2])
        self.assertNotIn('validate.py" -', body)
        self.assertIn("findings", body)


class NoDashes(unittest.TestCase):
    def test_no_em_or_en_dashes(self) -> None:
        for path in sorted(INTAKE_DIR.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            text = path.read_text("utf-8")
            for dash in DASHES:
                self.assertNotIn(dash, text, str(path.relative_to(INTAKE_DIR)))


if __name__ == "__main__":
    unittest.main()
