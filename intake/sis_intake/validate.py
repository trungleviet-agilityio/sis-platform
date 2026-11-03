"""Validate a platform.yaml manifest.

    python3 intake/sis_intake/validate.py FILE [--json]
    python3 -m sis_intake.validate FILE [--json]      (from intake/)

Exit codes: 0 valid (warnings printed), 1 errors, 2 parse or usage error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Run as a script path, sys.path[0] is sis_intake/ itself: add its parent so the package imports.
_PARENT = str(Path(__file__).resolve().parent.parent)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from sis_intake import rules, schema, yamlsubset  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "platform.schema.json"


class Report:
    def __init__(
        self,
        findings: list[rules.Finding],
        resolved: dict[str, dict[str, Any]],
        defaults: dict[str, Any] | None,
        parse_error: bool,
    ) -> None:
        self.findings = findings
        self.resolved = resolved
        self.defaults = defaults
        self.parse_error = parse_error

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


def _meta(rule_id: str, path: str, message: str) -> rules.Finding:
    return rules.Finding(rule_id, "error", path, message, [], [])


def validate_text(text: str) -> Report:
    try:
        manifest = yamlsubset.parse(text)
    except yamlsubset.YamlError as exc:
        return Report([_meta("PARSE", f"line {exc.line}", exc.message)], {}, None, True)
    if not isinstance(manifest, dict):
        return Report([_meta("PARSE", "(root)", "the document must be a mapping")], {}, None, True)

    with open(SCHEMA_PATH, encoding="utf-8") as handle:
        schema_doc = json.load(handle)
    findings = [
        _meta("SCHEMA", issue.path or "(root)", issue.message)
        for issue in schema.validate(manifest, schema_doc)
    ]
    if isinstance(manifest.get("envs"), dict) and not manifest["envs"]:
        findings.append(_meta("SCHEMA", "envs", "at least one env is required"))
    if findings:
        # The manifest is not well formed: only the structure-free scan (V10) is safe to run.
        findings.extend(rules.evaluate(manifest, only={"V10"}))
        return Report(findings, {}, None, False)

    findings.extend(rules.evaluate(manifest))
    defaults = rules.load_defaults()
    return Report(
        findings,
        rules.resolve_envs(manifest, defaults=defaults),
        defaults["runtimes"][manifest["runtime"]["kind"]],
        False,
    )


def validate_file(path: str) -> Report:
    with open(path, encoding="utf-8") as handle:
        return validate_text(handle.read())


def _render_text(report: Report) -> str:
    out: list[str] = []
    for f in report.findings:
        refs = ", ".join(f.pillars + f.wa_refs)
        suffix = f" [{refs}]" if refs else ""
        out.append(f"{f.severity:<7} {f.id:<6} {f.path}: {f.message}{suffix}")
    if report.resolved:
        out.append("")
        out.append("resolved:")
        for name, info in report.resolved.items():
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
    if report.defaults:
        out.append("runtime defaults:")
        for key, value in report.defaults.items():
            out.append(f"  {key}: {value}")
    out.append("")
    out.append(f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args
    files = [a for a in args if a != "--json"]
    if len(files) != 1 or files[0].startswith("-"):
        sys.stderr.write("usage: validate.py FILE [--json]\n")
        return 2
    try:
        report = validate_file(files[0])
    except OSError as exc:
        sys.stderr.write(f"cannot read {files[0]}: {exc.strerror or exc}\n")
        return 2
    except UnicodeDecodeError:
        sys.stderr.write(f"cannot read {files[0]}: not UTF-8 text\n")
        return 2
    if as_json:
        payload = {
            "file": files[0],
            "valid": report.valid,
            "findings": [f.to_dict() for f in report.findings],
            "resolved": report.resolved,
            "defaults": report.defaults,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(_render_text(report) + "\n")
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
