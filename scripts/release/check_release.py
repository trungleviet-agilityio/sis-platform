#!/usr/bin/env python3
"""Release check (ADR 0002, L4, L7): run before cutting a tag.

Usage:
  check_release.py --tag vX.Y.Z --sha SHA [--repo DIR] [--prev REF]

Prints, for the commit SHA that will carry the tag:
  - its workflow_sha (L2) and whether it moved since the previous release (--prev, default: the
    highest released v* tag below TAG that is an ancestor of SHA);
  - the closure paths that changed between the two (renames list both paths).
Fails (exit 1) when
  - TAG is a patch release (vX.Y.Z with Z > 0) and workflow_sha moved: a trust move needs a minor
    release (L7);
  - a `.claude-plugin/plugin.json` version, or `intake/sis_intake/__init__.py` `__version__`,
    differs from TAG (L4). Versions are read from the commit SHA, not the working tree.
Exit 2 on usage errors or an unreadable ref. Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "platform"))
import closure  # noqa: E402  (scripts/platform/closure.py)

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
INIT_PATH = "intake/sis_intake/__init__.py"
VERSION_LINE_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)


def parse_tag(tag: str) -> Optional[Tuple[int, int, int]]:
    match = TAG_RE.match(tag)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def previous_tag(repo: str, want: Tuple[int, int, int], sha: str) -> Optional[str]:
    best: Optional[Tuple[Tuple[int, int, int], str]] = None
    for name in closure.git(repo, "tag", "--list", "v*").split():
        version = parse_tag(name)
        if version is None or version >= want:
            continue
        try:
            closure.git(repo, "merge-base", "--is-ancestor", f"refs/tags/{name}", sha)
        except closure.ClosureError:
            continue
        if best is None or version > best[0]:
            best = (version, name)
    return best[1] if best else None


def version_problems(repo: str, tag: str, sha: str) -> List[str]:
    want = tag[1:]
    problems: List[str] = []
    listing = closure.git(repo, "ls-tree", "-r", "--name-only", "-z", sha)
    plugins = sorted(p for p in listing.split("\0") if p.endswith(".claude-plugin/plugin.json"))
    if not plugins:
        problems.append("no .claude-plugin/plugin.json found in the release commit (L4)")
    for path in plugins:
        try:
            doc = json.loads(closure.git(repo, "show", f"{sha}:{path}"))
        except (closure.ClosureError, ValueError) as exc:
            problems.append(f"{path}: cannot read ({exc}) (L4)")
            continue
        version = doc.get("version") if isinstance(doc, dict) else None
        if version is None:
            problems.append(f"{path}: no version (L4)")
        elif version != want:
            problems.append(f"{path}: version {version} does not match tag {tag} (L4)")
    try:
        init = closure.git(repo, "show", f"{sha}:{INIT_PATH}")
    except closure.ClosureError:
        return problems + [f"{INIT_PATH}: cannot read in the release commit (L4)"]
    found = VERSION_LINE_RE.search(init)
    if not found:
        problems.append(f"{INIT_PATH}: no __version__ found (L4)")
    elif found.group(1) != want:
        problems.append(f"{INIT_PATH}: __version__ {found.group(1)} does not match tag {tag} (L4)")
    return problems


def main(argv: List[str]) -> int:
    repo, tag, sha, prev = ".", "", "", ""
    args = list(argv)
    while args:
        flag = args.pop(0)
        if flag in ("--repo", "--tag", "--sha", "--prev") and args:
            value = args.pop(0)
            if flag == "--repo":
                repo = value
            elif flag == "--tag":
                tag = value
            elif flag == "--sha":
                sha = value
            else:
                prev = value
        else:
            print(__doc__, file=sys.stderr)
            return 2
    if not tag or not sha:
        print(__doc__, file=sys.stderr)
        return 2
    version = parse_tag(tag)
    if version is None:
        print(f"tag must look like vX.Y.Z, got '{tag}'", file=sys.stderr)
        return 2
    try:
        closure.git(repo, "cat-file", "-e", f"{sha}^{{commit}}")
    except closure.ClosureError:
        print(f"{sha} is not a commit in {repo}", file=sys.stderr)
        return 2
    problems: List[str] = []
    try:
        specs = closure.specs_at(repo, sha)
        if specs is None:
            print(f"{sha} has no {closure.CLOSURE_PATH}", file=sys.stderr)
            return 2
        current = closure.workflow_sha(repo, sha, specs)
        prev_ref = prev or previous_tag(repo, version, sha)
        print(f"tag: {tag}")
        print(f"sha: {sha}")
        print(f"workflow_sha: {current}")
        moved = False
        paths: List[str] = []
        if prev_ref is None:
            print("previous tag: none (first release)")
        else:
            try:
                prev_sha = closure.git(
                    repo, "rev-parse", "--verify", f"{prev_ref}^{{commit}}"
                ).strip()
            except closure.ClosureError:
                print(f"cannot resolve previous ref {prev_ref}", file=sys.stderr)
                return 2
            print(f"previous tag: {prev_ref}")
            prev_specs = closure.specs_at(repo, prev_sha)
            if prev_specs is None:
                moved = True
                print(
                    f"previous tag {prev_ref} has no {closure.CLOSURE_PATH}, so workflow_sha is new"
                )
                prev_specs = []
            else:
                before = closure.workflow_sha(repo, prev_sha, prev_specs)
                moved = before != current
                print(f"previous workflow_sha: {before}")
            union = sorted(set(specs) | set(prev_specs))
            paths = closure.changed_paths(repo, prev_sha, sha, union)
        print(f"workflow_sha moved: {'yes' if moved else 'no'}")
        if paths:
            print("closure paths changed:")
            for path in paths:
                print(f"  {path}")
        else:
            print("closure paths changed: none")
        if moved and prev_ref is not None and version[2] > 0:
            problems.append(
                f"patch release {tag} moves workflow_sha; a trust move needs a minor release (L7)"
            )
        problems += version_problems(repo, tag, sha)
    except closure.ClosureError as exc:
        print(f"check_release: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
