"""Tests for scripts/platform/check_lock.py (ADR 0002, L1, L3, C1). Standard library plus PyYAML,
Python 3.9 or later. Every case builds local fixture git repos; nothing touches the network.

    python3 -m unittest discover -s scripts/release/tests
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess  # noqa: S404  (one end-to-end exit-code check)
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, List, Optional
from unittest import mock

import helpers
from helpers import PLATFORM, REPO_ROOT, Repo, consumer, run_main

# isort: split
import check_lock  # noqa: E402  (sys.path is set by helpers)
import closure  # noqa: E402

A = "a" * 40
B = "b" * 40


class OfflineCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = consumer(self.tmp / "consumer", "v0.2.0", A, B)

    def run_check(self, *extra: str) -> tuple[int, str]:
        rc, _out, err = run_main(check_lock, [str(self.root), *extra])
        return rc, err

    def expect_ok(self) -> None:
        rc, err = self.run_check()
        self.assertEqual((rc, err), (0, ""))

    def expect_fail(self, fragment: str) -> None:
        rc, err = self.run_check()
        self.assertEqual(rc, 1, err)
        self.assertIn(fragment, err)

    def edit_lock(self, **changes: object) -> None:
        path = self.root / "platform.lock"
        doc = json.loads(path.read_text(encoding="utf-8"))
        for key, value in changes.items():
            if value is None:
                doc.pop(key, None)
            else:
                doc[key] = value
        path.write_text(json.dumps(doc), encoding="utf-8")

    def edit(self, rel: str, old: str, new: str) -> None:
        path = self.root / rel
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")


class LockSchema(OfflineCase):
    def test_a_good_consumer_passes(self) -> None:
        self.expect_ok()

    def test_missing_lock(self) -> None:
        (self.root / "platform.lock").unlink()
        self.expect_fail("platform.lock: cannot read")

    def test_lock_that_is_not_json(self) -> None:
        (self.root / "platform.lock").write_text("version = 1\n", encoding="utf-8")
        self.expect_fail("platform.lock: not valid JSON")

    def test_lock_that_is_not_an_object(self) -> None:
        (self.root / "platform.lock").write_text("[]", encoding="utf-8")
        self.expect_fail("platform.lock: must be a JSON object")

    def test_missing_key(self) -> None:
        self.edit_lock(workflow_sha=None)
        self.expect_fail("platform.lock: missing key 'workflow_sha'")

    def test_unknown_key(self) -> None:
        self.edit_lock(previous_workflow_sha=A)
        self.expect_fail("platform.lock: unknown key 'previous_workflow_sha'")

    def test_lock_version(self) -> None:
        self.edit_lock(lock_version=2)
        self.expect_fail("platform.lock: lock_version must be 1")

    def test_lock_version_true_is_not_one(self) -> None:
        self.edit_lock(lock_version=True)
        self.expect_fail("platform.lock: lock_version must be 1")

    def test_version_shape(self) -> None:
        self.edit_lock(version="0.2.0")
        self.expect_fail("platform.lock: version must look like vX.Y.Z")

    def test_release_sha_shape(self) -> None:
        self.edit_lock(release_sha="v0.2.0")
        self.expect_fail("platform.lock: release_sha must be 40 lowercase hex characters")

    def test_trailing_newline_fails_every_sha_and_version(self) -> None:
        # `$` in a match() also accepts a value that ends in a newline; fullmatch() must refuse it.
        self.edit_lock(release_sha=A + "\n")
        self.expect_fail("platform.lock: release_sha must be 40 lowercase hex characters")
        self.edit_lock(release_sha=A, workflow_sha=B + "\n", trusted_workflow_shas=[B])
        self.expect_fail("platform.lock: workflow_sha must be 40 lowercase hex characters")
        self.edit_lock(workflow_sha=B, trusted_workflow_shas=[B + "\n"])
        self.expect_fail("must be 40 lowercase hex")
        self.edit_lock(trusted_workflow_shas=[B], version="v0.2.0\n")
        self.expect_fail("platform.lock: version must look like vX.Y.Z")

    def test_workflow_sha_shape(self) -> None:
        self.edit_lock(workflow_sha=B.upper(), trusted_workflow_shas=[B])
        self.expect_fail("platform.lock: workflow_sha must be 40 lowercase hex characters")

    def test_trusted_list_empty(self) -> None:
        self.edit_lock(trusted_workflow_shas=[])
        self.expect_fail("platform.lock: trusted_workflow_shas must hold 1 or 2 values")

    def test_trusted_list_too_long(self) -> None:
        self.edit_lock(trusted_workflow_shas=[B, A, "c" * 40])
        self.expect_fail("platform.lock: trusted_workflow_shas must hold 1 or 2 values")

    def test_trusted_value_shape(self) -> None:
        self.edit_lock(trusted_workflow_shas=[B, "abc"])
        self.expect_fail(
            "platform.lock: trusted_workflow_shas value 'abc' must be 40 lowercase hex"
        )

    def test_trusted_values_distinct(self) -> None:
        self.edit_lock(trusted_workflow_shas=[B, B])
        self.expect_fail("platform.lock: trusted_workflow_shas values must be distinct")

    def test_trusted_must_contain_workflow_sha(self) -> None:
        self.edit_lock(trusted_workflow_shas=[A])
        self.expect_fail("platform.lock: trusted_workflow_shas must contain workflow_sha")

    def test_n_and_n_minus_one_pass(self) -> None:
        self.edit_lock(trusted_workflow_shas=[B, A])
        self.expect_ok()


class ManifestAndPins(OfflineCase):
    def test_platform_yaml_version_must_match(self) -> None:
        self.edit("platform.yaml", "v0.2.0", "v0.3.0")
        self.expect_fail(
            "platform.yaml: platform.version 'v0.3.0' does not match platform.lock version 'v0.2.0'"
        )

    def test_platform_yaml_missing(self) -> None:
        (self.root / "platform.yaml").unlink()
        self.expect_fail("platform.yaml: cannot read")

    def test_uses_sha_must_be_workflow_sha(self) -> None:
        self.edit(".github/workflows/terraform.yml", f"@{B}", f"@{A}")
        self.expect_fail(f"is pinned to {A}, not workflow_sha {B} (L3)")

    def test_uses_with_a_tag_is_refused(self) -> None:
        self.edit(".github/workflows/terraform.yml", f"@{B}", "@v0.2.0")
        self.expect_fail("is pinned to v0.2.0, not workflow_sha")

    def test_uses_without_a_ref_is_refused(self) -> None:
        self.edit(".github/workflows/terraform.yml", f"@{B}", "")
        self.expect_fail("has no @ref, expected workflow_sha")

    def test_uses_comment_must_be_the_lock_version(self) -> None:
        self.edit(".github/workflows/terraform.yml", "# v0.2.0", "# v0.1.0")
        self.expect_fail("has version comment 'v0.1.0' but platform.lock version is v0.2.0 (L3)")

    def test_uses_comment_missing(self) -> None:
        self.edit(".github/workflows/terraform.yml", " # v0.2.0", "")
        self.expect_fail("has no '# vX.Y.Z' version comment")

    def test_uses_in_flow_style_is_read(self) -> None:
        wf = self.root / ".github" / "workflows" / "flow.yaml"
        uses = f"{PLATFORM}/.github/workflows/reusable-terraform-plan.yml@{A}"
        wf.write_text("jobs:\n  plan: {uses: '" + uses + "'}  # v0.2.0\n", encoding="utf-8")
        self.expect_fail(f"flow.yaml:2: uses '{uses}' is pinned to {A}")

    def test_uses_in_a_composite_action_is_read(self) -> None:
        action = self.root / ".github" / "actions" / "x" / "action.yml"
        action.parent.mkdir(parents=True)
        uses = f"{PLATFORM}/.github/actions/y@{A}"
        action.write_text(
            "runs:\n  using: composite\n  steps:\n    - uses: " + uses + " # v0.2.0\n",
            encoding="utf-8",
        )
        self.expect_fail("action.yml:4: uses")

    def test_uses_of_a_case_variant_of_the_repo_is_still_checked(self) -> None:
        self.edit(
            ".github/workflows/terraform.yml",
            "trungleviet-agilityio/sis-platform",
            "Trungleviet-Agilityio/Sis-Platform",
        )
        self.edit(".github/workflows/terraform.yml", f"@{B}", f"@{A}")
        self.expect_fail("is pinned to")

    def test_other_actions_are_not_this_checks_business(self) -> None:
        wf = self.root / ".github" / "workflows" / "other.yml"
        wf.write_text(
            "jobs:\n  j:\n    steps:\n      - uses: actions/checkout@" + A + " # v7.0.0\n",
            encoding="utf-8",
        )
        self.expect_ok()

    def test_module_ref_must_be_release_sha(self) -> None:
        self.edit("infra/bootstrap/main.tf", f"ref={A}", f"ref={B}")
        self.expect_fail(f"is pinned to ref {B}, not release_sha {A} (L3)")

    def test_module_ref_may_not_be_a_tag(self) -> None:
        self.edit("infra/bootstrap/main.tf", f"ref={A}", "ref=v0.2.0")
        self.expect_fail("is pinned to ref v0.2.0, not release_sha")

    def test_module_without_ref(self) -> None:
        self.edit("infra/bootstrap/main.tf", f"?ref={A}", "")
        self.expect_fail("remote module source")

    def test_registry_module_is_refused(self) -> None:
        self.edit("infra/bootstrap/main.tf", "../../local-module", "terraform-aws-modules/vpc/aws")
        self.expect_fail("remote module source 'terraform-aws-modules/vpc/aws' is not sis-platform")

    def test_other_git_module_is_refused(self) -> None:
        self.edit(
            "infra/bootstrap/main.tf",
            "../../local-module",
            "git::https://github.com/o/r.git//m?ref=" + A,
        )
        self.expect_fail("remote module source 'git::https://github.com/o/r.git//m?ref=")

    def test_other_platform_repo_spelling_is_refused(self) -> None:
        self.edit(
            "infra/bootstrap/main.tf",
            "../../local-module",
            f"github.com/{PLATFORM}//modules/x?ref={A}",
        )
        self.expect_fail("remote module source")

    def test_provider_source_is_not_a_module_source(self) -> None:
        self.expect_ok()  # main.tf holds required_providers source = "hashicorp/aws"

    def test_terraform_dirs_are_skipped(self) -> None:
        cache = self.root / "infra" / "bootstrap" / ".terraform" / "modules" / "x.tf"
        cache.parent.mkdir(parents=True)
        cache.write_text('module "x" {\n  source = "registry/x/aws"\n}\n', encoding="utf-8")
        self.expect_ok()


class ModuleBypasses(OfflineCase):
    """Spellings that `terraform init` accepts and a line scan would miss."""

    REG = "terraform-aws-modules/vpc/aws"

    def add(self, name: str, text: str) -> None:
        (self.root / "infra" / "bootstrap" / name).write_text(text, encoding="utf-8")

    def expect_remote(self, source: str = REG) -> None:
        self.expect_fail(f"remote module source '{source}' is not sis-platform at release_sha (L3)")

    def test_unquoted_label(self) -> None:
        self.add("evil.tf", f'module evil {{\n  source = "{self.REG}"\n}}\n')
        self.expect_remote()

    def test_block_comment_before_module_on_the_line(self) -> None:
        self.add("evil.tf", f'/* x */ module "e" {{\n  source = "{self.REG}"\n}}\n')
        self.expect_remote()

    def test_module_after_a_closing_brace_on_the_same_line(self) -> None:
        self.add("evil.tf", f'locals {{}} module "e" {{\n  source = "{self.REG}"\n}}\n')
        self.expect_remote()

    def test_a_lone_quote_in_a_heredoc_does_not_hide_a_later_module(self) -> None:
        self.add(
            "evil.tf",
            'locals {\n  note = <<-EOT\n    say "hi\n  EOT\n}\n\n'
            f'module "e" {{\n  source = "{self.REG}"\n}}\n',
        )
        self.expect_remote()

    def test_single_line_module(self) -> None:
        self.add("evil.tf", f'module "e" {{ source = "{self.REG}" }}\n')
        self.expect_remote()

    def test_quoted_source_key(self) -> None:
        self.add("evil.tf", f'module "e" {{\n  "source" = "{self.REG}"\n}}\n')
        self.expect_remote()

    def test_source_after_other_arguments_and_comments(self) -> None:
        self.add(
            "evil.tf",
            f'module "e" {{\n  # source = "../ok"\n  x = 1\n  source = "{self.REG}"\n}}\n',
        )
        self.expect_remote()

    def test_commented_out_modules_are_ignored(self) -> None:
        self.add(
            "ok.tf",
            f'/* module "a" {{\n  source = "{self.REG}"\n}} */\n'
            f'# module "b" {{ source = "{self.REG}" }}\n'
            f'// module "c" {{ source = "{self.REG}" }}\n',
        )
        self.expect_ok()

    def test_slashes_inside_a_string_are_not_a_comment(self) -> None:
        # The platform URL holds `//modules`; stripping `//` comments must not cut it.
        self.expect_ok()
        self.edit("infra/bootstrap/main.tf", f"ref={A}", f"ref={B}")
        self.expect_fail("is pinned to ref")

    def tf_json(self, name: str, doc: object) -> None:
        self.add(name, json.dumps(doc))

    def test_tf_json_module(self) -> None:
        self.tf_json("evil.tf.json", {"module": {"e": {"source": self.REG}}})
        self.expect_remote()

    def test_tf_json_module_list_form(self) -> None:
        self.tf_json("evil.tf.json", {"module": [{"e": {"source": self.REG}}]})
        self.expect_remote()

    def test_tf_json_local_and_pinned_pass(self) -> None:
        url = f"git::https://github.com/{PLATFORM}.git//modules/x?ref={A}"
        self.tf_json("ok.tf.json", {"module": {"a": {"source": "./x"}, "b": {"source": url}}})
        self.expect_ok()

    def test_tf_json_with_a_wrong_ref(self) -> None:
        url = f"git::https://github.com/{PLATFORM}.git//modules/x?ref={B}"
        self.tf_json("bad.tf.json", {"module": {"b": {"source": url}}})
        self.expect_fail(f"is pinned to ref {B}, not release_sha {A} (L3)")

    def test_tf_json_that_is_not_json(self) -> None:
        self.add("bad.tf.json", "{")
        self.expect_fail("bad.tf.json: not valid JSON")

    def test_tofu_files(self) -> None:
        self.add("evil.tofu", f'module "e" {{\n  source = "{self.REG}"\n}}\n')
        self.expect_remote()

    def test_tofu_json_files(self) -> None:
        self.tf_json("evil.tofu.json", {"module": {"e": {"source": self.REG}}})
        self.expect_remote()

    def test_uppercase_extension(self) -> None:
        self.add("EVIL.TF", f'module "e" {{\n  source = "{self.REG}"\n}}\n')
        self.expect_remote()


class LowFindings(OfflineCase):
    def test_lock_version_float_is_not_one(self) -> None:
        (self.root / "platform.lock").write_text(
            (self.root / "platform.lock")
            .read_text()
            .replace('"lock_version": 1', '"lock_version": 1.0'),
            encoding="utf-8",
        )
        self.expect_fail("platform.lock: lock_version must be 1")

    def test_duplicate_keys_in_the_lock(self) -> None:
        path = self.root / "platform.lock"
        path.write_text(
            path.read_text().replace('"version"', '"version": "v9.9.9", "version"', 1),
            encoding="utf-8",
        )
        self.expect_fail("platform.lock: not valid JSON (duplicate key 'version')")

    def test_duplicate_keys_in_settings(self) -> None:
        path = self.root / ".claude" / "settings.json"
        path.write_text(
            path.read_text().replace('"ref"', '"ref": "main", "ref"', 1), encoding="utf-8"
        )
        self.expect_fail(".claude/settings.json: not valid JSON (duplicate key 'ref')")

    def test_uppercase_yaml_extension_is_scanned(self) -> None:
        wf = self.root / ".github" / "workflows" / "X.YML"
        uses = f"{PLATFORM}/.github/workflows/reusable-x.yml@{A}"
        wf.write_text("jobs:\n  j:\n    uses: " + uses + " # v0.2.0\n", encoding="utf-8")
        self.expect_fail("X.YML:3: uses")

    def test_action_yml_outside_github_is_scanned(self) -> None:
        action = self.root / "tools" / "x" / "action.yaml"
        action.parent.mkdir(parents=True)
        uses = f"{PLATFORM}/.github/actions/y@{A}"
        action.write_text("runs:\n  steps:\n    - uses: " + uses + " # v0.2.0\n", encoding="utf-8")
        self.expect_fail("tools/x/action.yaml:3: uses")

    def test_action_yml_in_terraform_cache_is_skipped(self) -> None:
        action = self.root / ".terraform" / "x" / "action.yml"
        action.parent.mkdir(parents=True)
        uses = f"{PLATFORM}/.github/actions/y@{A}"
        action.write_text("runs:\n  steps:\n    - uses: " + uses + " # v0.2.0\n", encoding="utf-8")
        self.expect_ok()

    def test_second_marketplace_for_the_platform_with_another_ref(self) -> None:
        path = self.root / ".claude" / "settings.json"
        doc = json.loads(path.read_text())
        alias = {"source": {"source": "github", "repo": PLATFORM.upper(), "ref": "main"}}
        doc["extraKnownMarketplaces"]["alias"] = alias
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.expect_fail(
            "extraKnownMarketplaces.alias points at sis-platform with ref 'main', "
            "expected the lock version 'v0.2.0' (L4)"
        )

    def test_second_marketplace_for_the_platform_with_the_lock_version_passes(self) -> None:
        path = self.root / ".claude" / "settings.json"
        doc = json.loads(path.read_text())
        alias = {"source": {"source": "github", "repo": PLATFORM, "ref": "v0.2.0"}}
        doc["extraKnownMarketplaces"]["alias"] = alias
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.expect_ok()

    def test_unrelated_marketplace_is_left_alone(self) -> None:
        path = self.root / ".claude" / "settings.json"
        doc = json.loads(path.read_text())
        doc["extraKnownMarketplaces"]["other"] = {"source": {"source": "github", "repo": "o/r"}}
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.expect_ok()


BAD = "1" * 40
BAD_URL = f"git::https://github.com/{PLATFORM}.git//modules/account-bootstrap?ref={BAD}"
NOT_PLAIN = "module source is not a single plain string literal"


class ModuleForms(OfflineCase):
    """A `source` that is not one plain string literal cannot be judged by a text scan (round 3)."""

    def add(self, name: str, text: str) -> None:
        (self.root / "infra" / "bootstrap" / name).write_text(text, encoding="utf-8")

    def test_parenthesised(self) -> None:
        self.add("x.tf", f'module "x" {{\n  source = ("{BAD_URL}")\n}}\n')
        self.expect_fail(NOT_PLAIN)

    def test_conditional(self) -> None:
        self.add("x.tf", 'module "x" {\n  source = true ? "./a" : "./b"\n}\n')
        self.expect_fail(NOT_PLAIN)

    def test_interpolated(self) -> None:
        self.add("x.tf", 'module "x" {\n  source = "./local${"/../"}"\n}\n')
        self.expect_fail(NOT_PLAIN)

    def test_template_directive(self) -> None:
        self.add("x.tf", 'module "x" {\n  source = "./local%{ if true }a%{ endif }"\n}\n')
        self.expect_fail(NOT_PLAIN)

    def test_escaped_quote(self) -> None:
        self.add("x.tf", 'module "x" {\n  source = "\\"x" source = "./local"\n}\n')
        self.expect_fail(NOT_PLAIN)

    def test_heredoc(self) -> None:
        self.add("x.tf", f'module "x" {{\n  source = <<EOT\n{BAD_URL}\nEOT\n}}\n')
        self.expect_fail(NOT_PLAIN)

    def test_a_reference(self) -> None:
        self.add("x.tf", 'module "x" {\n  source = var.where\n}\n')
        self.expect_fail(NOT_PLAIN)

    def test_a_source_key_inside_a_nested_object_is_not_the_module_source(self) -> None:
        self.add(
            "x.tf",
            'module "x" {\n  source = "./ok"\n  providers = {\n    source = var.p\n  }\n}\n',
        )
        self.expect_ok()

    def test_plain_literals_still_pass(self) -> None:
        self.add(
            "x.tf", 'module "x" { source = "./ok" }\nmodule "y" {\n  source = "../ok"  # c\n}\n'
        )
        self.expect_ok()


class LocalSources(OfflineCase):
    def add(self, source: str) -> None:
        path = self.root / "infra" / "bootstrap" / "x.tf"
        path.write_text(f'module "x" {{\n  source = "{source}"\n}}\n', encoding="utf-8")

    def test_terraform_cache_segment(self) -> None:
        self.add("./.terraform/modules/m")
        self.expect_fail(
            "local module source './.terraform/modules/m' goes through a .terraform or .git"
        )

    def test_git_segment(self) -> None:
        self.add("../.git/x")
        self.expect_fail("local module source '../.git/x' goes through a .terraform or .git")

    def test_dotted_segment_via_parent_hops(self) -> None:
        self.add("./a/../.terraform/m")
        self.expect_fail("goes through a .terraform or .git")

    def test_leaving_the_repository_root(self) -> None:
        self.add("../../../elsewhere")
        self.expect_fail("local module source '../../../elsewhere' leaves the repository root")

    def test_staying_inside_is_fine(self) -> None:
        self.add("../../local-module")
        self.expect_ok()

    def test_name_that_merely_starts_with_a_dot_is_fine(self) -> None:
        self.add("./.terraformish/m")
        self.expect_ok()


class PlatformCheckout(unittest.TestCase):
    """examples/consumer sits inside a sis-platform checkout and calls ../../../../modules/..."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.checkout = self.tmp / "plat"
        (self.checkout / "scripts" / "release").mkdir(parents=True)
        (self.checkout / "scripts" / "release" / "closure.txt").write_text(":(glob)x\n")
        self.root = consumer(self.checkout / "examples" / "consumer", "v0.2.0", A, B)
        self.main = self.root / "infra" / "bootstrap" / "main.tf"

    def point(self, source: str) -> None:
        text = self.main.read_text()
        self.main.write_text(text.replace("../../local-module", source))

    def run_check(self, *extra: str) -> tuple[int, str]:
        rc, _out, err = run_main(check_lock, [str(self.root), *extra])
        return rc, err

    def test_without_the_flag_the_module_path_leaves_the_root(self) -> None:
        self.point("../../../../modules/account-bootstrap")
        rc, err = self.run_check()
        self.assertEqual(rc, 1)
        self.assertIn("leaves the repository root", err)

    def test_with_the_flag_it_may_reach_the_checkout(self) -> None:
        self.point("../../../../modules/account-bootstrap")
        self.assertEqual(self.run_check("--platform-checkout"), (0, ""))

    def test_with_the_flag_it_may_not_leave_the_checkout(self) -> None:
        self.point("../../../../../escape")
        rc, err = self.run_check("--platform-checkout")
        self.assertEqual(rc, 1)
        self.assertIn("leaves the sis-platform checkout", err)

    def test_the_flag_needs_a_checkout(self) -> None:
        (self.checkout / "scripts" / "release" / "closure.txt").unlink()
        rc, err = self.run_check("--platform-checkout")
        self.assertEqual(rc, 2)
        self.assertIn("--platform-checkout: no sis-platform checkout above", err)


