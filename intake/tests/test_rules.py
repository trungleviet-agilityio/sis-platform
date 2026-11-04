"""One passing and one failing in-memory case per rule V01 to V18, plus resolution."""

from __future__ import annotations

import inspect
import unittest
from typing import Any

from sis_intake import rules

from .helpers import base_manifest, copy_of, ecs_manifest, eks_manifest, fired

TWELVE = "9" * 12


def all_built() -> dict[str, Any]:
    """Compat data with every built flag true."""
    compat = rules.load_compat()
    for runtime in compat["runtimes"].values():
        built = runtime["built"]
        built["runtime"] = True
        for group in ("engines", "delivery", "profiles"):
            for key in built[group]:
                built[group][key] = True
    return compat


def set_release(m: dict[str, Any], env: str, **release: Any) -> dict[str, Any]:
    m["envs"][env]["release"] = release
    return m


class RuleCases(unittest.TestCase):
    def assert_fires(self, rid: str, m: dict[str, Any], compat: Any = None) -> None:
        self.assertIn(rid, fired(m, compat), f"{rid} should fire")

    def assert_quiet(self, rid: str, m: dict[str, Any], compat: Any = None) -> None:
        self.assertNotIn(rid, fired(m, compat), f"{rid} should not fire")

    def test_baselines_are_quiet(self) -> None:
        for build in (base_manifest, ecs_manifest, eks_manifest):
            with self.subTest(build=build.__name__):
                self.assertEqual(fired(build()), {"V17"})

    def test_v01(self) -> None:
        good = set_release(
            base_manifest(),
            "dev",
            strategy="canary",
            steps=[10, 100],
            bake_minutes=5,
            rollback="alarm",
        )
        bad = set_release(
            base_manifest(),
            "dev",
            strategy="linear",
            steps=[10, 100],
            bake_minutes=5,
            rollback="health",
        )
        self.assert_quiet("V01", good)
        self.assert_fires("V01", bad)

    def test_v02(self) -> None:
        def make(steps: Any, bake: int) -> dict[str, Any]:
            return set_release(
                base_manifest(),
                "dev",
                strategy="canary",
                steps=steps,
                bake_minutes=bake,
                rollback="alarm",
            )

        self.assert_quiet("V02", make([10, 50, 100], 1))
        self.assert_fires("V02", make([10, 50], 5))
        self.assert_fires("V02", make([50, 10, 100], 5))
        self.assert_fires("V02", make([10, 10, 100], 5))
        self.assert_fires("V02", make([10, 100], 0))
        missing = set_release(base_manifest(), "dev", strategy="canary", rollback="alarm")
        self.assert_fires("V02", missing)

    def test_v03(self) -> None:
        bad = base_manifest()
        bad["envs"]["dev"]["delivery"] = "gitops"
        good = eks_manifest()
        good["envs"]["dev"]["delivery"] = "gitops"
        self.assert_fires("V03", bad)
        self.assert_quiet("V03", good)

    def test_v04(self) -> None:
        self.assert_quiet("V04", base_manifest())
        self.assert_quiet("V04", ecs_manifest())
        rolling = set_release(base_manifest(), "dev", strategy="rolling", rollback="health")
        self.assert_fires("V04", rolling)
        wrong_engine = set_release(
            base_manifest(), "dev", strategy="all-at-once", engine="ecs-native"
        )
        self.assert_fires("V04", wrong_engine)
        pipeline_ecs = ecs_manifest()
        set_release(
            pipeline_ecs,
            "dev",
            strategy="canary",
            steps=[10, 100],
            bake_minutes=1,
            rollback="alarm",
            engine="pipeline",
        )
        self.assert_fires("V04", pipeline_ecs)
        ec2_aao = copy_of(base_manifest())
        ec2_aao["runtime"] = {"kind": "ec2-asg", "front_door": "alb"}
        set_release(ec2_aao, "dev", strategy="all-at-once")
        self.assert_fires("V04", ec2_aao)

    def test_v04_hint_for_lambda(self) -> None:
        rolling = set_release(base_manifest(), "dev", strategy="rolling", rollback="health")
        found = [f for f in rules.evaluate(rolling) if f.id == "V04"]
        self.assertEqual(len(found), 1)
        self.assertIn("alias flip", found[0].message)

    def test_v05(self) -> None:
        def make(front_door: str) -> dict[str, Any]:
            m = ecs_manifest()
            m["runtime"]["front_door"] = front_door
            set_release(
                m,
                "dev",
                strategy="canary",
                steps=[10, 100],
                bake_minutes=1,
                rollback="alarm",
                engine="ecs-native",
            )
            return m

        self.assert_fires("V05", make("none"))
        self.assert_quiet("V05", make("alb"))
        self.assert_quiet("V05", ecs_manifest())

    def test_v06(self) -> None:
        low = ecs_manifest()
        low["budget"]["monthly_usd"] = 20
        edge = ecs_manifest()
        edge["budget"]["monthly_usd"] = 40
        self.assert_fires("V06", low)
        self.assert_quiet("V06", edge)
        self.assert_quiet("V06", base_manifest())

    def test_v06_threshold_is_forty(self) -> None:
        data = rules.load_rules()
        v06 = [r for r in data["rules"] if r["id"] == "V06"][0]
        self.assertEqual(v06["params"]["threshold_usd"], 40)

    def test_v07(self) -> None:
        bg = ecs_manifest()
        set_release(bg, "dev", strategy="blue-green", rollback="health", engine="ecs-native")
        self.assert_fires("V07", bg)
        self.assert_quiet("V07", ecs_manifest())

    def test_v08(self) -> None:
        payload = base_manifest()
        payload["workload"]["max_payload_mb"] = 10
        gpu = base_manifest()
        gpu["workload"]["needs"] = ["gpu"]
        long_job = base_manifest()
        long_job["runtime"]["front_door"] = "function-url"
        long_job["workload"]["max_duration_seconds"] = 901
        self.assert_fires("V08", payload)
        self.assert_fires("V08", gpu)
        self.assert_fires("V08", long_job)
        self.assert_quiet("V08", base_manifest())
        ecs_gpu = ecs_manifest()
        ecs_gpu["workload"]["needs"] = ["gpu"]
        self.assert_quiet("V08", ecs_gpu)

    def test_v09(self) -> None:
        slow = base_manifest()
        slow["workload"]["max_duration_seconds"] = 30
        edge = base_manifest()
        edge["workload"]["max_duration_seconds"] = 29
        url = base_manifest()
        url["runtime"]["front_door"] = "function-url"
        url["workload"]["max_duration_seconds"] = 30
        self.assert_fires("V09", slow)
        self.assert_quiet("V09", edge)
        self.assert_quiet("V09", url)

    def test_v10(self) -> None:
        bad = base_manifest()
        bad["workload"]["health_path"] = "/x/" + TWELVE
        as_int = base_manifest()
        as_int["workload"]["port"] = int(TWELVE)
        as_key = base_manifest()
        as_key["envs"]["dev"][TWELVE] = "x"
        eleven = base_manifest()
        eleven["workload"]["health_path"] = "/x/" + "9" * 11
        thirteen = base_manifest()
        thirteen["workload"]["health_path"] = "/x/" + "9" * 13
        for m in (bad, as_int, as_key):
            self.assert_fires("V10", m)
        for m in (eleven, thirteen, base_manifest()):
            self.assert_quiet("V10", m)

    def test_v11(self) -> None:
        bad = base_manifest()
        del bad["envs"]["prod"]["promote_from"]
        self.assert_fires("V11", bad)
        self.assert_quiet("V11", base_manifest())
        no_prod = base_manifest()
        del no_prod["envs"]["prod"]
        self.assert_quiet("V11", no_prod)

    def test_v11_reads_tier_not_name(self) -> None:
        named_prod = base_manifest()
        named_prod["envs"]["prod"]["tier"] = "nonprod"
        del named_prod["envs"]["prod"]["promote_from"]
        self.assert_quiet("V11", named_prod)
        renamed = base_manifest()
        renamed["envs"]["live"] = renamed["envs"].pop("prod")
        del renamed["envs"]["live"]["promote_from"]
        self.assert_fires("V11", renamed)

    def test_v12(self) -> None:
        bad = ecs_manifest()
        bad["database"] = {"kind": "postgres"}
        good = ecs_manifest()
        good["database"] = {"kind": "postgres", "schema_change": "expand-contract"}
        aao = base_manifest()
        aao["database"] = {"kind": "postgres"}
        set_release(aao, "prod", strategy="all-at-once")
        default_canary = base_manifest()
        default_canary["database"] = {"kind": "postgres"}
        self.assert_fires("V12", default_canary)
        self.assert_fires("V12", bad)
        self.assert_quiet("V12", good)
        self.assert_quiet("V12", aao)
        self.assert_quiet("V12", ecs_manifest())

    def test_v13(self) -> None:
        def make(strategy: str, rto: int) -> dict[str, Any]:
            m = base_manifest()
            m["dr"] = {"strategy": strategy, "rto_minutes": rto, "rpo_minutes": 60}
            return m

        self.assert_fires("V13", make("backup-restore", 30))
        self.assert_fires("V13", make("pilot-light", 5))
        self.assert_quiet("V13", make("backup-restore", 60))
        self.assert_quiet("V13", make("pilot-light", 30))
        self.assert_quiet("V13", make("multi-site", 5))
        self.assert_quiet("V13", make("warm-standby", 5))

    def test_v14(self) -> None:
        def make(budget: int) -> dict[str, Any]:
            m = base_manifest()
            m["dr"] = {"strategy": "warm-standby", "rto_minutes": 30, "rpo_minutes": 5}
            m["budget"]["monthly_usd"] = budget
            return m

        self.assert_fires("V14", make(50))
        self.assert_quiet("V14", make(100))
        self.assert_quiet("V14", base_manifest())

    def test_v15(self) -> None:
        low = eks_manifest()
        low["budget"]["monthly_usd"] = 50
        self.assert_fires("V15", low)
        self.assert_quiet("V15", eks_manifest())

    def test_v16(self) -> None:
        spot = base_manifest()
        spot["envs"]["prod"]["scale_to_zero"] = True
        fargate = ecs_manifest()
        fargate["envs"]["prod"]["fargate_spot"] = True
        dev = base_manifest()
        dev["envs"]["dev"]["scale_to_zero"] = True
        self.assert_fires("V16", spot)
        self.assert_fires("V16", fargate)
        self.assert_quiet("V16", dev)
        renamed = base_manifest()
        renamed["envs"]["live"] = renamed["envs"].pop("prod")
        renamed["envs"]["live"]["scale_to_zero"] = True
        self.assert_fires("V16", renamed)
        named_prod = base_manifest()
        named_prod["envs"]["prod"]["tier"] = "nonprod"
        named_prod["envs"]["prod"]["scale_to_zero"] = True
        self.assert_quiet("V16", named_prod)

    def test_v17(self) -> None:
        self.assert_fires("V17", base_manifest())
        built = all_built()
        self.assert_quiet("V17", base_manifest(), built)
        codepipeline = base_manifest()
        codepipeline["ci"]["provider"] = "codepipeline"
        self.assert_fires("V17", codepipeline, built)

    def test_v17_each_flag_alone(self) -> None:
        def one_unbuilt(path: list[str]) -> Any:
            compat = all_built()
            node = compat["runtimes"]["lambda-web"]["built"]
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = False
            return compat

        for path in (
            ["runtime"],
            ["engines", "pipeline"],
            ["delivery", "push"],
            ["profiles", "lambda-alias"],
        ):
            with self.subTest(flag=path):
                self.assert_fires("V17", base_manifest(), one_unbuilt(path))

    def test_v17_is_an_error_only_in_deploy_context(self) -> None:
        lint = [f for f in rules.evaluate(base_manifest()) if f.id == "V17"]
        deploy = [f for f in rules.evaluate(base_manifest(), context="deploy") if f.id == "V17"]
        self.assertTrue(lint and {f.severity for f in lint} == {"warning"})
        self.assertTrue(deploy and {f.severity for f in deploy} == {"error"})
        self.assertEqual(fired(base_manifest(), context="deploy", compat=all_built()), set())

    def test_v18(self) -> None:
        bad = ecs_manifest()
        set_release(bad, "prod", strategy="rolling", rollback="manual", engine="ecs-native")
        self.assert_fires("V18", bad)
        self.assert_quiet("V18", base_manifest())
        self.assert_quiet("V18", ecs_manifest())
        dev_only = ecs_manifest()
        set_release(dev_only, "dev", strategy="rolling", rollback="manual", engine="ecs-native")
        self.assert_quiet("V18", dev_only)
        renamed = ecs_manifest()
        renamed["envs"]["live"] = renamed["envs"].pop("prod")
        set_release(renamed, "live", strategy="rolling", rollback="manual", engine="ecs-native")
        self.assert_fires("V18", renamed)

    def test_v08_websockets(self) -> None:
        ws = base_manifest()
        ws["workload"]["needs"] = ["websockets"]
        ecs = ecs_manifest()
        ecs["workload"]["needs"] = ["websockets"]
        self.assert_fires("V08", ws)
        self.assert_quiet("V08", ecs)

    def test_v10_scans_raw_text_including_comments(self) -> None:
        raw_bad = "# account " + TWELVE + "\nschema_version: 1\n"
        raw_ok = "# account 12345\nschema_version: 1\n"
        self.assertIn("V10", fired(base_manifest(), raw_text=raw_bad))
        self.assertNotIn("V10", fired(base_manifest(), raw_text=raw_ok))
        hit = [f for f in rules.evaluate(base_manifest(), raw_text=raw_bad) if f.id == "V10"]
        self.assertEqual(hit[0].path, "line 1")

    def test_v19(self) -> None:
        def make(strategy: str, probes: Any) -> dict[str, Any]:
            release: dict[str, Any] = {
                "strategy": strategy,
                "steps": [10, 100],
                "bake_minutes": 5,
                "rollback": "alarm",
            }
            if probes is not None:
                release["probes"] = probes
            return set_release(base_manifest(), "dev", **release)

        self.assert_quiet("V19", make("canary", ["/health", "/version"]))
        self.assert_quiet("V19", make("linear", ["/version"]))
        self.assert_fires("V19", make("canary", None))
        self.assert_fires("V19", make("canary", ["/health"]))
        self.assert_fires("V19", make("linear", ["/health"]))
        self.assert_quiet("V19", set_release(base_manifest(), "dev", strategy="all-at-once"))

    def test_v19_uses_the_manifest_health_path(self) -> None:
        m = set_release(
            base_manifest(),
            "dev",
            strategy="canary",
            steps=[10, 100],
            bake_minutes=5,
            rollback="alarm",
            probes=["/health"],
        )
        m["workload"]["health_path"] = "/ready"
        self.assert_quiet("V19", m)

    def test_v20(self) -> None:
        unknown = base_manifest()
        unknown["envs"]["prod"]["promote_from"] = "staging"
        selfref = base_manifest()
        selfref["envs"]["prod"]["promote_from"] = "prod"
        cycle = base_manifest()
        cycle["envs"]["dev"]["promote_from"] = "prod"
        shared = base_manifest()
        shared["envs"]["prod"]["account"] = "dev"
        for m in (unknown, selfref, cycle, shared):
            self.assert_fires("V20", m)
            self.assertEqual(len([f for f in rules.evaluate(m) if f.id == "V20"]), 1)
        self.assert_quiet("V20", base_manifest())

    def test_v21(self) -> None:
        spot_on_lambda = base_manifest()
        spot_on_lambda["envs"]["dev"]["fargate_spot"] = True
        zero_on_eks = eks_manifest()
        zero_on_eks["envs"]["dev"]["scale_to_zero"] = True
        spot_on_ecs = ecs_manifest()
        spot_on_ecs["envs"]["dev"]["fargate_spot"] = True
        zero_on_lambda = base_manifest()
        zero_on_lambda["envs"]["dev"]["scale_to_zero"] = True
        off = base_manifest()
        off["envs"]["dev"]["fargate_spot"] = False
        self.assert_fires("V21", spot_on_lambda)
        self.assert_fires("V21", zero_on_eks)
        for m in (spot_on_ecs, zero_on_lambda, off, base_manifest()):
            self.assert_quiet("V21", m)

    def test_v22(self) -> None:
        no_class = base_manifest()
        del no_class["compliance"]
        regulated = base_manifest()
        regulated["compliance"] = {"data_class": "regulated"}
        ok = base_manifest()
        ok["compliance"] = {"data_class": "regulated", "kms_cmk": True}
        nonprod_only = base_manifest()
        del nonprod_only["compliance"]
        del nonprod_only["envs"]["prod"]
        self.assert_fires("V22", no_class)
        self.assert_fires("V22", regulated)
        self.assert_quiet("V22", ok)
        self.assert_quiet("V22", base_manifest())
        self.assert_quiet("V22", nonprod_only)

    def test_v23(self) -> None:
        def make(**dr: Any) -> dict[str, Any]:
            m = base_manifest()
            m["dr"] = dr
            return m

        self.assert_fires("V23", make(rto_minutes=240))
        self.assert_fires("V23", make(rpo_minutes=60))
        self.assert_fires("V23", make())
        self.assert_quiet("V23", make(rto_minutes=240, rpo_minutes=60))
        nonprod = base_manifest()
        del nonprod["dr"]
        del nonprod["envs"]["prod"]
        self.assert_quiet("V23", nonprod)

    def test_v24(self) -> None:
        for key in ("peak_rps", "p95_ms"):
            with self.subTest(key=key):
                m = base_manifest()
                del m["workload"][key]
                self.assert_fires("V24", m)
        none = base_manifest()
        del none["workload"]
        self.assert_fires("V24", none)
        self.assert_quiet("V24", base_manifest())
        nonprod = base_manifest()
        del nonprod["workload"]["peak_rps"]
        del nonprod["envs"]["prod"]
        self.assert_quiet("V24", nonprod)

    def test_v25(self) -> None:
        bad = base_manifest()
        bad["envs"]["dev"]["region"] = "us-east-1"
        self.assert_fires("V25", bad)
        self.assert_quiet("V25", base_manifest())
        wide = rules.load_defaults()
        wide["allowed_regions"] = ["ap-southeast-1", "us-east-1"]
        self.assertNotIn("V25", {f.id for f in rules.evaluate(bad, defaults=wide)})

    def test_predicates_do_not_hardcode_runtime_names_or_costs(self) -> None:
        source = inspect.getsource(rules)
        self.assertNotIn("startswith(", source)
        self.assertNotIn("73 USD", source)
        self.assertNotIn('"eks-workload"', source)

    def test_compat_data_drives_predicates(self) -> None:
        compat = rules.load_compat()
        compat["runtimes"]["lambda-web"]["family"] = "other"
        big = base_manifest()
        big["workload"]["max_payload_mb"] = 10
        self.assert_quiet("V08", big, compat)
        compat = rules.load_compat()
        compat["runtimes"]["lambda-web"]["gitops"] = True
        gitops = base_manifest()
        gitops["envs"]["dev"]["delivery"] = "gitops"
        self.assert_quiet("V03", gitops, compat)
        compat = rules.load_compat()
        compat["runtimes"]["ecs-fargate"]["gradual_needs_alb"] = False
        no_alb = ecs_manifest()
        no_alb["runtime"]["front_door"] = "none"
        set_release(
            no_alb,
            "dev",
            strategy="canary",
            steps=[10, 100],
            bake_minutes=1,
            rollback="alarm",
            engine="ecs-native",
        )
        self.assert_fires("V05", no_alb)
        self.assert_quiet("V05", no_alb, compat)
        compat = rules.load_compat()
        compat["runtimes"]["eks-workload"]["fixed_monthly_usd"] = 0
        low = eks_manifest()
        low["budget"]["monthly_usd"] = 50
        self.assert_fires("V15", low)
        self.assert_quiet("V15", low, compat)

    def test_rule_registry_decorator(self) -> None:
        ids = sorted(r["id"] for r in rules.load_rules()["rules"])
        self.assertEqual(sorted(rules.PREDICATES), ids)
        before = dict(rules.PREDICATES)
        try:

            @rules.rule("V99")
            def v99(ctx: rules.Ctx, params: dict[str, Any]) -> list[rules.Hit]:
                return []

            self.assertIs(rules.PREDICATES["V99"], v99)
        finally:
            rules.PREDICATES.clear()
            rules.PREDICATES.update(before)

    def test_rule_params_are_not_on_ctx(self) -> None:
        ctx = rules.Ctx(base_manifest(), rules.load_compat(), rules.load_defaults())
        self.assertFalse(hasattr(ctx, "params"))


