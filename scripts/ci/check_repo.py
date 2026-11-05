#!/usr/bin/env python3
"""Repo guard: structural rules for workflows and the Makefile (Phase 0, ADR 0001 Z9).

Usage:
  check_repo.py workflow FILE...   every `uses:` pinned by 40-hex SHA (local ./ excepted),
                                   top-level `permissions: {}`, triggers only pull_request,
                                   push, workflow_call
  check_repo.py makefile FILE...   no target name containing apply or destroy

Exit 0 when clean, 1 with one message per finding on stderr, 2 on usage errors.
Needs PyYAML (workflow mode).
"""

from __future__ import annotations

import re
import sys

ALLOWED_TRIGGERS = {"pull_request", "push", "workflow_call"}
USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)")
SHA_RE = re.compile(r"@[0-9a-f]{40}$")
TARGET_RE = re.compile(r"^([A-Za-z0-9_./%$()-]+(?:\s+[A-Za-z0-9_./%$()-]+)*)\s*:(?!=)")


def read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        print(f"{path}: cannot read ({exc.strerror})", file=sys.stderr)
        return None


def check_workflow(path: str) -> list[str]:
    import yaml  # imported here so makefile mode works without PyYAML

    text = read(path)
    if text is None:
        return [f"{path}: cannot read"]
    problems: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        match = USES_RE.match(line)
        if not match:
            continue
        ref = match.group(1).strip("\"'")
        if ref.startswith("./"):
            continue
        if not SHA_RE.search(ref):
            problems.append(f"{path}:{lineno}: uses '{ref}' is not pinned by a 40-hex SHA")
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [*problems, f"{path}: invalid YAML ({exc})"]
    if not isinstance(doc, dict):
        return [*problems, f"{path}: not a workflow mapping"]
    if doc.get("permissions", "missing") != {}:
        problems.append(f"{path}: top-level 'permissions: {{}}' is required")
    # YAML 1.1 reads the bare key `on` as boolean True.
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        triggers = {on}
    elif isinstance(on, (list, dict)):
        triggers = {str(t) for t in on}
    else:
        triggers = set()
        problems.append(f"{path}: no 'on:' triggers found")
    for trigger in sorted(triggers - ALLOWED_TRIGGERS):
        problems.append(
            f"{path}: trigger '{trigger}' is not allowed (only pull_request, push, workflow_call)"
        )
    return problems


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
                        f"{path}:{lineno}: target '{name}' contains '{bad}' (never allowed)"
                    )
    return problems


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] not in ("workflow", "makefile"):
        print(__doc__, file=sys.stderr)
        return 2
    check = check_workflow if argv[1] == "workflow" else check_makefile
    problems: list[str] = []
    for path in argv[2:]:
        problems.extend(check(path))
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
