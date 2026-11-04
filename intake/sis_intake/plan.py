"""The resolved plan (ADR 0002 M6) and the Terraform variable slice (M7).

`build_plan` returns the JSON document `validate.py FILE --json` prints. Workflows and env roots
read only this document. Adding a key is a minor change; renaming or removing one bumps FORMAT_VERSION.
"""

from __future__ import annotations

import re
from typing import Any

from sis_intake import rules

_VERSION = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
FORMAT_VERSION = 1
ROLE_VERBS = ("plan", "apply", "deploy")


def _version(platform: Any) -> str | None:
    """`platform.version` only when it has the vX.Y.Z shape, so a bad value is never echoed."""
    version = platform.get("version") if isinstance(platform, dict) else None
    if isinstance(version, str) and _VERSION.fullmatch(version):
        return version
    return None


def effective_p95(manifest: dict[str, Any], defaults: dict[str, Any]) -> int:
    """The p95 target in effect: the manifest value, else the default (also the SLO value)."""
    value = (manifest.get("workload") or {}).get("p95_ms", defaults["workload"]["p95_ms"])
    return int(value)


def _roles(prefix: str, env: str) -> dict[str, str]:
    """Role names (never ARNs), as in ADR 0002 T4: <prefix>-<env>-gha-{plan,apply,deploy}."""
    return {verb: f"{prefix}-{env}-gha-{verb}" for verb in ROLE_VERBS}


def _env_plan(
    view: rules.EnvView,
    manifest: dict[str, Any],
    compat: dict[str, Any],
    defaults: dict[str, Any],
) -> dict[str, Any]:
    prefix = manifest["project"]["prefix"]
    entry = compat["runtimes"][view.kind]
    built = entry["built"]
    workload = manifest.get("workload") or {}
    compliance = manifest.get("compliance") or {}
    data_class = compliance.get("data_class", defaults["compliance"]["data_class"])
    retention = defaults["tiers"][view.tier]["log_retention_days"]
    if data_class == "regulated":
        retention = defaults["regulated_log_retention_days"]
    alarms = [
        alarm
        for alarm in entry["alarms"]
        # A nonprod env with no probes has nothing to feed a probe alarm.
        if not (alarm in entry["probe_alarms"] and view.tier == "nonprod" and not view.probes)
    ]
    return {
        "tier": view.tier,
        "account": view.env["account"],
        "region": view.env["region"],
        "prefix": prefix,
        "delivery": view.delivery,
        "promote_from": view.env.get("promote_from"),
        "strategy": view.strategy,
        "steps": view.steps,
        "bake_minutes": view.bake_minutes if view.bake_minutes is not None else 0,
        "probes": view.probes,
        "rollback": view.rollback,
        "engine": view.engine,
        "deploy_role_profile": view.profile,
        "roles": _roles(prefix, view.name),
        "budget_monthly_usd": manifest["budget"]["monthly_usd"],
        "data_class": data_class,
        "observability": {
            "slo": {
                "availability_pct": defaults["tiers"][view.tier]["availability_pct"],
                "p95_ms": effective_p95(manifest, defaults),
            },
            "alarms": [f"{prefix}-{view.name}-{alarm}" for alarm in alarms],
            "log_retention_days": retention,
            "notify": f"{prefix}-{view.name}-notify",
        },
        "built": {
            "runtime": built["runtime"],
            "engine": built["engines"].get(view.engine, False),
            "delivery": built["delivery"].get(view.delivery, False),
            "profile": built["profiles"].get(view.profile or "", False),
        },
    }


def build_plan(
    manifest: dict[str, Any] | None,
    findings: list[rules.Finding],
    context: str,
    resolvable: bool,
    compat: dict[str, Any] | None = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The M6 document. When the manifest could not be resolved, the sections are null or empty."""
    compat = compat if compat is not None else rules.load_compat()
    defaults = defaults if defaults is not None else rules.load_defaults()
    raw = manifest if isinstance(manifest, dict) else {}
    platform = raw.get("platform")
    schema_version = raw.get("schema_version")
    plan: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "platform_version": _version(platform),
        "schema_version": schema_version if isinstance(schema_version, int) else None,
        "context": context,
        "valid": not any(f.severity == "error" for f in findings),
        "findings": [f.to_dict() for f in findings],
        "project": None,
        "runtime": None,
        "workload": None,
        "envs": {},
    }
    if not resolvable or manifest is None:
        return plan
    project = manifest["project"]
    runtime = manifest["runtime"]
    entry = compat["runtimes"][runtime["kind"]]
    workload = manifest.get("workload") or {}
    plan["project"] = {
        "name": project["name"],
        "prefix": project["prefix"],
        "owner": project["owner"],
    }
    plan["runtime"] = {
        "kind": runtime["kind"],
        "family": entry["family"],
        "arch": runtime.get("arch", defaults["arch"]),
        "front_door": runtime.get("front_door", defaults["runtimes"][runtime["kind"]]["front_door"]),
    }
    plan["workload"] = {
        "port": workload.get("port"),
        "health_path": rules.health_path(manifest, defaults),
        "peak_rps": workload.get("peak_rps"),
        "p95_ms": effective_p95(manifest, defaults),
    }
    views = sorted(rules.env_views(manifest, compat, defaults), key=lambda v: v.name)
    plan["envs"] = {view.name: _env_plan(view, manifest, compat, defaults) for view in views}
    return plan


def tfvars(plan: dict[str, Any], env: str) -> dict[str, Any]:
    """`{"platform": {...}}` for one env: the env's plan keys plus the shared sections (M7)."""
    section = {
        "format_version": plan["format_version"],
        "platform_version": plan["platform_version"],
        "schema_version": plan["schema_version"],
        "env": env,
        "project": plan["project"],
        "runtime": plan["runtime"],
        "workload": plan["workload"],
    }
    section.update(plan["envs"][env])
    return {"platform": section}
