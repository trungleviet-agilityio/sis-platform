"""Tests for scripts/tf/policy.py (ADR 0002, T11). Standard library only, Python 3.9 or later:

    python3 -m unittest discover -s scripts/tf -p 'test_policy.py'

Every fixture under fixtures/policy/fail is named <rule id>-<what>.json and must produce that
rule and exit 1. Every fixture under fixtures/policy/pass must exit 0.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import policy  # noqa: E402  (path set above)

FIXTURES = HERE / "fixtures" / "policy"
BOUNDARY = "arn:aws:iam::123456789012:policy/sis-dev-workload-boundary"

# What each rule says, so a test asserts the message and not only the exit code.
MESSAGES = {
    "P01": "Allow with a * action",
    "P02": "Allow with iam:*",
    "P03": "sts:AssumeRole*",
    "P04": "NotAction or NotResource",
    "P05": 'Resource "*" for actions with resource-level support',
    "P06": "",  # varies: two messages, asserted in dedicated tests
    "P07": "iam:PassRole",
    "P08": "a write to the boundary policy is allowed",
    "P09": "iam:DeleteRolePermissionsBoundary would strip the boundary",
    "P10": "",  # two messages (identity writes, trust rewrite), asserted in dedicated tests
    "P11": "administration of the",
}


def run_main(args: List[str]) -> Tuple[int, str]:
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = policy.main(args)
    return code, err.getvalue()


def write_doc(directory: Path, statements: object, name: str = "doc.json") -> str:
    path = directory / name
    path.write_text(
        json.dumps({"Version": "2012-10-17", "Statement": statements}), encoding="utf-8"
    )
    return str(path)


class FixtureTests(unittest.TestCase):
    def test_pass_fixtures_are_clean(self) -> None:
        files = sorted((FIXTURES / "pass").glob("*.json"))
        self.assertGreaterEqual(len(files), 5)
        for path in files:
            with self.subTest(fixture=path.name):
                code, out = run_main([str(path)])
                self.assertEqual(code, 0, out)
                self.assertIn("no findings", out)

    def test_fail_fixtures_report_their_rule(self) -> None:
        files = sorted((FIXTURES / "fail").glob("*.json"))
        rules = {p.name.split("-")[0] for p in files}
        self.assertEqual(
            rules, {"P01", "P02", "P03", "P04", "P05", "P06", "P07", "P08", "P09", "P10", "P11"}
        )
        for path in files:
            rule = path.name.split("-")[0]
            with self.subTest(fixture=path.name):
                code, out = run_main([str(path)])
                self.assertEqual(code, 1, out)
                hits = [line for line in out.splitlines() if f": {rule} statement 0:" in line]
                self.assertEqual(len(hits), 1, out)
                self.assertIn(MESSAGES[rule], hits[0])


class RuleDetailTests(unittest.TestCase):
    def test_escalation_without_the_boundary_condition(self) -> None:
        code, out = run_main([str(FIXTURES / "fail" / "P06-create-role-without-boundary.json")])
        self.assertEqual(code, 1)
        self.assertIn(
            "iam:CreateRole without iam:PermissionsBoundary equal to the boundary ARN", out
        )

    def test_wrong_boundary_value_is_refused(self) -> None:
        code, out = run_main([str(FIXTURES / "fail" / "P06-wrong-boundary.json")])
        self.assertEqual(code, 1)
        self.assertIn("without iam:PermissionsBoundary equal to the boundary ARN", out)

    def test_missing_boundary_arn_names_the_flag(self) -> None:
        code, out = run_main([str(FIXTURES / "fail" / "P06-no-boundary-arn-given.json")])
        self.assertEqual(code, 1)
        self.assertIn(
            "no boundary ARN given (--boundary-arn), so iam:CreateRole cannot be allowed", out
        )

    def test_boundary_arn_flag_overrides_the_file(self) -> None:
        path = str(FIXTURES / "pass" / "create-role-with-boundary.json")
        code, out = run_main([path, "--boundary-arn", "arn:aws:iam::123456789012:policy/other"])
        self.assertEqual(code, 1)
        self.assertIn("P06", out)

    def test_bare_document_with_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stmt = {
                "Effect": "Allow",
                "Action": "iam:CreateRole",
                "Resource": "arn:aws:iam::123456789012:role/x-*",
                "Condition": {"ArnEquals": {"iam:PermissionsBoundary": BOUNDARY}},
            }
            path = write_doc(Path(tmp), [stmt])
            self.assertEqual(run_main([path, "--boundary-arn", BOUNDARY])[0], 0)
            code, out = run_main([path])
            self.assertEqual(code, 1)
            self.assertIn("P06 statement 0: no boundary ARN given", out)

    def test_condition_key_is_case_insensitive_and_list_valued(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stmt = {
                "Effect": "Allow",
                "Action": ["iam:CreateRole"],
                "Resource": "arn:aws:iam::123456789012:role/x-*",
                "Condition": {"StringEquals": {"IAM:permissionsboundary": [BOUNDARY]}},
            }
            self.assertEqual(
                run_main([write_doc(Path(tmp), stmt), "--boundary-arn", BOUNDARY])[0], 0
            )

    def test_two_boundary_values_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stmt = {
                "Effect": "Allow",
                "Action": "iam:CreateRole",
                "Resource": "*",
                "Condition": {
                    "StringEquals": {
                        "iam:PermissionsBoundary": [BOUNDARY, "arn:aws:iam::123456789012:policy/x"]
                    }
                },
            }
            code, out = run_main([write_doc(Path(tmp), stmt), "--boundary-arn", BOUNDARY])
            self.assertEqual(code, 1)
            self.assertIn("P06", out)

    def test_deny_statements_never_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stmt = [{"Effect": "Deny", "Action": "*", "NotResource": "x", "Resource": "*"}]
            self.assertEqual(run_main([write_doc(Path(tmp), stmt)])[0], 0)

    def test_case_insensitive_action_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stmt = {
                "Effect": "Allow",
                "Action": "STS:assumerole",
                "Resource": "arn:aws:iam::123456789012:role/x",
            }
            code, out = run_main([write_doc(Path(tmp), stmt)])
            self.assertEqual(code, 1)
            self.assertIn("P03", out)

    def test_wildcard_on_star_resource_must_match_the_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ok = {"Effect": "Allow", "Action": "ec2:DescribeV*", "Resource": "*"}
            self.assertEqual(run_main([write_doc(Path(tmp), ok)])[0], 0)
            bad = {"Effect": "Allow", "Action": "ec2:Run*", "Resource": "*"}
            code, out = run_main([write_doc(Path(tmp), bad, "bad.json")])
            self.assertEqual(code, 1)
            self.assertIn("ec2:Run*", out)

    def test_policy_write_on_boundary_needs_a_matching_resource(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stmt = {
                "Effect": "Allow",
                "Action": "iam:CreatePolicyVersion",
                "Resource": "arn:aws:iam::123456789012:policy/sis-dev-app-*",
            }
            self.assertEqual(
                run_main([write_doc(Path(tmp), stmt), "--boundary-arn", BOUNDARY])[0], 0
            )


class ScopeTests(unittest.TestCase):
    def fail_text(self, name: str) -> str:
        code, out = run_main([str(FIXTURES / "fail" / name)])
        self.assertEqual(code, 1, out)
        return out

    def test_pass_role_with_condition_but_wildcard_role_fails(self) -> None:
        out = self.fail_text("P07-pass-role-wildcard-role-with-condition.json")
        self.assertIn("not role/<prefix>-<env>-<literal>", out)
        self.assertNotIn("without an iam:PassedToService", out)

    def test_pass_role_without_condition_reports_it(self) -> None:
        out = self.fail_text("P07-pass-role-without-service.json")
        self.assertIn("iam:PassRole without an iam:PassedToService condition", out)

    def test_pass_role_never_reaches_gha_roles(self) -> None:
        self.fail_text("P07-pass-role-gha-role-with-condition.json")
        self.fail_text("P07-pass-role-env-wildcard-reaches-gha.json")

    def test_pass_role_other_env_and_star_fail(self) -> None:
        self.fail_text("P07-pass-role-other-env-role.json")
        self.fail_text("P07-pass-role-resource-star-with-condition.json")

    def test_pass_role_scope_needs_the_boundary_arn(self) -> None:
        out = self.fail_text("P07-pass-role-no-boundary-arn-given.json")
        self.assertIn("no boundary ARN given (--boundary-arn)", out)

    def test_identity_writes_name_the_actions(self) -> None:
        out = self.fail_text("P10-create-access-key.json")
        self.assertIn("user, group or access key writes are not allowed: iam:CreateAccessKey", out)

    def test_identity_write_wildcard_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stmt = {
                "Effect": "Allow",
                "Action": "iam:Create*",
                "Resource": "arn:aws:iam::123456789012:role/sis-dev-app-*",
            }
            code, out = run_main([write_doc(Path(tmp), stmt), "--boundary-arn", BOUNDARY])
            self.assertEqual(code, 1)
            self.assertIn("iam:CreateUser", out)

    def test_trust_rewrite_outside_env_roles_fails(self) -> None:
        for name in (
            "P10-update-assume-role-any-role.json",
            "P10-update-assume-role-gha-role.json",
            "P10-update-assume-role-env-wildcard.json",
            "P10-update-assume-role-resource-star.json",
        ):
            with self.subTest(fixture=name):
                self.assertIn(
                    "iam:UpdateAssumeRolePolicy outside role/<prefix>-<env>-<literal>",
                    self.fail_text(name),
                )

    def test_state_bucket_and_repository_admin(self) -> None:
        self.assertIn(
            "state bucket is allowed: s3:PutBucketPolicy",
            self.fail_text("P11-state-bucket-policy.json"),
        )
        self.assertIn(
            "app ECR repository is allowed: ecr:SetRepositoryPolicy",
            self.fail_text("P11-ecr-set-repository-policy.json"),
        )


class PlanTests(unittest.TestCase):
    def test_clean_plan(self) -> None:
        code, out = run_main([str(FIXTURES / "plan-clean.json")])
        self.assertEqual(code, 0, out)

    def test_bad_plan_names_the_resource_address(self) -> None:
        code, out = run_main([str(FIXTURES / "plan-bad.json")])
        self.assertEqual(code, 1)
        self.assertIn("module.apply_profile.aws_iam_role_policy.apply: P06", out)
        self.assertIn("module.apply_profile.aws_iam_role_policy.apply: P05", out)

    def test_unknown_policy_fails_closed(self) -> None:
        code, out = run_main([str(FIXTURES / "plan-unknown.json")])
        self.assertEqual(code, 1)
        self.assertIn("P00 policy unknown at plan time, cannot be checked", out)

    def test_unknown_policy_can_be_downgraded(self) -> None:
        code, out = run_main([str(FIXTURES / "plan-unknown.json"), "--unknown", "warn"])
        self.assertEqual(code, 0)
        self.assertIn("P00", out)


class InputTests(unittest.TestCase):
    def test_missing_file_is_a_usage_error(self) -> None:
        code, out = run_main(["/nonexistent/policy.json"])
        self.assertEqual(code, 2)
        self.assertIn("error: /nonexistent/policy.json", out)

    def test_invalid_json_is_a_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            code, out = run_main([str(path)])
            self.assertEqual(code, 2)
            self.assertIn("error:", out)

    def test_unknown_shape_is_a_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "other.json"
            path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
            code, out = run_main([str(path)])
            self.assertEqual(code, 2)
            self.assertIn("not a plan, a fixture or a policy document", out)

    def test_plan_without_policies_is_a_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty-plan.json"
            path.write_text(json.dumps({"resource_changes": []}), encoding="utf-8")
            code, out = run_main([str(path)])
            self.assertEqual(code, 2)
            self.assertIn("no IAM policy found in the input", out)

    def test_policy_without_statement_is_a_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nostmt.json"
            path.write_text(
                json.dumps({"documents": [{"name": "x", "policy": {"Version": "2012-10-17"}}]}),
                encoding="utf-8",
            )
            code, out = run_main([str(path)])
            self.assertEqual(code, 2)
            self.assertIn("policy has no valid Statement", out)

    def test_stdin(self) -> None:
        doc: Optional[str] = json.dumps(
            {"Statement": {"Effect": "Allow", "Action": "*", "Resource": "x"}}
        )
        old = sys.stdin
        sys.stdin = io.StringIO(doc)
        try:
            code, out = run_main(["-"])
        finally:
            sys.stdin = old
        self.assertEqual(code, 1)
        self.assertIn("P01", out)


if __name__ == "__main__":
    unittest.main()
