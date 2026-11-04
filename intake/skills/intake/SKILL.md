---
name: intake
description: Interview the user about a product idea and produce three drafts for a sis-platform project, a validated platform.yaml, a first ADR with a Well-Architected review table, and a pipeline proposal. Use when the user wants to start a new project on sis-platform or asks for an intake, a platform.yaml or a runtime recommendation.
---

# sis-platform intake

Turn a product idea into a validated `platform.yaml` manifest by interviewing the user, then return three drafts as
text. Nothing is written into the project repo: the orchestrating session in the project repo writes the drafts.

Two roles:

- The `intake-interviewer` agent (tools: Read, Grep, Glob; no Bash) runs the interview and returns the draft
  manifest as text. It cannot run the validator.
- This skill runs in the orchestrating session. That session pipes the draft to the validator on stdin and sends the
  findings back to the interviewer until there are 0 errors (the loop in Procedure step 3).

## Rules

- Ask ONE question at a time and wait for the answer. Never batch questions.
- Follow `${CLAUDE_PLUGIN_ROOT}/rules/questions.json`: groups Q1 to Q10 in order, questions in order. Skip Q10 unless
  the app already exists. Read the file first; each question has `ask`, `manifest_path`, `options`, `recommend`
  and `pillar`.
- For every question, give your recommended answer with its Well-Architected pillar and one sentence of reason,
  taken from `recommend` and adjusted to the answers so far. The user can accept it or answer differently.
- Use the runtime defaults in `${CLAUDE_PLUGIN_ROOT}/rules/defaults.json` and the compatibility matrix in
  `${CLAUDE_PLUGIN_ROOT}/rules/compat.json` to propose runtime, front door, strategy and engine. arm64 is the default
  architecture for new apps.
- Never ask for, accept or write an AWS account ID. Accounts are labels (`dev`, `prod`). If the user pastes a
  12-digit number, ask them to use a label (rule V10).
- Never run AWS, Terraform or `gh` write commands. Never write into the project repo, and write no temp file. The
  only command the orchestrating session runs for this skill is the validator below, with the draft on stdin.
- The manifest uses a YAML subset: block maps and lists, plain or quoted scalars, int, bool, null, comments, one-line
  flow lists and flow maps. No anchors, aliases, tags, multi-line scalars or nested flow maps. Quote strings that look
  like numbers, dates or yes/no. Env names are 2 to 8 characters: a lowercase letter, then lowercase letters or digits (no hyphen).

## Procedure

1. Run the interview (the interviewer agent), Q1 to Q9 (and Q10 when it applies). If Q10 answers retire, retain,
   relocate or repurchase, stop and return a short note instead of a manifest.
2. The interviewer drafts the manifest from the example closest to the answers in
   `${CLAUDE_PLUGIN_ROOT}/examples/valid/` and `schema_version: 1`, and returns it as text. Every manifest needs
   `project.owner` (a GitHub login or team handle, never an email), `budget.monthly_usd`, and a `tier` (`prod` or
   `nonprod`) on each env. A `prod` tier env also needs `compliance.data_class`, `dr.rto_minutes`, `dr.rpo_minutes`,
   `workload.peak_rps` and `workload.p95_ms`.
3. The orchestrating session validates the draft by sending it to the validator on stdin:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/sis_intake/validate.py" - <<'YAML'
   <the manifest>
   YAML
   ```

   Exit code 0 means valid, 1 means errors, 2 means a parse or usage error. Send each finding (`id`, `path`,
   `message`, pillars) back to the interviewer. It fixes every error by changing the manifest or by asking the user a
   follow-up question, and returns a new draft; validate again. Loop until there are 0 errors. Explain each remaining
   warning to the user and ask whether to accept it or change the answer.
4. Report the resolved `engine` and `deploy_role_profile` per env that the validator prints.
5. Return the three drafts below as text in one reply, then stop.

## The three drafts

1. `platform.yaml`: the validated manifest in a yaml code block.
2. A first ADR (`docs/adr/0001-<project>-platform.md`) with: status `proposed`, context (the product idea and the
   interview answers), decision (runtime, front door, release strategy and engine, DR, accounts), and a
   `## Well-Architected review` table with one row per pillar (operational excellence, security, reliability,
   performance efficiency, cost optimization, sustainability). Each row cites the pillar best practices met (for
   example OPS06-BP04, SEC01-BP01, REL13-BP01, PERF02-BP01, COST02-BP05, SUS05-BP02), how the design meets them, and
   the gap and which phase closes it. Include the accepted warnings and why.
3. A pipeline proposal: build, test and plan on pull request; deploy to dev on merge to main; promote the same image
   digest to prod behind a GitHub environment approval; the release strategy and rollback trigger per env;
   the exact manual steps the owner must run (the account bootstrap apply is always run by the owner, never by an
   agent).

Say clearly at the end that the orchestrating session must write these files into the project repo.
