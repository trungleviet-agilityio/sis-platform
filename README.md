# sis-platform

Shared delivery platform for sis-dev projects on AWS: GitHub Actions + Terraform, OIDC roles with least privilege,
one artifact promoted by digest from dev to prod, and a runtime adapter per compute target.

Status: **phase 0** (design and the project manifest). Nothing here deploys anything yet.

## Idea

- A project repo stays thin: its app, its `infra/envs/*` and a `platform.yaml` manifest. Workflows and Terraform
  modules come from this repo, pinned by tag.
- An intake interview turns a product idea into `platform.yaml`: runtime, front door, environments, delivery
  model, release strategy and budget.
- Every runtime implements the same adapter contract (deploy, verify, rollback, status by image digest), so every
  project gets the same pipeline shape.

## Decisions

See [`docs/adr/`](docs/adr/).