class Symlinks(OfflineCase):
    def test_symlink_to_a_directory(self) -> None:
        (self.root / "vendor").mkdir()
        os.symlink("../../vendor", self.root / "infra" / "bootstrap" / "vend")
        self.expect_fail("symlink infra/bootstrap/vend points to a directory (not followed)")

    def test_symlink_that_leaves_the_root(self) -> None:
        outside = self.tmp / "outside.tf"
        outside.write_text('module "y" {\n  source = "x/y/aws"\n}\n')
        os.symlink(outside, self.root / "infra" / "bootstrap" / "o.tf")
        self.expect_fail("symlink infra/bootstrap/o.tf leaves the repository root")

    def test_directory_symlink_for_the_workflows_folder(self) -> None:
        shutil.move(str(self.root / ".github" / "workflows"), str(self.root / "ci"))
        os.symlink("../ci", self.root / ".github" / "workflows")
        self.expect_fail("symlink .github/workflows points to a directory")

    def test_symlink_to_a_file_inside_the_root_is_fine(self) -> None:
        os.symlink("../../platform.yaml", self.root / "infra" / "bootstrap" / "p.yaml")
        self.expect_ok()


class YamlStrictness(OfflineCase):
    def workflow(self, text: str) -> None:
        (self.root / ".github" / "workflows" / "a.yml").write_text(text, encoding="utf-8")

    def test_duplicate_keys_are_refused(self) -> None:
        reusable = f"{PLATFORM}/.github/workflows/reusable-terraform-plan.yml"
        self.workflow(
            f"jobs:\n  a:\n    uses: {reusable}@{BAD} # v0.2.0\n    uses: {reusable}@{B} # v0.2.0\n"
        )
        self.expect_fail("a.yml: invalid YAML (duplicate key")

    def test_binary_uses_is_refused(self) -> None:
        blob = base64.b64encode(f"{PLATFORM}/x@{BAD}".encode()).decode()
        self.workflow(f"jobs:\n  a:\n    uses: !!binary {blob}\n")
        self.expect_fail("a.yml: uses value is not a plain string")

    def test_platform_path_must_be_a_reusable_workflow(self) -> None:
        for path in (".github/workflows/ci.yml", ".github/actions/y", "scripts/x.sh", ""):
            tail = f"/{path}" if path else ""
            self.workflow(f"jobs:\n  a:\n    uses: {PLATFORM}{tail}@{B} # v0.2.0\n")
            self.expect_fail("is not a reusable-*.yml workflow of sis-platform (W1)")

    def test_reusable_workflow_path_passes(self) -> None:
        wf = f"{PLATFORM}/.github/workflows/reusable-oidc-smoke.yml"
        self.workflow(f"jobs:\n  a:\n    uses: {wf}@{B} # v0.2.0\n")
        self.expect_ok()


