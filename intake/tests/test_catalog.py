"""Rule data and code stay in sync; README table matches rules.json."""

from __future__ import annotations

import re
import unittest

from sis_intake import rules, ruletable

from .helpers import INTAKE_DIR

PILLARS = {"OPS", "SEC", "REL", "PERF", "COST", "SUS"}
WA_REF = re.compile(r"^(OPS|SEC|REL|PERF|COST|SUS)\d{2}(-BP\d{2})?$")


class Catalog(unittest.TestCase):
    def test_ids_match_predicates_one_to_one(self) -> None:
        ids = [r["id"] for r in rules.load_rules()["rules"]]
        self.assertEqual(ids, [f"V{n:02d}" for n in range(1, 19)])
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
            self.assertIn(row["release_strategy"], compat["runtimes"][kind]["strategies"])


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
