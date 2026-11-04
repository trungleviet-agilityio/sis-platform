#!/usr/bin/env python3
"""The one full IAM policy linter for composed apply and deploy policies (ADR 0002, T8, T11).

Credit: the rule set follows ship-it-safely `scripts/tf/policy.sh` (grep level rules) and lab
ADR 0007 S28, rewritten to read IAM documents instead of text.

Input, one or more FILE arguments (`-` reads stdin):
  * a Terraform plan in JSON (`terraform show -json plan`): every planned `aws_iam_policy`,
    `aws_iam_role_policy`, `aws_iam_user_policy` and `aws_iam_group_policy` is linted;
  * a fixture: {"boundary_arn": "...", "documents": [{"name": "...", "policy": {...}}]};
  * a bare IAM policy document ({"Statement": ...}).

Rules (a statement is checked when its Effect is Allow):
  P01 a `*` action
  P02 `iam:*`
  P03 `sts:AssumeRole*` (any action that grants an assume call)
  P04 NotAction or NotResource
  P05 `Resource: "*"` for an action that is not on the no-resource-level-support allowlist
  P06 iam:CreateRole, PutRolePolicy, AttachRolePolicy or PutRolePermissionsBoundary without the
      condition `iam:PermissionsBoundary` equal to the boundary ARN
  P07 iam:PassRole without an `iam:PassedToService` condition
  P08 a write to the boundary policy itself
  P09 iam:DeleteRolePermissionsBoundary (it strips the boundary)
  P00 a policy that is unknown at plan time cannot be checked (fails closed; `--unknown warn`
      only reports it)

Exit codes: 0 clean, 1 findings, 2 usage or unreadable input. Standard library only, Python 3.9
or later. Offline: it never calls AWS.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Actions that have no resource-level support (or are only meaningful on "*"). `Resource: "*"` is
# accepted for these and nothing else. Entries are IAM globs.
STAR_RESOURCE_ALLOWLIST = (
    "ecr:GetAuthorizationToken",
    "ec2:Describe*",
    "sts:GetCallerIdentity",
    "cloudwatch:GetMetricStatistics",
    "cloudwatch:GetMetricData",
    "cloudwatch:ListMetrics",
    "logs:DescribeLogGroups",
    "tag:GetResources",
    "xray:PutTraceSegments",
    "xray:PutTelemetryRecords",
)

ASSUME_ACTIONS = (
    "sts:AssumeRole",
    "sts:AssumeRoleWithSAML",
    "sts:AssumeRoleWithWebIdentity",
)
BOUNDARY_GATED_ACTIONS = (
    "iam:CreateRole",
    "iam:PutRolePolicy",
    "iam:AttachRolePolicy",
    "iam:PutRolePermissionsBoundary",
)
POLICY_WRITE_ACTIONS = (
    "iam:CreatePolicyVersion",
    "iam:DeletePolicy",
    "iam:DeletePolicyVersion",
    "iam:SetDefaultPolicyVersion",
    "iam:TagPolicy",
    "iam:UntagPolicy",
)
POLICY_RESOURCE_TYPES = (
    "aws_iam_policy",
    "aws_iam_role_policy",
    "aws_iam_user_policy",
    "aws_iam_group_policy",
)

Finding = Tuple[str, str, str]  # (document name, rule id, message)


class InputError(Exception):
    """The input cannot be read as a policy source."""


def _glob_match(pattern: str, text: str) -> bool:
    """IAM glob (`*` and `?` only, case-insensitive) of `pattern` against `text`."""
    regex = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
    return re.fullmatch(regex, text, re.IGNORECASE) is not None


def _grants(patterns: Iterable[str], name: str) -> bool:
    """True if any action pattern of a statement covers the action `name`."""
    return any(_glob_match(p, name) for p in patterns)


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _statements(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    statements = _as_list(doc.get("Statement"))
    if not statements or not all(isinstance(s, dict) for s in statements):
        raise InputError("policy has no valid Statement")
    return statements


def _condition_values(
    stmt: Dict[str, Any], key: str, operators: Optional[Tuple[str, ...]]
) -> Optional[List[str]]:
    """Values of condition `key` (any operator when `operators` is None); None when the key is
    absent."""
    cond = stmt.get("Condition")
    if not isinstance(cond, dict):
        return None
    found: Optional[List[str]] = None
    for operator, body in cond.items():
        if operators is not None and operator not in operators:
            continue
        if not isinstance(body, dict):
            continue
        for k, v in body.items():
            if k.lower() == key.lower():
                found = (found or []) + [str(x) for x in _as_list(v)]
    return found


def lint_document(name: str, doc: Dict[str, Any], boundary_arn: Optional[str]) -> List[Finding]:
    findings: List[Finding] = []
    for index, stmt in enumerate(_statements(doc)):
        if stmt.get("Effect") != "Allow":
            continue
        where = f"statement {index}"
        actions = [str(a) for a in _as_list(stmt.get("Action"))]
        resources = [str(r) for r in _as_list(stmt.get("Resource"))]

        def add(rule: str, message: str, where: str = where) -> None:
            findings.append((name, rule, f"{where}: {message}"))

        if any(a in ("*", "*:*") for a in actions):
            add("P01", "Allow with a * action")
        if any(a.lower() == "iam:*" for a in actions):
            add("P02", "Allow with iam:*")
        if any(_grants(actions, assume) for assume in ASSUME_ACTIONS):
            add("P03", "Allow grants sts:AssumeRole* (no role chaining)")
        if "NotAction" in stmt or "NotResource" in stmt:
            add("P04", "Allow with NotAction or NotResource")

        if "*" in resources:
            bad = [
                a for a in actions if not any(_glob_match(ok, a) for ok in STAR_RESOURCE_ALLOWLIST)
            ]
            if bad:
                add(
                    "P05",
                    'Resource "*" for actions with resource-level support: '
                    + ", ".join(sorted(bad)),
                )

        gated = [a for a in BOUNDARY_GATED_ACTIONS if _grants(actions, a)]
        if gated:
            values = _condition_values(
                stmt, "iam:PermissionsBoundary", ("StringEquals", "ArnEquals")
            )
            if boundary_arn is None:
                add(
                    "P06",
                    "no boundary ARN given (--boundary-arn), so "
                    + ", ".join(gated)
                    + " cannot be allowed",
                )
            elif values != [boundary_arn]:
                add(
                    "P06",
                    ", ".join(gated) + " without iam:PermissionsBoundary equal to the boundary ARN",
                )

        if (
            _grants(actions, "iam:PassRole")
            and _condition_values(stmt, "iam:PassedToService", None) is None
        ):
            add("P07", "iam:PassRole without an iam:PassedToService condition")

        if any(_grants(actions, w) for w in POLICY_WRITE_ACTIONS):
            hits_boundary = any(
                r == "*" or (boundary_arn is not None and _glob_match(r, boundary_arn))
                for r in resources
            )
            if hits_boundary:
                add("P08", "a write to the boundary policy is allowed")

        if _grants(actions, "iam:DeleteRolePermissionsBoundary"):
            add("P09", "iam:DeleteRolePermissionsBoundary would strip the boundary")
    return findings


def _load_policy(value: Any) -> Dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise InputError(f"policy is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise InputError("policy is not a JSON object")
    return value


def collect(
    data: Any, origin: str
) -> Tuple[List[Tuple[str, Optional[Dict[str, Any]]]], Optional[str]]:
    """Return ([(name, policy or None when unknown)], boundary ARN from the file)."""
    if not isinstance(data, dict):
        raise InputError(f"{origin}: top level is not a JSON object")
    if "resource_changes" in data or "planned_values" in data:
        docs: List[Tuple[str, Optional[Dict[str, Any]]]] = []
        for rc in data.get("resource_changes") or []:
            if rc.get("type") not in POLICY_RESOURCE_TYPES:
                continue
            change = rc.get("change") or {}
            if "delete" in (change.get("actions") or []) and "create" not in (
                change.get("actions") or []
            ):
                continue
            after = change.get("after") or {}
            unknown = (change.get("after_unknown") or {}).get("policy")
            address = str(rc.get("address", rc.get("type")))
            if unknown is True or "policy" not in after:
                docs.append((address, None))
            else:
                docs.append((address, _load_policy(after["policy"])))
        return docs, None
    if "documents" in data:
        boundary = data.get("boundary_arn")
        docs = []
        for i, entry in enumerate(data["documents"]):
            if not isinstance(entry, dict) or "policy" not in entry:
                raise InputError(f"{origin}: documents[{i}] has no policy")
            docs.append((str(entry.get("name", f"{origin}#{i}")), _load_policy(entry["policy"])))
        return docs, boundary if isinstance(boundary, str) else None
    if "Statement" in data:
        return [(origin, data)], None
    raise InputError(f"{origin}: not a plan, a fixture or a policy document")


def run(paths: List[str], boundary_arn: Optional[str], unknown: str) -> Tuple[int, List[str]]:
    lines: List[str] = []
    failed = False
    checked = 0
    for path in paths:
        try:
            if path == "-":
                data = json.load(sys.stdin)
            else:
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
            docs, file_boundary = collect(data, path)
            boundary = boundary_arn or file_boundary
            for name, policy in docs:
                checked += 1
                label = f"{path}: {name}"
                if policy is None:
                    lines.append(f"{label}: P00 policy unknown at plan time, cannot be checked")
                    failed = failed or unknown == "fail"
                    continue
                for _, rule, message in lint_document(label, policy, boundary):
                    lines.append(f"{label}: {rule} {message}")
                    failed = True
        except (OSError, json.JSONDecodeError, InputError) as exc:
            return 2, [f"error: {path}: {exc}"]
    if checked == 0:
        return 2, ["error: no IAM policy found in the input"]
    return (1 if failed else 0), lines


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Lint composed IAM policies (ADR 0002, T11).")
    parser.add_argument(
        "files", nargs="+", metavar="FILE", help="plan JSON, fixture or policy document; - is stdin"
    )
    parser.add_argument(
        "--boundary-arn",
        help="ARN of the workload permissions boundary (output workload_boundary_arn)",
    )
    parser.add_argument(
        "--unknown", choices=("fail", "warn"), default="fail", help="policies unknown at plan time"
    )
    args = parser.parse_args(argv)
    code, lines = run(args.files, args.boundary_arn, args.unknown)
    for line in lines:
        sys.stderr.write(line + "\n")
    if code == 0:
        sys.stderr.write("ok  policy lint: no findings\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
