#!/usr/bin/env python3
"""PreToolUse guard: block commands that change AWS or GitHub state, and reads of secret files.

Layer 3 of the guardrails (ADR 0001 B8, ADR 0002 S2). Permission deny rules match the command text
as
written, so `terraform -chdir=envs/dev apply` or `bash -c '...'` slip past them. This hook parses
the
whole command instead: it splits it into simple commands outside quotes, strips prefixes (`env`,
`sudo`,
`VAR=x`, `then`, ...), recurses into `bash -c`, `eval`, `python -c`, `$(...)` and `xargs`, and
checks the
tokens. Quoted text (a commit message, a heredoc body) is not a command. Exit code 2 blocks the
call and
shows stderr to Claude. Any internal error also blocks (fail closed) for Bash and the write tools.

The GitHub rules (merges, workflow dispatch, `gh api` writes, pushes to main) and the secret file
rules come from the ship-it-serverless guard (its ADR 0013): the `gh` token in this shell is the
owner's, so a `gh api` write could approve a pending environment deployment, which runs terraform
apply. Ideas for the push, secret file, credential literal, path scope and token rules come from
super-board (github.com/EricTechPro/super-board, MIT).

Accepted (ADR 0002 S7): Edit and Write on this guard and on `.claude/settings.json` are allowed; the
sis-platform sessions load the guard from the last tag, and the owner reviews every PR.
"""

# The hook runs under the system python3 (3.9 on macOS), so annotations must not be evaluated.
from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
import sys

BLOCKED = [
    (
        r"\bterraform\b[^\n;&|]*\s(apply|destroy|import|force-unlock)\b",
        "terraform apply/destroy/import",
    ),
    (
        r"\bterraform\b[^\n;&|]*\sstate\s+(rm|mv|push|replace-provider)\b",
        "terraform state mutation",
    ),
    (
        r"\baws\b[^\n;&|]*\ssecretsmanager\s+(put-secret-value|get-secret-value|create-secret|update-secret)\b",
        "Secrets Manager value access",
    ),
    (
        r"\baws\b[^\n;&|]*\siam\s+(create-access-key|create-user|attach-\w+-policy|put-\w+-policy)\b",
        "IAM write",
    ),
    (r"\baws\b[^\n;&|]*\ssts\s+assume-role\b", "manual role assumption"),
    (r"\bgh\s+(secret|variable)\s+(set|delete|remove)\b", "GitHub secret or variable write"),
    (r"\bgh\s+pr\s+merge\b", "PR merge (the owner merges)"),
    (r"\bgh\s+workflow\s+(run|enable|disable)\b", "workflow dispatch or toggle"),
    (r"\bgh\s+run\s+(rerun|cancel)\b", "workflow run rerun or cancel"),
    (r"\bgh\s+repo\s+(edit|delete|archive|unarchive|rename)\b", "repository settings change"),
    (r"\bgh\s+auth\s+(login|logout|refresh|token|setup-git)\b", "gh sign-in, scopes or token"),
    (
        r"\bgh\s+auth\s+status\b[^\n;&|]*\s(-[a-zA-Z]*t[a-zA-Z]*|--show-token)(\s|$)",
        "gh sign-in, scopes or token",
    ),
    (r"\bgh\s+(alias|extension|ext)\b", "gh alias or extension"),
    (r"\bgh\s+release\s+(create|edit|delete|upload|delete-asset)\b", "GitHub release change"),
    (r"\bgh\s+project\s+(delete|close|field-delete|item-delete)\b", "GitHub Project deletion"),
]

# ADR 0002 S2, ideas credited to super-board. The label never echoes the matched text.
CREDENTIAL_LITERALS = [
    (r"\bAKIA[0-9A-Z]{16}\b", "credential literal (AWS access key ID)"),
    (r"\bgh[pousr]_[A-Za-z0-9]{20,}", "credential literal (GitHub token)"),
    (r"\bgithub_pat_[A-Za-z0-9_]{20,}", "credential literal (GitHub token)"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "credential literal (private key)"),
]

