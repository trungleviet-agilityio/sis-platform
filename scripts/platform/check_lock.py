#!/usr/bin/env python3
"""The P9 check: a consumer repository is pinned to one sis-platform release (ADR 0002, L1 to L4).

Usage:
  check_lock.py [ROOT] [--remote] [--platform-repo SOURCE] [--platform-checkout]

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
--platform-repo replaces the public URL with a path or URL (the tests use a local fixture repo);
its value may not start with '-'.
--platform-checkout is for examples/consumer inside a sis-platform checkout: local module sources
may then leave ROOT, but never the checkout (the nearest ancestor holding
scripts/release/closure.txt). Without it, ROOT is the boundary.
Also refused: a module `source` that is not one plain string literal, a local source through a
.terraform or .git segment, a symlink to a directory or out of ROOT, a duplicate YAML key, a
`uses:` of sis-platform that is not a reusable-*.yml workflow.

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
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import closure  # noqa: E402  (same directory)

PLATFORM = "trungleviet-agilityio/sis-platform"
PLATFORM_URL = f"https://github.com/{PLATFORM}.git"
# A stuck git call must not hang a CI job.
GIT_TIMEOUT = 120
CLONE_TIMEOUT = 600
# The Phase 2 ADR flips this when the deploy workflow ships (O9, L3 c).
DEPLOY_TRUST_ALLOWED = False
DEPLOY_WORKFLOW = ".github/workflows/reusable-release.yml"

LOCK_KEYS = ("lock_version", "version", "release_sha", "workflow_sha", "trusted_workflow_shas")
VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
COMMENT_RE = re.compile(r"#\s*(\S+)")
PLATFORM_USES_RE = re.compile(rf"^{re.escape(PLATFORM)}(?:[/@]|$)", re.IGNORECASE)
MODULE_RE = re.compile(r'\bmodule\s+(?:"[^"]*"|[A-Za-z_][\w-]*)\s*\{')
ATTR_RE = re.compile(r'"?source"?[ \t]*=(?!=)[ \t]*')
REUSABLE_PATH_RE = re.compile(
    rf"^{re.escape(PLATFORM)}/\.github/workflows/reusable-[A-Za-z0-9._-]+\.yml$", re.IGNORECASE
)
NOT_PLAIN = "module source is not a single plain string literal"
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
    """Safe YAML load that refuses a repeated mapping key (GitHub keeps one, PyYAML the last)."""
    import yaml  # imported here so main() can name the missing dependency

    class UniqueKeyLoader(yaml.SafeLoader):
        def construct_mapping(self, node: Any, deep: bool = False) -> Dict[Any, Any]:
            self.flatten_mapping(node)
            mapping: Dict[Any, Any] = super().construct_mapping(node, deep=deep)
            if len(mapping) != len(node.value):
                raise yaml.constructor.ConstructorError(
                    None, None, "duplicate key in a mapping", node.start_mark
                )
            return mapping

    loader = UniqueKeyLoader(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


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
    if not (isinstance(doc["version"], str) and VERSION_RE.fullmatch(doc["version"])):
        problems.append(f"{rel}: version must look like vX.Y.Z")
    for key in ("release_sha", "workflow_sha"):
        if not (isinstance(doc[key], str) and SHA_RE.fullmatch(doc[key])):
            problems.append(f"{rel}: {key} must be 40 lowercase hex characters")
    trusted = doc["trusted_workflow_shas"]
    if not isinstance(trusted, list) or not 1 <= len(trusted) <= 2:
        problems.append(f"{rel}: trusted_workflow_shas must hold 1 or 2 values (N and N-1)")
    else:
        for value in trusted:
            if not (isinstance(value, str) and SHA_RE.fullmatch(value)):
                problems.append(
                    f"{rel}: trusted_workflow_shas value '{value}' must be 40 lowercase hex"
                )
        if len(set(map(str, trusted))) != len(trusted):
            problems.append(f"{rel}: trusted_workflow_shas values must be distinct")
        if doc["workflow_sha"] not in trusted:
            problems.append(f"{rel}: trusted_workflow_shas must contain workflow_sha")
    return problems


def collect_uses(node: Any) -> List[Any]:
    """Every value under a `uses` key; a non-string value is kept so the caller can refuse it."""
    found: List[Any] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses":
                found.append(value.strip() if isinstance(value, str) else value)
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
            if not isinstance(ref, str):
                problems.append(f"{rel}: uses value is not a plain string (L3)")
                continue
            if not PLATFORM_USES_RE.match(ref):
                continue
            at = [i for i, line in enumerate(lines, 1) if ref in line and "uses" in line]
            where = f"{rel}:{at[0]}" if at else rel
            if not REUSABLE_PATH_RE.match(ref.partition("@")[0]):
                problems.append(
                    f"{where}: uses '{ref}' is not a reusable-*.yml workflow of sis-platform (W1)"
                )
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
            if not versions or not all(VERSION_RE.fullmatch(v) for v in versions):
                problems.append(f"{where}: uses '{ref}' has no '# vX.Y.Z' version comment")
            elif versions != {lock["version"]}:
                bad = sorted(versions - {lock["version"]})[0]
                problems.append(
                    f"{where}: uses '{ref}' has version comment '{bad}' "
                    f"but platform.lock version is {lock['version']} (L3)"
                )
    return problems


def skip_heredoc(text: str, match: re.Match[str]) -> int:
    """Index just past the closing marker line of the heredoc that `match` opens."""
    end = re.search(rf"^[ \t]*{re.escape(match.group(1))}[ \t]*$", text[match.end() :], re.M)
    return len(text) if end is None else match.end() + end.end()


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
            stop = skip_heredoc(text, heredoc)
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


def skip_string(text: str, start: int) -> int:
    """Index just past the closing quote of the string that opens at `start` (or the end)."""
    i, n = start + 1, len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
        elif text[i] == '"':
            return i + 1
        else:
            i += 1
    return n


def block_end(text: str, start: int) -> int:
    """Index just past the `}` that closes the block whose `{` ended just before `start`."""
    depth, i, n = 1, start, len(text)
    while i < n:
        c = text[i]
        heredoc = HEREDOC_RE.match(text, i) if c == "<" else None
        if heredoc:
            i = skip_heredoc(text, heredoc)
            continue
        if c == '"':
            i = skip_string(text, i)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def read_source_value(body: str, start: int) -> Tuple[str, bool, int]:
    """(value, is one plain string literal, next index) of the attribute value at `start`."""
    n = len(body)
    if start < n and body[start] == '"':
        i, plain = start + 1, True
        while i < n and body[i] != '"':
            if body[i] == "\\" or (body[i] in "$%" and body[i + 1 : i + 2] == "{"):
                plain = False
            i += 2 if body[i] == "\\" else 1
        if i >= n:
            return body[start:].strip()[:80], False, n
        rest = body[i + 1 :]
        tail = rest[: rest.find("\n")] if "\n" in rest else rest
        return body[start + 1 : i], plain and not tail.strip(), i + 1
    eol = body.find("\n", start)
    snippet = body[start : n if eol < 0 else eol].strip()[:80]
    return snippet, False, start


def source_values(body: str) -> List[Tuple[str, bool]]:
    """The module's own `source` attributes (nesting depth 0): (value, is one plain literal)."""
    found: List[Tuple[str, bool]] = []
    depth, i, n = 0, 0, len(body)
    while i < n:
        c = body[i]
        if depth == 0 and c in 's"' and (i == 0 or body[i - 1] in " \t\n,{"):
            attr = ATTR_RE.match(body, i)
            if attr:
                value, plain, i = read_source_value(body, attr.end())
                found.append((value, plain))
                continue
        heredoc = HEREDOC_RE.match(body, i) if c == "<" else None
        if heredoc:
            i = skip_heredoc(body, heredoc)
            continue
        if c == '"':
            i = skip_string(body, i)
            continue
        if c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
        i += 1
    return found


