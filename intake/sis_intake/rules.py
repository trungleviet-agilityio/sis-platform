"""Decision rules V01 to V18: data in intake/rules/*.json, one predicate per rule ID."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from functools import cached_property
from pathlib import Path
from typing import Any, NamedTuple

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"

Manifest = dict[str, Any]
Hit = tuple[str, str]  # (path, message)

_TWELVE_DIGITS = re.compile(r"(?<!\d)\d{12}(?!\d)")
_TWO_VERSIONS_AT_ONCE_EXCEPT = "all-at-once"


class Finding(NamedTuple):
    id: str
    severity: str  # "error" or "warning"
    path: str
    message: str
    pillars: list[str]
    wa_refs: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
            "pillars": list(self.pillars),
            "wa_refs": list(self.wa_refs),
        }


def _load(name: str) -> dict[str, Any]:
    with open(RULES_DIR / name, encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
    return data


def load_rules() -> dict[str, Any]:
    return _load("rules.json")


def load_compat() -> dict[str, Any]:
    return _load("compat.json")


def load_defaults() -> dict[str, Any]:
    return _load("defaults.json")


def load_questions() -> dict[str, Any]:
    return _load("questions.json")


class EnvView(NamedTuple):
    name: str
    env: dict[str, Any]
    kind: str
    strategy: str
    engine: str
    front_door: str
    rollback: str
    profile: str | None


class Ctx:
    """Everything a predicate needs: the manifest, the data files and the resolved envs."""

    def __init__(
        self,
        manifest: Manifest,
        compat: dict[str, Any],
        defaults: dict[str, Any],
        params: dict[str, Any],
    ) -> None:
        self.manifest = manifest
        self.compat = compat
        self.defaults = defaults
        self.params = params
        runtime = manifest.get("runtime")
        self.kind: str = runtime.get("kind", "") if isinstance(runtime, dict) else ""

    @cached_property
    def envs(self) -> list[EnvView]:
        # Lazy: V10 must run on manifests that failed the schema, with no resolvable envs.
        return [
            _env_view(self.manifest, name, env, self.compat, self.defaults)
            for name, env in (self.manifest.get("envs") or {}).items()
        ]

    @property
    def budget(self) -> int | None:
        value = (self.manifest.get("budget") or {}).get("monthly_usd")
        return value if isinstance(value, int) else None


def _env_view(
    manifest: Manifest,
    name: str,
    env: dict[str, Any],
    compat: dict[str, Any],
    defaults: dict[str, Any],
) -> EnvView:
    kind = manifest["runtime"]["kind"]
    rel = env.get("release") or {}
    runtime_defaults = defaults["runtimes"][kind]
    declared = rel.get("engine", defaults["release"]["engine"])
    engine = compat["runtimes"][kind]["auto_engine"] if declared == "auto" else declared
    return EnvView(
        name=name,
        env=env,
        kind=kind,
        strategy=rel.get("strategy", runtime_defaults["release_strategy"]),
        engine=engine,
        front_door=manifest["runtime"].get("front_door", runtime_defaults["front_door"]),
        rollback=rel.get("rollback", defaults["release"]["rollback"]),
        profile=compat["deploy_role_profiles"].get(f"{kind}:{engine}"),
    )


def resolve_envs(
    manifest: Manifest,
    compat: dict[str, Any] | None = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Per env: the resolved strategy, engine, deploy_role_profile, front_door and rollback."""
    compat = compat if compat is not None else load_compat()
    defaults = defaults if defaults is not None else load_defaults()
    out: dict[str, dict[str, Any]] = {}
    for name, env in (manifest.get("envs") or {}).items():
        view = _env_view(manifest, name, env, compat, defaults)
        out[name] = {
            "strategy": view.strategy,
            "engine": view.engine,
            "deploy_role_profile": view.profile,
            "front_door": view.front_door,
            "rollback": view.rollback,
        }
    return out


# ---------------------------------------------------------------- predicates


def _p(env: EnvView, *parts: str) -> str:
    return ".".join(("envs", env.name) + parts)


def v01(ctx: Ctx) -> list[Hit]:
    return [
        (
            _p(e, "release", "rollback"),
            f"strategy {e.strategy} requires rollback: alarm, got {e.rollback}",
        )
        for e in ctx.envs
        if e.strategy in ("canary", "linear") and e.rollback != "alarm"
    ]


