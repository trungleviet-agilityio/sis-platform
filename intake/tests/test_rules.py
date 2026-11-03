"""One passing and one failing in-memory case per rule V01 to V18, plus resolution."""

from __future__ import annotations

import unittest
from typing import Any

from sis_intake import rules

from .helpers import base_manifest, copy_of, ecs_manifest, eks_manifest, fired

TWELVE = "9" * 12


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

    def test_v12(self) -> None:
        bad = ecs_manifest()
        bad["database"] = {"kind": "postgres"}
        good = ecs_manifest()
        good["database"] = {"kind": "postgres", "schema_change": "expand-contract"}
        aao = base_manifest()
        aao["database"] = {"kind": "postgres"}
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

    def test_v17(self) -> None:
        self.assert_fires("V17", base_manifest())
        built = rules.load_compat()
        for runtime in built["runtimes"].values():
            runtime["adapter_built"] = True
        self.assert_quiet("V17", base_manifest(), built)
        codepipeline = base_manifest()
        codepipeline["ci"]["provider"] = "codepipeline"
        self.assert_fires("V17", codepipeline, built)

    def test_v18(self) -> None:
        bad = ecs_manifest()
        set_release(bad, "prod", strategy="rolling", rollback="manual", engine="ecs-native")
        self.assert_fires("V18", bad)
        self.assert_quiet("V18", base_manifest())
        self.assert_quiet("V18", ecs_manifest())
        dev_only = ecs_manifest()
        set_release(dev_only, "dev", strategy="rolling", rollback="manual", engine="ecs-native")
        self.assert_quiet("V18", dev_only)


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


if __name__ == "__main__":
    unittest.main()
