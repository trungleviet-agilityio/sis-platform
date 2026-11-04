#!/usr/bin/env python3
"""Read-only audit of a GitHub repository's settings against the sis-platform baseline (ADR 0001 A12, ADR 0002 O13).

Run it through check-settings.sh. It only issues `gh api` GET requests (see api_get) and prints names, never values.
Python 3.9, standard library only.

Checks (each failure is one `FAIL` line; the exit code is 1 when there is any):
  visibility    the repository is public (F30: environment reviewers need it on Free, Pro and Team)
  branch        an active ruleset on the default branch: deletion, non_fast_forward, pull_request squash only,
                required status check `check` (GitHub Actions), no bypass actors
  tag           an active ruleset on refs/tags/v*: update and deletion blocked (immutable tags)
  environments  every required environment (dev, prod for a repo named *-canary) exists with a required reviewer and
                custom branch policies restricted to exactly `main`; any other environment is checked the same way
  names         secret and variable names against the O13 allowlist
  actions       SHA pinning required, read-only default workflow token, secret scanning with push protection
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional

GITHUB_ACTIONS_APP_ID = 15368
REQUIRED_CHECK = "check"
DEFAULT_ENVS_FOR_CANARY = ["dev", "prod"]
ENV_SECRET_ALLOWLIST = {"AWS_ACCOUNT_ID"}  # O13: the one environment secret
# O13: plan callers read AWS_ACCOUNT_ID_<ENV> from repo secrets. No repo variable may exist (OD2: releases come from
# platform.yaml only, and the account ID is a secret, not a variable).
REPO_SECRET_RE = re.compile(r"^AWS_ACCOUNT_ID_[A-Z0-9]+$")


class ApiError(Exception):
    pass


def api_get(path: str) -> Any:
    """The only GitHub access in this script: `gh api <path>`, which is a GET unless -X, -f, -F or --input is given.

    No such flag is ever passed, and the path must be a repository read, so no write is possible from here."""
    if not path.startswith("/repos/"):
        raise ApiError("refusing a non-repository path: %s" % path)
    cmd = [
        "gh", "api",
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2022-11-28",
        path,
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    except OSError as exc:
        raise ApiError("cannot run gh: %s" % exc)
    if proc.returncode != 0:
        first = (proc.stderr.strip().splitlines() or ["no output"])[0]
        raise ApiError("GET %s failed: %s" % (path, first))
    try:
        return json.loads(proc.stdout)
    except ValueError:
        raise ApiError("GET %s returned invalid JSON" % path)


class Report:
    def __init__(self) -> None:
        self.failures = 0

    def ok(self, msg: str) -> None:
        print("ok   %s" % msg)

    def warn(self, msg: str) -> None:
        print("WARN %s" % msg)

    def fail(self, msg: str) -> None:
        self.failures += 1
        print("FAIL %s" % msg)


def names(payload: Any, key: str) -> List[str]:
    return sorted(str(item.get("name", "")) for item in (payload or {}).get(key, []))


def check_repo(base: str, rep: Report) -> Dict[str, Any]:
    repo = api_get(base)
    if repo.get("private") or repo.get("visibility", "public") != "public":
        rep.fail("repository is private (visibility %s); required reviewers need a public repo on Free, Pro or Team"
                 % repo.get("visibility", "private"))
    else:
        rep.ok("repository is public")
    sa = repo.get("security_and_analysis")
    if not isinstance(sa, dict):
        rep.warn("security_and_analysis not reported (token lacks admin read?); secret scanning not checked")
    else:
        for key, label in (("secret_scanning", "secret scanning"),
                           ("secret_scanning_push_protection", "secret scanning push protection")):
            status = (sa.get(key) or {}).get("status")
            if status == "enabled":
                rep.ok("%s enabled" % label)
            elif status is None:
                rep.warn("%s status not reported" % label)
            else:
                rep.fail("%s is %s, expected enabled" % (label, status))
    return repo


def rule_types(rulesets: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out = {}  # type: Dict[str, Dict[str, Any]]
    for rs in rulesets:
        for rule in rs.get("rules", []):
            out.setdefault(rule.get("type", ""), {}).update(rule.get("parameters") or {})
    return out


def load_rulesets(base: str, target: str) -> List[Dict[str, Any]]:
    listing = api_get(base + "/rulesets?includes_parents=false&per_page=100")
    return [api_get("%s/rulesets/%s" % (base, item["id"])) for item in listing if item.get("target") == target]


def includes(rs: Dict[str, Any]) -> List[str]:
    return list(((rs.get("conditions") or {}).get("ref_name") or {}).get("include") or [])


def check_branch(base: str, default_branch: str, rep: Report) -> None:
    covering = [rs for rs in load_rulesets(base, "branch")
                if set(includes(rs)) & {"~DEFAULT_BRANCH", "~ALL", "refs/heads/" + default_branch}]
    if not covering:
        rep.fail("no branch ruleset covers the default branch '%s'" % default_branch)
        return
    active = [rs for rs in covering if rs.get("enforcement") == "active"]
    if not active:
        for rs in covering:
            rep.fail("branch ruleset '%s' enforcement is '%s', expected 'active'" % (rs.get("name"), rs.get("enforcement")))
        return
    rep.ok("active branch ruleset on '%s': %s" % (default_branch, ", ".join(rs.get("name", "?") for rs in active)))
    rules = rule_types(active)
    for needed in ("deletion", "non_fast_forward", "pull_request", "required_status_checks"):
        if needed not in rules:
            rep.fail("branch ruleset is missing rule %s" % needed)
    if "pull_request" in rules:
        methods = rules["pull_request"].get("allowed_merge_methods")
        if methods != ["squash"]:
            rep.fail("pull_request rule must allow only squash merges (got: %s)"
                     % (",".join(methods) if methods else "unset"))
    if "required_status_checks" in rules:
        checks = rules["required_status_checks"].get("required_status_checks") or []
        mine = [c for c in checks if c.get("context") == REQUIRED_CHECK]
        if not mine:
            rep.fail("required status check '%s' is missing from the branch ruleset" % REQUIRED_CHECK)
        else:
            app = mine[0].get("integration_id")
            if app is None:
                rep.warn("required check '%s' accepts any source; pin it to GitHub Actions (integration %d)"
                         % (REQUIRED_CHECK, GITHUB_ACTIONS_APP_ID))
            elif app != GITHUB_ACTIONS_APP_ID:
                rep.fail("required check '%s' comes from integration %s, expected GitHub Actions (%d)"
                         % (REQUIRED_CHECK, app, GITHUB_ACTIONS_APP_ID))
            else:
                rep.ok("required check '%s' from GitHub Actions" % REQUIRED_CHECK)
    bypass = [b for rs in active for b in (rs.get("bypass_actors") or [])]
    if bypass:
        rep.fail("branch ruleset has %d bypass actor(s); none are allowed" % len(bypass))
    else:
        rep.ok("branch ruleset has no bypass actors")


def check_tag(base: str, rep: Report) -> None:
    covering = [rs for rs in load_rulesets(base, "tag") if set(includes(rs)) & {"refs/tags/v*", "refs/tags/*", "~ALL"}]
    if not covering:
        rep.fail("no tag ruleset covers refs/tags/v*")
        return
    active = [rs for rs in covering if rs.get("enforcement") == "active"]
    if not active:
        for rs in covering:
            rep.fail("tag ruleset '%s' enforcement is '%s', expected 'active'" % (rs.get("name"), rs.get("enforcement")))
        return
    rules = rule_types(active)
    for needed in ("update", "deletion"):
        if needed not in rules:
            rep.fail("tag ruleset is missing rule %s" % needed)
    if "update" in rules and "deletion" in rules:
        rep.ok("tag ruleset blocks update and deletion of refs/tags/v*")


def check_env(base: str, name: str, rep: Report) -> None:
    env = api_get("%s/environments/%s" % (base, name))
    reviewers = []  # type: List[Any]
    for rule in env.get("protection_rules", []):
        if rule.get("type") == "required_reviewers":
            reviewers.extend(rule.get("reviewers") or [])
    if reviewers:
        rep.ok("environment '%s' has %d required reviewer(s)" % (name, len(reviewers)))
    else:
        rep.fail("environment '%s' has no required reviewers" % name)
    dbp = env.get("deployment_branch_policy") or {}
    if not dbp.get("custom_branch_policies") or dbp.get("protected_branches"):
        rep.fail("environment '%s' deployment branches are not restricted to custom branch policies" % name)
    else:
        listing = api_get("%s/environments/%s/deployment-branch-policies" % (base, name))
        got = sorted("%s:%s" % (p.get("type", "branch"), p.get("name")) for p in listing.get("branch_policies", []))
        if got == ["branch:main"]:
            rep.ok("environment '%s' deploys from branch main only" % name)
        else:
            rep.fail("environment '%s' branch policy must be exactly main (got: %s)" % (name, ", ".join(got) or "none"))
    for s in names(api_get("%s/environments/%s/secrets?per_page=100" % (base, name)), "secrets"):
        if s not in ENV_SECRET_ALLOWLIST:
            rep.fail("environment '%s' secret '%s' is not in the allowlist (%s)"
                     % (name, s, ", ".join(sorted(ENV_SECRET_ALLOWLIST))))
    for v in names(api_get("%s/environments/%s/variables?per_page=100" % (base, name)), "variables"):
        rep.fail("environment '%s' variable '%s' is not allowed (no variable may hold release behavior)" % (name, v))


def check_environments(base: str, required: List[str], rep: Report) -> List[str]:
    present = names(api_get(base + "/environments?per_page=100"), "environments")
    for want in required:
        if want not in present:
            rep.fail("environment '%s' not found" % want)
    for name in present:
        check_env(base, name, rep)
    return present


def check_names(base: str, required: List[str], present_envs: List[str], rep: Report) -> None:
    before = rep.failures
    repo_secrets = names(api_get(base + "/actions/secrets?per_page=100"), "secrets")
    for s in repo_secrets:
        if not REPO_SECRET_RE.match(s):
            rep.fail("repo secret '%s' is not in the allowlist (AWS_ACCOUNT_ID_<ENV>)" % s)
    for v in names(api_get(base + "/actions/variables?per_page=100"), "variables"):
        rep.fail("repo variable '%s' is not allowed (no variable may hold release behavior)" % v)
    for env in required:
        want = "AWS_ACCOUNT_ID_%s" % env.upper()
        if want not in repo_secrets:
            rep.fail("repo secret '%s' is missing (plan callers read it)" % want)
        if env in present_envs:
            env_secrets = names(api_get("%s/environments/%s/secrets?per_page=100" % (base, env)), "secrets")
            if "AWS_ACCOUNT_ID" not in env_secrets:
                rep.fail("environment '%s' lacks secret AWS_ACCOUNT_ID" % env)
    if rep.failures == before:
        rep.ok("secret and variable names match the O13 allowlist")


def check_actions(base: str, rep: Report) -> None:
    perms = api_get(base + "/actions/permissions")
    if perms.get("enabled") is False:
        rep.warn("GitHub Actions is disabled for this repository")
    pinned = perms.get("sha_pinning_required")
    if pinned is True:
        rep.ok("Actions SHA pinning is required")
    elif pinned is None:
        rep.fail("Actions SHA pinning: sha_pinning_required not reported; confirm the setting in the UI")
    else:
        rep.fail("Actions SHA pinning is not required (sha_pinning_required is false)")
    wf = api_get(base + "/actions/permissions/workflow")
    token = wf.get("default_workflow_permissions")
    if token == "read":
        rep.ok("default workflow permissions are read")
    else:
        rep.fail("default workflow permissions are '%s', expected 'read'" % token)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only GitHub settings audit (A12).")
    ap.add_argument("repo", help="OWNER/REPO")
    ap.add_argument("--envs", help="comma separated environments that must exist (default: dev,prod for a repo named "
                    "*-canary, none otherwise; pass '' for none)")
    args = ap.parse_args(argv)
    if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", args.repo):
        print("error: repo must be OWNER/REPO", file=sys.stderr)
        return 2
    if args.envs is not None:
        required = [e for e in args.envs.split(",") if e]
    elif args.repo.endswith("-canary"):
        required = list(DEFAULT_ENVS_FOR_CANARY)
    else:
        required = []
    base = "/repos/" + args.repo
    rep = Report()
    try:
        repo = check_repo(base, rep)
        check_branch(base, repo.get("default_branch", "main"), rep)
        check_tag(base, rep)
        present = check_environments(base, required, rep)
        check_names(base, required, present, rep)
        check_actions(base, rep)
    except ApiError as exc:
        print("FAIL cannot read settings: %s" % exc)
        return 1
    print("%d failure(s)" % rep.failures)
    return 1 if rep.failures else 0


if __name__ == "__main__":
    sys.exit(main())
