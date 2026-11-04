"""Tests for the adapter contract schemas (K1 to K8). Stdlib only, Python 3.9 compatible.

Run: python3 -m unittest discover -s adapters/tests   (from the repo root)

The schemas must stay inside the keyword subset that intake/sis_intake/schema.py interprets (Z4), so one
interpreter validates the manifest, the adapter declaration and every result line. No adapter exists in
Phase 1; these tests pin the contract that Phase 2 adapters and the conformance suite (K7) are built against.
"""

import copy
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ADAPTERS = os.path.dirname(HERE)
ROOT = os.path.dirname(ADAPTERS)
sys.path.insert(0, os.path.join(ROOT, "intake"))

from sis_intake import schema as z4  # noqa: E402

JSON_TYPES = {"string", "integer", "number", "boolean", "array", "object", "null"}
ALLOWED_SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"

# K4: exit code -> states a result line may carry with it. Cross-field rules are outside the Z4 subset, so
# they live here and in CONTRACT.md, and the conformance suite (K7) repeats them.
EXIT_STATES = {
    0: {"succeeded"},
    1: {"failed", "rolled_back"},
    2: {"failed"},
    3: {"publishing", "verifying", "shifting", "baking"},
}
STATES = ["publishing", "verifying", "shifting", "baking", "succeeded", "failed", "rolled_back"]
VERBS = ["deploy", "verify", "rollback", "status"]

DIGEST = "sha256:" + "ab12cd34ef56" * 5 + "ab12"
SHA = "0123456789abcdef0123456789abcdef01234567"


def load(name):
    with open(os.path.join(ADAPTERS, name), encoding="utf-8") as fh:
        return json.load(fh)


