"""Shared builders for the intake tests."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from sis_intake import rules

INTAKE_DIR = Path(__file__).resolve().parent.parent
EXAMPLES = INTAKE_DIR / "examples"


def base_manifest() -> dict[str, Any]:
    """A valid lambda-web manifest with no rule findings other than V17."""
    return {
        "schema_version": 1,
        "project": {"name": "demo", "prefix": "dm", "owner": "demo-team"},
        "platform": {"version": "v0.2.0"},
        "workload": {
            "shape": "web",
            "port": 8080,
            "health_path": "/health",
            "max_duration_seconds": 10,
            "max_payload_mb": 1,
            "peak_rps": 50,
            "p95_ms": 500,
        },
        "runtime": {"kind": "lambda-web", "arch": "arm64", "front_door": "http-api"},
        "ci": {"provider": "github-actions"},
        "budget": {"monthly_usd": 50},
        "dr": {"strategy": "backup-restore", "rto_minutes": 240, "rpo_minutes": 1440},
        "compliance": {"data_class": "internal"},
        "database": {"kind": "none"},
        "envs": {
            "dev": {
                "tier": "nonprod",
                "account": "dev",
                "region": "ap-southeast-1",
                "delivery": "push",
            },
            "prod": {
                "tier": "prod",
                "account": "prod",
                "region": "ap-southeast-1",
                "delivery": "push",
                "promote_from": "dev",
            },
        },
    }


def ecs_manifest() -> dict[str, Any]:
    """A valid ecs-fargate manifest (rolling, ecs-native, alb) with no findings but V17."""
    m = base_manifest()
    m["runtime"] = {"kind": "ecs-fargate", "arch": "arm64", "front_door": "alb"}
    for env in m["envs"].values():
        env["release"] = {"strategy": "rolling", "rollback": "health", "engine": "ecs-native"}
    return m


def eks_manifest() -> dict[str, Any]:
    m = base_manifest()
    m["runtime"] = {"kind": "eks-workload", "arch": "arm64", "front_door": "alb"}
    m["budget"] = {"monthly_usd": 200}
    for env in m["envs"].values():
        env["release"] = {"strategy": "rolling", "rollback": "health", "engine": "argo-rollouts"}
    return m


def fired(manifest: dict[str, Any], compat: Any = None, **kwargs: Any) -> set[str]:
    return {f.id for f in rules.evaluate(manifest, compat=compat, **kwargs)}


def copy_of(value: Any) -> Any:
    return copy.deepcopy(value)
