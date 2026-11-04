# Front door for local checks. CI calls the same targets, so local and CI results match.
# No apply or destroy targets, ever: a human runs those (scripts/ci/selftest.sh enforces it).
# Works with the GNU Make 3.81 that ships with macOS.

SHELL := /bin/bash
PYTHON ?= python3
# The CI tools (pre-commit and friends) need 3.13; the intake tests use PYTHON so they can run on the 3.9 floor.
VENV_PYTHON ?= python3.13

.DEFAULT_GOAL := help
.PHONY: help venv lint test validate-examples check require-intake

help: ## List targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# Built once and reused; rebuilt when the hash-locked requirements change. A stamp file, because the venv
# interpreter is a symlink that touch must not follow.
.venv-ci/.installed: scripts/ci/requirements.txt
	PYTHON=$(VENV_PYTHON) scripts/ci/venv.sh .venv-ci
	@touch $@

venv: .venv-ci/.installed ## Hash-locked CI venv (.venv-ci) with pre-commit and PyYAML

require-intake:
	@test -d intake/sis_intake || { echo "error: intake/ is missing (the intake package is built in its own lane). Nothing to run." >&2; exit 1; }

lint: .venv-ci/.installed ## pre-commit hooks on all files, shellcheck, actionlint and the repo guard self-tests
	PATH="$(CURDIR)/.venv-ci/bin:$$PATH" pre-commit run --all-files --show-diff-on-failure
	shellcheck -x $$(find scripts -name '*.sh' | sort)
	scripts/ci/selftest.sh
	$(if $(wildcard .github/workflows/*.yml),actionlint,@echo "no workflows yet, skipping actionlint")

test: require-intake ## Intake and sis-team unit tests (stdlib unittest, 3.9 and 3.13)
	$(PYTHON) -m unittest discover -s intake/tests -t intake
	$(PYTHON) -m unittest discover -s plugins/sis-team/scripts -p 'test_*.py'
	@if command -v $(VENV_PYTHON) >/dev/null 2>&1; then $(VENV_PYTHON) -m unittest discover -s plugins/sis-team/scripts -p 'test_*.py'; fi

validate-examples: require-intake ## Every valid example exits 0, every invalid one exits non-zero
	@scripts/ci/validate-examples.sh

check: lint test validate-examples ## Everything a PR must pass (CI job `check`)

.PHONY: tf-check
tf-check: ## Offline Terraform checks for modules/: fmt, validate, tests, tflint, README, policy.py (no AWS)
	scripts/tf/check.sh
