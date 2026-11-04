#!/usr/bin/env python3
"""The workflow closure (ADR 0002, L2): the files whose change moves `workflow_sha`.

`scripts/release/closure.txt` lists `:(glob)` git pathspecs, one per line (`#` starts a comment).

    workflow_sha = git log -1 --format=%H <release_sha> -- <closure pathspecs>

History on `main` is linear (squash merges only), so the value is well defined and deterministic;
it is never stored in the commit it names. Standard library only, Python 3.9 or later.

Usage: closure.py [--repo DIR] [--ref REF]    print the workflow_sha of REF (default HEAD)
"""

from __future__ import annotations

import subprocess  # noqa: S404  (read-only git)
import sys
from typing import List, Optional, Set

CLOSURE_PATH = "scripts/release/closure.txt"


class ClosureError(Exception):
    """A git or closure problem, with a message fit to print."""


def git(repo: str, *args: str) -> str:
    cmd = ["git", "-C", repo, *args]
    done = subprocess.run(cmd, capture_output=True, check=False)  # noqa: S603
    if done.returncode != 0:
        detail = done.stderr.decode(errors="replace").strip()
        raise ClosureError(f"git {args[0]} failed: {detail}")
    return done.stdout.decode(errors="replace")


def parse_specs(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def specs_at(repo: str, ref: str) -> Optional[List[str]]:
    """The closure pathspecs as committed at `ref`, or None when that commit has no closure.txt."""
    cmd = ["git", "-C", repo, "show", f"{ref}:{CLOSURE_PATH}"]
    done = subprocess.run(cmd, capture_output=True, check=False)  # noqa: S603
    if done.returncode != 0:
        return None
    return parse_specs(done.stdout.decode(errors="replace"))


def workflow_sha(repo: str, ref: str, specs: List[str]) -> str:
    if not specs:
        raise ClosureError("the closure has no pathspecs")
    try:
        out = git(repo, "log", "-1", "--format=%H", ref, "--", *specs).strip()
    except ClosureError as exc:
        raise ClosureError(f"git log failed for {ref}: {exc}") from exc
    if not out:
        raise ClosureError(f"no commit touches the closure pathspecs at {ref}")
    return out


def changed_paths(repo: str, old: str, new: str, specs: List[str]) -> List[str]:
    """Paths under the closure that differ between two refs. Renames are listed as two paths."""
    if not specs:
        return []
    out = git(repo, "diff", "--name-only", "--no-renames", "-z", old, new, "--", *specs)
    return sorted(p for p in out.split("\0") if p)


def tracked_files(repo: str, specs: List[str]) -> Set[str]:
    """Tracked files in the working tree of `repo` that the pathspecs cover."""
    if not specs:
        return set()
    out = git(repo, "ls-files", "-z", "--", *specs)
    return {p for p in out.split("\0") if p}


def main(argv: List[str]) -> int:
    repo, ref = ".", "HEAD"
    args = list(argv)
    while args:
        flag = args.pop(0)
        if flag in ("--repo", "--ref") and args:
            if flag == "--repo":
                repo = args.pop(0)
            else:
                ref = args.pop(0)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    try:
        specs = specs_at(repo, ref)
        if specs is None:
            raise ClosureError(f"{ref} has no {CLOSURE_PATH}")
        print(workflow_sha(repo, ref, specs))
    except ClosureError as exc:
        print(f"closure: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
