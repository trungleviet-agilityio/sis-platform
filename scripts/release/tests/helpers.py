"""Fixture builders for the lock and release tests: throwaway git repos, never the network.

A `Repo` is a local git repository that stands in for sis-platform (the `--platform-repo` of
check_lock.py). `consumer` writes a consumer checkout that passes every offline L3 check.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess  # noqa: S404  (fixture git repos)
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "platform"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "release"))

GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}

CLOSURE = """# closure fixture
:(glob)scripts/release/closure.txt
:(glob).github/workflows/reusable-*.yml
:(glob)scripts/platform/**
:(glob)scripts/aws/**
:(glob)scripts/lib.sh
:(glob)scripts/tf/policy.py
"""

PLUGIN = '{"name": "%s", "version": "%s"}\n'
INIT = '"""pkg."""\n\n__version__ = "%s"\n'
PLATFORM = "trungleviet-agilityio/sis-platform"


def git(repo: Path, *args: str) -> str:
    cmd = ["git", "-C", str(repo), *args]
    out = subprocess.run(cmd, capture_output=True, env=GIT_ENV, check=True)  # noqa: S603
    return out.stdout.decode().strip()


class Repo:
    """A fixture git repository with `main` checked out."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True, exist_ok=True)
        git(path, "init", "-q", "-b", "main")

    def write(self, rel: str, text: str) -> None:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def move(self, old: str, new: str) -> None:
        (self.path / new).parent.mkdir(parents=True, exist_ok=True)
        git(self.path, "mv", old, new)

    def commit(self, message: str = "c") -> str:
        git(self.path, "add", "-A")
        git(self.path, "commit", "-q", "--allow-empty", "-m", message)
        return git(self.path, "rev-parse", "HEAD")

    def tag(self, name: str, ref: str = "HEAD") -> str:
        git(self.path, "tag", name, ref)
        return git(self.path, "rev-parse", f"{name}^{{commit}}")

    def head(self) -> str:
        return git(self.path, "rev-parse", "HEAD")

    def checkout_new(self, branch: str, start: str = "HEAD") -> None:
        git(self.path, "checkout", "-q", "-b", branch, start)

    def checkout(self, branch: str) -> None:
        git(self.path, "checkout", "-q", branch)

    def seed(self, version: str = "0.1.0") -> str:
        """Initial closure content plus plugin files and a version constant."""
        self.write("scripts/release/closure.txt", CLOSURE)
        self.write("scripts/platform/tool.py", "print('tool')\n")
        self.write("scripts/aws/helper.sh", "# helper\n")
        self.write("scripts/lib.sh", "# lib\n")
        self.write("scripts/tf/policy.py", "# policy\n")
        self.write("scripts/tf/test_policy.py", "# test, outside the closure\n")
        self.write(".github/workflows/reusable-terraform-apply.yml", "name: apply\n")
        self.write("docs/readme.md", "docs\n")
        self.bump_versions(version)
        return self.commit("seed")

    def bump_versions(self, version: str) -> None:
        self.write("intake/.claude-plugin/plugin.json", PLUGIN % ("sis-intake", version))
        self.write("plugins/sis-team/.claude-plugin/plugin.json", PLUGIN % ("sis-team", version))
        self.write("intake/sis_intake/__init__.py", INIT % version)


def lock_text(
    version: str, release_sha: str, workflow: str, trusted: Optional[List[str]] = None
) -> str:
    doc: Dict[str, Any] = {
        "lock_version": 1,
        "version": version,
        "release_sha": release_sha,
        "workflow_sha": workflow,
        "trusted_workflow_shas": trusted if trusted is not None else [workflow],
    }
    return json.dumps(doc, indent=2) + "\n"


def consumer(
    path: Path,
    version: str,
    release_sha: str,
    workflow: str,
    trusted: Optional[List[str]] = None,
) -> Path:
    """A consumer checkout that passes offline L3 for the given lock values."""
    source = f"git::https://github.com/{PLATFORM}.git//modules/account-bootstrap?ref={release_sha}"
    uses = f"{PLATFORM}/.github/workflows/reusable-terraform-plan.yml@{workflow}"
    marketplace = {
        "extraKnownMarketplaces": {
            "sis-platform": {"source": {"source": "github", "repo": PLATFORM, "ref": version}}
        }
    }
    files = {
        "platform.lock": lock_text(version, release_sha, workflow, trusted),
        "platform.yaml": f"schema_version: 1\nplatform: {{version: {version}}}\n",
        ".github/workflows/terraform.yml": (
            f"name: t\non: push\njobs:\n  plan:\n    uses: {uses} # {version}\n"
        ),
        "infra/bootstrap/main.tf": (
            f'module "bootstrap" {{\n  source = "{source}"\n}}\n\n'
            'module "local" {\n  source = "../../local-module"\n}\n\n'
            'terraform {\n  required_providers {\n    aws = {\n      source = "hashicorp/aws"\n'
            "    }\n  }\n}\n"
        ),
        ".claude/settings.json": json.dumps(marketplace),
    }
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return path


def run_main(module: Any, argv: List[str]) -> Tuple[int, str, str]:
    """Run module.main(argv) and return (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = module.main(argv)
    return rc, out.getvalue(), err.getvalue()
