#!/usr/bin/env python3
"""The P9 check: a consumer repository is pinned to one sis-platform release (ADR 0002, L1 to L4).

Usage:
  check_lock.py [ROOT] [--remote] [--platform-repo SOURCE]

ROOT is the consumer repository (default: the current directory). Offline (the default) it needs no
network and no git, and checks:
  L1  platform.lock is JSON with exactly lock_version (1), version (vX.Y.Z), release_sha,
      workflow_sha and trusted_workflow_shas (1 to 2 distinct 40-hex values holding workflow_sha)
  L3  platform.yaml `platform.version` = lock `version`
  L3  every `trungleviet-agilityio/sis-platform/...@<x> # <v>` under .github/ (any YAML form) has
      x = workflow_sha and v = version
  L3  every `git::https://github.com/trungleviet-agilityio/sis-platform.git//modules/<m>?ref=<x>`
      has x = release_sha, and no other remote module source exists (local ./ and ../ are fine)
  L4  .claude/settings.json pins the `sis-platform` marketplace to ref = version
With --remote it also clones sis-platform (blobless, read-only; git only) and checks:
  tag `version` resolves to release_sha; release_sha is an ancestor of the main tip; the closure
  (scripts/release/closure.txt) recomputed at release_sha is workflow_sha; and for every SHA in
  trusted_workflow_shas: (a) it is an ancestor of the main tip, (b) it is the workflow_sha of some
  released v* tag, (c) its tree has no .github/workflows/reusable-release.yml while
  DEPLOY_TRUST_ALLOWED is false (Phase 1; the Phase 2 ADR flips it), so the deploy role stays inert.
--platform-repo replaces the public URL with a path or URL (the tests use a local fixture repo).

Exit 0 when clean, 1 with one message per finding on stderr, 2 on usage errors.
Standard library plus PyYAML (for the workflow files and platform.yaml), Python 3.9 or later.
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # noqa: S404  (read-only git, --remote only)
import sys
import tempfile
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import closure  # noqa: E402  (same directory)

PLATFORM = "trungleviet-agilityio/sis-platform"
PLATFORM_URL = f"https://github.com/{PLATFORM}.git"
# The Phase 2 ADR flips this when the deploy workflow ships (O9, L3 c).
DEPLOY_TRUST_ALLOWED = False
DEPLOY_WORKFLOW = ".github/workflows/reusable-release.yml"

LOCK_KEYS = ("lock_version", "version", "release_sha", "workflow_sha", "trusted_workflow_shas")
VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
COMMENT_RE = re.compile(r"#\s*(\S+)")
PLATFORM_USES_RE = re.compile(rf"^{re.escape(PLATFORM)}(?:[/@]|$)", re.IGNORECASE)
MODULE_RE = re.compile(r'\bmodule\s+(?:"[^"]*"|[A-Za-z_][\w-]*)\s*\{')
SOURCE_RE = re.compile(r'(?:^|[\s{,])"?source"?\s*=\s*"(?P<s>[^"]*)"')
HEREDOC_RE = re.compile(r"<<-?([A-Za-z_]\w*)[ \t]*\n")
HCL_SUFFIXES = (".tf", ".tofu")
JSON_SUFFIXES = (".tf.json", ".tofu.json")
ACTION_NAMES = ("action.yml", "action.yaml")
PLATFORM_MODULE_RE = re.compile(
    rf"^git::https://github\.com/{re.escape(PLATFORM)}\.git//modules/[a-z0-9-]+\?ref=(?P<ref>.+)$"
)
SKIP_DIRS = {".git", ".terraform"}


def _unique_keys(pairs: List[Any]) -> Dict[str, Any]:
    found: Dict[str, Any] = {}
    for key, value in pairs:
        if key in found:
            raise ValueError(f"duplicate key '{key}'")
        found[key] = value
    return found


def load_json(text: str) -> Any:
    """json.loads that refuses a repeated key (a parser keeps the last one, another the first)."""
    return json.loads(text, object_pairs_hook=_unique_keys)


def read_text(root: str, rel: str) -> tuple[Optional[str], List[str]]:
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as handle:
            return handle.read(), []
    except OSError as exc:
        return None, [f"{rel}: cannot read ({exc.strerror})"]


def load_yaml(text: str) -> Any:
    import yaml  # imported here so the message below can name the missing dependency

    return yaml.safe_load(text)


def check_lock_schema(rel: str, doc: Any) -> List[str]:
    if not isinstance(doc, dict):
        return [f"{rel}: must be a JSON object"]
    problems = [f"{rel}: missing key '{k}'" for k in LOCK_KEYS if k not in doc]
    problems += [f"{rel}: unknown key '{k}'" for k in doc if k not in LOCK_KEYS]
    if problems:
        return problems
    lock_version = doc["lock_version"]
    if type(lock_version) is not int or lock_version != 1:
        problems.append(f"{rel}: lock_version must be 1")
    if not (isinstance(doc["version"], str) and VERSION_RE.match(doc["version"])):
        problems.append(f"{rel}: version must look like vX.Y.Z")
    for key in ("release_sha", "workflow_sha"):
        if not (isinstance(doc[key], str) and SHA_RE.match(doc[key])):
            problems.append(f"{rel}: {key} must be 40 lowercase hex characters")
    trusted = doc["trusted_workflow_shas"]
    if not isinstance(trusted, list) or not 1 <= len(trusted) <= 2:
        problems.append(f"{rel}: trusted_workflow_shas must hold 1 or 2 values (N and N-1)")
    else:
        for value in trusted:
            if not (isinstance(value, str) and SHA_RE.match(value)):
                problems.append(
                    f"{rel}: trusted_workflow_shas value '{value}' must be 40 lowercase hex"
                )
        if len(set(map(str, trusted))) != len(trusted):
            problems.append(f"{rel}: trusted_workflow_shas values must be distinct")
        if doc["workflow_sha"] not in trusted:
            problems.append(f"{rel}: trusted_workflow_shas must contain workflow_sha")
    return problems


def collect_uses(node: Any) -> List[str]:
    found: List[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                found.append(value.strip())
            else:
                found.extend(collect_uses(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(collect_uses(item))
    return found


def yaml_files(root: str) -> List[str]:
    """yml/yaml files under .github/, plus every action.yml/yaml (not under .git or .terraform)."""
    found: Set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        rel_dir = os.path.relpath(dirpath, root)
        under_github = rel_dir == ".github" or rel_dir.startswith(".github" + os.sep)
        for name in sorted(filenames):
            lower = name.lower()
            if (under_github and lower.endswith((".yml", ".yaml"))) or lower in ACTION_NAMES:
                found.add(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(found)


def check_uses(root: str, lock: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    for rel in yaml_files(root):
        text, errs = read_text(root, rel)
        if text is None:
            problems += errs
            continue
        try:
            doc = load_yaml(text)
        except Exception as exc:  # noqa: BLE001  (any YAML error is a finding)
            problems.append(f"{rel}: invalid YAML ({exc})")
            continue
        lines = text.splitlines()
        for ref in collect_uses(doc):
            if not PLATFORM_USES_RE.match(ref):
                continue
            at = [i for i, line in enumerate(lines, 1) if ref in line and "uses" in line]
            where = f"{rel}:{at[0]}" if at else rel
            _, sep, pinned = ref.partition("@")
            if not sep:
                problems.append(f"{where}: uses '{ref}' has no @ref, expected workflow_sha (L3)")
                continue
            if pinned != lock["workflow_sha"]:
                problems.append(
                    f"{where}: uses '{ref}' is pinned to {pinned}, "
                    f"not workflow_sha {lock['workflow_sha']} (L3)"
                )
                continue
            comments = [COMMENT_RE.search(lines[i - 1]) for i in at]
            versions = {m.group(1) for m in comments if m}
            if not versions or not all(VERSION_RE.match(v) for v in versions):
                problems.append(f"{where}: uses '{ref}' has no '# vX.Y.Z' version comment")
            elif versions != {lock["version"]}:
                bad = sorted(versions - {lock["version"]})[0]
                problems.append(
                    f"{where}: uses '{ref}' has version comment '{bad}' "
                    f"but platform.lock version is {lock['version']} (L3)"
                )
    return problems


def strip_comments(text: str) -> str:
    """Blank out `#`, `//` and `/* */` comments, leaving strings and heredocs whole.

    Comment markers inside a quoted string (the platform URL holds `//modules`) are not comments,
    and a quote inside a heredoc must not open a string. Newlines are kept.
    """
    out: List[str] = []
    i, n, in_str = 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            in_str = c != '"'
            i += 1
            continue
        heredoc = HEREDOC_RE.match(text, i) if c == "<" else None
        if heredoc:
            end = re.search(
                rf"^[ \t]*{re.escape(heredoc.group(1))}[ \t]*$", text[heredoc.end() :], re.M
            )
            stop = n if end is None else heredoc.end() + end.end()
            out.append(text[i:stop])
            i = stop
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif text.startswith("/*", i):
            close = text.find("*/", i + 2)
            stop = n if close < 0 else close + 2
            out.append("".join(ch if ch == "\n" else " " for ch in text[i:stop]))
            i = stop
        elif c == "#" or text.startswith("//", i):
            newline = text.find("\n", i)
            stop = n if newline < 0 else newline
            out.append(" " * (stop - i))
            i = stop
        else:
            out.append(c)
            i += 1
    return "".join(out)


def block_end(text: str, start: int) -> int:
    """Index just past the `}` that closes the block whose `{` ended just before `start`."""
    depth, i, n, in_str = 1, start, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def module_sources(text: str) -> List[str]:
    """Every `source = "..."` in a `module <label> { }` block, wherever the block starts."""
    clean = strip_comments(text)
    sources: List[str] = []
    for start in MODULE_RE.finditer(clean):
        body = clean[start.end() : block_end(clean, start.end())]
        sources += [m.group("s") for m in SOURCE_RE.finditer(body)]
    return sources


def json_module_sources(doc: Any) -> List[str]:
    """`module.<name>.source` of a *.tf.json document (each level may be an object or a list)."""

    def as_list(value: Any) -> List[Any]:
        return value if isinstance(value, list) else [value]

    sources: List[str] = []
    if not isinstance(doc, dict):
        return sources
    for group in as_list(doc.get("module")):
        if not isinstance(group, dict):
            continue
        for body in group.values():
            for item in as_list(body):
                if isinstance(item, dict) and isinstance(item.get("source"), str):
                    sources.append(item["source"])
    return sources


def check_modules(root: str, lock: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            lower = name.lower()
            is_json = lower.endswith(JSON_SUFFIXES)
            if not (is_json or lower.endswith(HCL_SUFFIXES)):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            text, errs = read_text(root, rel)
            if text is None:
                problems += errs
                continue
            if is_json:
                try:
                    sources = json_module_sources(load_json(text))
                except ValueError as exc:
                    problems.append(f"{rel}: not valid JSON ({exc})")
                    continue
            else:
                sources = module_sources(text)
            for source in sources:
                if source.startswith(("./", "../")):
                    continue
                match = PLATFORM_MODULE_RE.match(source)
                if not match:
                    problems.append(
                        f"{rel}: remote module source '{source}' is not sis-platform at "
                        "release_sha (L3)"
                    )
                elif match.group("ref") != lock["release_sha"]:
                    problems.append(
                        f"{rel}: module source '{source}' is pinned to ref {match.group('ref')}, "
                        f"not release_sha {lock['release_sha']} (L3)"
                    )
    return problems


def check_settings(root: str, lock: Dict[str, Any]) -> List[str]:
    rel = ".claude/settings.json"
    text, errs = read_text(root, rel)
    if text is None:
        return errs
    try:
        doc = load_json(text)
    except ValueError as exc:
        return [f"{rel}: not valid JSON ({exc})"]
    market = None
    if isinstance(doc, dict) and isinstance(doc.get("extraKnownMarketplaces"), dict):
        market = doc["extraKnownMarketplaces"].get("sis-platform")
    head = f"{rel}: extraKnownMarketplaces.sis-platform"
    if not isinstance(market, dict) or not isinstance(market.get("source"), dict):
        return [f"{head} is missing (L4)"]
    source = market["source"]
    problems: List[str] = []
    if source.get("source") != "github":
        problems.append(f"{head}.source.source must be 'github' (L4)")
    if source.get("repo") != PLATFORM:
        problems.append(f"{head}.source.repo is '{source.get('repo')}', expected {PLATFORM} (L4)")
    if source.get("ref") != lock["version"]:
        problems.append(
            f"{head}.source.ref is '{source.get('ref')}', expected the lock version "
            f"'{lock['version']}' (L4)"
        )
    markets = doc["extraKnownMarketplaces"]
    for name, entry in markets.items():
        if name == "sis-platform" or not isinstance(entry, dict):
            continue
        other = entry.get("source")
        if not isinstance(other, dict) or not any(
            isinstance(v, str) and "sis-platform" in v.lower() for v in other.values()
        ):
            continue
        if other.get("ref") != lock["version"]:
            problems.append(
                f"{rel}: extraKnownMarketplaces.{name} points at sis-platform with ref "
                f"'{other.get('ref')}', expected the lock version '{lock['version']}' (L4)"
            )
    return problems


def check_offline(root: str) -> tuple[List[str], Optional[Dict[str, Any]]]:
    """Findings, and the lock when platform.lock itself is well formed."""
    text, problems = read_text(root, "platform.lock")
    if text is None:
        return problems, None
    try:
        doc = load_json(text)
    except ValueError as exc:
        return [f"platform.lock: not valid JSON ({exc})"], None
    schema_problems = check_lock_schema("platform.lock", doc)
    if schema_problems:
        return schema_problems, None
    lock: Dict[str, Any] = doc
    manifest, errs = read_text(root, "platform.yaml")
    if manifest is None:
        problems += errs
    else:
        try:
            parsed = load_yaml(manifest)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"platform.yaml: invalid YAML ({exc})")
        else:
            platform = parsed.get("platform") if isinstance(parsed, dict) else None
            version = platform.get("version") if isinstance(platform, dict) else None
            if version != lock["version"]:
                problems.append(
                    f"platform.yaml: platform.version '{version}' does not match "
                    f"platform.lock version '{lock['version']}' (L3)"
                )
    problems += check_uses(root, lock)
    problems += check_modules(root, lock)
    problems += check_settings(root, lock)
    return problems, lock


class Platform:
    """A local clone of sis-platform, read-only."""

    def __init__(self, path: str) -> None:
        self.path = path

    def run(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        cmd = ["git", "-C", self.path, *args]
        return subprocess.run(cmd, capture_output=True, check=False)  # noqa: S603

    def out(self, *args: str) -> Optional[str]:
        done = self.run(*args)
        return done.stdout.decode().strip() if done.returncode == 0 else None

    def is_commit(self, sha: str) -> bool:
        return self.run("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0

    def is_ancestor(self, sha: str, tip: str) -> bool:
        return self.run("merge-base", "--is-ancestor", sha, tip).returncode == 0

    def has_file(self, sha: str, rel: str) -> bool:
        return self.run("cat-file", "-e", f"{sha}:{rel}").returncode == 0

    def released_workflow_shas(self, tip: str) -> Set[str]:
        """workflow_sha of every vX.Y.Z tag whose commit is on main (other tags release nothing).

        Annotated tags are the preferred form for releases; a lightweight tag counts the same
        here, and the immutable-tag ruleset (L4) is what protects either kind.
        """
        found: Set[str] = set()
        for tag in (self.out("tag", "--list", "v*") or "").splitlines():
            if not VERSION_RE.match(tag):
                continue
            commit = self.out("rev-parse", f"refs/tags/{tag}^{{commit}}")
            specs = closure.specs_at(self.path, tag)
            if commit is None or specs is None or not self.is_ancestor(commit, tip):
                continue  # a tag from before the closure existed cannot be a released workflow_sha
            try:
                found.add(closure.workflow_sha(self.path, commit, specs))
            except closure.ClosureError:
                continue
        return found


def clone(source: str, into: str) -> tuple[Optional[Platform], List[str]]:
    cmd = ["git", "clone", "--quiet", "--no-checkout"]
    if source.startswith(("https://", "http://", "file://")):
        cmd.append("--filter=blob:none")
    cmd += [source, into]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    done = subprocess.run(cmd, capture_output=True, check=False, env=env)  # noqa: S603
    if done.returncode != 0:
        detail = done.stderr.decode(errors="replace").strip().splitlines()
        return None, [f"cannot clone {source} ({detail[-1] if detail else 'git failed'})"]
    return Platform(into), []


def check_remote(lock: Dict[str, Any], source: str) -> List[str]:
    problems: List[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        platform, errs = clone(source, os.path.join(tmp, "sis-platform"))
        if platform is None:
            return errs
        tip = platform.out("rev-parse", "--verify", "refs/remotes/origin/main^{commit}")
        if tip is None:
            return ["sis-platform has no main branch to check against (L3)"]
        version, release, workflow = lock["version"], lock["release_sha"], lock["workflow_sha"]
        tagged = platform.out("rev-parse", "--verify", f"refs/tags/{version}^{{commit}}")
        if tagged is None:
            problems.append(f"tag {version} does not exist in sis-platform (L3)")
        elif tagged != release:
            problems.append(f"tag {version} resolves to {tagged}, not release_sha {release} (L3)")
        if not platform.is_commit(release):
            problems.append(f"release_sha {release} is not a commit in sis-platform (L3)")
        else:
            if not platform.is_ancestor(release, tip):
                problems.append(
                    f"release_sha {release} is not an ancestor of the sis-platform main tip (L3)"
                )
            specs = closure.specs_at(platform.path, release)
            if specs is None:
                problems.append(f"release_sha {release} has no {closure.CLOSURE_PATH} (L2)")
            else:
                try:
                    computed = closure.workflow_sha(platform.path, release, specs)
                except closure.ClosureError as exc:
                    problems.append(f"cannot recompute the closure at release_sha ({exc})")
                else:
                    if computed != workflow:
                        problems.append(
                            f"the closure recomputed at release_sha is {computed}, "
                            f"not workflow_sha {workflow} (L3)"
                        )
        released: Optional[Set[str]] = None
        for sha in lock["trusted_workflow_shas"]:
            head = f"trusted_workflow_shas {sha}:"
            if not platform.is_commit(sha):
                problems.append(f"{head} not a commit in sis-platform (L3)")
                continue
            if not platform.is_ancestor(sha, tip):
                problems.append(f"{head} not an ancestor of the sis-platform main tip (L3 a)")
            if released is None:
                released = platform.released_workflow_shas(tip)
            if sha not in released:
                problems.append(f"{head} not the workflow_sha of any released v* tag (L3 b)")
            if not DEPLOY_TRUST_ALLOWED and platform.has_file(sha, DEPLOY_WORKFLOW):
                problems.append(
                    f"{head} its tree holds {DEPLOY_WORKFLOW} while DEPLOY_TRUST_ALLOWED is false "
                    "(L3 c)"
                )
    return problems


def main(argv: List[str]) -> int:
    root, remote, source = ".", False, PLATFORM_URL
    args = list(argv)
    positional: List[str] = []
    while args:
        arg = args.pop(0)
        if arg == "--remote":
            remote = True
        elif arg == "--platform-repo" and args:
            source = args.pop(0)
        elif arg.startswith("-") or len(positional) == 1:
            print(__doc__, file=sys.stderr)
            return 2
        else:
            positional.append(arg)
    if positional:
        root = positional[0]
    if not os.path.isdir(root):
        print(f"{root}: is not a directory", file=sys.stderr)
        return 2
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("PyYAML is required (make venv, or pip install PyYAML)", file=sys.stderr)
        return 2
    problems, lock = check_offline(root)
    if remote and lock is not None:
        problems += check_remote(lock, source)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
