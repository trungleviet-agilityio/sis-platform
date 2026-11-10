"""CLI exit codes and JSON output, via script path and via -m."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .helpers import EXAMPLES, INTAKE_DIR

SCRIPT = INTAKE_DIR / "sis_intake" / "validate.py"
FINDING_KEYS = {"id", "severity", "path", "message", "pillars", "wa_refs"}
GOLDEN_TOP = [
    "format_version",
    "platform_version",
    "schema_version",
    "context",
    "valid",
    "findings",
    "project",
    "runtime",
    "workload",
    "envs",
]
GOLDEN_ENV = [
    "tier",
    "account",
    "region",
    "prefix",
    "delivery",
    "promote_from",
    "strategy",
    "steps",
    "bake_minutes",
    "probes",
    "rollback",
    "engine",
    "deploy_role_profile",
    "roles",
    "budget_monthly_usd",
    "data_class",
    "observability",
    "built",
]
TWELVE = "9" * 12


def run_script(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    # Run from a neutral directory so only the script path handling can make imports work.
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            cwd=tmp,
            check=False,
            input=stdin,
        )


def finding_ids(proc: subprocess.CompletedProcess[str]) -> list[str]:
    data = json.loads(proc.stdout)
    return [f["id"] for f in data["findings"]]


class Cli(unittest.TestCase):
    def test_exit_0_valid_prints_warnings_and_resolution(self) -> None:
        proc = run_script(str(EXAMPLES / "valid" / "ship-it-safely.yaml"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("V06", proc.stdout)
        self.assertIn("ecs-native", proc.stdout)
        self.assertIn("deploy_role_profile", proc.stdout)

    def test_exit_1_on_errors(self) -> None:
        proc = run_script(str(EXAMPLES / "invalid" / "canary-no-alarm.yaml"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("V01", proc.stdout)

    def test_exit_2_on_parse_error(self) -> None:
        proc = run_script(str(EXAMPLES / "invalid" / "anchor.yaml"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("line", proc.stdout + proc.stderr)

    def test_exit_2_on_usage_errors(self) -> None:
        self.assertEqual(run_script().returncode, 2)
        self.assertEqual(run_script("/no/such/file.yaml").returncode, 2)

    def test_json_output(self) -> None:
        proc = run_script(str(EXAMPLES / "valid" / "ship-it-safely.yaml"), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertTrue(data["valid"])
        self.assertGreater(len(data["findings"]), 0)
        for finding in data["findings"]:
            self.assertEqual(set(finding), FINDING_KEYS)
            self.assertIsInstance(finding["pillars"], list)
            self.assertIsInstance(finding["wa_refs"], list)
        self.assertEqual(data["envs"]["prod"]["engine"], "ecs-native")

    def test_json_golden_m6_keys(self) -> None:
        proc = run_script(str(EXAMPLES / "valid" / "ship-it-serverless.yaml"), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(list(data), GOLDEN_TOP)
        self.assertEqual(data["format_version"], 1)
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["platform_version"], "v0.2.0")
        self.assertEqual(data["context"], "lint")
        self.assertEqual(list(data["project"]), ["name", "prefix", "owner"])
        self.assertEqual(data["project"]["owner"], "trungleviet-agilityio")
        self.assertEqual(list(data["runtime"]), ["kind", "family", "arch", "front_door"])
        self.assertEqual(data["runtime"]["family"], "lambda")
        self.assertEqual(list(data["workload"]), ["port", "health_path", "peak_rps", "p95_ms"])
        self.assertEqual(list(data["envs"]), ["dev", "prod"])
        for name, env in data["envs"].items():
            with self.subTest(env=name):
                self.assertEqual(list(env), GOLDEN_ENV)
                self.assertEqual(list(env["roles"]), ["plan", "apply", "deploy"])
                self.assertEqual(
                    list(env["observability"]),
                    ["slo", "alarms", "log_retention_days", "notify"],
                )
                self.assertEqual(list(env["observability"]["slo"]), ["availability_pct", "p95_ms"])
                self.assertEqual(list(env["built"]), ["runtime", "engine", "delivery", "profile"])
                self.assertEqual(set(env["built"].values()), {False})
                self.assertNotIn("arn:", json.dumps(env))
        dev, prod = data["envs"]["dev"], data["envs"]["prod"]
        self.assertEqual(
            dev["roles"],
            {
                "plan": "sis-dev-gha-plan",
                "apply": "sis-dev-gha-apply",
                "deploy": "sis-dev-gha-deploy",
            },
        )
        self.assertEqual(dev["tier"], "nonprod")
        self.assertEqual(dev["data_class"], "internal")
        self.assertEqual(dev["budget_monthly_usd"], 20)
        self.assertEqual(dev["steps"], [10, 100])
        self.assertEqual(dev["probes"], ["/health", "/version"])
        self.assertEqual(dev["observability"]["log_retention_days"], 14)
        self.assertEqual(prod["observability"]["log_retention_days"], 90)
        self.assertEqual(prod["observability"]["notify"], "sis-prod-notify")
        self.assertEqual(
            prod["observability"]["alarms"],
            [
                "sis-prod-5xx-rate",
                "sis-prod-p95-latency",
                "sis-prod-throttles",
                "sis-prod-probe-failures",
            ],
        )
        self.assertEqual(prod["observability"]["slo"]["p95_ms"], 500)
        self.assertEqual(prod["promote_from"], "dev")
        self.assertIsNone(dev["promote_from"])
        self.assertEqual(prod["prefix"], "sis")

    def leak_texts(self) -> list[str]:
        base = (EXAMPLES / "valid" / "ship-it-serverless.yaml").read_text("utf-8")
        hyphen = "-".join(["9999"] * 3)
        return [
            base.replace("version: v0.2.0", "version: " + TWELVE),
            base.replace("account: dev", 'account: "' + TWELVE + '"'),
            base.replace("account: dev", 'account: "' + hyphen + '"'),
            base.replace("owner: trungleviet-agilityio", "owner: " + TWELVE),
            "# note " + TWELVE + "\n" + base,
            base.replace("health_path: /health", "health_path: /" + hyphen),
        ]

    def test_no_account_id_in_any_output(self) -> None:
        digits = TWELVE + "|" + "-".join(["9999"] * 3)
        for index, text in enumerate(self.leak_texts()):
            for args in (("--json",), ()):
                with self.subTest(case=index, args=args):
                    proc = run_script("-", *args, stdin=text)
                    self.assertEqual(proc.returncode, 1)
                    for needle in digits.split("|"):
                        self.assertNotIn(needle, proc.stdout)
                        self.assertNotIn(needle, proc.stderr)

    def test_platform_version_is_null_unless_it_matches(self) -> None:
        base = (EXAMPLES / "valid" / "ship-it-serverless.yaml").read_text("utf-8")
        data = json.loads(
            run_script(
                "-", "--json", stdin=base.replace("version: v0.2.0", "version: " + TWELVE)
            ).stdout
        )
        self.assertIsNone(data["platform_version"])
        ok = json.loads(run_script("-", "--json", stdin=base).stdout)
        self.assertEqual(ok["platform_version"], "v0.2.0")

    def test_envs_are_sorted_and_p95_is_one_value(self) -> None:
        base = (EXAMPLES / "valid" / "ship-it-serverless.yaml").read_text("utf-8")
        data = json.loads(run_script("-", "--json", stdin=base).stdout)
        self.assertEqual(list(data["envs"]), sorted(data["envs"]))
        no_p95 = base.replace(", p95_ms: 500", "")
        data = json.loads(run_script("-", "--json", stdin=no_p95).stdout)
        self.assertEqual(data["workload"]["p95_ms"], 1000)
        for env in data["envs"].values():
            self.assertEqual(env["observability"]["slo"]["p95_ms"], data["workload"]["p95_ms"])

    def test_nonprod_without_probes_has_no_probe_alarm(self) -> None:
        text = (EXAMPLES / "valid" / "minimal.yaml").read_text("utf-8")
        data = json.loads(run_script("-", "--json", stdin=text).stdout)
        alarms = data["envs"]["dev"]["observability"]["alarms"]
        self.assertEqual(data["envs"]["dev"]["probes"], [])
        self.assertNotIn("demo-dev-probe-failures", alarms)
        self.assertIn("demo-dev-5xx-rate", alarms)

    def test_text_with_errors_prints_findings_only(self) -> None:
        proc = run_script(str(EXAMPLES / "invalid" / "canary-no-alarm.yaml"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("V01", proc.stdout)
        self.assertNotIn("resolved:", proc.stdout)
        self.assertNotIn("runtime defaults:", proc.stdout)
        ok = run_script(str(EXAMPLES / "valid" / "minimal.yaml"))
        self.assertIn("resolved:", ok.stdout)
        self.assertIn("runtime defaults:", ok.stdout)

    def test_input_over_one_megabyte_is_a_parse_error(self) -> None:
        big = "# " + "x" * (1024 * 1024) + "\n"
        for args in (("-", "--json"), ("-",)):
            with self.subTest(args=args):
                proc = run_script(*args, stdin=big)
                self.assertEqual(proc.returncode, 2)
                self.assertIn("1048576", proc.stdout + proc.stderr)
        self.assertEqual(finding_ids(run_script("-", "--json", stdin=big)), ["PARSE"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.yaml"
            path.write_text(big, "utf-8")
            proc = run_script(str(path), "--json")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(finding_ids(proc), ["PARSE"])
        text = (EXAMPLES / "valid" / "minimal.yaml").read_text("utf-8")
        edge = text + "# " + "x" * (1024 * 1024 - len(text) - 3) + "\n"
        self.assertEqual(len(edge.encode()), 1024 * 1024)
        self.assertEqual(run_script("-", stdin=edge).returncode, 0)

    def test_json_for_a_schema_invalid_manifest_keeps_the_shape(self) -> None:
        proc = run_script(str(EXAMPLES / "invalid" / "unknown-key.yaml"), "--json")
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertEqual(list(data), GOLDEN_TOP)
        self.assertFalse(data["valid"])
        self.assertEqual(data["envs"], {})
        self.assertIsNone(data["runtime"])

    def test_regulated_log_retention(self) -> None:
        text = (EXAMPLES / "valid" / "ship-it-serverless.yaml").read_text("utf-8")
        text = text.replace(
            "compliance: {data_class: internal}",
            "compliance: {data_class: regulated, kms_cmk: true}",
        )
        data = json.loads(run_script("-", "--json", stdin=text).stdout)
        self.assertEqual(data["envs"]["dev"]["data_class"], "regulated")
        self.assertEqual(data["envs"]["dev"]["observability"]["log_retention_days"], 365)

    def test_json_output_on_errors(self) -> None:
        proc = run_script(str(EXAMPLES / "invalid" / "canary-no-alarm.yaml"), "--json")
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertFalse(data["valid"])
        self.assertIn("V01", [f["id"] for f in data["findings"]])

    def test_json_output_on_parse_error(self) -> None:
        proc = run_script(str(EXAMPLES / "invalid" / "anchor.yaml"), "--json")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(finding_ids(proc), ["PARSE"])

    def run_text(self, text: str, *args: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.yaml"
            path.write_text(text, "utf-8")
            return run_script(str(path), *args)

    def test_schema_version_true_is_rejected(self) -> None:
        base = (EXAMPLES / "valid" / "minimal.yaml").read_text("utf-8")
        proc = self.run_text(base.replace("schema_version: 1", "schema_version: true"))
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("SCHEMA", proc.stdout)

    def test_huge_integer_and_deep_nesting_are_parse_errors(self) -> None:
        for text in ("a: " + "9" * 5000 + "\n", "".join("  " * i + "k:\n" for i in range(400))):
            with self.subTest(size=len(text)):
                proc = self.run_text(text, "--json")
                self.assertEqual(proc.returncode, 2, proc.stderr[-300:])
                self.assertEqual(finding_ids(proc), ["PARSE"])

    def test_module_invocation(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "sis_intake.validate", str(EXAMPLES / "valid" / "minimal.yaml")],
            capture_output=True,
            text=True,
            cwd=str(INTAKE_DIR),
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_stdin_dash(self) -> None:
        text = (EXAMPLES / "valid" / "minimal.yaml").read_text("utf-8")
        ok = run_script("-", stdin=text)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        bad = run_script(
            "-", "--json", stdin=text.replace("schema_version: 1", "schema_version: 2")
        )
        self.assertEqual(bad.returncode, 1)
        self.assertIn("SCHEMA", finding_ids(bad))
        broken = run_script("-", "--json", stdin="a: &x 1\n")
        self.assertEqual(broken.returncode, 2)
        self.assertEqual(finding_ids(broken), ["PARSE"])

    def test_json_for_an_unreadable_file(self) -> None:
        proc = run_script("/no/such/file.yaml", "--json")
        self.assertEqual(proc.returncode, 2)
        data = json.loads(proc.stdout)
        self.assertEqual(finding_ids(proc), ["PARSE"])
        self.assertFalse(data["valid"])
        self.assertEqual(list(data), GOLDEN_TOP)

    def test_json_for_usage_errors(self) -> None:
        proc = run_script("--json")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(finding_ids(proc), ["PARSE"])

    def test_non_utf8_input_is_a_parse_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.yaml"
            path.write_bytes(b"\xff\xfe\x00")
            proc = run_script(str(path), "--json")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(finding_ids(proc), ["PARSE"])

    def test_comment_with_an_account_id_gives_v10(self) -> None:
        text = (EXAMPLES / "valid" / "minimal.yaml").read_text("utf-8")
        proc = run_script("-", "--json", stdin="# account " + TWELVE + "\n" + text)
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        errors = [f["id"] for f in data["findings"] if f["severity"] == "error"]
        self.assertEqual(errors, ["V10"])

    def test_context_deploy_exit_codes(self) -> None:
        path = str(EXAMPLES / "valid" / "ship-it-serverless.yaml")
        self.assertEqual(run_script(path).returncode, 0)
        self.assertEqual(run_script(path, "--context", "lint").returncode, 0)
        deploy = run_script(path, "--context", "deploy", "--json")
        self.assertEqual(deploy.returncode, 1)
        data = json.loads(deploy.stdout)
        self.assertEqual(data["context"], "deploy")
        errors = {f["id"] for f in data["findings"] if f["severity"] == "error"}
        self.assertEqual(errors, {"V17"})
        self.assertEqual(json.loads(run_script(path, "--json").stdout)["context"], "lint")

    def test_bad_context_is_a_usage_error(self) -> None:
        path = str(EXAMPLES / "valid" / "minimal.yaml")
        self.assertEqual(run_script(path, "--context", "prod").returncode, 2)
        self.assertEqual(run_script(path, "--context").returncode, 2)

    def test_emit_tfvars(self) -> None:
        path = str(EXAMPLES / "valid" / "ship-it-serverless.yaml")
        proc = run_script(path, "--emit", "tfvars", "--env", "prod")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(list(data), ["platform"])
        slice_ = data["platform"]
        self.assertEqual(slice_["env"], "prod")
        self.assertEqual(slice_["tier"], "prod")
        self.assertEqual(slice_["deploy_role_profile"], "lambda-alias")
        self.assertEqual(slice_["roles"]["apply"], "sis-prod-gha-apply")
        self.assertEqual(slice_["project"]["owner"], "trungleviet-agilityio")
        self.assertNotIn("envs", slice_)
        self.assertNotIn("findings", slice_)

    def test_emit_tfvars_errors(self) -> None:
        path = str(EXAMPLES / "valid" / "minimal.yaml")
        self.assertEqual(run_script(path, "--emit", "tfvars").returncode, 2)
        self.assertEqual(run_script(path, "--emit", "tfvars", "--env", "nope").returncode, 2)
        self.assertEqual(run_script(path, "--emit", "yaml", "--env", "dev").returncode, 2)
        both = run_script(path, "--emit", "tfvars", "--env", "dev", "--json")
        self.assertEqual(both.returncode, 2)
        bad = run_script(
            str(EXAMPLES / "invalid" / "canary-no-alarm.yaml"), "--emit", "tfvars", "--env", "dev"
        )
        self.assertEqual(bad.returncode, 1)
        self.assertEqual(bad.stdout, "")


if __name__ == "__main__":
    unittest.main()
