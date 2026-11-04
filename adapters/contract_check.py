"""Cross-field checks for an adapter result line (contract v1). Stdlib only, Python 3.9 compatible.

The JSON Schemas in this directory stay inside the Z4 keyword subset, so rules that relate two
fields live here. The Phase 2 conformance suite (K7) imports this module; so do the schema
tests.

    from contract_check import check_line
    problems = check_line(doc, verb="deploy", exit_code=0, inputs=os.environ)
"""

import json
import os
import sys
from collections.abc import Mapping
from typing import Any, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "intake"))

from sis_intake import schema as z4  # noqa: E402

STATES = ["publishing", "verifying", "shifting", "baking", "succeeded", "failed", "rolled_back"]
VERBS = ["deploy", "verify", "rollback", "status"]

# K4: exit code -> states a result line may carry with it.
EXIT_STATES = {
    0: {"succeeded"},
    1: {"failed", "rolled_back"},
    2: {"failed"},
    3: {"publishing", "verifying", "shifting", "baking"},
}


def load_schema(name: str) -> dict[str, Any]:
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        schema: dict[str, Any] = json.load(fh)
    return schema


def release_id(env: str, digest: str) -> str:
    """K5: <env>-<first 12 hex of the digest>."""
    return "{}-{}".format(env, digest[len("sha256:") :][:12])


def check_line(
    doc: dict[str, Any],
    verb: Optional[str] = None,
    exit_code: Optional[int] = None,
    inputs: Optional[Mapping[str, str]] = None,
) -> list[str]:
    """Schema plus cross-field rules. Returns a list of problem strings (empty means valid).

    verb: the verb that ran. exit_code: its exit code.
    inputs: a mapping of the SIS_* variables it ran with.
    """
    out = [i.message for i in z4.validate(doc, load_schema("result.schema.json"))]
    if out:
        return out
    if doc["release_id"] != release_id(doc["env"], doc["digest"]):
        out.append("release_id must be <env>-<first 12 hex of the digest> (K5)")
    if verb is not None and doc["verb"] != verb:
        out.append("verb {!r} does not match the verb that ran ({!r})".format(doc["verb"], verb))
    if exit_code is not None and doc["state"] not in EXIT_STATES[exit_code]:
        out.append(f"state {doc['state']!r} is not allowed with exit code {exit_code} (K4)")
    pct = doc["traffic"]["candidate_percent"]
    if doc["state"] == "succeeded" and pct != 100:
        out.append("succeeded needs candidate_percent 100 (1g addition)")
    if doc["state"] == "rolled_back" and pct != 0:
        out.append("rolled_back needs candidate_percent 0 (1g addition)")
    if inputs is not None:
        out.extend(_check_inputs(doc, inputs))
    return out


def _check_inputs(doc: dict[str, Any], inputs: Mapping[str, str]) -> list[str]:
    out: list[str] = []
    # In rollback, SIS_PREV_DIGEST is the target that becomes live; the line describes the target.
    want = inputs.get("SIS_PREV_DIGEST") if doc["verb"] == "rollback" else inputs.get("SIS_DIGEST")
    if want is not None and doc["digest"] != want:
        which = "SIS_PREV_DIGEST" if doc["verb"] == "rollback" else "SIS_DIGEST"
        out.append(f"digest must equal {which}")
    if inputs.get("SIS_ENV") is not None and doc["env"] != inputs["SIS_ENV"]:
        out.append("env must equal SIS_ENV")
    # SIS_SHA belongs to SIS_DIGEST, so it is only echoed for the verbs that act on that digest.
    if (
        doc["verb"] != "rollback"
        and inputs.get("SIS_SHA") is not None
        and doc["sha"] != inputs["SIS_SHA"]
    ):
        out.append("sha must equal SIS_SHA")
    return out
