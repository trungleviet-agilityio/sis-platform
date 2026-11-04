"""Decision rules V01 to V25: data in intake/rules/*.json, one predicate per rule ID."""

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

CONTEXTS = ("lint", "deploy")
GRADUAL = ("canary", "linear")
HEALTH_PLACEHOLDER = "<health_path>"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "platform.schema.json"

# A 12-digit run or the hyphenated 4-4-4 form. Hex-digit boundaries keep a digit run inside a longer
# hex string (a commit SHA) from matching. The documentation example stays allowed.
_ACCOUNT_LIKE = re.compile(
    r"(?<![0-9A-Fa-f])\d{12}(?![0-9A-Fa-f])|(?<![0-9A-Za-z-])\d{4}-\d{4}-\d{4}(?![0-9A-Za-z-])"
)
_ALLOWED_ACCOUNT_LIKE = frozenset({"1234-5678-9012"})
REDACTED = "<redacted>"


def account_like(text: str) -> list[str]:
    """Every account-ID-like run in the text (V10)."""
    return [m for m in _ACCOUNT_LIKE.findall(text) if m not in _ALLOWED_ACCOUNT_LIKE]


def redact(text: str) -> str:
    """Replace account-ID-like runs, so no output ever carries one."""
    return _ACCOUNT_LIKE.sub(
        lambda m: m.group(0) if m.group(0) in _ALLOWED_ACCOUNT_LIKE else REDACTED, text
    )


def redact_obj(value: Any) -> Any:
    """`redact` over every string, key and value, in a JSON-like structure."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_obj(v) for v in value]
    if isinstance(value, dict):
        return {redact(str(k)): redact_obj(v) for k, v in value.items()}
    return value


def env_flag_names(compat: dict[str, Any]) -> set[str]:
    """Env boolean flags: the schema's boolean env properties plus every runtime's `env_flags`."""
    with open(SCHEMA_PATH, encoding="utf-8") as handle:
        props = json.load(handle)["$defs"]["env"]["properties"]
    flags = {name for name, spec in props.items() if spec.get("type") == "boolean"}
    for entry in compat["runtimes"].values():
        flags.update(entry["env_flags"])
    return flags


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
    """One env with every release default resolved (tier, runtime, auto engine)."""

    name: str
    env: dict[str, Any]
    kind: str
    tier: str
    delivery: str
    strategy: str
    engine: str
    front_door: str
    rollback: str
    profile: str | None
    steps: list[int]
    bake_minutes: int | None
    probes: list[str]


def health_path(manifest: Manifest, defaults: dict[str, Any]) -> str:
    value = (manifest.get("workload") or {}).get("health_path")
    return value if isinstance(value, str) else str(defaults["workload"]["health_path"])


class Ctx:
    """Everything a predicate needs: the manifest, the data files and the resolved envs.

    Rule parameters are not here: the runner passes them to each predicate (ADR 0002 D12).
    """

    def __init__(
        self,
        manifest: Manifest,
        compat: dict[str, Any],
        defaults: dict[str, Any],
        context: str = "lint",
        raw_text: str | None = None,
    ) -> None:
        self.manifest = manifest
        self.compat = compat
        self.defaults = defaults
        self.context = context
        self.raw_text = raw_text
        runtime = manifest.get("runtime")
        self.kind: str = runtime.get("kind", "") if isinstance(runtime, dict) else ""

    @cached_property
    def envs(self) -> list[EnvView]:
        # Lazy: V10 must run on manifests that failed the schema, with no resolvable envs.
        return env_views(self.manifest, self.compat, self.defaults)

    @property
    def entry(self) -> dict[str, Any] | None:
        entry: dict[str, Any] | None = self.compat["runtimes"].get(self.kind)
        return entry

    @property
    def health_path(self) -> str:
        return health_path(self.manifest, self.defaults)

    @cached_property
    def flags(self) -> set[str]:
        return env_flag_names(self.compat)

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
    tier = env.get("tier", "nonprod")
    rel = env.get("release") or {}
    runtime_defaults = defaults["runtimes"][kind]
    tier_defaults = defaults["tiers"][tier]
    declared = rel.get("engine", defaults["release"]["engine"])
    engine = compat["runtimes"][kind]["auto_engine"] if declared == "auto" else declared
    strategy = rel.get("strategy", runtime_defaults["release_strategy"][tier])
    gradual = strategy in GRADUAL
    health = health_path(manifest, defaults)
    default_probes = [
        health if p == HEALTH_PLACEHOLDER else p for p in tier_defaults.get("probes", [])
    ]
    steps = rel.get("steps", tier_defaults.get("steps", []) if gradual else [])
    bake = rel.get("bake_minutes", tier_defaults.get("bake_minutes") if gradual else None)
    return EnvView(
        name=name,
        env=env,
        kind=kind,
        tier=tier,
        delivery=env.get("delivery", defaults["delivery"]),
        strategy=strategy,
        engine=engine,
        front_door=manifest["runtime"].get("front_door", runtime_defaults["front_door"]),
        rollback=rel.get("rollback", tier_defaults["rollback"]),
        profile=compat["deploy_role_profiles"].get(f"{kind}:{engine}"),
        steps=list(steps),
        bake_minutes=bake,
        probes=list(rel.get("probes", default_probes if gradual else [])),
    )


def env_views(
    manifest: Manifest,
    compat: dict[str, Any] | None = None,
    defaults: dict[str, Any] | None = None,
) -> list[EnvView]:
    """Every env with its release settings resolved. Needs a schema-valid manifest."""
    compat = compat if compat is not None else load_compat()
    defaults = defaults if defaults is not None else load_defaults()
    return [
        _env_view(manifest, name, env, compat, defaults)
        for name, env in (manifest.get("envs") or {}).items()
    ]


def resolve_envs(
    manifest: Manifest,
    compat: dict[str, Any] | None = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Per env: the resolved strategy, engine, deploy_role_profile, front_door and rollback."""
    out: dict[str, dict[str, Any]] = {}
    for view in env_views(manifest, compat, defaults):
        out[view.name] = {
            "strategy": view.strategy,
            "engine": view.engine,
            "deploy_role_profile": view.profile,
            "front_door": view.front_door,
            "rollback": view.rollback,
        }
    return out