def manifest_schema():
    with open(os.path.join(ROOT, "intake", "schema", "platform.schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def metaschema_problems(schema):
    """Stdlib stand-in for the 2020-12 metaschema, limited to what the Z4 subset can express."""
    problems = list(z4.check_schema_keywords(schema))
    if schema.get("$schema") != ALLOWED_SCHEMA_URI:
        problems.append("/: $schema must be " + ALLOWED_SCHEMA_URI)
    for key in ("$id", "title", "description"):
        if not isinstance(schema.get(key), str) or not schema[key]:
            problems.append("/: %s must be a non-empty string" % key)
    _walk(schema, schema, "", problems)
    return problems


def _walk(node, root, path, problems):
    where = path or "/"
    if not isinstance(node, dict):
        problems.append("%s: schema must be an object" % where)
        return
    typ = node.get("type")
    if typ is not None and typ not in JSON_TYPES:
        problems.append("%s: bad type %r" % (where, typ))
    if "enum" in node and (not isinstance(node["enum"], list) or not node["enum"]):
        problems.append("%s: enum must be a non-empty array" % where)
    if "pattern" in node:
        try:
            re.compile(node["pattern"])
        except re.error as exc:
            problems.append("%s: pattern does not compile: %s" % (where, exc))
    props = node.get("properties", {})
    for name in node.get("required", []):
        if name not in props:
            problems.append("%s: required %r is not in properties" % (where, name))
    if "$ref" in node:
        try:
            z4._resolve(node["$ref"], root)
        except ValueError as exc:
            problems.append("%s: %s" % (where, exc))
    if typ == "object" and props and node.get("additionalProperties") is not False:
        problems.append("%s: object with properties must set additionalProperties false" % where)
    for name, sub in props.items():
        _walk(sub, root, path + "/properties/" + name, problems)
    for name, sub in node.get("$defs", {}).items():
        _walk(sub, root, path + "/$defs/" + name, problems)
    if isinstance(node.get("items"), dict):
        _walk(node["items"], root, path + "/items", problems)


def check_line(doc, verb_expected=None, exit_code=None):
    """Full result-line check: schema, K5 release_id, K4 exit code vs state. Returns a list of problems."""
    out = [i.message for i in z4.validate(doc, load("result.schema.json"))]
    if out:
        return out
    if doc["release_id"] != "%s-%s" % (doc["env"], doc["digest"][len("sha256:"):][:12]):
        out.append("release_id must be <env>-<first 12 hex of the digest> (K5)")
    if verb_expected and doc["verb"] != verb_expected:
        out.append("verb %r does not match the verb that ran (%r)" % (doc["verb"], verb_expected))
    if exit_code is not None and doc["state"] not in EXIT_STATES[exit_code]:
        out.append("state %r is not allowed with exit code %d (K4)" % (doc["state"], exit_code))
    pct = doc["traffic"]["candidate_percent"]
    if doc["state"] not in ("shifting", "baking") and pct not in (0, 100):
        out.append("candidate_percent is 0 or 100 outside shifting and baking")
    return out


def line(**over):
    base = {
        "contract_version": 1,
        "verb": "deploy",
        "env": "dev",
        "release_id": "dev-" + DIGEST[len("sha256:"):][:12],
        "digest": DIGEST,
        "sha": SHA,
        "live_ref": "",
        "candidate_ref": "7",
        "traffic": {"candidate_percent": 100},
        "state": "succeeded",
        "endpoint": "https://example.invalid",
        "message": "ok",
    }
    base.update(copy.deepcopy(over))
    return base


class MetaschemaTests(unittest.TestCase):
    def test_schemas_pass_metaschema_and_z4_subset(self):
        for name in ("adapter.schema.json", "result.schema.json"):
            with self.subTest(schema=name):
                self.assertEqual(metaschema_problems(load(name)), [])

    def test_metaschema_check_catches_unsupported_keyword(self):
        bad = load("result.schema.json")
        bad["properties"]["message"]["minLength"] = 1
        self.assertTrue(metaschema_problems(bad))
        bad = load("result.schema.json")
        bad["properties"]["state"] = {"oneOf": [{"type": "string"}]}
        self.assertTrue(metaschema_problems(bad))

    def test_contract_version_is_const_1_in_both(self):
        for name in ("adapter.schema.json", "result.schema.json"):
            self.assertEqual(load(name)["properties"]["contract_version"], {"const": 1})


class ResultStateTests(unittest.TestCase):
    def test_state_enum_is_k4(self):
        self.assertEqual(load("result.schema.json")["properties"]["state"]["enum"], STATES)

    def test_every_state_validates_with_its_exit_code(self):
        for code, states in EXIT_STATES.items():
            for state in sorted(states):
                pct = 25 if state in ("shifting", "baking") else 100
                if state in ("failed", "rolled_back"):
                    pct = 0
                with self.subTest(exit=code, state=state):
                    doc = line(state=state, traffic={"candidate_percent": pct})
                    self.assertEqual(check_line(doc, exit_code=code), [])

    def test_every_state_is_covered_by_some_exit_code(self):
        covered = set().union(*EXIT_STATES.values())
        self.assertEqual(covered, set(STATES))

    def test_state_with_wrong_exit_code_is_rejected(self):
        for code, states in EXIT_STATES.items():
            for state in STATES:
                if state in states:
                    continue
                with self.subTest(exit=code, state=state):
                    doc = line(state=state, traffic={"candidate_percent": 0})
                    self.assertTrue(check_line(doc, exit_code=code))

    def test_every_verb_validates(self):
        for verb in VERBS:
            with self.subTest(verb=verb):
                self.assertEqual(check_line(line(verb=verb), verb_expected=verb, exit_code=0), [])

    def test_in_progress_line_mid_shift(self):
        doc = line(state="shifting", traffic={"candidate_percent": 10})
        self.assertEqual(check_line(doc, exit_code=3), [])

    def test_refused_line_exit_2(self):
        doc = line(state="failed", traffic={"candidate_percent": 0}, message="policy refused")
        self.assertEqual(check_line(doc, exit_code=2), [])


class ResultInvalidTests(unittest.TestCase):
    def assertBad(self, **over):
        self.assertTrue(check_line(line(**over)), over)

    def test_missing_each_required_field(self):
        for key in load("result.schema.json")["required"]:
            bad = line()
            del bad[key]
            with self.subTest(missing=key):
                self.assertTrue(check_line(bad))

    def test_required_is_exactly_the_k3_fields(self):
        k3 = ["contract_version", "verb", "env", "release_id", "digest", "sha", "live_ref", "candidate_ref",
              "traffic", "state", "endpoint", "message"]
        self.assertEqual(sorted(load("result.schema.json")["required"]), sorted(k3))

    def test_bad_values(self):
        self.assertBad(contract_version=2)
        self.assertBad(contract_version="1")
        self.assertBad(verb="promote")
        self.assertBad(state="done")
        self.assertBad(state="Succeeded")
        self.assertBad(digest="sha256:abc")
        self.assertBad(digest="md5:" + "a" * 32)
        self.assertBad(sha="main")
        self.assertBad(sha="0123456789ABCDEF0123456789ABCDEF01234567")
        self.assertBad(env="Dev")
        self.assertBad(release_id="dev-123")
        self.assertBad(traffic={"candidate_percent": 101})
        self.assertBad(traffic={"candidate_percent": -1})
        self.assertBad(traffic={"candidate_percent": 50.5})
        self.assertBad(traffic={})
        self.assertBad(traffic={"candidate_percent": 100, "extra": 1})
        self.assertBad(message=None)
        self.assertBad(version="1")  # A2's old field is gone; unknown keys are refused

    def test_release_id_must_match_env_and_digest(self):
        self.assertBad(release_id="prod-" + DIGEST[len("sha256:"):][:12])
        self.assertBad(release_id="dev-" + "0" * 12)

    def test_verb_mismatch_is_rejected(self):
        self.assertTrue(check_line(line(verb="status"), verb_expected="deploy"))

    def test_progress_percent_outside_shift_is_rejected(self):
        doc = line(state="succeeded", traffic={"candidate_percent": 30})
        self.assertTrue(check_line(doc))

    def test_not_an_object(self):
        self.assertTrue(check_line([line()]))


def adapter(**over):
    base = {
        "contract_version": 1,
        "kind": "lambda-web",
        "strategies": ["all-at-once", "canary", "linear"],
        "engines": ["auto", "codedeploy"],
        "deploy_role_profile": "lambda-codedeploy",
        "egress_hosts": {
            "deploy": ["lambda.{region}.amazonaws.com", "ecr.{region}.amazonaws.com"],
            "verify": ["lambda.{region}.amazonaws.com"],
            "rollback": ["lambda.{region}.amazonaws.com"],
            "status": ["lambda.{region}.amazonaws.com"],
        },
        "max_step_seconds": 900,
    }
    base.update(copy.deepcopy(over))
    return base


def manifest_kinds():
    return manifest_schema()["properties"]["runtime"]["properties"]["kind"]["enum"]


def find_enum(node, key, must_contain):
    """First `properties.<key>.enum` that contains must_contain, anywhere in the manifest schema."""
    if isinstance(node, dict):
        props = node.get("properties", {})
        if key in props and all(m in props[key].get("enum", []) for m in must_contain):
            return props[key]["enum"]
        for value in node.values():
            found = find_enum(value, key, must_contain)
            if found:
                return found
    return None


class AdapterDeclarationTests(unittest.TestCase):
    def issues(self, doc):
        return z4.validate(doc, load("adapter.schema.json"))

    def test_valid_declaration(self):
        self.assertEqual(self.issues(adapter()), [])

    def test_valid_for_every_runtime_kind(self):
        kinds = manifest_kinds()
        self.assertTrue(kinds)
        for kind in kinds:
            with self.subTest(kind=kind):
                self.assertEqual(self.issues(adapter(kind=kind)), [])

    def test_kind_is_open_pattern_for_project_adapters(self):
        # P15 step 4: a project adapter may add a kind later, so kind is a pattern, not the manifest enum.
        self.assertIn("pattern", load("adapter.schema.json")["properties"]["kind"])
        self.assertEqual(self.issues(adapter(kind="project-batch")), [])

    def test_strategies_match_manifest_enum(self):
        enum = find_enum(manifest_schema(), "strategy", ["all-at-once", "canary"])
        self.assertEqual(load("adapter.schema.json")["properties"]["strategies"]["items"]["enum"], enum)

    def test_engines_match_manifest_enum(self):
        enum = find_enum(manifest_schema(), "engine", ["auto", "pipeline"])
        self.assertEqual(load("adapter.schema.json")["properties"]["engines"]["items"]["enum"], enum)

    def test_missing_required(self):
        for key in load("adapter.schema.json")["required"]:
            bad = adapter()
            del bad[key]
            with self.subTest(missing=key):
                self.assertTrue(self.issues(bad))

    def test_required_is_exactly_the_k6_fields(self):
        k6 = ["contract_version", "kind", "strategies", "engines", "deploy_role_profile", "egress_hosts",
              "max_step_seconds"]
        self.assertEqual(sorted(load("adapter.schema.json")["required"]), sorted(k6))

    def test_egress_needs_every_verb(self):
        for verb in VERBS:
            bad = adapter()
            del bad["egress_hosts"][verb]
            with self.subTest(missing=verb):
                self.assertTrue(self.issues(bad))

    def test_egress_templates_allow_only_region_placeholder(self):
        for host in ("lambda.{account}.amazonaws.com", "*.amazonaws.com", "https://lambda.amazonaws.com",
                     "lambda.{region.amazonaws.com", "Lambda.amazonaws.com", "host name"):
            with self.subTest(host=host):
                bad = adapter()
                bad["egress_hosts"]["deploy"] = [host]
                self.assertTrue(self.issues(bad))
        ok = adapter()
        ok["egress_hosts"]["deploy"] = ["s3.{region}.amazonaws.com", "sts.amazonaws.com"]
        self.assertEqual(self.issues(ok), [])

    def test_bad_values(self):
        for over in (
            {"contract_version": 2},
            {"kind": "Lambda"},
            {"strategies": []},
            {"strategies": ["big-bang"]},
            {"engines": []},
            {"engines": ["jenkins"]},
            {"max_step_seconds": 0},
            {"max_step_seconds": "900"},
            {"deploy_role_profile": "Bad Profile"},
            {"unknown_key": True},
        ):
            with self.subTest(over=over):
                self.assertTrue(self.issues(adapter(**over)))


class NoImplementationTests(unittest.TestCase):
    def test_phase_1_ships_no_adapter(self):
        for name in sorted(os.listdir(ADAPTERS)):
            self.assertNotIn(name, manifest_kinds())
            path = os.path.join(ADAPTERS, name)
            if os.path.isfile(path):
                self.assertFalse(os.access(path, os.X_OK), name + " must not be executable")

    def test_no_account_ids_or_dashes(self):
        pat = re.compile(r"(?<![0-9A-Za-z])(?!123456789012)[0-9]{12}(?![0-9A-Za-z])")
        for name in ("CONTRACT.md", "adapter.schema.json", "result.schema.json"):
            with open(os.path.join(ADAPTERS, name), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(pat.search(text), name)
            self.assertNotIn(chr(0x2014), text, name)
            self.assertNotIn(chr(0x2013), text, name)


class ContractDocTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ADAPTERS, "CONTRACT.md"), encoding="utf-8") as fh:
            self.doc = fh.read()

    def test_doc_names_every_input_state_verb_and_rule(self):
        tokens = ["SIS_CONTRACT_VERSION", "SIS_PLAN", "SIS_ENV", "SIS_DIGEST", "SIS_SHA", "SIS_RELEASE_ID",
                  "SIS_PREV_DIGEST", "adapter.json", "conformance", "major"] + STATES + VERBS
        for token in tokens:
            with self.subTest(token=token):
                self.assertIn(token, self.doc)

    def test_doc_exit_code_table(self):
        for row in ("| 0 |", "| 1 |", "| 2 |", "| 3 |"):
            self.assertIn(row, self.doc)


if __name__ == "__main__":
    unittest.main()
