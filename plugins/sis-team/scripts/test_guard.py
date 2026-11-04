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
