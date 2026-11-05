"""Tests for the JSON Schema subset interpreter and the real platform schema."""

from __future__ import annotations

import json
import unittest
from typing import Any

from sis_intake import schema

from .helpers import INTAKE_DIR, base_manifest, copy_of


def paths(instance: Any, sch: dict[str, Any]) -> list[str]:
    return [i.path for i in schema.validate(instance, sch)]


class Keywords(unittest.TestCase):
    def test_type(self) -> None:
        cases = [
            ("string", "x", 1),
            ("integer", 3, "3"),
            ("integer", 3, True),
            ("number", 1.5, "1.5"),
            ("boolean", True, 1),
            ("array", [], {}),
            ("object", {}, []),
            ("null", None, 0),
        ]
        for typ, good, bad in cases:
            with self.subTest(type=typ):
                self.assertEqual(schema.validate(good, {"type": typ}), [])
                self.assertEqual(len(schema.validate(bad, {"type": typ})), 1)

    def test_enum(self) -> None:
        sch = {"enum": ["a", "b"]}
        self.assertEqual(schema.validate("a", sch), [])
        self.assertEqual(len(schema.validate("c", sch)), 1)

    def test_const(self) -> None:
        sch = {"const": 1}
        self.assertEqual(schema.validate(1, sch), [])
        self.assertEqual(len(schema.validate(2, sch)), 1)

    def test_const_and_enum_distinguish_bool_from_int(self) -> None:
        self.assertEqual(len(schema.validate(True, {"const": 1})), 1)
        self.assertEqual(len(schema.validate(1.0, {"const": True})), 1)
        self.assertEqual(len(schema.validate(True, {"enum": [0, 1]})), 1)
        self.assertEqual(schema.validate(1, {"enum": [0, 1]}), [])
        self.assertEqual(schema.validate(True, {"const": True}), [])

    def test_pattern_rejects_trailing_newline(self) -> None:
        sch = {"type": "string", "pattern": "^[a-z]+$"}
        self.assertEqual(schema.validate("abc", sch), [])
        self.assertEqual(len(schema.validate("abc\n", sch)), 1)

    def test_required(self) -> None:
        sch = {"type": "object", "required": ["a"]}
        self.assertEqual(schema.validate({"a": 1}, sch), [])
        self.assertEqual(len(schema.validate({}, sch)), 1)

    def test_properties_and_additional(self) -> None:
        sch = {
            "type": "object",
            "properties": {"a": {"type": "integer"}},
            "additionalProperties": False,
        }
        self.assertEqual(schema.validate({"a": 1}, sch), [])
        self.assertEqual(paths({"a": "x"}, sch), ["a"])
        self.assertEqual(paths({"a": 1, "b": 2}, sch), ["b"])

    def test_additional_properties_schema(self) -> None:
        sch = {"type": "object", "additionalProperties": {"type": "integer"}}
        self.assertEqual(schema.validate({"a": 1, "b": 2}, sch), [])
        self.assertEqual(paths({"a": 1, "b": "x"}, sch), ["b"])

    def test_items_and_min_items(self) -> None:
        sch = {"type": "array", "items": {"type": "integer"}, "minItems": 1}
        self.assertEqual(schema.validate([1, 2], sch), [])
        self.assertEqual(paths([1, "x"], sch), ["[1]"])
        self.assertEqual(len(schema.validate([], sch)), 1)

    def test_pattern(self) -> None:
        sch = {"type": "string", "pattern": "^a+$"}
        self.assertEqual(schema.validate("aaa", sch), [])
        self.assertEqual(len(schema.validate("b", sch)), 1)

    def test_minimum_maximum(self) -> None:
        sch = {"type": "integer", "minimum": 1, "maximum": 5}
        self.assertEqual(schema.validate(3, sch), [])
        self.assertEqual(len(schema.validate(0, sch)), 1)
        self.assertEqual(len(schema.validate(6, sch)), 1)

    def test_ref(self) -> None:
        sch = {"$defs": {"n": {"type": "integer"}}, "properties": {"a": {"$ref": "#/$defs/n"}}}
        self.assertEqual(schema.validate({"a": 1}, sch), [])
        self.assertEqual(paths({"a": "x"}, sch), ["a"])

    def test_ref_unsupported(self) -> None:
        with self.assertRaises(ValueError):
            schema.validate(1, {"$ref": "other.json#/x"})

    def test_nested_path(self) -> None:
        sch = {"properties": {"a": {"properties": {"b": {"items": {"type": "string"}}}}}}
        self.assertEqual(paths({"a": {"b": ["x", 1]}}, sch), ["a.b[1]"])


class SchemaFile(unittest.TestCase):
    def setUp(self) -> None:
        self.sch = json.loads((INTAKE_DIR / "schema" / "platform.schema.json").read_text("utf-8"))

    def test_only_supported_keywords(self) -> None:
        self.assertEqual(schema.check_schema_keywords(self.sch), [])

    def test_unknown_keyword_is_reported(self) -> None:
        bad = {"properties": {"a": {"type": "string", "format": "uri"}}}
        problems = schema.check_schema_keywords(bad)
        self.assertEqual(len(problems), 1)
        self.assertIn("format", problems[0])

    def test_property_named_like_keyword_is_not_flagged(self) -> None:
        ok = {"properties": {"format": {"type": "string"}}}
        self.assertEqual(schema.check_schema_keywords(ok), [])

    def test_identity(self) -> None:
        self.assertEqual(self.sch["$id"], "urn:sis-platform:platform:1")
        self.assertIn("2020-12", self.sch["$schema"])

    def test_base_manifest_is_valid(self) -> None:
        self.assertEqual(schema.validate(base_manifest(), self.sch), [])

    def test_unknown_key_rejected_everywhere(self) -> None:
        for where in ([], ["project"], ["envs", "dev"], ["runtime"]):
            with self.subTest(where=where):
                m = copy_of(base_manifest())
                target = m
                for key in where:
                    target = target[key]
                target["bogus"] = 1
                issues = schema.validate(m, self.sch)
                self.assertEqual(len(issues), 1)
                self.assertIn("bogus", issues[0].message)

    def test_enums_and_ranges(self) -> None:
        mutations = [
            ("runtime", "kind", "vm"),
            ("workload", "port", 0),
            ("workload", "port", 70000),
            ("ci", "provider", "jenkins"),
            ("budget", "monthly_usd", -1),
        ]
        for section, key, value in mutations:
            with self.subTest(key=key, value=value):
                m = copy_of(base_manifest())
                m[section][key] = value
                self.assertEqual(len(schema.validate(m, self.sch)), 1)

    def test_required_top_level(self) -> None:
        for key in ("schema_version", "project", "platform", "runtime", "envs"):
            with self.subTest(key=key):
                m = copy_of(base_manifest())
                del m[key]
                self.assertEqual(len(schema.validate(m, self.sch)), 1)

    def test_schema_version_must_be_one(self) -> None:
        m = copy_of(base_manifest())
        m["schema_version"] = 2
        self.assertEqual(len(schema.validate(m, self.sch)), 1)


if __name__ == "__main__":
    unittest.main()