# ADR 0002 B16: the project-scope token is read only by board.py, and GH_TOKEN is never set in the
# shell.
BOARD_TOKEN_ITEM = "sis-board-token"  # noqa: S105  (a Keychain item name, not a secret)
# A command that merely searches or records the name (grep, git commit -m) is not a read.
BOARD_TOKEN_SAFE_COMMANDS = {"grep", "rg", "git"}
INLINE_TOKEN = re.compile(r"^(GH_TOKEN|GITHUB_TOKEN|GH_ENTERPRISE_TOKEN)=")

STDIN_LABEL = "shell reads its script from stdin"
STDIN_HINT = (
    "A shell must run a script file or a -c string the guard "
    "can read. Print the command for the user."
)
RM_HINT = "Recursive deletes stay under this repo or worktree. Print the command for the user."
PROTECTED_BRANCHES = {"main", "master"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
MAX_DEPTH = 5

# Words that start a simple command inside a compound one: `if x; then rm ...; fi`.
PREFIX_WORDS = {
    "then", "do", "else", "elif", "if", "while", "until", "!", "{", "}",
    "exec", "time", "command", "builtin", "nohup", "coproc",
}  # fmt: skip

# Files that .gitignore keeps out of git because they can hold secrets, account IDs or state.
# The committed infra/terraform/envs/*/terraform.tfvars and every *.example file stay readable.
SECRET_FILE_PATTERNS = [
    r"(^|/)\.env(\.(?!example$)[^/]+)?$",
    r"\.tfstate(\.[^/]*)?$",
    r"(^|/)(\w[\w.-]*\.)?tfplan(\.json)?$",
    r"\.tfvars\.json$",
    r"\.auto\.tfvars$",
    r"(^|/)bootstrap/accounts/[^/]+\.tfvars$",
    r"\.tfbackend$",
    r"(^|/)\.terraform(-[^/]+)?/",
    r"(^|/)\.aws/",
    r"(^|/)\.ssh/",
    r"\.pem$",
    r"(^|/)id_(rsa|ecdsa|ed25519)(\.pub)?$",
]


def block(label: str, hint: str = "Print the exact command for the user instead.") -> int:
    print(
        f"sis-team guard blocked this call ({label}). ADR 0001 B8: Claude prepares it, "
        f"the user runs it at the checkpoint. {hint}",
        file=sys.stderr,
    )
    return 2


# ---------------------------------------------------------------------------------------------
# Shell text helpers
# ---------------------------------------------------------------------------------------------


def words(segment: str) -> list[str]:
    """Shell-split a simple command; on a quoting error drop the quote characters and split."""
    try:
        return shlex.split(segment)
    except ValueError:
        return re.sub(r"[\"']", "", segment).split()


def mask(text: str, double: bool = True) -> str:
    """Blank the inside of quoted strings (same length), so quoted text is never matched as a
    command.

    With double=False only single quotes are blanked (a `$(...)` inside double quotes still runs).
    """
    out: list[str] = []
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if not quote:
            if ch == "\\" and i + 1 < len(text):
                out.append(text[i : i + 2])
                i += 2
                continue
            if ch in "'\"":
                quote = ch
            out.append(ch)
        elif quote == "'":
            if ch == "'":
                quote = ""
                out.append(ch)
            else:
                out.append(" ")
        else:
            if ch == "\\" and i + 1 < len(text):
                out.append("  " if double else text[i : i + 2])
                i += 2
                continue
            if ch == '"':
                quote = ""
                out.append(ch)
            else:
                out.append(" " if double else ch)
        i += 1
    return "".join(out)


def split_segments(text: str) -> list[tuple[str, bool, bool]]:
    """Split on ; | & newline ( ) and backtick outside quotes. `&&` and `||` fall out of the same
    rule.

    Each item is (segment, piped, procsub): piped when a single `|` came right before it, procsub
    when
    it ends in `<` and a `(` follows (a process substitution feeds it).
    """
    segs: list[tuple[str, bool, bool]] = []
    cur: list[str] = []
    state = {"sep": ""}
    quote = ""
    i = 0
    n = len(text)

    def flush(proc: bool = False) -> None:
        body = "".join(cur).strip()
        if body:
            segs.append((body, state["sep"] == "|", proc))
        cur.clear()

    while i < n:
        ch = text[i]
        if quote == "'":
            cur.append(ch)
            if ch == "'":
                quote = ""
        elif quote == '"':
            if ch == "\\" and i + 1 < n:
                cur.append(text[i : i + 2])
                i += 2
                continue
            cur.append(ch)
            if ch == '"':
                quote = ""
        elif ch == "\\" and i + 1 < n:
            cur.append(text[i : i + 2])
            i += 2
            continue
        elif ch in "'\"":
            quote = ch
            cur.append(ch)
        elif ch == "|":
            flush()
            if i + 1 < n and text[i + 1] == "|":
                state["sep"] = "||"
                i += 1
            else:
                state["sep"] = "|"
                if i + 1 < n and text[i + 1] == "&":
                    i += 1
        elif ch == "(" and cur and cur[-1].endswith("<"):
            flush(proc=True)
            state["sep"] = "("
        elif ch in ";\n`()":
            flush()
            state["sep"] = ch
        elif ch == "&":
            redirect = (i > 0 and text[i - 1] in "<>") or (i + 1 < n and text[i + 1] == ">")
            if redirect:
                cur.append(ch)
            else:
                flush()
                state["sep"] = "&"
        else:
            cur.append(ch)
        i += 1
    flush()
    return segs


def substitutions(text: str) -> list[str]:
    """Command substitutions that run even inside double quotes: $(...) and backticks."""
    visible = mask(text, double=False)
    found = re.findall(r"\$\(([^()]*)\)", visible) + re.findall(r"`([^`]*)`", visible)
    return [f for f in found if f.strip()]


def strip_heredocs(command: str) -> tuple[str, list[tuple[str, str]]]:
    """Remove heredoc bodies. Returns the text and (command part, body) pairs.

    A heredoc whose terminator never appears is left in place (it is then just more commands).
    """
    lines = command.split("\n")
    out: list[str] = []
    bodies: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        m = re.search(r"(?<!<)<<(?!<)-?\s*", mask(line))
        if not m:
            continue
        marker = re.match(r"""(['"]?)([A-Za-z_]\w*)\1""", line[m.end() :])
        if not marker:
            continue
        end = next(
            (j for j in range(i, len(lines)) if lines[j].strip() == marker.group(2)),
            None,
        )
        if end is None:
            continue
        bodies.append((line[: m.start()], "\n".join(lines[i:end])))
        i = end + 1
    return "\n".join(out), bodies


def strip_prefix(toks: list[str]) -> list[str]:
    """Drop VAR=val, compound-command words and wrappers (env, sudo, nice, timeout) from the
    front."""
    t = list(toks)
    valued = {
        "env": {"-u", "-C", "-S"},
        "sudo": {"-u", "-g", "-h", "-p", "-C", "-r", "-t", "-U", "-T"},
        "nice": {"-n"},
        "ionice": {"-n", "-c", "-p"},
        "timeout": {"-s", "-k"},
    }
    while t:
        w = t[0]
        if re.match(r"^[A-Za-z_]\w*=", w) or w in PREFIX_WORDS:
            t.pop(0)
        elif w in valued:
            t.pop(0)
            while t and (t[0].startswith("-") or (w == "env" and "=" in t[0])):
                opt = t.pop(0)
                if opt in valued[w] and t:
                    t.pop(0)
            if w == "timeout" and t:
                t.pop(0)  # the duration
        else:
            break
    return t


# ---------------------------------------------------------------------------------------------
# Path scope (ADR 0002 S2)
# ---------------------------------------------------------------------------------------------


def _norm_home() -> str:
    return os.path.realpath(os.path.expanduser("~"))


def repo_root(cwd: str) -> str:
    """The top level of the repo that holds cwd (the worktree, inside a worktree).

    Outside a repo, cwd itself, unless that is `/` or the home directory: then no root ("").
    """
    base = cwd or os.getcwd()
    top = ""
    try:
        out = subprocess.run(  # noqa: S603  # fixed argv, no shell
            ["git", "-C", base, "rev-parse", "--show-toplevel"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0:
            top = out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        top = ""
    real = os.path.realpath(top or base)
    if not top and real in ("/", _norm_home()):
        return ""
    return real


def scratch_root(path: str | None = None) -> str | None:
    """The Claude scratchpad parent `/tmp/claude-<uid>`, only if it is safe to trust.

    It must exist, be a real directory (not a symlink), be owned by this user and not be group or
    world writable.
    """
    candidate = path if path is not None else f"/tmp/claude-{os.getuid()}"  # noqa: S108
    try:
        st = os.lstat(candidate)
    except OSError:
        return None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return None
    if st.st_uid != os.getuid() or st.st_mode & 0o022:
        return None
    return os.path.realpath(candidate)


def extra_roots() -> list[str]:
    """Directories from SIS_GUARD_EXTRA_ROOTS; `/`, the home directory and the temp roots are
    refused."""
    refused = {"/", _norm_home(), os.path.realpath("/tmp"), "/private/tmp", "/tmp"}  # noqa: S108
    roots = []
    for extra in os.environ.get("SIS_GUARD_EXTRA_ROOTS", "").split(os.pathsep):
        if extra:
            real = os.path.realpath(os.path.expanduser(extra))
            if real not in refused:
                roots.append(real)
    return roots


def allowed_roots(cwd: str) -> list[str]:
    """The repo or worktree, the trusted scratchpad parent, and the extra roots."""
    roots = [r for r in (repo_root(cwd), scratch_root()) if r]
    return roots + extra_roots()


def resolve(path: str, cwd: str) -> str | None:
    """Absolute real path, or None when the text holds a variable or substitution we cannot
    expand."""
    expanded = os.path.expandvars(os.path.expanduser(path))
    if "$" in expanded or "`" in expanded:
        return None
    return os.path.realpath(os.path.join(cwd or os.getcwd(), expanded))


def inside(path: str, roots: list[str], allow_root_itself: bool = False) -> bool:
    """True when path is below one of the roots (the root itself only if allowed)."""
    for root in roots:
        if path.startswith(root.rstrip(os.sep) + os.sep) or (allow_root_itself and path == root):
            return True
    return False


def rm_recursive_problem(args: list[str], cwd: str, roots: list[str]) -> str | None:
    """Return the first target of a recursive `rm` (args after `rm`) not strictly inside a root."""
    flags: list[str] = []
    targets: list[str] = []
    ended = False
    for a in args:
        if not ended and a == "--":
            ended = True
        elif not ended and a.startswith("-"):
            flags.append(a)
        else:
            targets.append(a)
    recursive = any(
        f == "--recursive" or (not f.startswith("--") and re.search(r"[rR]", f)) for f in flags
    )
    if not recursive:
        return None
    for t in targets:
        resolved = resolve(t, cwd)
        if resolved is None or not inside(resolved, roots):
            return t
    return None


def find_problem(args: list[str], cwd: str, roots: list[str]) -> str | None:
    """Return a start path of a destructive `find` (-delete or -exec rm) outside the roots."""
    destructive = "-delete" in args or any(
        a in ("-exec", "-execdir", "-ok", "-okdir")
        and i + 1 < len(args)
        and os.path.basename(args[i + 1]) == "rm"
        for i, a in enumerate(args)
    )
    if not destructive:
        return None
    starts = []
    for a in args:
        if a.startswith("-") or a in ("(", "!", ")"):
            break
        starts.append(a)
    for s in starts or ["."]:
        resolved = resolve(s, cwd)
        if resolved is None or not inside(resolved, roots, allow_root_itself=True):
            return s
    return None


def cd_target(toks: list[str], cwd: str) -> str | None:
    """The directory a plain `cd <dir>` moves to, "" when it cannot be resolved, None if not a
    cd."""
    if not toks or toks[0] != "cd":
        return None
    rest = [a for a in toks[1:] if a != "--"]
    if len(rest) != 1:
        return ""
    return resolve(rest[0], cwd) or ""


# ---------------------------------------------------------------------------------------------
# gh and git
# ---------------------------------------------------------------------------------------------

FIELD_FLAGS = ("-f", "-F", "--field", "--raw-field", "--input")
# gh api flags that take a value, so the value is not mistaken for the endpoint.
VALUE_FLAGS = (
    "-H",
    "--header",
    "-q",
    "--jq",
    "-t",
    "--template",
    "-p",
    "--preview",
    "--hostname",
    "--cache",
)


def graphql_problem(args: list[str]) -> bool:
    """True unless the call is one inline literal query with no mutation (no file, no variable)."""
    queries: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        value = None
        if a == "--input" or a.startswith("--input="):
            return True
        if a in ("-f", "-F", "--field", "--raw-field") and i + 1 < len(args):
            value = args[i + 1]
            i += 1
        else:
            m = re.match(r"^(?:-[fF]|--(?:raw-)?field=)(.*)$", a)
            if m:
                value = m.group(1)
        if value is not None and value.startswith("query="):
            queries.append(value[len("query=") :])
        i += 1
    if not queries:
        return True
    return any(
        q.startswith(("@", "$")) or re.search(r"mutation", q, re.I) is not None for q in queries
    )


def gh_api_write(args: list[str]) -> bool:
    """True when a `gh api` call (args after `api`) is not a plain read.

    A read is a GET with no request fields, or an inline literal GraphQL query without a mutation.
    """
    method = None
    has_fields = False
    endpoint = None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-X", "--method") and i + 1 < len(args):
            method = args[i + 1]
            i += 1
        elif a.startswith("--method="):
            method = a.split("=", 1)[1]
        elif a.startswith("-X") and len(a) > 2:
            method = a[2:]
        elif a in FIELD_FLAGS or re.match(r"^(-[fF].|--(raw-)?field=|--input=)", a):
            has_fields = True
            if a in FIELD_FLAGS:
                i += 1
        elif a in VALUE_FLAGS:
            i += 1
        elif not a.startswith("-") and endpoint is None:
            endpoint = a
        i += 1
    if endpoint is not None and endpoint.strip("/") == "graphql":
        return graphql_problem(args)
    effective = (method or ("POST" if has_fields else "GET")).upper()
    return effective != "GET"


def current_branch(cwd: str) -> str:
    try:
        out = subprocess.run(  # noqa: S603  # fixed argv, no shell
            ["git", "-C", cwd or ".", "symbolic-ref", "--short", "-q", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def branch_name(ref: str) -> str:
    for prefix in ("refs/heads/", "heads/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix) :]
    return ref


TAG_LABEL = "push of a release tag"


def is_release_ref(ref: str) -> bool:
    """refs/tags/*, tags/*, a version-like name (v1, v1.2.3) or a v* glob."""
    ref = ref.lstrip("+")
    return ref.startswith(("refs/tags/", "tags/")) or re.match(r"^v(\d|\*)", ref) is not None


def git_push_problem(toks: list[str], cwd: str) -> str | None:
    """Return why a `git push` (tokens starting at `git`) is blocked.

    Blocked: force, mirror and delete pushes (flags or an empty-source refspec), and any push that
    updates main or master.
    """
    i = 1
    where = cwd or "."
    while i < len(toks) and toks[i].startswith("-"):
        if toks[i] == "-C" and i + 1 < len(toks):
            where = os.path.join(where, toks[i + 1])
            i += 2
        elif toks[i] in ("-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"):
            i += 2
        else:
            i += 1
    if i >= len(toks) or toks[i] != "push":
        return None
    args = toks[i + 1 :]
    valued = {"-o", "--push-option", "--receive-pack", "--exec"}
    skip = [j for j, a in enumerate(args) if a in valued]
    args = [a for j, a in enumerate(args) if j not in skip and j - 1 not in skip]
    if any(a in ("--tags", "--follow-tags") for a in args):
        return TAG_LABEL
    for f in [a for a in args if a.startswith("-")]:
        if f in ("-f", "--force", "--mirror", "--all", "--delete", "-d", "--prune") or (
            re.match(r"^-[a-zA-Z]*[fd]", f) and not f.startswith("--")
        ):
            return f"git push {f}"
    rest = [a for a in args if not a.startswith("-")]
    if "tag" in rest[1:2]:
        return TAG_LABEL
    has_repo_flag = any(a.startswith("--repo=") for a in args)
    refspecs = (rest if has_repo_flag else rest[1:]) or ["HEAD"]
    for spec in refspecs:
        if spec.startswith("+"):
            return "force push (+refspec)"
        src, colon, dst = spec.partition(":")
        if any(is_release_ref(r) for r in (src, dst)):
            return TAG_LABEL
        if colon and not src:
            return f"git push delete refspec ({spec})"
        target = branch_name(dst if dst else src)
        if target == "HEAD":
            target = current_branch(where)
        if target in PROTECTED_BRANCHES:
            return f"push to {target}"
    return None


def secret_path(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(re.search(pat, p) for pat in SECRET_FILE_PATTERNS)


# ---------------------------------------------------------------------------------------------
# Bash
# ---------------------------------------------------------------------------------------------


def drop_empty_quotes(text: str) -> str:
    return text.replace("''", "").replace('""', "")


def is_python(leader: str) -> bool:
    return re.match(r"^python(\d+(\.\d+)*)?$", leader) is not None


def check_python_arg(arg: str, cwd: str, depth: int) -> int:
    """A `python -c` program: scan it raw, and check every string literal as a command."""
    for pattern, label in BLOCKED:
        if re.search(pattern, arg):
            return block(label)
    for m in re.finditer(r"'([^']*)'|\"([^\"]*)\"", arg):
        inner = m.group(1) or m.group(2) or ""
        if inner.strip():
            rc = check_bash(inner, cwd, depth + 1)
            if rc:
                return rc
    return 0


def shell_c_argument(args: list[str]) -> str | None:
    for i, a in enumerate(args):
        if re.match(r"^-[a-zA-Z]*c[a-zA-Z]*$", a) and i + 1 < len(args):
            return args[i + 1]
    return None


def check_tokens(toks: list[str], cwd: str, roots: list[str], depth: int) -> int:
    """Check one simple command whose prefixes are already stripped."""
    if not toks:
        return 0
    leader = os.path.basename(toks[0])
    args = toks[1:]
    if leader in SHELLS:
        arg = shell_c_argument(args)
        if arg is not None:
            return check_bash(arg, cwd, depth + 1)
    elif leader == "eval":
        return check_bash(" ".join(args), cwd, depth + 1)
    elif is_python(leader):
        if "-c" in args and args.index("-c") + 1 < len(args):
            return check_python_arg(args[args.index("-c") + 1], cwd, depth)
    elif leader == "xargs":
        valued = {"-I", "-n", "-P", "-d", "-L", "-E", "-s", "-a"}
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in valued else 1
        rest = strip_prefix(args[i:])
        if rest and os.path.basename(rest[0]) == "rm":
            flags = [f for f in rest[1:] if f.startswith("-") and f != "--"]
            if any(
                f == "--recursive" or (not f.startswith("--") and "r" in f.lower()) for f in flags
            ):
                return block("rm -r outside the repo (xargs input)", RM_HINT)
        return check_tokens(rest, cwd, roots, depth)
    elif leader == "find":
        bad = find_problem(args, cwd, roots)
        if bad is not None:
            return block(f"rm -r outside the repo (find {bad})", RM_HINT)
    elif leader == "rm":
        bad = rm_recursive_problem(args, cwd, roots)
        if bad is not None:
            return block(f"rm -r outside the repo ({bad})", RM_HINT)
    elif leader == "gh":
        # Global repo flags sit anywhere after `gh`; drop them so the verb words are adjacent.
        cleaned = []
        skip = False
        for a in args:
            if skip:
                skip = False
            elif a in ("-R", "--repo"):
                skip = True
            elif not a.startswith("--repo="):
                cleaned.append(a)
        args = cleaned
        toks = [toks[0], *args]
        if args and args[0] == "api" and gh_api_write(args[1:]):
            return block(
                "gh api write",
                "Only GET reads are allowed through gh api. Print the call for the user.",
            )
    elif leader == "git":
        problem = git_push_problem(toks, cwd)
        if problem:
            return block(
                problem,
                "Push a feature branch and open a PR; main changes only through a merged PR.",
            )
    normalized = " ".join([leader, *args])
    for pattern, label in BLOCKED:
        if re.search("^" + pattern[2:], normalized):
            return block(label)
    return 0


def shell_input_problem(
    leader: str, args: list[str], cwd: str, depth: int, piped: bool, procsub: bool, has_bodies: bool
) -> int | None:
    """Check a shell or `source` that takes its script from somewhere other than `-c`.

    Returns a block code, 0 when the script was a literal here-string that passed the scan, or None
    when
    the command is not a shell reading input (nothing to do).
    """
    is_shell = leader in SHELLS
    if not is_shell and leader not in ("source", "."):
        return None
    if is_shell and shell_c_argument(args) is not None:
        return None
    herestring = None
    stdin_file = False
    heredoc = False
    clean: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("<<<"):
            herestring = a[3:] or (args[i + 1] if i + 1 < len(args) else "")
            i += 1 if a[3:] else 2
        elif a.startswith("<<"):
            heredoc = True
            i += 1 if a not in ("<<", "<<-") else 2
        elif a == "<":
            stdin_file = True
            i += 2
        elif a.startswith("<") and not a.startswith("<("):
            stdin_file = True
            i += 1
        elif re.match(r"^(\d*>>?|&>>?)", a):
            i += 2 if re.fullmatch(r"(\d*>>?|&>>?)", a) else 1
        else:
            clean.append(a)
            i += 1
    if procsub:
        return block(
            "shell fed from a process substitution",
            "A shell must run a script file or a -c string the guard "
            "can read. Print the command for the user.",
        )
    script = [a for a in clean if not a.startswith("-")]
    if any(re.match(r"^/dev/(stdin|fd/|tty)", a) for a in script):
        return block(STDIN_LABEL, STDIN_HINT)
    if herestring is not None:
        return check_bash(herestring, cwd, depth + 1)
    if heredoc:
        return 0 if has_bodies else block(STDIN_LABEL, STDIN_HINT)
    if stdin_file:
        return block(STDIN_LABEL, STDIN_HINT)
    reads_stdin = is_shell and ("-s" in clean or not script)
    if piped and reads_stdin:
        return block(
            "shell fed from a pipe",
            "A shell must run a script file or a -c string the guard "
            "can read. Print the command for the user.",
        )
    return None


def check_segment(
    seg: str,
    cwd: str,
    roots: list[str],
    depth: int,
    piped: bool = False,
    procsub: bool = False,
    has_bodies: bool = False,
) -> int:
    toks = words(seg)
    if not toks:
        return 0
    if any(INLINE_TOKEN.match(t) for t in toks):
        return block(
            "inline GitHub token",
            "Never set GH_TOKEN or GITHUB_TOKEN in a command; "
            "board.py sets it for its own subprocess.",
        )
    stripped = strip_prefix(toks)
    leader = os.path.basename(stripped[0]) if stripped else ""
    names_token = BOARD_TOKEN_ITEM in " ".join(toks) or BOARD_TOKEN_ITEM in drop_empty_quotes(seg)
    if names_token and leader not in BOARD_TOKEN_SAFE_COMMANDS:
        return block(
            "board token read",
            "Only board.py reads the sis-board-token Keychain item. Ask the user.",
        )
    if stripped:
        fed = shell_input_problem(leader, stripped[1:], cwd, depth, piped, procsub, has_bodies)
        if fed:
            return fed
    rc = check_tokens(stripped, cwd, roots, depth)
    if rc:
        return rc
    for w in toks:
        if secret_path(w):
            return block(
                f"secret file {w}", "Name the file and ask the user; never print its content."
            )
    return 0


def check_bash(command: str, cwd: str, depth: int = 0) -> int:
    if depth > MAX_DEPTH:
        return block("shell nesting too deep")
    flat = drop_empty_quotes(command)
    for pattern, label in CREDENTIAL_LITERALS:
        if re.search(pattern, flat):
            return block(
                label, "Use the environment or the Keychain through the tool, never a literal."
            )
    text, bodies = strip_heredocs(command)
    # Layer 1: the verbs anywhere outside quotes and heredocs (catches grammar the parser does not
    # know).
    masked = mask(text)
    for pattern, label in BLOCKED:
        if re.search(pattern, masked):
            return block(label)
    here = cwd or os.getcwd()
    roots = allowed_roots(here)
    # Layer 2: command substitutions, then every simple command with its prefixes stripped.
    for inner in substitutions(text):
        rc = check_bash(inner, here, depth + 1)
        if rc:
            return rc
    visible = mask(text, double=False)
    if re.search(r"\bgit\b[^;&|\n]*\bpush\b[^;&|\n]*(\$\(|`)", visible):
        return block(
            "git push with a command substitution",
            "The remote or refspec cannot be checked. Write the branch name out.",
        )
    for seg, piped, procsub in split_segments(text):
        moved = cd_target(words(seg), here)
        if moved is not None:
            here = moved
            continue
        if not here:
            if "rm" in words(seg):
                return block("rm -r outside the repo (unknown directory)", RM_HINT)
            continue
        rc = check_segment(seg, here, roots, depth, piped, procsub, bool(bodies))
        if rc:
            return rc
    # A heredoc fed to a shell or python is a program, not text.
    for head, body in bodies:
        lead = strip_prefix(words(head))
        name = os.path.basename(lead[0]) if lead else ""
        if name in SHELLS or is_python(name):
            rc = check_bash(body, here, depth + 1)
            if rc:
                return rc
    return 0


def check_file_tool(tool: str, tool_input: dict[str, object], cwd: str) -> int:
    for key in ("file_path", "notebook_path", "path", "glob", "pattern"):
        value = tool_input.get(key)
        if isinstance(value, str) and key != "pattern" and secret_path(value):
            return block(
                f"secret file {value}", "Name the file and ask the user; never read its content."
            )
    if tool in WRITE_TOOLS:
        for key in ("file_path", "notebook_path"):
            value = tool_input.get(key)
            if not isinstance(value, str):
                continue
            resolved = resolve(value, cwd)
            if resolved is None or not inside(resolved, allowed_roots(cwd)):
                return block(
                    f"write outside the repo ({value})",
                    "Edit and Write stay inside this repo or worktree. Ask the user.",
                )
    return 0


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        event = None
    if not isinstance(event, dict):
        return block("malformed hook input", "The guard failed closed. Ask the user.")
    tool = event.get("tool_name", "Bash")
    try:
        tool_input = event.get("tool_input", {}) or {}
        cwd = str(event.get("cwd", ""))
        if tool == "Bash":
            return check_bash(str(tool_input.get("command", "")), cwd)
        return check_file_tool(tool, tool_input, cwd)
    except Exception as exc:  # noqa: BLE001  # fail closed on anything unexpected
        if tool == "Bash" or tool in WRITE_TOOLS:
            return block(
                f"guard error {type(exc).__name__}", "The guard failed closed. Ask the user."
            )
        return 0


if __name__ == "__main__":
    sys.exit(main())
