# Runbook: leaked token or bad commit

Use when a secret, token, key or account ID reached a commit, a PR, a log or chat, or when a commit on a branch or
`main` must be treated as hostile. The repo is public: assume anything pushed is already copied. Never paste the
leaked value into a ticket, a PR or this file.

## 1. First ten minutes: revoke, then clean

Order matters. Revoking beats deleting the commit.

| What leaked | Revoke first |
|---|---|
| Git PAT (fine-grained) | GitHub, Settings, Developer settings: delete the token; make a new one with the same minimal scopes |
| Board token (classic `project`) | Delete it, create a new one, store it in the Keychain with `kc` |
| AWS access key or session | Deny and revoke sessions (step 3); deactivate the key, then delete it |
| Anthropic or other API key | Revoke in the provider console, issue a new one |
| Account ID only | Not a credential: remove it from the file, no rotation. Record it as a repo-guard miss |
| GitHub environment secret (`AWS_ACCOUNT_ID`) | An identifier, not a credential: fix the leak, no rotation |

## 2. Remove it from the repo

1. Open a PR that deletes the value. Do not force-push `main` (the ruleset blocks it; do not try to bypass).
2. If it sits in a PR only: close the PR, delete the branch. GitHub keeps the commit reachable by SHA, so the
   revoke in step 1 still applies.
3. If a history rewrite is wanted for a branch you own, the owner does it and confirms no one else has it checked
   out.
4. For a leaked value in `main` history, treat it as permanent: the revoke is the fix. Ask GitHub support to purge
   cached views only for serious leaks.

## 3. AWS: deny and revoke sessions

1. Owner, with Identity Center admin credentials, in the affected account (`dev` or `prod`): attach an inline
   deny-all policy to the affected role, then revoke active sessions (IAM console, role, "Revoke sessions"). Do this
   before investigating.
2. Look for use: CloudTrail `lookup-events` in both regions (`ap-southeast-1`, `us-east-1`) for the role name and
   the `AssumeRoleWithWebIdentity` event. Paste only `eventName`, `errorCode` and time.
3. Check the account trail, IAM Access Analyzer findings, and the budget and cost anomaly alerts for new resources.
4. Remove the deny after the cause is fixed and the trust is re-verified (`oidc-trust-broken.md` step 6).

## 4. Bad commit already merged to main

1. Do not push to `main`. Open a revert PR (`git revert <sha>`), mark it urgent and ask the owner to merge it.
2. If the bad commit touched the workflow closure (`scripts/release/closure.txt` paths), `workflow_sha` moved. Do
   not add it to `trusted_workflow_shas`. If a release tag already points at it, cut a fixed minor release (L7: a
   trust move needs a minor), roll trust forward by O10 and drop the bad SHA from the list at once.
3. If a tag points at a bad release: tags are immutable by the ruleset, so publish a new tag and tell consumers to
   bump. Consumers pin tags and SHAs, so no one is silently affected.

## 5. Why it happened, and the guard

1. Which control should have caught it: gitleaks, the 12-digit ID hook, `check_repo.py`, V10, zizmor?
2. Add a fixture or a rule so it fails next time. Guard changes go through `scripts/ci/` and a PR.
3. Note the incident in the PR description: what, when, what was revoked. No values.

## 6. Close out

- New credentials created and stored in the Keychain (`kc`), never in files.
- Old credentials confirmed dead (a failing call with the old value).
- Revert PR merged. `make check` green on `main`.
