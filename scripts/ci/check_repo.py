#!/usr/bin/env python3
"""Repo guard: structural rules for workflows and the Makefile (ADR 0001 Z9, ADR 0002 H1 to H10).

Usage:
  check_repo.py workflow FILE...        rules for GitHub workflow files (listed below)
  check_repo.py makefile FILE...        no target name containing apply or destroy
  check_repo.py closure --repo DIR --closure FILE WORKFLOW...
                                        every `.platform/<path>` a workflow uses is covered by the
                                        closure pathspecs (H6)
  check_repo.py repo [ROOT]             everything above, discovered under ROOT (default: .)

Workflow rules:
  H1  every `uses:` (read from parsed YAML, flow style included) is pinned by a 40-hex SHA, with a
      `# vX.Y.Z` comment; local ./ actions are the only exception
  H2  top-level `permissions: {}`; no write-all or read-all at any level; `id-token: write` only
      on a job that assumes a role, prints OIDC claims or calls a reusable workflow
  H3  harden-runner is the first step of every job; a credentialed job (id-token: write) uses
      `egress-policy: block` with exact hosts and no wildcard; account hosts come only from
      `secrets.AWS_ACCOUNT_ID*`, the region only from `needs.resolve.outputs.region` or a literal;
      a credentialed job in a reusable workflow is gated by `needs.resolve.outputs.family == '<x>'`
  H4  triggers are pull_request, push or workflow_call; a `reusable-*.yml` declares
      workflow_call only; the consumer profile (examples/consumer) also allows schedule (W5
      weekly platform check) and workflow_dispatch with the inputs env (choice), sha and digest only
  H5  a checkout of sis-platform uses `ref: ${{ job.workflow_sha }}` and a non-cone
      `sparse-checkout`
  H8  workflow concurrency cancels in progress only for pull_request, never for pushes
  H10 a job with `id-token: write` or an `environment` sits under a concurrency group with
      `cancel-in-progress: false`
  AA3 in reusable-terraform-apply.yml, the `resolve` job and every credentialed job start (after
      harden-runner) with a step that refuses events other than push and workflow_dispatch and
      refs other than refs/heads/main

Exit 0 when clean, 1 with one message per finding on stderr, 2 on usage errors.
Needs PyYAML (workflow and repo modes).

The harden-runner policy is ported and simplified from ship-it-safely
scripts/guard/harden_runner_policy.py (lab ADR 0007 S45, A9),
and the duplicate-key YAML loader from workflow_yaml.py there.
"""

from __future__ import annotations

import os
import posixpath
import re
import subprocess  # noqa: S404  (git ls-files for the closure check)
import sys
from typing import Any

ALLOWED_TRIGGERS = {"pull_request", "push", "workflow_call"}
# A consumer also runs the W5 platform check weekly (schedule) and dispatches applies and smokes.
CONSUMER_TRIGGERS = ALLOWED_TRIGGERS | {"workflow_dispatch", "schedule"}
CONSUMER_INPUTS = ("env", "sha", "digest")
PLATFORM_REPO = "trungleviet-agilityio/sis-platform"
SHA_RE = re.compile(r"@[0-9a-f]{40}$")
VERSION_COMMENT_RE = re.compile(r"#\s*v\d+\.\d+\.\d+")
TARGET_RE = re.compile(r"^([A-Za-z0-9_./%$()-]+(?:\s+[A-Za-z0-9_./%$()-]+)*)\s*:(?!=)")
HARDEN_ACTION = "step-security/harden-runner@"
# One endpoint is a run of non-space characters; `${{ ... }}` may hold spaces and stays whole.
ENDPOINT_RE = re.compile(r"(?:\$\{\{.*?\}\}|\S)+")
EXPRESSION_RE = re.compile(r"\$\{\{\s*(.*?)\s*\}\}", re.DOTALL)
PORT_RE = re.compile(r":[0-9]{1,5}$")
ACCOUNT_ID_RE = re.compile(r"(?<![0-9A-Za-z])[0-9]{12}(?![0-9A-Za-z])")
ACCOUNT_EXPR_RE = re.compile(r"^secrets\.AWS_ACCOUNT_ID(_[A-Z0-9]+)?$")
REGION_EXPR = "needs.resolve.outputs.region"
VARS_EXPR_RE = re.compile(r"^vars\.[A-Za-z_][A-Za-z0-9_]*$")
FAMILY_TERM_RE = re.compile(r"needs\.resolve\.outputs\.family=='[A-Za-z0-9_-]+'")
# Reusable files whose credentialed jobs are not per runtime family (claims and trust smoke test).
FAMILY_EXEMPT = ("reusable-oidc-smoke.yml",)
CANCEL_PR_ONLY = "${{ github.event_name == 'pull_request' }}"
ASSUME_RUN_RE = re.compile(
    r"ACTIONS_ID_TOKEN_REQUEST|assume-role|assume_role|getIDToken|job_workflow_ref", re.IGNORECASE
)
ASSUME_ACTIONS = ("aws-actions/configure-aws-credentials@",)
PLATFORM_PATH_RE = re.compile(r"\.platform/([A-Za-z0-9_./-]+)")
DIR_REF_RE = re.compile(
    r"""(?:\$\(dirname\s+"?\$\{?(?:0|BASH_SOURCE\[0\])\}?"?\)|\$\{?(?P<root>ROOT)\}?)"""
    r"""/(?P<rel>[^"'\s;&|)]+)"""
)
CALL_RE = re.compile(
    r"""(?:^|&&|\|\||[;(]|\bthen\b|\bdo\b|\belse\b)\s*(?:(?:bash|sh|source|\.)\s+|(?=\./))"""
    r"""["']?(?P<p>[^\s"';&|)]+)"""
)


