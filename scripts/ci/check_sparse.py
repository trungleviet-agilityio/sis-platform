#!/usr/bin/env python3
"""Sparse-checkout drift check (ADR 0002 O11, AB8): every sis-platform checkout in a reusable
workflow lists exactly the closure, translated to non-cone sparse patterns, in the same order.

Usage: check_sparse.py --closure scripts/release/closure.txt WORKFLOW...

Translation of each closure line: `:(glob)<p>` becomes `/<p>` and `:(exclude,glob)<p>` becomes
`!/<p>`. Git pathspec globs and gitignore-style sparse patterns read `*` and `**` the same way for
these paths, and the leading `/` anchors a pattern at the repository root. The patterns are written
literally in the workflows (reviewable, visible to the H6 closure guard, known before the checkout);
this check keeps them equal to closure.txt, so a closure edit without the workflow edit fails CI.
A CI check, not part of the closure. Needs PyYAML.

Exit 0 when every checkout matches, 1 with one message per finding, 2 on usage errors.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_repo  # noqa: E402  (same directory: the duplicate-key YAML loader)

PREFIXES = ((":(glob)", "/"), (":(exclude,glob)", "!/"))


def expected_patterns(closure_text: str) -> List[str]:
    patterns: List[str] = []
    for raw in closure_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for magic, lead in PREFIXES:
            if line.startswith(magic):
                patterns.append(lead + line[len(magic) :])
                break
        else:
            raise ValueError(f"closure line '{line}' is not :(glob) or :(exclude,glob)")
    return patterns


def platform_checkouts(doc: Any) -> List[Any]:
    found: List[Any] = []
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    for job in (jobs or {}).values() if isinstance(jobs, dict) else []:
        steps = job.get("steps") if isinstance(job, dict) else None
        for step in steps if isinstance(steps, list) else []:
            uses = step.get("uses") if isinstance(step, dict) else None
            with_ = step.get("with") if isinstance(step, dict) else None
            if (
                isinstance(uses, str)
                and uses.startswith("actions/checkout@")
                and isinstance(with_, dict)
                and str(with_.get("repository", "")).lower() == check_repo.PLATFORM_REPO
            ):
                found.append(with_.get("sparse-checkout"))
    return found


def check(path: str, expected: List[str]) -> List[str]:
    _, doc, problems = check_repo.parse_yaml(path)
    if problems:
        return problems
    out: List[str] = []
    for value in platform_checkouts(doc):
        have = [p.strip() for p in str(value or "").splitlines() if p.strip()]
        if have != expected:
            missing = [p for p in expected if p not in have]
            extra = [p for p in have if p not in expected]
            detail = f"missing {missing}, extra {extra}" if missing or extra else "order differs"
            out.append(
                f"{path}: sis-platform sparse-checkout differs from closure.txt ({detail}) (AB8)"
            )
    return out


def main(argv: List[str]) -> int:
    if len(argv) < 3 or argv[0] != "--closure":
        print(__doc__, file=sys.stderr)
        return 2
    text = check_repo.read(argv[1])
    if text is None:
        return 2
    try:
        expected = expected_patterns(text)
    except ValueError as exc:
        print(f"{argv[1]}: {exc}", file=sys.stderr)
        return 1
    problems: List[str] = []
    for path in argv[2:]:
        problems += check(path, expected)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