# ---------------------------------------------------------------- registry

Predicate = Callable[[Ctx, dict[str, Any]], list[Hit]]
PREDICATES: dict[str, Predicate] = {}


def rule(rule_id: str) -> Callable[[Predicate], Predicate]:
    """Register the predicate for a rule ID (one predicate per entry in rules.json)."""

    def register(fn: Predicate) -> Predicate:
        PREDICATES[rule_id] = fn
        return fn

    return register


# ---------------------------------------------------------------- predicates


def _p(env: EnvView, *parts: str) -> str:
    return ".".join(("envs", env.name) + parts)


def _prod_names(ctx: Ctx) -> list[str]:
    return [e.name for e in ctx.envs if e.tier == "prod"]


@rule("V01")
def v01(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    return [
        (
            _p(e, "release", "rollback"),
            f"strategy {e.strategy} requires rollback: alarm (alarms, or metric plus probe "
            f"judgment), got {e.rollback}",
        )
        for e in ctx.envs
        if e.strategy in GRADUAL and e.rollback != "alarm"
    ]


@rule("V02")
def v02(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    hits: list[Hit] = []
    minimum = params["min_bake_minutes"]
    for e in ctx.envs:
        if e.strategy not in params["strategies"]:
            continue
        if not e.steps:
            hits.append(
                (_p(e, "release", "steps"), f"{e.strategy} needs steps (rising, ending at 100)")
            )
        else:
            rising = all(a < b for a, b in zip(e.steps, e.steps[1:]))
            if not rising or e.steps[-1] != 100:
                hits.append(
                    (
                        _p(e, "release", "steps"),
                        f"steps must rise strictly and end at 100, got {e.steps}",
                    )
                )
        if e.bake_minutes is None or e.bake_minutes < minimum:
            hits.append(
                (
                    _p(e, "release", "bake_minutes"),
                    f"{e.strategy} needs bake_minutes >= {minimum}",
                )
            )
    return hits


@rule("V03")
def v03(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    entry = ctx.entry
    if entry is None or entry["gitops"]:
        return []
    allowed = [k for k, v in ctx.compat["runtimes"].items() if v["gitops"]]
    return [
        (
            _p(e, "delivery"),
            "delivery: gitops is only for {}, runtime is {}".format(", ".join(allowed), e.kind),
        )
        for e in ctx.envs
        if e.delivery == "gitops"
    ]


@rule("V04")
def v04(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    hits: list[Hit] = []
    entry = ctx.entry
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


@rule("V05")
def v05(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    entry = ctx.entry
    if entry is None or not entry["gradual_needs_alb"]:
        return []
    return [
        (
            _p(e, "release", "strategy"),
            f"{e.strategy} on {e.kind} needs front_door: alb, got {e.front_door}",
        )
        for e in ctx.envs
        if e.strategy in params["strategies"] and e.front_door != "alb"
    ]


@rule("V06")
def v06(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    budget = ctx.budget
    if budget is None or budget >= params["threshold_usd"]:
        return []
    if any(e.front_door == "alb" for e in ctx.envs):
        return [
            (
                "budget.monthly_usd",
                f"an ALB has a fixed monthly cost; budget {budget} USD is under "
                f"{params['threshold_usd']}",
            )
        ]
    return []


@rule("V07")
def v07(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    return [
        (_p(e, "release", "strategy"), "blue-green doubles capacity during a deploy")
        for e in ctx.envs
        if e.strategy == "blue-green"
    ]


@rule("V08")
def v08(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    entry = ctx.entry
    if entry is None:
        return []
    work = ctx.manifest.get("workload") or {}
    limits = entry["limits"]
    hits: list[Hit] = []
    duration = work.get("max_duration_seconds")
    limit = limits.get("max_duration_seconds")
    if isinstance(duration, int) and limit is not None and duration > limit:
        hits.append(
            ("workload.max_duration_seconds", f"{ctx.kind} stops at {limit} s, got {duration}")
        )
    payload = work.get("max_payload_mb")
    limit = limits.get("max_payload_mb")
    if isinstance(payload, int) and limit is not None and payload > limit:
        hits.append(
            (
                "workload.max_payload_mb",
                f"{ctx.kind} synchronous payload limit is {limit} MB, got {payload}",
            )
        )
    needs = [n for n in (work.get("needs") or []) if n in entry["unsupported_needs"]]
    if needs:
        hits.append(
            ("workload.needs", "{} cannot provide: {}".format(ctx.kind, ", ".join(needs)))
        )
    return hits


@rule("V09")
def v09(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    duration = (ctx.manifest.get("workload") or {}).get("max_duration_seconds")
    limit = params["max_duration_seconds"]
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


@rule("V10")
def v10(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    message = "a 12-digit number looks like an AWS account ID; use an account label"
    if ctx.raw_text is not None:
        # The raw text covers keys, values and comments (ADR 0002 D15).
        return [
            (f"line {number}", message)
            for number, line in enumerate(ctx.raw_text.splitlines(), start=1)
            if account_like(line)
        ]
    return [
        (path or "(root)", message) for path, text in _walk(ctx.manifest, "") if account_like(text)
    ]


@rule("V11")
def v11(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    return [
        (
            _p(e, "promote_from"),
            "a prod tier env must set promote_from (one artifact promoted by digest)",
        )
        for e in ctx.envs
        if e.tier == "prod" and not e.env.get("promote_from")
    ]


@rule("V12")
def v12(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    db = ctx.manifest.get("database") or {}
    entry = ctx.entry
    if entry is None or db.get("kind", "none") == "none":
        return []
    if db.get("schema_change") == "expand-contract":
        return []
    return [
        (
            _p(e, "release", "strategy"),
            f"strategy {e.strategy} runs two versions at once: "
            "set database.schema_change: expand-contract",
        )
        for e in ctx.envs
        if e.strategy in entry["two_versions_live"]
    ][:1]


@rule("V13")
def v13(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    dr = ctx.manifest.get("dr") or {}
    rto = dr.get("rto_minutes")
    if not isinstance(rto, int):
        return []
    strategy = dr.get("strategy", ctx.defaults["dr"]["strategy"])
    if strategy == "backup-restore" and rto < params["backup_restore_min_rto"]:
        return [
            (
                "dr.rto_minutes",
                f"backup-restore cannot meet an RTO under "
                f"{params['backup_restore_min_rto']} minutes, got {rto}",
            )
        ]
    if strategy not in ("warm-standby", "multi-site") and rto < params["other_min_rto"]:
        return [
            (
                "dr.rto_minutes",
                f"{strategy} cannot meet an RTO under {params['other_min_rto']} minutes, got {rto}",
            )
        ]
    return []


@rule("V14")
def v14(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    strategy = (ctx.manifest.get("dr") or {}).get("strategy")
    budget = ctx.budget
    if (
        strategy in ("warm-standby", "multi-site")
        and budget is not None
        and budget < params["threshold_usd"]
    ):
        return [
            (
                "dr.strategy",
                f"{strategy} needs a second region running; budget {budget} USD is under "
                f"{params['threshold_usd']}",
            )
        ]
    return []


@rule("V15")
def v15(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    entry = ctx.entry
    budget = ctx.budget
    if entry is None or budget is None or budget >= params["threshold_usd"]:
        return []
    fixed = entry["fixed_monthly_usd"]
    if fixed <= 0:
        return []
    return [
        (
            "budget.monthly_usd",
            f"{ctx.kind} has a fixed cost of about {fixed} USD per month (control plane); "
            f"budget {budget} USD is under {params['threshold_usd']}",
        )
    ]


@rule("V16")
def v16(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    hits: list[Hit] = []
    for e in ctx.envs:
        if e.tier != "prod":
            continue
        for flag in sorted(ctx.flags):
            if e.env.get(flag) is True:
                hits.append((_p(e, flag), f"{flag} on prod risks availability"))
    return hits


@rule("V17")
def v17(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    hits: list[Hit] = []
    entry = ctx.entry
    if entry is not None:
        built = entry["built"]
        if not built["runtime"]:
            hits.append(("runtime.kind", f"adapter for {ctx.kind} is not built yet"))
        else:
            for e in ctx.envs:
                missing: list[str] = []
                if not built["engines"].get(e.engine, False):
                    missing.append(f"engine {e.engine}")
                if not built["delivery"].get(e.delivery, False):
                    missing.append(f"delivery {e.delivery}")
                if e.profile is None or not built["profiles"].get(e.profile, False):
                    missing.append(f"deploy role profile {e.profile}")
                if missing:
                    hits.append((_p(e), "not built yet: " + ", ".join(missing)))
    if (ctx.manifest.get("ci") or {}).get("provider") == "codepipeline":
        hits.append(("ci.provider", "ci.provider codepipeline is not built yet"))
    return hits


@rule("V18")
def v18(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    return [
        (
            _p(e, "release", "rollback"),
            f"prod with rollback: manual and strategy {e.strategy} has no automatic rollback",
        )
        for e in ctx.envs
        if e.tier == "prod" and e.rollback == "manual" and e.strategy != "all-at-once"
    ]


@rule("V19")
def v19(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    health = ctx.health_path

    def norm(path: str) -> str:
        return path.lower().rstrip("/") or "/"

    return [
        (
            _p(e, "release", "probes"),
            f"{e.strategy} needs release.probes with a path other than the health path {health}",
        )
        for e in ctx.envs
        if e.strategy in GRADUAL and not any(norm(p) != norm(health) for p in e.probes)
    ]


def _cycles(graph: dict[str, str]) -> list[list[str]]:
    """Each promote cycle once, as an ordered list of env names starting at its smallest name."""
    found: dict[frozenset[str], list[str]] = {}
    for start in graph:
        seen: list[str] = []
        node = start
        while node in graph and node not in seen:
            seen.append(node)
            node = graph[node]
        if node in seen:
            members = seen[seen.index(node) :]
            first = members.index(min(members))
            found.setdefault(frozenset(members), members[first:] + members[:first])
    return sorted(found.values())


@rule("V20")
def v20(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    hits: list[Hit] = []
    names = {e.name for e in ctx.envs}
    graph: dict[str, str] = {}
    for e in ctx.envs:
        source = e.env.get("promote_from")
        if source is None:
            continue
        if source == e.name:
            hits.append((_p(e, "promote_from"), "promote_from must name a different env"))
        elif source not in names:
            hits.append((_p(e, "promote_from"), f"promote_from names an unknown env '{source}'"))
        else:
            graph[e.name] = str(source)
    for cycle in _cycles(graph):
        chain = " -> ".join(cycle + [cycle[0]])
        hits.append((f"envs.{cycle[0]}.promote_from", f"the promote graph has a cycle: {chain}"))
    by_account: dict[str, list[str]] = {}
    for e in ctx.envs:
        by_account.setdefault(str(e.env.get("account")), []).append(e.name)
    for label, owners in by_account.items():
        if len(owners) > 1:
            hits.append(
                (
                    f"envs.{owners[1]}.account",
                    "envs {} share the account label '{}'; use one account per env".format(
                        ", ".join(owners), label
                    ),
                )
            )
    return hits


@rule("V21")
def v21(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    entry = ctx.entry
    if entry is None:
        return []
    return [
        (_p(e, flag), f"{flag} is not available on {e.kind} (allowed: {allowed})")
        for e in ctx.envs
        for flag in sorted(ctx.flags)
        if e.env.get(flag) is True and flag not in entry["env_flags"]
        for allowed in [", ".join(entry["env_flags"]) or "none"]
    ]


@rule("V22")
def v22(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    hits: list[Hit] = []
    compliance = ctx.manifest.get("compliance") or {}
    prod = _prod_names(ctx)
    if prod and not compliance.get("data_class"):
        hits.append(
            (
                "compliance.data_class",
                "prod tier env(s) {} need compliance.data_class".format(", ".join(prod)),
            )
        )
    if compliance.get("data_class") == "regulated" and compliance.get("kms_cmk") is not True:
        hits.append(("compliance.kms_cmk", "data_class regulated needs kms_cmk: true"))
    return hits


def _missing(section: Any, keys: tuple[str, ...]) -> list[str]:
    data = section if isinstance(section, dict) else {}
    return [k for k in keys if not isinstance(data.get(k), int)]


@rule("V23")
def v23(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    prod = _prod_names(ctx)
    missing = _missing(ctx.manifest.get("dr"), ("rto_minutes", "rpo_minutes"))
    if prod and missing:
        return [
            (
                "dr",
                "prod tier env(s) {} need {}".format(
                    ", ".join(prod), " and ".join(f"dr.{k}" for k in missing)
                ),
            )
        ]
    return []


@rule("V24")
def v24(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    prod = _prod_names(ctx)
    missing = _missing(ctx.manifest.get("workload"), ("peak_rps", "p95_ms"))
    if prod and missing:
        return [
            (
                "workload",
                "prod tier env(s) {} need {}".format(
                    ", ".join(prod), " and ".join(f"workload.{k}" for k in missing)
                ),
            )
        ]
    return []


@rule("V25")
def v25(ctx: Ctx, params: dict[str, Any]) -> list[Hit]:
    allowed = ctx.defaults["allowed_regions"]
    return [
        (
            _p(e, "region"),
            "region {} is not allowed (allowed: {})".format(
                e.env.get("region"), ", ".join(allowed)
            ),
        )
        for e in ctx.envs
        if e.env.get("region") not in allowed
    ]


def evaluate(
    manifest: Manifest,
    rules: dict[str, Any] | None = None,
    compat: dict[str, Any] | None = None,
    defaults: dict[str, Any] | None = None,
    only: set[str] | None = None,
    context: str = "lint",
    raw_text: str | None = None,
) -> list[Finding]:
    """Run every rule (or only the ids in `only`) on a schema-valid manifest.

    `context` is `lint` or `deploy` (M8): a rule with `deploy_severity` becomes that severity
    under `deploy`. `raw_text` is the manifest source, scanned by V10 so comments are covered.
    """
    if context not in CONTEXTS:
        raise ValueError(f"context must be one of {CONTEXTS}, got {context!r}")
    rules = rules if rules is not None else load_rules()
    compat = compat if compat is not None else load_compat()
    defaults = defaults if defaults is not None else load_defaults()
    ctx = Ctx(manifest, compat, defaults, context, raw_text)
    findings: list[Finding] = []
    for entry in rules["rules"]:
        if only is not None and entry["id"] not in only:
            continue
        severity = entry["severity"]
        if context == "deploy" and "deploy_severity" in entry:
            severity = entry["deploy_severity"]
        for path, message in PREDICATES[entry["id"]](ctx, entry.get("params", {})):
            findings.append(
                Finding(
                    id=entry["id"],
                    severity="error" if severity == "E" else "warning",
                    path=path,
                    message=message,
                    pillars=list(entry["pillars"]),
                    wa_refs=list(entry["wa_refs"]),
                )
            )
    return findings