def module_sources(text: str) -> List[Tuple[str, bool]]:
    """Every module `source` in `module <label> { }` blocks: (value, is one plain literal)."""
    clean = strip_comments(text)
    sources: List[Tuple[str, bool]] = []
    for start in MODULE_RE.finditer(clean):
        body = clean[start.end() : block_end(clean, start.end()) - 1]
        sources += source_values(body)
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


def inside(path: str, boundary: str) -> bool:
    return path == boundary or path.startswith(boundary.rstrip(os.sep) + os.sep)


def local_source_problems(
    rel: str, source: str, dirpath: str, boundary: str, boundary_name: str
) -> List[str]:
    """A ./ or ../ module source stays in the boundary and avoids .terraform and .git."""
    target = os.path.normpath(os.path.join(dirpath, source))
    segments = set(source.split("/")) | set(target.split(os.sep))
    if segments & SKIP_DIRS:
        return [
            f"{rel}: local module source '{source}' goes through a .terraform or .git directory"
        ]
    if not inside(os.path.realpath(target), boundary):
        return [f"{rel}: local module source '{source}' leaves the {boundary_name}"]
    return []


def check_symlinks(root: str) -> List[str]:
    """A symlink to a directory, or out of ROOT, hides files from the scans (not followed)."""
    problems: List[str] = []
    real_root = os.path.realpath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(dirnames + filenames):
            path = os.path.join(dirpath, name)
            if not os.path.islink(path):
                continue
            rel = os.path.relpath(path, root)
            real = os.path.realpath(path)
            if os.path.isdir(real):
                problems.append(f"{rel}: symlink {rel} points to a directory (not followed) (L3)")
            elif not inside(real, real_root):
                problems.append(f"{rel}: symlink {rel} leaves the repository root (L3)")
    return problems


