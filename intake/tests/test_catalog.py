"""Rule data and code stay in sync; README table matches rules.json."""

from __future__ import annotations

import json
import re
import unittest

from sis_intake import rules, ruletable

from .helpers import INTAKE_DIR

PILLARS = {"OPS", "SEC", "REL", "PERF", "COST", "SUS"}
WA_REF = re.compile(r"^[A-Z]{3,4}[0-9]{2}-BP[0-9]{2}$")


class Catalog(unittest.TestCase):
    def test_ids_match_predicates_one_to_one(self) -> None:
        ids = [r["id"] for r in rules.load_rules()["rules"]]
        self.assertEqual(ids, [f"V{n:02d}" for n in range(1, 26)])
        self.assertEqual(sorted(ids), sorted(rules.PREDICATES))

    def test_every_rule_has_metadata(self) -> None:
        for rule in rules.load_rules()["rules"]:
            with self.subTest(rule=rule["id"]):
                self.assertIn(rule["severity"], ("E", "W"))
                self.assertTrue(rule["rule"])
                self.assertGreaterEqual(len(rule["pillars"]), 1)
                self.assertTrue(set(rule["pillars"]) <= PILLARS)
                self.assertGreaterEqual(len(rule["wa_refs"]), 1)
                for ref in rule["wa_refs"]:
                    self.assertRegex(ref, WA_REF)

    def test_severities_follow_the_adr(self) -> None:
        warnings = {"V06", "V07", "V13", "V14", "V15", "V16", "V17", "V18"}
        self.assertEqual(
            {r["id"] for r in rules.load_rules()["rules"] if r["severity"] == "W"}, warnings
        )
        for rule in rules.load_rules()["rules"]:
            want = "W" if rule["id"] in warnings else "E"
            self.assertEqual(rule["severity"], want, rule["id"])

    def test_questions_groups(self) -> None:
        data = rules.load_questions()
        groups = data["groups"]
        self.assertEqual([g["id"] for g in groups], [f"Q{n}" for n in range(1, 11)])
        for group in groups:
            with self.subTest(group=group["id"]):
                self.assertTrue(group["title"])
                self.assertGreaterEqual(len(group["pillars"]), 1)
                self.assertGreaterEqual(len(group["questions"]), 1)
                for q in group["questions"]:
                    self.assertTrue(q["id"] and q["ask"] and q["pillar"])
        self.assertTrue([g for g in groups if g["id"] == "Q10"][0]["optional"])
        by_id = {q["id"]: q for g in groups for q in g["questions"]}
        self.assertIn("websockets", by_id["q2.needs"]["options"])
        self.assertEqual(by_id["q5.probes"]["manifest_path"], "envs.<env>.release.probes")
        paths = {q["manifest_path"] for q in by_id.values()}
        for path in ("project.owner", "workload.peak_rps", "workload.p95_ms", "envs.<env>.tier"):
            self.assertIn(path, paths)

    def test_compat_engines_resolve_per_m3(self) -> None:
        compat = rules.load_compat()
        auto = {k: v["auto_engine"] for k, v in compat["runtimes"].items()}
        self.assertEqual(
            auto,
            {
                "lambda-web": "pipeline",
                "lambda-events": "pipeline",
                "ecs-fargate": "ecs-native",
                "ec2-asg": "asg",
                "eks-workload": "argo-rollouts",
            },
        )
        for kind, runtime in compat["runtimes"].items():
            self.assertIn(runtime["auto_engine"], runtime["engines"], kind)
            for engine in runtime["engines"]:
                self.assertIn(f"{kind}:{engine}", compat["deploy_role_profiles"])

    def test_defaults_cover_every_runtime(self) -> None:
        defaults = rules.load_defaults()
        compat = rules.load_compat()
        self.assertEqual(defaults["arch"], "arm64")
        self.assertEqual(set(defaults["runtimes"]), set(compat["runtimes"]))
        for kind, row in defaults["runtimes"].items():
            for key in (
                "front_door",
                "release_strategy",
                "network",
                "dr",
                "cost",
                "sustainability",
            ):
                self.assertTrue(row[key], f"{kind}.{key}")
            for tier in ("nonprod", "prod"):
                self.assertIn(row["release_strategy"][tier], compat["runtimes"][kind]["strategies"])


