"""Every example file yields exactly what its header says."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from sis_intake import validate

from .helpers import EXAMPLES

EXPECT = re.compile(r"^# expect: (\S+)\s*$")

ERROR_RULES = {"V01", "V02", "V03", "V04", "V05", "V08", "V09", "V10", "V11", "V12"}


def expected_id(path: Path) -> str:
    first = path.read_text(encoding="utf-8").splitlines()[0]
    match = EXPECT.match(first)
    if match is None:
        raise AssertionError(f"{path.name}: first line must be '# expect: <ID>'")
    return match.group(1)


class Valid(unittest.TestCase):
    def test_no_errors(self) -> None:
        files = sorted((EXAMPLES / "valid").glob("*.yaml"))
        self.assertEqual(
            [f.name for f in files],
            ["minimal.yaml", "ship-it-safely.yaml", "ship-it-serverless.yaml"],
        )
        for path in files:
            with self.subTest(path=path.name):
                report = validate.validate_file(str(path))
                errors = [f.id for f in report.findings if f.severity == "error"]
                self.assertEqual(errors, [])

    def test_ship_it_safely_warnings(self) -> None:
        report = validate.validate_file(str(EXAMPLES / "valid" / "ship-it-safely.yaml"))
        warnings = {f.id for f in report.findings if f.severity == "warning"}
        self.assertTrue({"V06", "V16"} <= warnings, warnings)

    def test_ship_it_serverless_resolution(self) -> None:
        report = validate.validate_file(str(EXAMPLES / "valid" / "ship-it-serverless.yaml"))
        self.assertEqual(report.resolved["dev"]["engine"], "pipeline")
        self.assertEqual(report.resolved["dev"]["deploy_role_profile"], "lambda-alias")


class Invalid(unittest.TestCase):
    def test_each_yields_exactly_its_expectation(self) -> None:
        files = sorted((EXAMPLES / "invalid").glob("*.yaml"))
        seen = set()
        for path in files:
            want = expected_id(path)
            seen.add(want)
            with self.subTest(path=path.name):
                report = validate.validate_file(str(path))
                errors = [f.id for f in report.findings if f.severity == "error"]
                self.assertEqual(errors, [want])
        self.assertTrue(seen >= ERROR_RULES, f"missing: {sorted(ERROR_RULES - seen)}")
        self.assertTrue({"SCHEMA", "PARSE"} <= seen)

    def test_account_id_only_in_v10_example(self) -> None:
        pattern = re.compile(r"(?<!\d)\d{12}(?!\d)")
        root = EXAMPLES.parent
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if pattern.search(path.read_text(encoding="utf-8")):
                self.assertEqual(path.name, "account-id.yaml", str(path))


if __name__ == "__main__":
    unittest.main()
