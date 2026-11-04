#!/usr/bin/env python3
"""Resolve step of every reusable workflow (ADR 0002 O11, W2, M6, M7). Runs without credentials.

Usage:
  resolve.py --caller DIR --trust-only
  resolve.py --caller DIR --env ENV [--tfvars FILE]

DIR is the caller's checkout (it holds platform.lock and platform.yaml). The job context comes
from the environment, set by the workflow from `job.*` (F17): JOB_WORKFLOW_REPOSITORY,
JOB_WORKFLOW_FILE_PATH and JOB_WORKFLOW_SHA. Checks, in order:
  O11  the job runs the sis-platform repository, a `.github/workflows/reusable-*.yml` file, at a
       40-hex SHA
  O11  that SHA is in the caller's committed platform.lock `trusted_workflow_shas` (schema per L1)
  M8   the manifest is valid under `--context lint` (the validator at the same SHA)
  M6   ENV is an env of the plan; family, region, prefix and role names have their documented
       shape, and the role names are <prefix>-<env>-gha-{plan,apply,deploy}
With --tfvars it writes the M7 `--emit tfvars --env ENV` output to FILE, mode 0600 (keep FILE
under $RUNNER_TEMP: it never lands in the repo). Prints `key=value` lines for $GITHUB_OUTPUT:
release_sha and workflow_sha (from the lock), job_workflow_sha (the job context) and, with --env,
env, family, region, prefix, plan_role, apply_role, deploy_role. Every value is checked against
a fixed pattern first, so none can carry a newline or a second key.

Exit 0 when resolved, 1 with one message per finding on stderr, 2 on usage errors. Standard
library only, Python 3.9 or later.
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # noqa: S404  (the validator at the same SHA)
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_lock  # noqa: E402  (same directory)

PLATFORM = check_lock.PLATFORM
WORKFLOW_FILE_RE = re.compile(r"^\.github/workflows/reusable-[a-z0-9-]+\.yml$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ENV_RE = re.compile(r"^[a-z][a-z0-9]{1,7}$")
FAMILY_RE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-[0-9]$")
PREFIX_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
ROLE_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
VALIDATOR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "intake", "sis_intake", "validate.py"
)
VALIDATOR_TIMEOUT = 120


def check_identity(environ: Dict[str, str]) -> Tuple[Optional[str], List[str]]:
    """O11: the job context names this repository, a reusable file and a full SHA."""
    problems: List[str] = []
    repository = environ.get("JOB_WORKFLOW_REPOSITORY", "")
    path = environ.get("JOB_WORKFLOW_FILE_PATH", "")
    sha = environ.get("JOB_WORKFLOW_SHA", "")
    if repository.lower() != PLATFORM.lower():
        problems.append(f"job.workflow_repository is '{repository}', not {PLATFORM} (O11)")
    if not WORKFLOW_FILE_RE.fullmatch(path):
        problems.append(
            f"job.workflow_file_path is '{path}', not .github/workflows/reusable-*.yml (O11)"
        )
    if not SHA_RE.fullmatch(sha):
        problems.append("job.workflow_sha is not a 40-hex commit SHA (O11)")
        return None, problems
    return sha, problems


def load_lock(caller: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    text, errs = check_lock.read_text(caller, "platform.lock")
    if text is None:
        return None, errs
    try:
        doc = check_lock.load_json(text)
    except ValueError as exc:
        return None, [f"platform.lock: invalid JSON ({exc})"]
    problems = check_lock.check_lock_schema("platform.lock", doc)
    return (None if problems else doc), problems


def run_validator(manifest: str, *args: str) -> Tuple[int, str, str]:
    cmd = [sys.executable, "-I", VALIDATOR, manifest, *args]
    try:
        done = subprocess.run(  # noqa: S603
            cmd, capture_output=True, check=False, timeout=VALIDATOR_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return 2, "", f"the validator timed out after {VALIDATOR_TIMEOUT} seconds"
    return (
        done.returncode,
        done.stdout.decode(errors="replace"),
        done.stderr.decode(errors="replace"),
    )


def checked(problems: List[str], name: str, value: Any, pattern: re.Pattern[str]) -> str:
    text = value if isinstance(value, str) else ""
    if not pattern.fullmatch(text):
        problems.append(f"resolved plan: {name} '{value}' does not match {pattern.pattern}")
    return text


def resolve_env(caller: str, env: str, tfvars: Optional[str]) -> Tuple[Dict[str, str], List[str]]:
    manifest = os.path.join(caller, "platform.yaml")
    code, out, err = run_validator(manifest, "--json", "--context", "lint")
    try:
        plan = json.loads(out) if out else None
    except ValueError:
        plan = None
    if code != 0 or not isinstance(plan, dict) or plan.get("valid") is not True:
        findings = plan.get("findings", []) if isinstance(plan, dict) else []
        lines = [
            f"{f.get('id')} {f.get('path')}: {f.get('message')}"
            for f in findings
            if isinstance(f, dict) and f.get("severity") == "error"
        ]
        detail = "; ".join(lines) or err.strip() or f"exit code {code}"
        return {}, [f"platform.yaml is not valid under --context lint (M8): {detail}"]
    envs: Dict[str, Any] = plan["envs"] if isinstance(plan.get("envs"), dict) else {}
    if env not in envs:
        return {}, [f"env '{env}' is not an env of platform.yaml (M6)"]
    slice_: Dict[str, Any] = envs[env] if isinstance(envs[env], dict) else {}
    runtime: Dict[str, Any] = plan["runtime"] if isinstance(plan.get("runtime"), dict) else {}
    roles: Dict[str, Any] = slice_["roles"] if isinstance(slice_.get("roles"), dict) else {}
    problems: List[str] = []
    out_map = {
        "env": env,
        "family": checked(problems, "runtime.family", runtime.get("family"), FAMILY_RE),
        "region": checked(problems, f"envs.{env}.region", slice_.get("region"), REGION_RE),
        "prefix": checked(problems, f"envs.{env}.prefix", slice_.get("prefix"), PREFIX_RE),
    }
    for kind in ("plan", "apply", "deploy"):
        name = checked(problems, f"envs.{env}.roles.{kind}", roles.get(kind), ROLE_RE)
        expected = f"{out_map['prefix']}-{env}-gha-{kind}"
        if name and name != expected:
            problems.append(f"resolved plan: envs.{env}.roles.{kind} is '{name}', not {expected}")
        out_map[f"{kind}_role"] = name
    if problems:
        return {}, problems
    if tfvars is not None:
        code, out, err = run_validator(manifest, "--emit", "tfvars", "--env", env)
        try:
            emitted = json.loads(out)
        except ValueError:
            emitted = None
        if code != 0 or not isinstance(emitted, dict) or "platform" not in emitted:
            return {}, [f"--emit tfvars --env {env} failed (M7): {err.strip() or code}"]
        fd = os.open(tfvars, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(emitted, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return out_map, []


def main(argv: List[str], environ: Dict[str, str]) -> int:
    caller: Optional[str] = None
    env: Optional[str] = None
    tfvars: Optional[str] = None
    trust_only = False
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--trust-only":
            trust_only = True
        elif arg in ("--caller", "--env", "--tfvars") and args:
            value = args.pop(0)
            if arg == "--caller":
                caller = value
            elif arg == "--env":
                env = value
            else:
                tfvars = value
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if caller is None or trust_only == (env is not None) or (trust_only and tfvars is not None):
        print(__doc__, file=sys.stderr)
        return 2
    if env is not None and not ENV_RE.fullmatch(env):
        print(f"env '{env}' must match {ENV_RE.pattern} (AA1)", file=sys.stderr)
        return 1

    sha, problems = check_identity(environ)
    lock, lock_problems = load_lock(caller)
    problems += lock_problems
    if sha is not None and lock is not None and sha not in lock["trusted_workflow_shas"]:
        problems.append(
            f"job.workflow_sha {sha} is not in platform.lock trusted_workflow_shas (O11, L1)"
        )
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    assert lock is not None and sha is not None  # noqa: S101  (narrowing for the type checker)
    outputs = {
        "release_sha": lock["release_sha"],
        "workflow_sha": lock["workflow_sha"],
        "job_workflow_sha": sha,
    }
    if env is not None:
        resolved, problems = resolve_env(caller, env, tfvars)
        if problems:
            for problem in problems:
                print(problem, file=sys.stderr)
            return 1
        outputs.update(resolved)
    for key, value in outputs.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], dict(os.environ)))