class DataKeys(unittest.TestCase):
    def schema_kinds(self) -> list[str]:
        sch = json.loads((INTAKE_DIR / "schema" / "platform.schema.json").read_text("utf-8"))
        kinds: list[str] = sch["properties"]["runtime"]["properties"]["kind"]["enum"]
        return kinds

    def test_schema_compat_defaults_have_the_same_runtime_keys(self) -> None:
        kinds = sorted(self.schema_kinds())
        self.assertEqual(sorted(rules.load_compat()["runtimes"]), kinds)
        self.assertEqual(sorted(rules.load_defaults()["runtimes"]), kinds)

    def test_compat_capability_fields(self) -> None:
        compat = rules.load_compat()
        families = {"lambda-web": "lambda", "lambda-events": "lambda", "ecs-fargate": "ecs"}
        for kind, entry in compat["runtimes"].items():
            with self.subTest(kind=kind):
                self.assertIsInstance(entry["family"], str)
                self.assertIsInstance(entry["gradual_needs_alb"], bool)
                self.assertIsInstance(entry["gitops"], bool)
                self.assertIsInstance(entry["fixed_monthly_usd"], int)
                self.assertTrue(set(entry["two_versions_live"]) <= set(entry["strategies"]))
                self.assertNotIn("all-at-once", entry["two_versions_live"])
                self.assertTrue(set(entry["env_flags"]) <= {"scale_to_zero", "fargate_spot"})
                self.assertGreaterEqual(len(entry["alarms"]), 1)
                self.assertNotIn("adapter_built", entry)
                if kind in families:
                    self.assertEqual(entry["family"], families[kind])
        self.assertEqual(compat["runtimes"]["ecs-fargate"]["env_flags"].count("fargate_spot"), 1)
        for kind, entry in compat["runtimes"].items():
            if kind != "ecs-fargate":
                self.assertNotIn("fargate_spot", entry["env_flags"])
        self.assertEqual(
            compat["runtimes"]["lambda-web"]["alarms"],
            ["5xx-rate", "p95-latency", "throttles", "probe-failures"],
        )

    def test_built_flags_are_all_false_in_phase_1(self) -> None:
        compat = rules.load_compat()
        profiles = compat["deploy_role_profiles"]
        for kind, entry in compat["runtimes"].items():
            with self.subTest(kind=kind):
                built = entry["built"]
                self.assertEqual(set(built), {"runtime", "engines", "delivery", "profiles"})
                self.assertIs(built["runtime"], False)
                self.assertEqual(set(built["engines"]), set(entry["engines"]))
                self.assertEqual(set(built["delivery"]), {"push", "gitops"})
                want = {profiles[f"{kind}:{e}"] for e in entry["engines"]}
                self.assertEqual(set(built["profiles"]), want)
                for group in ("engines", "delivery", "profiles"):
                    self.assertEqual(set(built[group].values()), {False})

    def test_defaults_phase_1_values(self) -> None:
        defaults = rules.load_defaults()
        self.assertEqual(defaults["allowed_regions"], ["ap-southeast-1"])
        self.assertEqual(defaults["tiers"]["nonprod"]["log_retention_days"], 14)
        self.assertEqual(defaults["tiers"]["prod"]["log_retention_days"], 90)
        self.assertEqual(defaults["regulated_log_retention_days"], 365)
        self.assertEqual(defaults["tiers"]["prod"]["steps"], [10, 100])
        self.assertEqual(defaults["tiers"]["prod"]["bake_minutes"], 5)
        self.assertEqual(defaults["runtimes"]["lambda-web"]["front_door"], "http-api")
        self.assertEqual(defaults["runtimes"]["lambda-web"]["release_strategy"]["prod"], "canary")
        self.assertEqual(
            defaults["runtimes"]["lambda-web"]["release_strategy"]["nonprod"], "all-at-once"
        )


class ReadmeTable(unittest.TestCase):
    def test_readme_table_in_sync(self) -> None:
        readme = (INTAKE_DIR / "README.md").read_text(encoding="utf-8")
        self.assertEqual(ruletable.extract(readme), ruletable.render())

    def test_render_lists_every_rule(self) -> None:
        table = ruletable.render()
        for rule in rules.load_rules()["rules"]:
            self.assertIn("| {} |".format(rule["id"]), table)


if __name__ == "__main__":
    unittest.main()
