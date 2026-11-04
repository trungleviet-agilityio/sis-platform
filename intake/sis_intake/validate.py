"""Validate a platform.yaml manifest and print findings or the resolved plan.

    python3 intake/sis_intake/validate.py FILE|- [--json] [--context lint|deploy]
    python3 intake/sis_intake/validate.py FILE|- --emit tfvars --env ENV
    python3 -m sis_intake.validate FILE|- ...                  (from intake/)

`-` reads the manifest from stdin. `--json` prints the resolved plan (ADR 0002 M6) and always prints
JSON, including a PARSE finding when the input cannot be read. `--context deploy` turns V17 into an
error (M8). `--emit tfvars --env ENV` prints `{"platform": {...}}` for one env (M7), and prints
nothing when the manifest has errors.

Exit codes: 0 valid (warnings printed), 1 errors, 2 parse or usage error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, NamedTuple

# Run as a script path, sys.path[0] is sis_intake/ itself: add its parent so the package imports.
_PARENT = str(Path(__file__).resolve().parent.parent)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from sis_intake import plan, rules, schema, yamlsubset  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "platform.schema.json"
USAGE = (
    "usage: validate.py FILE|- [--json] [--context lint|deploy]\n"
    "       validate.py FILE|- --emit tfvars --env ENV\n"
)


class Report:
    def __init__(
        self,
        findings: list[rules.Finding],
        manifest: dict[str, Any] | None,
        context: str,
        resolvable: bool,
        parse_error: bool,
    ) -> None:
        # No output ever carries an account-ID-like run, not even an echoed bad value.
        self.findings = [
            f._replace(path=rules.redact(f.path), message=rules.redact(f.message)) for f in findings
        ]
        self.manifest = manifest
        self.context = context
        self.resolvable = resolvable
        self.parse_error = parse_error
        self._plan: dict[str, Any] | None = None

    @property
    def errors(self) -> list[rules.Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[rules.Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def exit_code(self) -> int:
        if self.parse_error:
            return 2
        return 1 if self.errors else 0

    @property
    def plan(self) -> dict[str, Any]:
        if self._plan is None:
            built = plan.build_plan(self.manifest, self.findings, self.context, self.resolvable)
            self._plan = rules.redact_obj(built)
        return self._plan

    @property
    def envs(self) -> dict[str, Any]:
        envs: dict[str, Any] = self.plan["envs"]
        return envs


def _meta(rule_id: str, path: str, message: str) -> rules.Finding:
    return rules.Finding(rule_id, "error", path, message, [], [])


def parse_failure(path: str, message: str, context: str = "lint") -> Report:
    """A report for input that could not be read or parsed (exit 2)."""
    return Report([_meta("PARSE", path, message)], None, context, False, True)


def validate_text(text: str, context: str = "lint") -> Report:
    try:
        manifest = yamlsubset.parse(text)
    except yamlsubset.YamlError as exc:
        return parse_failure(f"line {exc.line}", exc.message, context)
    if not isinstance(manifest, dict):
        return parse_failure("(root)", "the document must be a mapping", context)

    with open(SCHEMA_PATH, encoding="utf-8") as handle:
        schema_doc = json.load(handle)
    findings = [
        _meta("SCHEMA", issue.path or "(root)", issue.message)
        for issue in schema.validate(manifest, schema_doc)
    ]
    if findings:
        # The manifest is not well formed: only the structure-free scan (V10) is safe to run.
        findings.extend(rules.evaluate(manifest, only={"V10"}, context=context, raw_text=text))
        return Report(findings, manifest, context, False, False)

    findings.extend(rules.evaluate(manifest, context=context, raw_text=text))
    return Report(findings, manifest, context, True, False)


def validate_file(path: str, context: str = "lint") -> Report:
    with open(path, encoding="utf-8") as handle:
        return validate_text(handle.read(), context)


def _render_text(report: Report) -> str:
    out: list[str] = []
    for f in report.findings:
        refs = ", ".join(f.pillars + f.wa_refs)
        suffix = f" [{refs}]" if refs else ""
        out.append(f"{f.severity:<7} {f.id:<6} {f.path}: {f.message}{suffix}")
    if report.resolvable and report.manifest is not None:
        out.append("")
        out.append("resolved:")
        for name, info in rules.resolve_envs(report.manifest).items():
            out.append(
                "  {}: strategy={} engine={} deploy_role_profile={} "
                "front_door={} rollback={}".format(
                    name,
                    info["strategy"],
                    info["engine"],
                    info["deploy_role_profile"],
                    info["front_door"],
                    info["rollback"],
                )
            )
        out.append("runtime defaults:")
        for key, value in rules.load_defaults()["runtimes"][
            report.manifest["runtime"]["kind"]
        ].items():
            out.append(f"  {key}: {value}")
    out.append("")
    out.append(f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    return "\n".join(out)


class Options(NamedTuple):
    source: str
    as_json: bool
    context: str
    emit: str | None
    env: str | None


def _parse_args(args: list[str]) -> tuple[Options | None, str]:
    """The options, or None and a usage problem."""
    as_json = False
    context = "lint"
    emit: str | None = None
    env: str | None = None
    positional: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json":
            as_json = True
        elif arg in ("--context", "--emit", "--env"):
            index += 1
            if index >= len(args):
                return None, f"{arg} needs a value"
            value = args[index]
            if arg == "--context":
                context = value
            elif arg == "--emit":
                emit = value
            else:
                env = value
        elif arg.startswith("-") and arg != "-":
            return None, f"unknown option {arg}"
        else:
            positional.append(arg)
        index += 1
    if len(positional) != 1:
        return None, "expected exactly one FILE (or - for stdin)"
    if context not in rules.CONTEXTS:
        return None, "--context must be lint or deploy"
    if emit is not None and emit != "tfvars":
        return None, "--emit supports only tfvars"
    if emit is not None and (env is None or as_json):
        return None, "--emit tfvars needs --env ENV and cannot be combined with --json"
    if emit is None and env is not None:
        return None, "--env is only used with --emit tfvars"
    return Options(positional[0], as_json, context, emit, env), ""


def _read(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    with open(source, encoding="utf-8") as handle:
        return handle.read()


def _fail(report: Report, as_json: bool, usage: str = "") -> int:
    if usage:
        sys.stderr.write(usage)
    if as_json:
        sys.stdout.write(json.dumps(report.plan, indent=2) + "\n")
    else:
        sys.stderr.write(_render_text(report) + "\n" if not usage else "")
    return report.exit_code


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    options, problem = _parse_args(args)
    if options is None:
        report = parse_failure("(usage)", problem)
        return _fail(report, "--json" in args, f"{problem}\n{USAGE}")
    try:
        text = _read(options.source)
    except OSError as exc:
        report = parse_failure("(input)", f"cannot read {options.source}: {exc.strerror or exc}")
        return _fail(
            report, options.as_json, f"cannot read {options.source}: {exc.strerror or exc}\n"
        )
    except UnicodeDecodeError:
        report = parse_failure("(input)", f"cannot read {options.source}: not UTF-8 text")
        return _fail(report, options.as_json, f"cannot read {options.source}: not UTF-8 text\n")

    report = validate_text(text, options.context)
    if options.emit is not None and options.env is not None:
        if not report.valid or report.parse_error:
            sys.stderr.write(_render_text(report) + "\n")
            return report.exit_code
        if options.env not in report.envs:
            sys.stderr.write(f"unknown env '{options.env}' (envs: {', '.join(report.envs)})\n")
            return 2
        sys.stdout.write(json.dumps(plan.tfvars(report.plan, options.env), indent=2) + "\n")
        return 0
    if options.as_json:
        sys.stdout.write(json.dumps(report.plan, indent=2) + "\n")
    else:
        sys.stdout.write(_render_text(report) + "\n")
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