def read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        print(f"{path}: cannot read ({exc.strerror})", file=sys.stderr)
        return None


def load_yaml(text: str) -> Any:
    """Parse YAML, refusing a mapping with a repeated key (GitHub keeps one, PyYAML the last)."""
    import yaml  # imported here so makefile mode works without PyYAML

    class UniqueKeyLoader(yaml.SafeLoader):
        def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
            self.flatten_mapping(node)
            mapping = super().construct_mapping(node, deep=deep)
            if len(mapping) != len(node.value):
                raise yaml.constructor.ConstructorError(
                    None, None, "duplicate key in a mapping", node.start_mark
                )
            return mapping

    loader = UniqueKeyLoader(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def parse_yaml(path: str) -> tuple[str, Any, list[str]]:
    """Read and parse one YAML file: (text, document, problems). Problems is empty on success."""
    import yaml

    text = read(path)
    if text is None:
        return "", None, [f"{path}: cannot read"]
    try:
        return text, load_yaml(text), []
    except yaml.YAMLError as exc:
        return text, None, [f"{path}: invalid YAML ({exc})"]


def collect_uses(node: Any) -> list[str]:
    """Every string value under a `uses` key anywhere in the parsed document."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                found.append(value.strip())
            else:
                found.extend(collect_uses(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(collect_uses(item))
    return found


def check_uses(path: str, text: str, doc: Any) -> list[str]:
    """H1: SHA pin and `# vX.Y.Z` comment for every `uses:`."""
    problems: list[str] = []
    lines = text.splitlines()
    for ref in collect_uses(doc):
        if ref.startswith("./"):
            continue
        if not SHA_RE.search(ref):
            problems.append(f"{path}: uses '{ref}' is not pinned by a 40-hex SHA")
            continue
        at = [i for i, line in enumerate(lines, 1) if ref in line and "uses" in line]
        if not at or not all(VERSION_COMMENT_RE.search(lines[i - 1]) for i in at):
            where = f"{path}:{at[0]}" if at else path
            problems.append(f"{where}: uses '{ref}' has no '# vX.Y.Z' version comment")
    return problems


def triggers_of(doc: dict[Any, Any]) -> tuple[set[str], Any]:
    # YAML 1.1 reads the bare key `on` as boolean True.
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        return {on}, on
    if isinstance(on, (list, dict)):
        return {str(t) for t in on}, on
    return set(), on


def perms_problems(where: str, perms: Any) -> list[str]:
    if isinstance(perms, str) and perms.strip().lower() in ("write-all", "read-all"):
        return [f"{where}: permissions '{perms}' is not allowed (list the scopes you need)"]
    return []


def has_id_token(perms: Any) -> bool:
    value = perms.get("id-token") if isinstance(perms, dict) else None
    return isinstance(value, str) and value.strip().lower() == "write"


def effective_lines(script: str) -> str:
    """Script lines that can run something: no comments, no echo or printf."""
    kept = []
    for line in script.splitlines():
        text = line.strip()
        if text and not text.startswith(("#", "echo ", "printf ")):
            kept.append(text)
    return "\n".join(kept)


def job_assumes_role(job: dict[str, Any]) -> bool:
    """Advisory heuristic for H2: a text match, not proof that the step really assumes a role."""
    if "uses" in job:  # a call of a reusable workflow: the callee assumes the role
        return True
    steps = job.get("steps")
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict):
            continue
        uses = step.get("uses")
        if isinstance(uses, str) and uses.startswith(ASSUME_ACTIONS):
            return True
        run = step.get("run")
        if isinstance(run, str) and ASSUME_RUN_RE.search(effective_lines(run)):
            return True
        script = (
            (step.get("with") or {}).get("script") if isinstance(step.get("with"), dict) else None
        )
        if isinstance(script, str) and ASSUME_RUN_RE.search(effective_lines(script)):
            return True
    return False


def family_gated(condition: Any) -> bool:
    """Whether an `if:` is the family test, optionally AND-ed with other terms (never OR-ed)."""
    text = re.sub(r"\s+", "", str(condition))
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2]
    if "||" in text or "${{" in text:
        return False
    return any(FAMILY_TERM_RE.fullmatch(term) for term in text.split("&&"))


def push_cancel_problems(where: str, concurrency: Any) -> list[str]:
    """H8: on a push workflow, cancel-in-progress is false or exactly the pull_request-only test."""
    cancel = cancel_value(concurrency)
    if cancel is None or is_false(cancel):
        return []
    if re.sub(r"\s+", " ", str(cancel)).strip() == CANCEL_PR_ONLY:
        return []
    return [
        f"{where}: concurrency cancels in progress for pushes; use "
        f"cancel-in-progress: {CANCEL_PR_ONLY} (H8)"
    ]


def cancel_value(concurrency: Any) -> Any:
    if isinstance(concurrency, dict) and "group" in concurrency:
        return concurrency.get("cancel-in-progress", False)
    return None  # no usable group


def is_false(value: Any) -> bool:
    return value is False or (isinstance(value, str) and value.strip().lower() == "false")


def is_true(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def endpoint_problems(endpoint: str, credentialed: bool) -> list[str]:
    problems: list[str] = []
    expressions = EXPRESSION_RE.findall(endpoint)
    literal = EXPRESSION_RE.sub("", endpoint)
    if not PORT_RE.search(endpoint):
        problems.append(f"endpoint '{endpoint}' has no :port")
    if ACCOUNT_ID_RE.search(literal):
        problems.append("an endpoint holds a 12-digit literal (build it from a secret expression)")
    if credentialed:
        if "*" in literal:
            problems.append(f"endpoint '{endpoint}' holds a wildcard (list exact hosts)")
        problems.extend(
            f"endpoint '{endpoint}' uses the expression '{e}' (allowed: secrets.AWS_ACCOUNT_ID*, "
            f"{REGION_EXPR})"
            for e in expressions
            if not ACCOUNT_EXPR_RE.match(e) and e != REGION_EXPR
        )
    else:
        for e in expressions:
            if re.search(r"\bsecrets\b", e, re.IGNORECASE):
                problems.append(
                    f"endpoint '{endpoint}' reads a secret in a job without credentials"
                )
            elif not VARS_EXPR_RE.match(e) and e != REGION_EXPR:
                problems.append(
                    f"endpoint '{endpoint}' uses the expression '{e}' (a job without "
                    f"credentials may use vars.X and {REGION_EXPR} only)"
                )
    return problems


def harden_problems(job: dict[str, Any], credentialed: bool) -> list[str]:
    steps = job.get("steps")
    first = steps[0] if isinstance(steps, list) and steps else None
    uses = first.get("uses") if isinstance(first, dict) else None
    if not isinstance(uses, str) or not uses.startswith(HARDEN_ACTION):
        return ["the first step is not step-security/harden-runner"]
    assert isinstance(first, dict)  # noqa: S101  (narrowing for the type checker)
    problems = [
        f"harden-runner must not set `{k}:`" for k in ("if", "continue-on-error") if k in first
    ]
    raw_with = first.get("with")
    with_: dict[str, Any] = raw_with if isinstance(raw_with, dict) else {}
    policy = with_.get("egress-policy")
    if credentialed:
        if policy != "block":
            problems.append("has id-token: write, so egress-policy must be block")
        problems.extend(
            f"has id-token: write, so {key} must be true"
            for key in ("disable-telemetry", "disable-sudo-and-containers")
            if not is_true(with_.get(key))
        )
        if "container" in job or "services" in job:
            problems.append("has id-token: write, so `container:` and `services:` are not allowed")
    elif policy != "audit":
        problems.append("has no id-token: write, so egress-policy must be audit (written out)")
    endpoints = with_.get("allowed-endpoints")
    for endpoint in ENDPOINT_RE.findall(endpoints if isinstance(endpoints, str) else ""):
        problems.extend(endpoint_problems(endpoint, credentialed))
    return problems


def checkout_problems(job: dict[str, Any], reusable: bool = False) -> list[str]:
    problems: list[str] = []
    steps = job.get("steps")
    for step in steps if isinstance(steps, list) else []:
        uses = step.get("uses") if isinstance(step, dict) else None
        with_ = step.get("with") if isinstance(step, dict) else None
        if not (isinstance(uses, str) and uses.startswith("actions/checkout@")):
            continue
        if not isinstance(with_, dict):
            continue
        repository = str(with_.get("repository", ""))
        literal = repository.lower() == PLATFORM_REPO
        # In a reusable file a checkout into .platform, or of a computed repository, is the
        # platform checkout.
        into_platform = str(with_.get("path", "")).strip().strip("./") == "platform"
        if not literal and not (reusable and (into_platform or "${{" in repository)):
            continue
        if not literal:
            problems.append(
                f"a platform checkout must set repository to the literal {PLATFORM_REPO}, "
                "not an expression (O11)"
            )
        ref = re.sub(r"\s+", "", str(with_.get("ref", "")))
        if ref != "${{job.workflow_sha}}":
            problems.append("a platform checkout must use ref: ${{ job.workflow_sha }} (H5)")
        if not with_.get("sparse-checkout"):
            problems.append("a platform checkout must set sparse-checkout (H5)")
        elif not is_false(with_.get("sparse-checkout-cone-mode")):
            problems.append("a platform checkout must set sparse-checkout-cone-mode: false (O11)")
    return problems


def check_triggers(path: str, doc: dict[Any, Any], consumer: bool, reusable: bool) -> list[str]:
    problems: list[str] = []
    triggers, on = triggers_of(doc)
    if not triggers:
        return [f"{path}: no 'on:' triggers found"]
    allowed = CONSUMER_TRIGGERS if consumer else ALLOWED_TRIGGERS
    for trigger in sorted(triggers - allowed):
        names = "pull_request, push, workflow_call" + (
            ", schedule, workflow_dispatch with inputs env, sha, digest" if consumer else ""
        )
        problems.append(f"{path}: trigger '{trigger}' is not allowed (only {names})")
    if reusable:
        for trigger in sorted(triggers - {"workflow_call"}):
            if trigger in allowed:
                problems.append(
                    f"{path}: reusable workflow declares trigger '{trigger}' "
                    "(only workflow_call is allowed)"
                )
    if consumer and isinstance(on, dict) and "workflow_dispatch" in on:
        section = on["workflow_dispatch"]
        inputs = section.get("inputs") if isinstance(section, dict) else None
        for name, definition in (inputs if isinstance(inputs, dict) else {}).items():
            if name not in CONSUMER_INPUTS:
                problems.append(
                    f"{path}: workflow_dispatch input '{name}' is not allowed "
                    f"(only {', '.join(CONSUMER_INPUTS)})"
                )
            elif name == "env" and not (
                isinstance(definition, dict) and definition.get("type") == "choice"
            ):
                problems.append(f"{path}: workflow_dispatch input 'env' must be type: choice")
    return problems


PLATFORM_BARE_RE = re.compile(r"\.platform(?![A-Za-z0-9_.-]|/)")
PATH_LINE_RE = re.compile(r"""^\s*path:\s*["']?\.platform["']?\s*$""")


def reusable_problems(path: str, text: str, doc: Any) -> list[str]:
    """Extra rules for reusable-*.yml: no local actions; every .platform use is a visible path."""
    problems = [
        f"{path}: uses the local action '{ref}', which the caller's checkout does not hold"
        for ref in collect_uses(doc)
        if ref.startswith("./")
    ]
    for lineno, line in enumerate(text.splitlines(), 1):
        code = line.split(" #")[0]
        if re.search(r"working-directory:.*\.platform", code):
            problems.append(
                f"{path}:{lineno}: working-directory under .platform hides script paths from the "
                "closure check (H6); write the full .platform/<path>"
            )
        elif PLATFORM_BARE_RE.search(code) and not PATH_LINE_RE.match(code):
            problems.append(
                f"{path}:{lineno}: refers to .platform without a trailing slash, so the closure "
                "check cannot see the path (H6); write .platform/<path>"
            )
    return problems


APPLY_FILE = "reusable-terraform-apply.yml"
# The one accepted text of the AA3 gate step (compared with all whitespace removed).
APPLY_GATE_RUN = """
case "$EVENT" in
  push | workflow_dispatch) ;;
  *) echo "::error::apply runs only on push or workflow_dispatch, not on ${EVENT} (AA3)"; exit 1 ;;
esac
if [ "$REF" != "refs/heads/main" ]; then
  echo "::error::apply runs only from refs/heads/main, not from ${REF} (O1)"
  exit 1
fi
"""
APPLY_GATE_MESSAGE = (
    "the step after harden-runner must be the AA3 gate: env EVENT and REF only, and the run text "
    "of APPLY_GATE_RUN in scripts/ci/check_repo.py, refusing events other than push and "
    "workflow_dispatch and refs other than refs/heads/main (AA3)"
)


def squash(value: Any) -> str:
    return re.sub(r"\s+", "", str(value))


def apply_gate_problems(job: dict[str, Any]) -> list[str]:
    """AA3: in the apply workflow, the step after harden-runner refuses other events and refs.

    Literal on purpose: the step's env is exactly EVENT (github.event_name) and REF (github.ref),
    its `run` equals APPLY_GATE_RUN with whitespace ignored, and it sets no `if`,
    `continue-on-error`, `shell`, `working-directory` or `uses` that could skip or soften it.
    """
    steps = job.get("steps")
    step = steps[1] if isinstance(steps, list) and len(steps) > 1 else None
    if not isinstance(step, dict):
        return [APPLY_GATE_MESSAGE]
    problems = [
        f"the AA3 gate step must not set `{key}:`"
        for key in ("if", "continue-on-error", "shell", "working-directory", "uses")
        if key in step
    ]
    env = step.get("env")
    ok = (
        isinstance(env, dict)
        and set(env) == {"EVENT", "REF"}
        and squash(env.get("EVENT")) == "${{github.event_name}}"
        and squash(env.get("REF")) == "${{github.ref}}"
        and isinstance(step.get("run"), str)
        and squash(step["run"]) == squash(APPLY_GATE_RUN)
    )
    return problems if ok else [*problems, APPLY_GATE_MESSAGE]


def check_workflow(path: str) -> list[str]:
    text, doc, problems = parse_yaml(path)
    if problems:
        return problems
    if not isinstance(doc, dict):
        return [f"{path}: not a workflow mapping"]
    base = os.path.basename(path)
    reusable = base.startswith("reusable-")
    consumer = "examples/consumer/" in path.replace(os.sep, "/")

    problems = check_uses(path, text, doc)
    if reusable:
        problems += reusable_problems(path, text, doc)
    if doc.get("permissions", "missing") != {}:
        problems.append(f"{path}: top-level 'permissions: {{}}' is required")
    problems += perms_problems(path, doc.get("permissions"))
    problems += check_triggers(path, doc, consumer, reusable)

    triggers, _ = triggers_of(doc)
    if "push" in triggers:
        problems += push_cancel_problems(path, doc.get("concurrency"))

    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return [*problems, f"{path}: no jobs mapping"]
    for job_id, job in jobs.items():
        job = job if isinstance(job, dict) else {}
        here = f"{path}: job '{job_id}'"
        perms = job.get("permissions", doc.get("permissions"))
        problems += perms_problems(here, job.get("permissions"))
        credentialed = has_id_token(perms)
        if "push" in triggers:
            problems += push_cancel_problems(here, job.get("concurrency"))
        if credentialed and not job_assumes_role(job):
            problems.append(
                f"{here}: id-token: write on a job that neither assumes a role, prints OIDC claims "
                "nor calls a reusable workflow (H2)"
            )
        if credentialed or "environment" in job:
            concurrency = job.get("concurrency", doc.get("concurrency"))
            cancel = cancel_value(concurrency)
            if cancel is None:
                problems.append(
                    f"{here}: has id-token: write or an environment, so it needs a concurrency "
                    "group with cancel-in-progress: false (H10)"
                )
            elif not is_false(cancel):
                problems.append(
                    f"{here}: has id-token: write or an environment, so concurrency "
                    "cancel-in-progress must be false (H10)"
                )
        if "uses" in job:  # a reusable-workflow call has no steps; its callee is checked itself
            continue
        problems += [f"{here}: {m}" for m in harden_problems(job, credentialed)]
        problems += [f"{here}: {m}" for m in checkout_problems(job, reusable)]
        if base == APPLY_FILE and (job_id == "resolve" or credentialed):
            problems += [f"{here}: {m}" for m in apply_gate_problems(job)]
        gated = family_gated(job.get("if", ""))
        if credentialed and reusable and base not in FAMILY_EXEMPT and not gated:
            problems.append(
                f"{here}: a credentialed job in a reusable workflow must be gated by "
                "if: needs.resolve.outputs.family == '<family>' (W2)"
            )
    return problems


def check_uses_only(path: str) -> list[str]:
    """Other YAML under .github (composite actions, dependabot): only the `uses:` pin rule (H1)."""
    text, doc, problems = parse_yaml(path)
    return problems or check_uses(path, text, doc)


def check_makefile(path: str) -> list[str]:
    text = read(path)
    if text is None:
        return [f"{path}: cannot read"]
    problems: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.startswith(("\t", "#")):
            continue
        match = TARGET_RE.match(line)
        if not match:
            continue
        names = match.group(1).split()
        if names and names[0] == ".PHONY":
            names = names[1:]
        for name in names:
            low = name.lower()
            for bad in ("apply", "destroy"):
                if bad in low:
                    problems.append(
                        f"{path}: line {lineno}: target '{name}' contains '{bad}' (never allowed)"
                    )
    return problems


def git_files(repo: str, pathspecs: list[str] | None = None) -> set[str]:
    cmd = ["git", "-C", repo, "ls-files", "-z"]
    if pathspecs is not None:
        if not pathspecs:
            return set()
        cmd += ["--", *pathspecs]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout.decode()  # noqa: S603
    return {p for p in out.split("\0") if p}


def sourced_by(repo: str, rel: str) -> tuple[list[str], list[str]]:
    """Paths a bash script runs or sources, and the calls whose path holds a variable.

    Followed: `$(dirname "$0")/x`, `$(dirname "${BASH_SOURCE[0]}")/x` and `$ROOT/x` anywhere on a
    line, and `source x`, `. x`, `bash x`, `sh x`, `./x` at a command position (line start, after
    `&&`, `||`, `;`, `(`, `then`, `do`, `else`), resolved from the script's directory. Not followed:
    Python imports and data files read by other means, so closure.txt must list whole directories.
    """
    text = read(os.path.join(repo, rel))
    found: list[str] = []
    unresolved: list[str] = []
    for line in (text or "").splitlines():
        if line.lstrip().startswith("#"):
            continue
        for match in DIR_REF_RE.finditer(line):
            base = "" if match.group("root") else posixpath.dirname(rel)
            found.append(posixpath.normpath(posixpath.join(base, match.group("rel"))))
        rest = DIR_REF_RE.sub("@@", line)
        for call in CALL_RE.finditer(rest):
            target = call.group("p")
            if target.startswith(("@@", "-")):
                continue
            if "$" in target:
                unresolved.append(target)
            else:
                found.append(posixpath.normpath(posixpath.join(posixpath.dirname(rel), target)))
    return found, unresolved


def check_closure(workflow: str, repo: str, closure: str) -> list[str]:
    text = read(workflow)
    if text is None:
        return [f"{workflow}: cannot read"]
    refs = sorted({m.rstrip(".") for m in PLATFORM_PATH_RE.findall(text)})
    if not refs:
        return []
    closure_text = read(closure)
    if closure_text is None:
        return [f"{workflow}: uses .platform/ paths but the closure file {closure} cannot be read"]
    specs = [s.strip() for s in closure_text.splitlines() if s.strip() and not s.startswith("#")]
    tracked = git_files(repo)
    covered = git_files(repo, specs)
    problems: list[str] = []
    for ref in refs:
        if ref.endswith("/"):
            files = sorted(f for f in tracked if f.startswith(ref))
        else:
            files = (
                [ref] if ref in tracked else sorted(f for f in tracked if f.startswith(ref + "/"))
            )
        if not files:
            problems.append(
                f"{workflow}: .platform/{ref} is not a tracked file (renamed or removed?) (H6)"
            )
        queue, seen = list(files), set()
        while queue:
            current = queue.pop()
            if current in seen:
                continue
            seen.add(current)
            if current not in covered:
                problems.append(f"{workflow}: .platform/{current} is not covered by {closure} (H6)")
            deps, unresolved = sourced_by(repo, current)
            problems.extend(
                f"{workflow}: .platform/{current} runs or sources {target}, a path with a "
                "variable the closure check cannot resolve (H6)"
                for target in unresolved
            )
            for dep in deps:
                members = (
                    [dep]
                    if dep in tracked
                    else sorted(f for f in tracked if f.startswith(dep + "/"))
                )
                if not members:
                    if dep.endswith((".sh", ".py")):
                        problems.append(
                            f"{workflow}: .platform/{current} sources {dep}, not tracked (H6)"
                        )
                    continue  # any other missing path is an output or a temp file
                for member in members:
                    if member not in covered:
                        problems.append(
                            f"{workflow}: .platform/{current} sources {member}, which is not "
                            f"covered by {closure} (H6)"
                        )
                    queue.append(member)
    return sorted(set(problems))


def check_repo(root: str) -> list[str]:
    problems: list[str] = []
    reusable_files: list[str] = []
    for base in (".github", os.path.join("examples", "consumer", ".github")):
        top = os.path.join(root, base)
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames.sort()
            for name in sorted(filenames):
                if not name.endswith((".yml", ".yaml")):
                    continue
                path = os.path.join(dirpath, name)
                in_workflows = os.path.dirname(path) == os.path.join(top, "workflows")
                problems += check_workflow(path) if in_workflows else check_uses_only(path)
                if in_workflows and name.startswith("reusable-"):
                    reusable_files.append(path)
    makefile = os.path.join(root, "Makefile")
    if os.path.exists(makefile):
        problems += check_makefile(makefile)
    closure = os.path.join(root, "scripts", "release", "closure.txt")
    for path in reusable_files:
        problems += check_closure(path, root, closure)
    return problems


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("workflow", "makefile", "closure", "repo"):
        print(__doc__, file=sys.stderr)
        return 2
    mode, args = argv[1], argv[2:]
    problems: list[str] = []
    if mode == "closure":
        if len(args) < 5 or args[0] != "--repo" or args[2] != "--closure":
            print(__doc__, file=sys.stderr)
            return 2
        for path in args[4:]:
            problems += check_closure(path, args[1], args[3])
    elif mode == "repo":
        root = args[0] if args else "."
        if not os.path.isdir(root):
            print(f"{root}: is not a directory", file=sys.stderr)
            return 2
        if not any(
            os.path.exists(os.path.join(root, name)) for name in (".github", "Makefile", "examples")
        ):
            print(
                f"{root}: no .github, examples or Makefile found, nothing to check", file=sys.stderr
            )
            return 2
        problems = check_repo(root)
    else:
        if not args:
            print(__doc__, file=sys.stderr)
            return 2
        check = check_workflow if mode == "workflow" else check_makefile
        for path in args:
            problems += check(path)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