class Settings(OfflineCase):
    def test_settings_missing(self) -> None:
        (self.root / ".claude" / "settings.json").unlink()
        self.expect_fail(".claude/settings.json: cannot read")

    def test_settings_not_json(self) -> None:
        (self.root / ".claude" / "settings.json").write_text("{", encoding="utf-8")
        self.expect_fail(".claude/settings.json: not valid JSON")

    def test_marketplace_missing(self) -> None:
        (self.root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        self.expect_fail("extraKnownMarketplaces.sis-platform is missing")

    def test_marketplace_ref_must_be_the_version(self) -> None:
        self.edit(".claude/settings.json", '"ref": "v0.2.0"', '"ref": "main"')
        self.expect_fail("source.ref is 'main', expected the lock version 'v0.2.0' (L4)")

    def test_marketplace_repo_must_be_the_platform(self) -> None:
        self.edit(".claude/settings.json", PLATFORM, "someone/else")
        self.expect_fail("source.repo is 'someone/else'")

    def test_marketplace_source_kind(self) -> None:
        self.edit(".claude/settings.json", '"source": "github"', '"source": "git"')
        self.expect_fail("source.source must be 'github'")


class Usage(OfflineCase):
    def test_unknown_option(self) -> None:
        rc, _out, err = run_main(check_lock, [str(self.root), "--bogus"])
        self.assertEqual(rc, 2)
        self.assertIn("Usage:", err)

    def test_not_a_directory(self) -> None:
        rc, _out, err = run_main(check_lock, [str(self.root / "nope")])
        self.assertEqual(rc, 2)
        self.assertIn("is not a directory", err)

    def test_exit_status_from_a_real_process(self) -> None:
        script = REPO_ROOT / "scripts" / "platform" / "check_lock.py"
        done = subprocess.run(  # noqa: S603
            [sys.executable, str(script), str(self.root)], capture_output=True, check=False
        )
        self.assertEqual(done.returncode, 0, done.stderr.decode())
        (self.root / "platform.lock").unlink()
        done = subprocess.run(  # noqa: S603
            [sys.executable, str(script), str(self.root)], capture_output=True, check=False
        )
        self.assertEqual(done.returncode, 1)
        self.assertIn("platform.lock: cannot read", done.stderr.decode())


class RemoteCase(OfflineCase):
    """A fixture sis-platform repo: v0.1.0 (c1), v0.1.1 (docs only), v0.2.0 (moves the closure)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.plat = Repo(self.tmp / "platform")
        self.c1 = self.plat.seed("0.1.0")
        self.plat.tag("v0.1.0")
        self.plat.write("docs/readme.md", "more docs\n")
        self.c2 = self.plat.commit("docs")
        self.plat.tag("v0.1.1")
        self.plat.write("scripts/platform/tool.py", "print('v2')\n")
        self.c3 = self.plat.commit("tool")
        self.plat.bump_versions("0.2.0")
        self.c4 = self.plat.commit("bump")
        self.plat.tag("v0.2.0")
        # v0.2.0 is c4; its workflow_sha is c3 (the last commit that touched the closure).
        self.root = consumer(self.tmp / "consumer", "v0.2.0", self.c4, self.c3)

    def run_remote(self) -> tuple[int, str]:
        rc, _out, err = run_main(
            check_lock, [str(self.root), "--remote", "--platform-repo", str(self.plat.path)]
        )
        return rc, err

    def expect_remote_ok(self) -> None:
        self.assertEqual(self.run_remote(), (0, ""))

    def expect_remote_fail(self, fragment: str) -> None:
        rc, err = self.run_remote()
        self.assertEqual(rc, 1, err)
        self.assertIn(fragment, err)

    def relock(self, release: str, workflow: str, trusted: Optional[List[str]] = None) -> None:
        self.root = consumer(self.tmp / "consumer", "v0.2.0", release, workflow, trusted)


class RemoteChecks(RemoteCase):
    def test_a_good_consumer_passes_remotely(self) -> None:
        self.expect_remote_ok()

    def test_offline_mode_never_touches_the_platform_repo(self) -> None:
        shutil.rmtree(self.plat.path)
        self.expect_ok()

    def test_remote_without_a_source_uses_the_public_url(self) -> None:
        self.assertEqual(check_lock.PLATFORM_URL, f"https://github.com/{PLATFORM}.git")

    def test_clone_failure_is_reported(self) -> None:
        shutil.rmtree(self.plat.path)
        self.expect_remote_fail("cannot clone")

    def test_tag_missing(self) -> None:
        helpers.git(self.plat.path, "tag", "-d", "v0.2.0")
        self.expect_remote_fail("tag v0.2.0 does not exist in sis-platform")

    def test_tag_points_elsewhere(self) -> None:
        self.relock(self.c2, self.c3)
        self.expect_remote_fail(f"tag v0.2.0 resolves to {self.c4}, not release_sha {self.c2}")

    def test_release_sha_not_on_main(self) -> None:
        self.plat.checkout_new("side", self.c4)
        self.plat.write("scripts/platform/tool.py", "print('side')\n")
        side = self.plat.commit("side")
        helpers.git(self.plat.path, "tag", "-f", "v0.2.0", side)
        self.plat.checkout("main")
        self.relock(side, side)
        self.expect_remote_fail(
            f"release_sha {side} is not an ancestor of the sis-platform main tip"
        )

    def test_recomputed_workflow_sha_must_match(self) -> None:
        self.relock(self.c4, self.c1, [self.c1])
        self.expect_remote_fail(
            f"the closure recomputed at release_sha is {self.c3}, not workflow_sha {self.c1} (L3)"
        )

    def test_trusted_sha_not_a_commit(self) -> None:
        self.relock(self.c4, self.c3, [self.c3, "d" * 40])
        self.expect_remote_fail(f"trusted_workflow_shas {'d' * 40}: not a commit in sis-platform")

    def test_trusted_sha_not_on_main(self) -> None:
        # An impostor: a commit on a side branch that carries the closure at some other state.
        self.plat.checkout_new("side", self.c4)
        self.plat.write("scripts/platform/tool.py", "print('evil')\n")
        evil = self.plat.commit("evil")
        self.plat.checkout("main")
        self.relock(self.c4, self.c3, [self.c3, evil])
        self.expect_remote_fail(
            f"trusted_workflow_shas {evil}: not an ancestor of the sis-platform main tip (L3 a)"
        )

    def test_trusted_sha_not_a_released_workflow_sha(self) -> None:
        # On main, but no v* tag's closure recomputes to it (the closure moved only at c1 and c3).
        self.relock(self.c4, self.c3, [self.c3, self.c4])
        self.expect_remote_fail(
            f"trusted_workflow_shas {self.c4}: not the workflow_sha of any released v* tag (L3 b)"
        )

    def test_a_tag_on_a_side_branch_does_not_make_a_workflow_sha_released(self) -> None:
        self.plat.checkout_new("side", self.c4)
        self.plat.write("scripts/platform/tool.py", "print('side')\n")
        side = self.plat.commit("side")
        self.plat.tag("v0.9.0", side)
        self.plat.checkout("main")
        self.relock(self.c4, self.c3, [self.c3, side])
        self.expect_remote_fail(
            f"trusted_workflow_shas {side}: not the workflow_sha of any released v* tag (L3 b)"
        )

    def test_previous_released_workflow_sha_is_trusted(self) -> None:
        self.relock(self.c4, self.c3, [self.c3, self.c1])
        self.expect_remote_ok()

    def test_trusted_sha_that_holds_reusable_release_is_refused(self) -> None:
        self.plat.write(".github/workflows/reusable-release.yml", "name: release\n")
        self.plat.write("scripts/platform/tool.py", "print('v3')\n")
        c5 = self.plat.commit("deploy workflow")
        self.plat.bump_versions("0.3.0")
        self.plat.commit("bump")
        self.plat.tag("v0.3.0")
        self.relock(self.c4, self.c3, [self.c3, c5])
        self.expect_remote_fail(
            f"trusted_workflow_shas {c5}: its tree holds .github/workflows/reusable-release.yml "
            "while DEPLOY_TRUST_ALLOWED is false (L3 c)"
        )

    def test_deploy_trust_flag_lifts_the_third_check(self) -> None:
        self.plat.write(".github/workflows/reusable-release.yml", "name: release\n")
        c5 = self.plat.commit("deploy workflow")
        self.plat.tag("v0.3.0")
        self.relock(self.c4, self.c3, [self.c3, c5])
        self.expect_remote_fail("(L3 c)")
        original = check_lock.DEPLOY_TRUST_ALLOWED
        check_lock.DEPLOY_TRUST_ALLOWED = True
        self.addCleanup(setattr, check_lock, "DEPLOY_TRUST_ALLOWED", original)
        self.expect_remote_ok()

    def test_remote_also_reports_offline_findings(self) -> None:
        self.edit_lock(lock_version=2)
        self.expect_remote_fail("platform.lock: lock_version must be 1")

    def test_a_tag_from_before_the_closure_existed_is_skipped(self) -> None:
        # v0.0.9 has no closure.txt: it is no released workflow_sha and must not crash the check.
        plat = Repo(self.tmp / "platform2")
        plat.write("README.md", "x\n")
        plat.commit("init")
        plat.tag("v0.0.9")
        plat.seed("0.2.0")
        workflow = plat.head()
        plat.tag("v0.2.0")
        self.root = consumer(self.tmp / "consumer2", "v0.2.0", workflow, workflow)
        rc, _out, err = run_main(
            check_lock, [str(self.root), "--remote", "--platform-repo", str(plat.path)]
        )
        self.assertEqual((rc, err), (0, ""))


class Subprocesses(RemoteCase):
    def test_platform_repo_may_not_look_like_an_option(self) -> None:
        rc, _out, err = run_main(check_lock, [str(self.root), "--remote", "--platform-repo", "-x"])
        self.assertEqual(rc, 2)
        self.assertIn("--platform-repo value must not start with '-'", err)

    def test_clone_separates_the_source_with_double_dash(self) -> None:
        seen: List[Any] = []
        real = subprocess.run

        def spy(cmd: List[str], *args: Any, **kwargs: Any) -> Any:
            if "clone" in cmd:
                seen.append((cmd, kwargs.get("timeout")))
            return real(cmd, *args, **kwargs)

        with mock.patch("subprocess.run", spy):
            self.expect_remote_ok()
        cmd, timeout = seen[0]
        self.assertEqual(cmd[cmd.index("--") + 1], str(self.plat.path))
        self.assertIsNotNone(timeout)

    def test_every_git_call_has_a_timeout(self) -> None:
        timeouts: List[Any] = []
        real = subprocess.run

        def spy(cmd: List[str], *args: Any, **kwargs: Any) -> Any:
            timeouts.append(kwargs.get("timeout"))
            return real(cmd, *args, **kwargs)

        with mock.patch("subprocess.run", spy):
            self.expect_remote_ok()
        self.assertTrue(timeouts)
        self.assertNotIn(None, timeouts)

    def test_a_clone_timeout_is_reported(self) -> None:
        boom = subprocess.TimeoutExpired("git", 1)
        with mock.patch("subprocess.run", side_effect=boom):
            self.expect_remote_fail("cannot clone")
            self.assertIn("timed out", self.run_remote()[1])

    def test_a_git_timeout_in_the_closure_helpers_is_an_error(self) -> None:
        boom = subprocess.TimeoutExpired("git", 1)
        with mock.patch("subprocess.run", side_effect=boom):
            with self.assertRaises(closure.ClosureError) as ctx:
                closure.git(str(self.plat.path), "status")
            self.assertIn("timed out", str(ctx.exception))
            self.assertIsNone(closure.specs_at(str(self.plat.path), "HEAD"))
            self.assertFalse(closure.git_ok(str(self.plat.path), "status"))


if __name__ == "__main__":
    unittest.main()