class Resolution(unittest.TestCase):
    def test_auto_engine_per_runtime(self) -> None:
        expected = {
            "lambda-web": ("pipeline", "lambda-alias"),
            "lambda-events": ("pipeline", "lambda-alias"),
            "ecs-fargate": ("ecs-native", "ecs-native"),
            "ec2-asg": ("asg", "asg-instance-refresh"),
            "eks-workload": ("argo-rollouts", "argo-rollouts"),
        }
        for kind, (engine, profile) in expected.items():
            with self.subTest(kind=kind):
                m = base_manifest()
                m["runtime"] = {"kind": kind}
                for env in m["envs"].values():
                    env["release"] = {"engine": "auto"}
                resolved = rules.resolve_envs(m)
                self.assertEqual(resolved["dev"]["engine"], engine)
                self.assertEqual(resolved["dev"]["deploy_role_profile"], profile)

    def test_explicit_engine_profile(self) -> None:
        m = ecs_manifest()
        set_release(m, "dev", strategy="rolling", rollback="health", engine="codedeploy")
        self.assertEqual(rules.resolve_envs(m)["dev"]["deploy_role_profile"], "codedeploy-ecs")

    def test_defaults_used_when_release_missing(self) -> None:
        m = base_manifest()
        r = rules.resolve_envs(m)["dev"]
        self.assertEqual(r["strategy"], "all-at-once")
        self.assertEqual(r["engine"], "pipeline")
        self.assertEqual(r["front_door"], "http-api")

    def test_tier_defaults(self) -> None:
        views = rules.env_views(base_manifest())
        dev, prod = views[0], views[1]
        self.assertEqual(
            (dev.tier, dev.strategy, dev.rollback), ("nonprod", "all-at-once", "manual")
        )
        self.assertEqual((dev.steps, dev.probes), ([], []))
        self.assertEqual((prod.tier, prod.strategy, prod.rollback), ("prod", "canary", "alarm"))
        self.assertEqual((prod.steps, prod.bake_minutes), ([10, 100], 5))
        self.assertEqual(prod.probes, ["/health", "/version"])
        self.assertEqual(prod.delivery, "push")

    def test_default_probes_follow_health_path(self) -> None:
        m = base_manifest()
        m["workload"]["health_path"] = "/ready"
        self.assertEqual(rules.env_views(m)[1].probes, ["/ready", "/version"])

    def test_explicit_values_beat_tier_defaults(self) -> None:
        m = base_manifest()
        set_release(m, "prod", strategy="all-at-once", rollback="manual")
        prod = rules.env_views(m)[1]
        self.assertEqual((prod.strategy, prod.rollback, prod.steps), ("all-at-once", "manual", []))

    def test_defaults_alone_have_no_errors(self) -> None:
        m = base_manifest()
        for env in m["envs"].values():
            env.pop("delivery", None)
        self.assertEqual([f for f in rules.evaluate(m) if f.severity == "error"], [])

    def test_non_lambda_runtimes_keep_a_rolling_default(self) -> None:
        for build in (ecs_manifest, eks_manifest):
            m = build()
            for env in m["envs"].values():
                env.pop("release")
            self.assertEqual({v.strategy for v in rules.env_views(m)}, {"rolling"})


if __name__ == "__main__":
    unittest.main()
