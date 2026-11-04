#!/usr/bin/env python3
"""Run the T11 policy lint over a Terraform plan in a reusable workflow (ADR 0002 W3, T11).

Usage: plan-policy.py PLAN_JSON --boundary-arn ARN

`scripts/tf/policy.py` exits 2 when its input holds no IAM policy, which is right for its
fixtures but wrong for a plan that creates no IAM policy (a first env root with one
`terraform_data`). This wrapper asks policy.py's own collector which policies the plan holds:
none means a pass with a note, otherwise it runs policy.py's rules unchanged (unknown policies
fail closed, P00). The boundary ARN is the bootstrap's `<prefix>-<env>-workload-boundary` in the
env account.

Exit 0 clean, 1 findings, 2 usage or unreadable input. Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import json
import os
import sys
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tf"))
import policy  # noqa: E402  (scripts/tf/policy.py, in the closure)


def main(argv: List[str]) -> int:
    if len(argv) != 3 or argv[1] != "--boundary-arn" or not argv[2]:
        print(__doc__, file=sys.stderr)
        return 2
    path, boundary = argv[0], argv[2]
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or "format_version" not in data:
            raise policy.InputError(f"{path}: not the JSON of terraform show -json")
        docs, _ = policy.collect(data, path)
    except (OSError, ValueError, policy.InputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not docs:
        print("ok  policy lint: the plan creates or changes no IAM policy", file=sys.stderr)
        return 0
    return policy.main([path, "--boundary-arn", boundary])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
