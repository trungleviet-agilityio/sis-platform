---
paths:
  - "intake/**"
---

# intake rules

- Runtime code runs on Python 3.9 or later, standard library only. PyYAML and other third-party imports are allowed
  in `intake/tests/` only, and those tests skip with a message when the package is missing.
- Manifests use the YAML subset in `intake/README.md`. Extend the loader only with a conformance test against
  `yaml.safe_load`.
- The schema uses only the keyword subset listed in ADR 0001 Z4; `test_schema` fails on any other keyword.
- Every rule in `rules/rules.json` has an ID, severity, pillars, `wa_refs`, one predicate in `rules.py`, a pass and
  a fail test, and (for errors) an `examples/invalid/` file whose first line is `# expect: <ID>`.
- After changing `rules.json`, regenerate the README table: `cd intake && python3 -m sis_intake.ruletable --write`.
- The only 12-digit number allowed is the placeholder in `examples/invalid/account-id.yaml`.