def check_modules(
    root: str, lock: Dict[str, Any], boundary: str, boundary_name: str = "repository root"
) -> List[str]:
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
                    sources = [(v, True) for v in json_module_sources(load_json(text))]
                except ValueError as exc:
                    problems.append(f"{rel}: not valid JSON ({exc})")
                    continue
            else:
                sources = module_sources(text)
            for source, plain in sources:
                if not plain:
                    problems.append(f"{rel}: {NOT_PLAIN}: {source} (L3)")
                elif source.startswith(("./", "../")):
                    problems += local_source_problems(rel, source, dirpath, boundary, boundary_name)
                else:
                    match = PLATFORM_MODULE_RE.match(source)
                    if not match:
                        problems.append(
                            f"{rel}: remote module source '{source}' is not sis-platform at "
                            "release_sha (L3)"
                        )
                    elif match.group("ref") != lock["release_sha"]:
                        problems.append(
                            f"{rel}: module source '{source}' is pinned to ref "
                            f"{match.group('ref')}, not release_sha {lock['release_sha']} (L3)"
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


def check_offline(
    root: str, boundary: Optional[str] = None, boundary_name: str = "repository root"
) -> tuple[List[str], Optional[Dict[str, Any]]]:
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
    problems += check_symlinks(root)
    problems += check_uses(root, lock)
    problems += check_modules(root, lock, boundary or os.path.realpath(root), boundary_name)
    problems += check_settings(root, lock)
    return problems, lock


class Platform:
    """A local clone of sis-platform, read-only."""

    def __init__(self, path: str) -> None:
        self.path = path

    def run(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        cmd = ["git", "-C", self.path, *args]
        try:
            return subprocess.run(  # noqa: S603
                cmd, capture_output=True, check=False, timeout=GIT_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, 124, b"", b"timed out")

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
            try:
                specs = closure.specs_at(self.path, tag)
                if commit is None or specs is None or not self.is_ancestor(commit, tip):
                    continue  # a tag from before the closure existed cannot be released
                found.add(closure.workflow_sha(self.path, commit, specs))
            except closure.ClosureError:
                continue
        return found


def clone(source: str, into: str) -> tuple[Optional[Platform], List[str]]:
    cmd = ["git", "clone", "--quiet", "--no-checkout"]
    if source.startswith(("https://", "http://", "file://")):
        cmd.append("--filter=blob:none")
    cmd += ["--", source, into]  # "--": a source can never be read as an option
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        done = subprocess.run(  # noqa: S603
            cmd, capture_output=True, check=False, env=env, timeout=CLONE_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return None, [f"cannot clone {source} (timed out after {CLONE_TIMEOUT} seconds)"]
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
            try:
                specs = closure.specs_at(platform.path, release)
            except closure.ClosureError as exc:
                specs = None
                problems.append(f"release_sha {release}: {exc} (L2)")
            else:
                if specs is None:
                    problems.append(f"release_sha {release} has no {closure.CLOSURE_PATH} (L2)")
            if specs is not None:
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


def find_checkout(root: str) -> Optional[str]:
    """The nearest ancestor of ROOT holding scripts/release/closure.txt (a platform checkout)."""
    here = os.path.dirname(os.path.realpath(root))
    while True:
        if os.path.isfile(os.path.join(here, closure.CLOSURE_PATH)):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def main(argv: List[str]) -> int:
    root, remote, source, checkout = ".", False, PLATFORM_URL, False
    args = list(argv)
    positional: List[str] = []
    while args:
        arg = args.pop(0)
        if arg == "--remote":
            remote = True
        elif arg == "--platform-checkout":
            checkout = True
        elif arg == "--platform-repo" and args:
            source = args.pop(0)
            if source.startswith("-"):
                print("--platform-repo value must not start with '-'", file=sys.stderr)
                return 2
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
    boundary, boundary_name = None, "repository root"
    if checkout:
        boundary = find_checkout(root)
        if boundary is None:
            print(f"--platform-checkout: no sis-platform checkout above {root}", file=sys.stderr)
            return 2
        boundary_name = "sis-platform checkout"
    problems, lock = check_offline(root, boundary, boundary_name)
    if remote and lock is not None:
        problems += check_remote(lock, source)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