def v02(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    minimum = ctx.params["min_bake_minutes"]
    for e in ctx.envs:
        if e.strategy not in ctx.params["strategies"]:
            continue
        rel = e.env.get("release") or {}
        steps = rel.get("steps")
        if not isinstance(steps, list) or not steps:
            hits.append(
                (_p(e, "release", "steps"), f"{e.strategy} needs steps (rising, ending at 100)")
            )
        else:
            rising = all(a < b for a, b in zip(steps, steps[1:]))
            if not rising or steps[-1] != 100:
                hits.append(
                    (
                        _p(e, "release", "steps"),
                        f"steps must rise strictly and end at 100, got {steps}",
                    )
                )
        bake = rel.get("bake_minutes")
        if not isinstance(bake, int) or bake < minimum:
            hits.append(
                (
                    _p(e, "release", "bake_minutes"),
                    f"{e.strategy} needs bake_minutes >= {minimum}",
                )
            )
    return hits


def v03(ctx: Ctx) -> list[Hit]:
    return [
        (
            _p(e, "delivery"),
            "delivery: gitops is only for {}, runtime is {}".format(
                ", ".join(ctx.params["gitops_runtimes"]), e.kind
            ),
        )
        for e in ctx.envs
        if e.env.get("delivery") == "gitops" and e.kind not in ctx.params["gitops_runtimes"]
    ]


def v04(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    entry = ctx.compat["runtimes"].get(ctx.kind)
    if entry is None:
        return hits
    for e in ctx.envs:
        if e.strategy not in entry["strategies"]:
            hint = entry["hints"].get(e.strategy)
            text = "{} does not support strategy {} (allowed: {})".format(
                e.kind,
                e.strategy,
                ", ".join(entry["strategies"]),
            )
            hits.append((_p(e, "release", "strategy"), text + (": " + hint if hint else "")))
        elif e.engine not in entry["engines"]:
            hits.append(
                (
                    _p(e, "release", "engine"),
                    "{} does not support engine {} (allowed: {})".format(
                        e.kind, e.engine, ", ".join(entry["engines"])
                    ),
                )
            )
        elif (
            e.engine in entry["engine_strategies"]
            and e.strategy not in entry["engine_strategies"][e.engine]
        ):
            allowed = ", ".join(entry["engine_strategies"][e.engine])
            hits.append(
                (
                    _p(e, "release", "engine"),
                    f"engine {e.engine} on {e.kind} supports only: {allowed}",
                )
            )
    return hits


def v05(ctx: Ctx) -> list[Hit]:
    return [
        (
            _p(e, "release", "strategy"),
            f"{e.strategy} on {e.kind} needs front_door: alb, got {e.front_door}",
        )
        for e in ctx.envs
        if e.kind in ctx.params["runtimes"]
        and e.strategy in ctx.params["strategies"]
        and e.front_door != "alb"
    ]


def v06(ctx: Ctx) -> list[Hit]:
    budget = ctx.budget
    if budget is None or budget >= ctx.params["threshold_usd"]:
        return []
    if any(e.front_door == "alb" for e in ctx.envs):
        return [
            (
                "budget.monthly_usd",
                f"an ALB has a fixed monthly cost; budget {budget} USD is under "
                f"{ctx.params['threshold_usd']}",
            )
        ]
    return []


def v07(ctx: Ctx) -> list[Hit]:
    return [
        (_p(e, "release", "strategy"), "blue-green doubles capacity during a deploy")
        for e in ctx.envs
        if e.strategy == "blue-green"
    ]


def v08(ctx: Ctx) -> list[Hit]:
    if not ctx.kind.startswith("lambda"):
        return []
    work = ctx.manifest.get("workload") or {}
    p = ctx.params
    hits: list[Hit] = []
    duration = work.get("max_duration_seconds")
    if isinstance(duration, int) and duration > p["max_duration_seconds"]:
        hits.append(
            (
                "workload.max_duration_seconds",
                f"Lambda stops at {p['max_duration_seconds']} s, got {duration}",
            )
        )
    payload = work.get("max_payload_mb")
    if isinstance(payload, int) and payload > p["max_payload_mb"]:
        hits.append(
            (
                "workload.max_payload_mb",
                f"Lambda synchronous payload limit is {p['max_payload_mb']} MB, got {payload}",
            )
        )
    needs = [n for n in (work.get("needs") or []) if n in p["needs"]]
    if needs:
        hits.append(("workload.needs", "Lambda cannot provide: {}".format(", ".join(needs))))
    return hits


def v09(ctx: Ctx) -> list[Hit]:
    duration = (ctx.manifest.get("workload") or {}).get("max_duration_seconds")
    limit = ctx.params["max_duration_seconds"]
    if not isinstance(duration, int) or duration <= limit:
        return []
    if any(e.front_door == "http-api" for e in ctx.envs):
        return [
            (
                "workload.max_duration_seconds",
                f"HTTP API integration timeout is about {limit} s, got {duration}",
            )
        ]
    return []


def _walk(value: Any, path: str) -> list[tuple[str, str]]:
    """Yield (path, text) for every key and scalar in the manifest."""
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            sub = f"{path}.{key}" if path else str(key)
            found.append((sub, str(key)))
            found.extend(_walk(item, sub))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_walk(item, f"{path}[{index}]"))
    elif value is not None:
        found.append((path, str(value)))
    return found


def v10(ctx: Ctx) -> list[Hit]:
    return [
        (path or "(root)", "a 12-digit number looks like an AWS account ID; use an account label")
        for path, text in _walk(ctx.manifest, "")
        if _TWELVE_DIGITS.search(text)
    ]


def v11(ctx: Ctx) -> list[Hit]:
    return [
        (_p(e, "promote_from"), "prod must set promote_from (one artifact promoted by digest)")
        for e in ctx.envs
        if e.name == "prod" and not e.env.get("promote_from")
    ]


def v12(ctx: Ctx) -> list[Hit]:
    db = ctx.manifest.get("database") or {}
    if db.get("kind", "none") == "none" or db.get("schema_change") == "expand-contract":
        return []
    return [
        (
            _p(e, "release", "strategy"),
            f"strategy {e.strategy} runs two versions at once: "
            "set database.schema_change: expand-contract",
        )
        for e in ctx.envs
        if e.strategy != _TWO_VERSIONS_AT_ONCE_EXCEPT
    ][:1]


def v13(ctx: Ctx) -> list[Hit]:
    dr = ctx.manifest.get("dr") or {}
    rto = dr.get("rto_minutes")
    if not isinstance(rto, int):
        return []
    strategy = dr.get("strategy", ctx.defaults["dr"]["strategy"])
    if strategy == "backup-restore" and rto < ctx.params["backup_restore_min_rto"]:
        return [
            (
                "dr.rto_minutes",
                f"backup-restore cannot meet an RTO under "
                f"{ctx.params['backup_restore_min_rto']} minutes, got {rto}",
            )
        ]
    if strategy not in ("warm-standby", "multi-site") and rto < ctx.params["other_min_rto"]:
        return [
            (
                "dr.rto_minutes",
                f"{strategy} cannot meet an RTO under "
                f"{ctx.params['other_min_rto']} minutes, got {rto}",
            )
        ]
    return []


def v14(ctx: Ctx) -> list[Hit]:
    strategy = (ctx.manifest.get("dr") or {}).get("strategy")
    budget = ctx.budget
    if (
        strategy in ("warm-standby", "multi-site")
        and budget is not None
        and budget < ctx.params["threshold_usd"]
    ):
        return [
            (
                "dr.strategy",
                f"{strategy} needs a second region running; budget {budget} USD is under "
                f"{ctx.params['threshold_usd']}",
            )
        ]
    return []


def v15(ctx: Ctx) -> list[Hit]:
    budget = ctx.budget
    if ctx.kind == "eks-workload" and budget is not None and budget < ctx.params["threshold_usd"]:
        return [
            (
                "budget.monthly_usd",
                f"an EKS control plane costs about 73 USD per month; budget {budget} USD is "
                f"under {ctx.params['threshold_usd']}",
            )
        ]
    return []


def v16(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    for e in ctx.envs:
        if e.name != "prod":
            continue
        for flag in ("scale_to_zero", "fargate_spot"):
            if e.env.get(flag) is True:
                hits.append((_p(e, flag), f"{flag} on prod risks availability"))
    return hits


def v17(ctx: Ctx) -> list[Hit]:
    hits: list[Hit] = []
    entry = ctx.compat["runtimes"].get(ctx.kind)
    if entry is not None and not entry["adapter_built"]:
        hits.append(("runtime.kind", f"adapter for {ctx.kind} is not built yet"))
    if (ctx.manifest.get("ci") or {}).get("provider") == "codepipeline":
        hits.append(("ci.provider", "ci.provider codepipeline is not built yet"))
    return hits


def v18(ctx: Ctx) -> list[Hit]:
    return [
        (
            _p(e, "release", "rollback"),
            f"prod with rollback: manual and strategy {e.strategy} has no automatic rollback",
        )
        for e in ctx.envs
        if e.name == "prod" and e.rollback == "manual" and e.strategy != "all-at-once"
    ]


PREDICATES: dict[str, Callable[[Ctx], list[Hit]]] = {
    "V01": v01,
    "V02": v02,
    "V03": v03,
    "V04": v04,
    "V05": v05,
    "V06": v06,
    "V07": v07,
    "V08": v08,
    "V09": v09,
    "V10": v10,
    "V11": v11,
    "V12": v12,
    "V13": v13,
    "V14": v14,
    "V15": v15,
    "V16": v16,
    "V17": v17,
    "V18": v18,
}


def evaluate(
    manifest: Manifest,
    rules: dict[str, Any] | None = None,
    compat: dict[str, Any] | None = None,
    defaults: dict[str, Any] | None = None,
    only: set[str] | None = None,
) -> list[Finding]:
    """Run every rule (or only the ids in `only`) on a schema-valid manifest."""
    rules = rules if rules is not None else load_rules()
    compat = compat if compat is not None else load_compat()
    defaults = defaults if defaults is not None else load_defaults()
    findings: list[Finding] = []
    for rule in rules["rules"]:
        if only is not None and rule["id"] not in only:
            continue
        ctx = Ctx(manifest, compat, defaults, rule.get("params", {}))
        for path, message in PREDICATES[rule["id"]](ctx):
            findings.append(
                Finding(
                    id=rule["id"],
                    severity="error" if rule["severity"] == "E" else "warning",
                    path=path,
                    message=message,
                    pillars=list(rule["pillars"]),
                    wa_refs=list(rule["wa_refs"]),
                )
            )
    return findings
