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


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    # Run from a neutral directory so only the script path handling can make imports work.
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            cwd=tmp,
            check=False,
        )


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
        self.assertEqual(data["resolved"]["prod"]["engine"], "ecs-native")

    def test_json_output_on_errors(self) -> None:
        proc = run_script(str(EXAMPLES / "invalid" / "canary-no-alarm.yaml"), "--json")
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertFalse(data["valid"])
        self.assertIn("V01", [f["id"] for f in data["findings"]])

    def test_json_output_on_parse_error(self) -> None:
        proc = run_script(str(EXAMPLES / "invalid" / "anchor.yaml"), "--json")
        self.assertEqual(proc.returncode, 2)
        data = json.loads(proc.stdout)
        self.assertEqual([f["id"] for f in data["findings"]], ["PARSE"])

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
                self.assertEqual([f["id"] for f in json.loads(proc.stdout)["findings"]], ["PARSE"])

    def test_module_invocation(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "sis_intake.validate", str(EXAMPLES / "valid" / "minimal.yaml")],
            capture_output=True,
            text=True,
            cwd=str(INTAKE_DIR),
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_stdin_dash_not_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.yaml"
            path.write_text((EXAMPLES / "valid" / "minimal.yaml").read_text("utf-8"), "utf-8")
            self.assertEqual(run_script(str(path)).returncode, 0)


if __name__ == "__main__":
    unittest.main()
