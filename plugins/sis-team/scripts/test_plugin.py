"""Structure tests of the sis-team plugin and the sis-platform marketplace (ADR 0002 S4, S6, L4).

Stdlib only, Python 3.9 compatible.

Run: python3 -m unittest discover -s plugins/sis-team/scripts -p 'test_*.py'
"""

from __future__ import annotations

import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(PLUGIN))
MARKETPLACE = os.path.join(ROOT, ".claude-plugin", "marketplace.json")

# Skills that spawn agents, write files or open PRs. The model must not start them on its own.
SIDE_EFFECT_SKILLS = {"plan", "run", "close", "board-sync"}
EXPECTED_SKILLS = {"plan", "run", "close", "review", "team", "diagram", "board", "board-sync"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def load_json(path: str) -> dict[str, object]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert isinstance(data, dict)
    return data


def frontmatter(path: str) -> dict[str, str]:
    """The top-level `key: value` lines of a markdown file's frontmatter block."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise AssertionError(f"{path}: no frontmatter block")
    out: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and re.match(r"^[a-z][a-z-]*$", key):
            out[key] = value.strip()
    return out


def plugin_files() -> list[str]:
    found = []
    for base in (PLUGIN, os.path.join(ROOT, ".claude-plugin")):
        for dirpath, _dirs, files in os.walk(base):
            found.extend(os.path.join(dirpath, f) for f in files if not f.endswith(".pyc"))
    return found


class Marketplace(unittest.TestCase):
    def test_two_relative_entries(self) -> None:
        data = load_json(MARKETPLACE)
        self.assertEqual(data["name"], "sis-platform")
        plugins = data["plugins"]
        assert isinstance(plugins, list)
        sources = {p["name"]: p["source"] for p in plugins}
        self.assertEqual(sources, {"sis-intake": "./intake", "sis-team": "./plugins/sis-team"})
        self.assertEqual(len(plugins), 2)

    def test_each_entry_points_at_a_plugin_of_the_same_name(self) -> None:
        data = load_json(MARKETPLACE)
        plugins = data["plugins"]
        assert isinstance(plugins, list)
        for entry in plugins:
            with self.subTest(plugin=entry["name"]):
                self.assertTrue(entry["source"].startswith("./"))
                self.assertNotIn("..", entry["source"])
                manifest = os.path.join(ROOT, entry["source"], ".claude-plugin", "plugin.json")
                self.assertEqual(load_json(manifest)["name"], entry["name"])
                self.assertTrue(entry.get("description"))


class Manifest(unittest.TestCase):
    def test_plugin_json(self) -> None:
        data = load_json(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"))
        self.assertEqual(data["name"], "sis-team")
        self.assertEqual(data["repository"], "https://github.com/trungleviet-agilityio/sis-platform")
        self.assertRegex(str(data["version"]), r"^\d+\.\d+\.\d+$")

    def test_hook_covers_read_and_write_tools(self) -> None:
        data = load_json(os.path.join(PLUGIN, "hooks", "hooks.json"))
        hooks = data["hooks"]
        assert isinstance(hooks, dict)
        entries = hooks["PreToolUse"]
        self.assertEqual(len(entries), 1)
        matched = set(entries[0]["matcher"].split("|"))
        self.assertTrue({"Bash", "Read", "Grep"} | WRITE_TOOLS <= matched, matched)
        command = entries[0]["hooks"][0]["command"]
        self.assertIn("scripts/guard.py", command)
        self.assertTrue(os.path.isfile(os.path.join(PLUGIN, "scripts", "guard.py")))


class Skills(unittest.TestCase):
    def skill_dirs(self) -> list[str]:
        base = os.path.join(PLUGIN, "skills")
        return sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))

    def test_expected_skills_exist(self) -> None:
        self.assertEqual(set(self.skill_dirs()), EXPECTED_SKILLS)

    def test_frontmatter(self) -> None:
        for name in self.skill_dirs():
            with self.subTest(skill=name):
                fm = frontmatter(os.path.join(PLUGIN, "skills", name, "SKILL.md"))
                self.assertEqual(fm.get("name"), name)
                self.assertGreater(len(fm.get("description", "")), 20)

    def test_side_effect_skills_are_user_invoked_only(self) -> None:
        for name in sorted(SIDE_EFFECT_SKILLS):
            with self.subTest(skill=name):
                fm = frontmatter(os.path.join(PLUGIN, "skills", name, "SKILL.md"))
                self.assertEqual(fm.get("disable-model-invocation"), "true")

    def test_read_only_board_status_is_model_invocable(self) -> None:
        fm = frontmatter(os.path.join(PLUGIN, "skills", "board", "SKILL.md"))
        self.assertNotIn("disable-model-invocation", fm)


class Agents(unittest.TestCase):
    def test_frontmatter(self) -> None:
        base = os.path.join(PLUGIN, "agents")
        for fname in sorted(os.listdir(base)):
            with self.subTest(agent=fname):
                fm = frontmatter(os.path.join(base, fname))
                self.assertEqual(fm.get("name"), fname[: -len(".md")])
                self.assertTrue(fm.get("description"))


class Hygiene(unittest.TestCase):
    def test_no_lab_text(self) -> None:
        for path in plugin_files():
            if os.path.basename(path) == "test_plugin.py":
                continue  # this file names the phrase it forbids
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            with self.subTest(file=os.path.relpath(path, ROOT)):
                self.assertNotRegex(text, r"(?i)ship-it-safely lab")
                self.assertNotRegex(text, r"(?i)\bthe lab\b")

    def test_no_dashes(self) -> None:
        for path in plugin_files():
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            with self.subTest(file=os.path.relpath(path, ROOT)):
                self.assertNotIn(chr(0x2014), text)
                self.assertNotIn(chr(0x2013), text)

    def test_borrowed_ideas_are_credited(self) -> None:
        for rel in ("scripts/guard.py", "agents/security-reviewer.md"):
            with open(os.path.join(PLUGIN, rel), encoding="utf-8") as fh:
                text = fh.read()
            with self.subTest(file=rel):
                self.assertIn("github.com/EricTechPro/super-board", text)
                self.assertIn("MIT", text)


if __name__ == "__main__":
    unittest.main()
