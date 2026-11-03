"""Tests for the stdlib YAML subset loader."""

from __future__ import annotations

import importlib
import unittest
from typing import Any

from sis_intake.yamlsubset import YamlError, parse

from .helpers import EXAMPLES

yaml: Any
try:
    yaml = importlib.import_module("yaml")
except ImportError:  # pragma: no cover
    yaml = None


def error_line(text: str) -> int:
    try:
        parse(text)
    except YamlError as exc:
        return exc.line
    raise AssertionError(f"expected YamlError for {text!r}")


class ParseValid(unittest.TestCase):
    def test_scalars(self) -> None:
        doc = parse("a: 1\nb: true\nc: false\nd: null\ne: ~\nf:\ng: hello world\nh: v0.1.0\n")
        self.assertEqual(
            doc,
            {
                "a": 1,
                "b": True,
                "c": False,
                "d": None,
                "e": None,
                "f": None,
                "g": "hello world",
                "h": "v0.1.0",
            },
        )

    def test_quoted(self) -> None:
        doc = parse("a: \"x: y # z\"\nb: 'it''s'\nc: \"tab\\there\"\nd: '123'\n")
        self.assertEqual(doc, {"a": "x: y # z", "b": "it's", "c": "tab\there", "d": "123"})

    def test_comments(self) -> None:
        doc = parse("# header\na: 1  # trailing\n\nb: 2\n")
        self.assertEqual(doc, {"a": 1, "b": 2})

    def test_nested_map_and_list(self) -> None:
        text = "a:\n  b:\n    c: 1\n  d:\n    - x\n    - z\n"
        self.assertEqual(parse(text), {"a": {"b": {"c": 1}, "d": ["x", "z"]}})

    def test_list_of_maps(self) -> None:
        text = "items:\n  - name: a\n    n: 1\n  - name: b\n"
        self.assertEqual(parse(text), {"items": [{"name": "a", "n": 1}, {"name": "b"}]})

    def test_flow(self) -> None:
        doc = parse("a: [1, 2, 3]\nb: {x: 1, y: two}\nc: []\nd: {}\ne: ['a, b', c]\n")
        self.assertEqual(
            doc, {"a": [1, 2, 3], "b": {"x": 1, "y": "two"}, "c": [], "d": {}, "e": ["a, b", "c"]}
        )

    def test_flow_map_with_list_value(self) -> None:
        doc = parse("r: {strategy: canary, steps: [10, 100], rollback: alarm}\n")
        self.assertEqual(
            doc, {"r": {"strategy": "canary", "steps": [10, 100], "rollback": "alarm"}}
        )

    def test_empty_document(self) -> None:
        self.assertIsNone(parse("# nothing\n"))

    def test_url_value(self) -> None:
        self.assertEqual(parse("u: https://example.com/x\n"), {"u": "https://example.com/x"})


class ParseRejects(unittest.TestCase):
    def test_anchor(self) -> None:
        self.assertEqual(error_line("a: 1\nb: &x 2\n"), 2)

    def test_alias(self) -> None:
        self.assertEqual(error_line("a: 1\nb: *x\n"), 2)

    def test_tag(self) -> None:
        self.assertEqual(error_line("a: !!str 1\n"), 1)

    def test_multi_document(self) -> None:
        self.assertEqual(error_line("a: 1\n---\nb: 2\n"), 2)

    def test_nested_flow_list(self) -> None:
        self.assertEqual(error_line("a: 1\nb: [[1], 2]\n"), 2)

    def test_nested_flow_map(self) -> None:
        self.assertEqual(error_line("a: {b: {c: 1}}\n"), 1)

    def test_flow_list_in_list(self) -> None:
        self.assertEqual(error_line("a: 1\nb: 2\nc: [1, [2]]\n"), 3)

    def test_flow_map_in_list(self) -> None:
        self.assertEqual(error_line("c: [{a: 1}]\n"), 1)

    def test_flow_double_list_in_map(self) -> None:
        self.assertEqual(error_line("c: {x: [[1]]}\n"), 1)

    def test_block_scalar(self) -> None:
        self.assertEqual(error_line("a: |\n  text\n"), 1)

    def test_multiline_plain(self) -> None:
        self.assertEqual(error_line("a: one\n  two\n"), 2)

    def test_tab_indent(self) -> None:
        self.assertEqual(error_line("a:\n\tb: 1\n"), 2)

    def test_duplicate_key(self) -> None:
        self.assertEqual(error_line("a: 1\nb: 2\na: 3\n"), 3)

    def test_unterminated_quote(self) -> None:
        self.assertEqual(error_line('a: "oops\n'), 1)

    def test_unknown_escape(self) -> None:
        self.assertEqual(error_line('a: "\\q"\n'), 1)

    def test_ambiguous_scalars(self) -> None:
        for bad in ("yes", "off", "1.5", "010", "2026-11-03", "0x1F", "10:30"):
            with self.subTest(bad=bad):
                self.assertEqual(error_line(f"a: {bad}\n"), 1)

    def test_bad_indent(self) -> None:
        self.assertEqual(error_line("a:\n    b: 1\n  c: 2\n"), 3)

    def test_nested_list_item(self) -> None:
        self.assertEqual(error_line("a:\n  - - 1\n"), 2)

    def test_missing_colon(self) -> None:
        self.assertEqual(error_line("a: 1\njust text\n"), 2)

    def test_error_message_has_line(self) -> None:
        with self.assertRaises(YamlError) as ctx:
            parse("a: 1\nb: &x 2\n")
        self.assertTrue(str(ctx.exception).startswith("line 2:"))


@unittest.skipIf(yaml is None, "PyYAML not installed: skipping the safe_load conformance test")
class Conformance(unittest.TestCase):
    def test_examples_match_safe_load(self) -> None:
        files = sorted((EXAMPLES / "valid").glob("*.yaml"))
        self.assertGreaterEqual(len(files), 3)
        for path in files:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                expected: Any = yaml.safe_load(text)
                self.assertEqual(parse(text), expected)

    def test_snippets_match_safe_load(self) -> None:
        snippets = [
            "a: 1\nb: [x, 'y z']\nc: {k: v}\n",
            "l:\n  - a: 1\n    b: 2\n  - c\n  - 'd: e'\n",
            "q: \"a\\nb\"\nr: 'it''s'\ns: ''\n",
            "t: true\nf: false\nn: null\nz: ~\ni: -5\n",
        ]
        for text in snippets:
            with self.subTest(text=text):
                self.assertEqual(parse(text), yaml.safe_load(text))


if __name__ == "__main__":
    unittest.main()
