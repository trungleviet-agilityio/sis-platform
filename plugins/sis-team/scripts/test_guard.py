"""Tests of the sis-team PreToolUse guard (guard.py).

Every blocked form with the message it must print, and the reads, pushes and writes it must allow
(an allowed call exits 0 with an empty stderr). Runs on the system python3 (3.9) and on 3.13.

Run: python3 -m unittest discover -s plugins/sis-team/scripts -p 'test_*.py'
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Mapping

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard.py")


def run(event: Mapping[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # runs guard.py with a fixed argv
        [sys.executable, "-I", GUARD],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        check=False,
    )


def bash_run(command: str, cwd: str = "") -> subprocess.CompletedProcess[str]:
    return run({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})


def bash(command: str, cwd: str = "") -> int:
    return bash_run(command, cwd).returncode


def read(path: str) -> int:
    return run({"tool_name": "Read", "tool_input": {"file_path": path}}).returncode


# (command, label the block message must carry). The message starts
# "sis-team guard blocked this call (<label>)".
BLOCKED_CASES = [
    # AWS and Terraform (the original rules)
    ("terraform -chdir=envs/dev apply -auto-approve", "terraform apply/destroy/import"),
    ("terraform destroy", "terraform apply/destroy/import"),
    ("terraform state rm aws_s3_bucket.x", "terraform state mutation"),
    ("aws secretsmanager get-secret-value --secret-id x", "Secrets Manager value access"),
    ("aws iam create-access-key --user-name x", "IAM write"),
    ("aws sts assume-role --role-arn x --role-session-name y", "manual role assumption"),
    # GitHub writes
    ("gh secret set TOKEN", "GitHub secret or variable write"),
    ("gh variable set AWS_REGION --body ap-southeast-1", "GitHub secret or variable write"),
    ("gh pr merge 12 --squash", "PR merge (the owner merges)"),
    ("gh workflow run terraform-iac.yml -f env=dev", "workflow dispatch or toggle"),
    ("gh run rerun 123", "workflow run rerun or cancel"),
    ("gh repo edit --visibility private", "repository settings change"),
    ("gh auth token", "gh sign-in, scopes or token"),
    ("gh auth refresh -s project", "gh sign-in, scopes or token"),
    ("gh project delete 3 --owner me", "GitHub Project deletion"),
    # gh api writes, including the deployment approval path
    ("gh api -X POST repos/o/r/actions/runs/1/pending_deployments -f state=approved", "gh api write"),
    ("gh api --method=PUT repos/o/r/actions/secrets/X --input body.json", "gh api write"),
    ("gh api repos/o/r/environments/dev -XDELETE", "gh api write"),
    ("gh api repos/o/r/rulesets/1 -f enforcement=disabled", "gh api write"),
    ("gh api graphql -f query='mutation { deleteProjectV2(input: {}) { id }}'", "gh api write"),
    ("bash -c 'gh api -X PATCH repos/o/r -f private=true'", "gh api write"),
    ("echo ok && gh api -X POST repos/o/r/dispatches -f event_type=x", "gh api write"),
    # pushes that change main or rewrite history
    ("git push origin main", "push to main"),
    ("git push origin HEAD:main", "push to main"),
    ("git push origin feat/x:refs/heads/main", "push to main"),
    ("git push --force origin feat/x", "git push --force"),
    ("git push -f origin feat/x", "git push -f"),
    ("git push origin +feat/x", "force push (+refspec)"),
    ("git push --mirror origin", "git push --mirror"),
    ("git push origin --delete feat/x", "git push --delete"),
    ("git -C ../other push origin main", "push to main"),
    # secret files read through the shell
    ("cat app/.env", "secret file app/.env"),
    ("cat envs/dev/terraform.tfstate", "secret file envs/dev/terraform.tfstate"),
    ("cat bootstrap/accounts/dev.tfvars", "secret file bootstrap/accounts/dev.tfvars"),
    ("less envs/dev/.terraform/terraform.tfstate", "secret file envs/dev/.terraform/"),
    ("cat ~/.aws/credentials", "secret file ~/.aws/credentials"),
    ("cat ~/.ssh/id_ed25519", "secret file ~/.ssh/id_ed25519"),
]

ALLOWED_CASES = [
    "terraform -chdir=envs/dev validate",
    "terraform init -backend=false",
    "gh pr view 12 --json state",
    "gh pr create --draft --title x --body-file b.md",
    "gh pr checks 12",
    "gh run view 123 --log",
    "gh api repos/o/r/pulls --paginate --jq '.[] | .number'",
    "gh api -X GET search/issues -f q=repo:o/r",
    "gh api -H 'Accept: application/vnd.github+json' repos/o/r/environments",
    "gh api graphql -f query='query { viewer { login } }'",
    "git push -u origin feat/x",
    "git push --force-with-lease origin feat/x",
    "cat app/.env.example",
    "cat envs/dev/terraform.tfvars",
    "cat bootstrap/accounts/dev.tfvars.example",
    "cat envs/dev/.terraform.lock.hcl",
    "scripts/aws/check-config.sh",
    "cat project.env",
]


class BlockedCommands(unittest.TestCase):
    def test_blocks(self) -> None:
        for command, label in BLOCKED_CASES:
            with self.subTest(command=command):
                done = bash_run(command)
                self.assertEqual(done.returncode, 2)
                self.assertIn(f"sis-team guard blocked this call ({label}", done.stderr)

    def test_message_cites_the_adr(self) -> None:
        self.assertIn("ADR 0001 B8", bash_run("gh pr merge 1").stderr)

    def test_blocks_push_of_current_main(self) -> None:
        with tempfile.TemporaryDirectory() as repo:
            subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)  # noqa: S603,S607
            for command in ("git push", "git push origin"):
                done = bash_run(command, cwd=repo)
                self.assertEqual(done.returncode, 2)
                self.assertIn("push to main", done.stderr)
            git = ["git", "-C", repo, "checkout", "-q", "-b", "feat/x"]
            subprocess.run(git, check=True)  # noqa: S603,S607
            self.assertEqual(bash("git push -u origin HEAD", cwd=repo), 0)


class AllowedCommands(unittest.TestCase):
    def test_allows(self) -> None:
        for command in ALLOWED_CASES:
            with self.subTest(command=command):
                done = bash_run(command)
                self.assertEqual(done.returncode, 0)
                self.assertEqual(done.stderr, "")


# Credential-shaped test values are assembled at run time so this file holds no literal for gitleaks.
FAKE_AWS_KEY = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
FAKE_GH_PAT = "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
FAKE_FINE_PAT = "github" + "_pat_" + "11ABCDEFG0abcdefghijkl_mnopqrstuvwxyz0123456789"
FAKE_PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"

# Added by ADR 0002 S2 (ideas credited to super-board, MIT).
S2_COMMAND_CASES = [
    # credential literals in a command
    (f"aws s3 ls --access-key {FAKE_AWS_KEY}", "credential literal (AWS access key ID)"),
    (f"curl -H 'Authorization: token {FAKE_GH_PAT}' https://api.github.com", "credential literal (GitHub token)"),
    (f"git clone https://{FAKE_FINE_PAT}@github.com/o/r.git", "credential literal (GitHub token)"),
    (f"echo '{FAKE_PEM}' > k", "credential literal (private key)"),
    # board project items are never deleted
    ("gh project item-delete 3 --owner me --id X", "GitHub Project deletion"),
    # B16: the board token lives in the Keychain and is read only by board.py
    ("security find-generic-password -s sis-board-token -w", "board token read"),
    ("TOKEN=$(security find-generic-password -a me -s sis-board-token -w)", "board token read"),
    ("kc get sis-board-token", "board token read"),
    ("python3 -c 'print(open(\"sis-board-token\").read())'", "board token read"),
    # B16: no inline GH_TOKEN or GITHUB_TOKEN
    ("GH_TOKEN=abc gh project item-list 3", "inline GitHub token"),
    ("export GH_TOKEN=abc", "inline GitHub token"),
    ("env GITHUB_TOKEN=abc gh issue list", "inline GitHub token"),
    ("cd x && GITHUB_TOKEN=\"$T\" gh pr view 1", "inline GitHub token"),
]

S2_ALLOWED = [
    "aws s3 ls",
    "gh project item-list 3 --owner me",
    "gh project item-add 3 --owner me --url https://github.com/o/r/issues/1",
    "python3 plugins/sis-team/scripts/board.py status",
    "grep -rn sis-board-token docs",
    "git commit -m 'docs: the sis-board-token Keychain item'",
    "echo $GH_TOKEN_NAME",
    "gh auth status",
    "echo AKIA is the AWS key prefix",
]


class S2Commands(unittest.TestCase):
    def test_blocks(self) -> None:
        for command, label in S2_COMMAND_CASES:
            with self.subTest(command=command):
                done = bash_run(command)
                self.assertEqual(done.returncode, 2)
                self.assertIn(f"sis-team guard blocked this call ({label}", done.stderr)

    def test_allows(self) -> None:
        for command in S2_ALLOWED:
            with self.subTest(command=command):
                done = bash_run(command)
                self.assertEqual(done.returncode, 0)
                self.assertEqual(done.stderr, "")

    def test_message_never_echoes_the_secret(self) -> None:
        done = bash_run(f"aws s3 ls --access-key {FAKE_AWS_KEY}")
        self.assertNotIn(FAKE_AWS_KEY, done.stderr)


def write(tool: str, path: str, cwd: str, key: str = "file_path") -> subprocess.CompletedProcess[str]:
    return run({"tool_name": tool, "tool_input": {key: path, "content": "x"}, "cwd": cwd})


class PathScope(unittest.TestCase):
    """ADR 0002 S2: Edit and Write stay in the repo or worktree; rm -r stays under the repo root."""

    root = ""
    outside = ""
    _tmp: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(cls._tmp.name)
        cls.root = os.path.join(base, "repo")
        cls.outside = os.path.join(base, "other")
        os.makedirs(os.path.join(cls.root, "sub"))
        os.makedirs(cls.outside)
        subprocess.run(["git", "init", "-q", cls.root], check=True)  # noqa: S603,S607
        os.symlink(cls.outside, os.path.join(cls.root, "link"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def assert_write_blocked(self, tool: str, path: str, cwd: str, key: str = "file_path") -> None:
        done = write(tool, path, cwd, key)
        self.assertEqual(done.returncode, 2, path)
        self.assertIn("sis-team guard blocked this call (write outside the repo", done.stderr)

    def test_write_outside_is_blocked(self) -> None:
        elsewhere = os.path.join(self.outside, "f.txt")
        for tool in ("Write", "Edit", "MultiEdit"):
            with self.subTest(tool=tool):
                self.assert_write_blocked(tool, elsewhere, self.root)
        self.assert_write_blocked("NotebookEdit", elsewhere, self.root, "notebook_path")
        self.assert_write_blocked("Write", os.path.expanduser("~/.zshrc"), self.root)

    def test_write_escaping_the_root_is_blocked(self) -> None:
        self.assert_write_blocked("Write", "../other/f.txt", self.root)
        self.assert_write_blocked("Write", "sub/../../other/f.txt", self.root)
        self.assert_write_blocked("Write", os.path.join(self.root, "link", "f.txt"), self.root)
        self.assert_write_blocked("Write", os.path.dirname(self.root), self.root)

    def test_write_inside_is_allowed(self) -> None:
        for path in ("a.txt", "sub/a.txt", os.path.join(self.root, "sub", "deep", "a.txt")):
            with self.subTest(path=path):
                done = write("Write", path, self.root)
                self.assertEqual(done.returncode, 0)
                self.assertEqual(done.stderr, "")
        self.assertEqual(write("Edit", "a.txt", os.path.join(self.root, "sub")).returncode, 0)
        done = write("NotebookEdit", "n.ipynb", self.root, "notebook_path")
        self.assertEqual(done.returncode, 0)

    def test_worktree_is_its_own_root(self) -> None:
        wt = os.path.join(os.path.dirname(self.root), "wt")
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ["PATH"]}  # fmt: skip
        git = ["git", "-C", self.root]
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "x"], check=True, env=env)  # noqa: S603
        subprocess.run([*git, "worktree", "add", "-q", wt, "-b", "wt-branch"], check=True)  # noqa: S603
        self.assertEqual(write("Write", "a.txt", wt).returncode, 0)
        self.assert_write_blocked("Write", os.path.join(self.root, "a.txt"), wt)

    def test_extra_roots_env(self) -> None:
        event = {"tool_name": "Write", "tool_input": {"file_path": os.path.join(self.outside, "f")},
                 "cwd": self.root}  # fmt: skip
        env = {**os.environ, "SIS_GUARD_EXTRA_ROOTS": self.outside}
        done = subprocess.run(  # noqa: S603
            [sys.executable, "-I", GUARD], input=json.dumps(event), capture_output=True,
            text=True, check=False, env=env,
        )  # fmt: skip
        self.assertEqual(done.returncode, 0)

    def test_rm_recursive_outside_is_blocked(self) -> None:
        for command in [
            f"rm -rf {self.outside}",
            "rm -rf ../other",
            "rm -r /tmp/x",
            "rm -fr ~/projects",
            "rm -rf $HOME/x",
            "rm --recursive /var/tmp/x",
            "rm -R /opt/x",
            "rm -rf /",
            "rm -rf .",
            "rm -rf ..",
            "rm -rf link/data",
            "rm -rf sub /etc/x",
            'rm -rf "$UNSET_VAR/x"',
            f"cd {self.outside} && rm -rf x",
            "cd .. && rm -rf other",
            "sudo rm -rf /usr/local/x",
            "ls && rm -rf /tmp/*",
        ]:
            with self.subTest(command=command):
                done = bash_run(command, cwd=self.root)
                self.assertEqual(done.returncode, 2)
                self.assertIn("sis-team guard blocked this call (rm -r outside the repo", done.stderr)

    def test_rm_inside_or_not_recursive_is_allowed(self) -> None:
        for command in [
            "rm -rf build",
            "rm -rf ./dist/x sub/y",
            f"rm -r {self.root}/sub/out",
            "rm -rf *",
            "rm -f /tmp/x",
            "rm /tmp/x",
            "cd sub && rm -rf out",
            "rm -rf -- sub/out",
            "echo rm -rf /tmp/x",
            "git rm -r --cached sub",
        ]:
            with self.subTest(command=command):
                done = bash_run(command, cwd=self.root)
                self.assertEqual(done.returncode, 0)
                self.assertEqual(done.stderr, "")


class FileTools(unittest.TestCase):
    def test_reads(self) -> None:
        self.assertEqual(read("/repo/app/.env"), 2)
        self.assertEqual(read("/repo/envs/dev/terraform.tfstate.backup"), 2)
        self.assertEqual(read("/repo/envs/dev/.terraform-prod/environment"), 2)
        self.assertEqual(read("/repo/envs/dev/backend.tfbackend"), 2)
        self.assertEqual(read("/repo/app/.env.example"), 0)
        self.assertEqual(read("/repo/envs/prod/terraform.tfvars"), 0)
        self.assertEqual(read("/repo/envs/dev/backend.tfbackend.example"), 0)

    def test_read_message(self) -> None:
        done = run({"tool_name": "Read", "tool_input": {"file_path": "/repo/app/.env"}})
        self.assertIn("secret file /repo/app/.env", done.stderr)

    def test_grep_glob(self) -> None:
        grep = {"tool_name": "Grep", "tool_input": {"pattern": "account", "glob": "*.tfstate"}}
        self.assertEqual(run(grep).returncode, 2)
        grep = {"tool_name": "Grep", "tool_input": {"pattern": "tfstate", "path": "infra"}}
        self.assertEqual(run(grep).returncode, 0)

    def test_bad_input_is_ignored(self) -> None:
        done = subprocess.run(  # noqa: S603  # runs guard.py with a fixed argv
            [sys.executable, GUARD], input="not json", text=True, check=False
        )
        self.assertEqual(done.returncode, 0)


if __name__ == "__main__":
    unittest.main()
