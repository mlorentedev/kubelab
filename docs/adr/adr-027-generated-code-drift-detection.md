---
id: adr-027-generated-code-drift-detection
type: adr
status: active
created: "2026-03-27"
owner: manu
---

# ADR-027: Generated Code Drift Detection

> **Status:** Accepted
> **Date:** 2026-03-27
> **Supersedes:** None
> **Related:** ADR-020 (IaC Lifecycle), ADR-014 (Secrets Management), ADR-023 (Hub-Spoke GitOps)

## Context

KubeLab follows IaC principles: Git is the source of truth, the cluster reflects Git. Several scripts derive tracked files from the SSOT (`common.yaml`, SOPS secrets):

| Script | SSOT Source | Tracked Output |
|--------|------------|----------------|
| `sync_homepage_config.py` | common.yaml + Jinja2 templates | 8 files in `infra/k8s/base/services/homepage-config/` |
| `sync_k8s_images.py` | common.yaml `apps.services.*.image` | `infra/k8s/base/kustomization.yaml` (images block) |
| `sync_oidc_hashes.py` | SOPS secrets (OIDC client hashes) | `authelia.yaml` + `overlays/prod/patches.yaml` |

These files are committed to Git because:
- GitOps (Argo CD) needs final manifests in Git to deploy
- PRs show exactly what changes in the cluster
- Deploy is deterministic — same commit = same result

**Problem:** If a developer changes `common.yaml` but forgets to run the sync scripts, the tracked files drift from the SSOT. Deploy applies stale manifests. No validation exists to catch this.

This is not an architectural flaw — it's a well-known pattern ("checked-in generated code") used by Go (`go generate`), Protobuf, Terraform, and Helm. The missing piece is **drift detection**.

Other generators in the codebase (`generator_traefik.py`, `generator_ansible.py`, `generator_authelia.py`) write to `generated/` directories excluded via `.gitignore` — they already follow the correct pattern and are not affected.

## Decision

### 1. Unified `toolkit sync` CLI command

Consolidate the three loose scripts under a single CLI interface:

```
toolkit sync --check              # Validate all (exit 1 if drift)
toolkit sync --check homepage     # Validate one
toolkit sync homepage             # Execute sync (modify files)
toolkit sync images               # Execute sync
toolkit sync oidc-hashes --env X  # Execute sync (needs SOPS)
```

The `--check` flag compares generated output against the file on disk without modifying it. Exit code 0 = in sync, 1 = drift detected. Same contract as `ruff format --check`.

### 2. Enforcement at two points

**Pre-commit (`make check`):**
```makefile
check: lint type test validate-sync
```

**Pre-deploy (`make deploy-k8s`):**
```makefile
deploy-k8s: apply-secrets validate-sync
    @$(TOOLKIT) infra k8s deploy --env $(ENV)
```

Both call:
```makefile
validate-sync:
    @$(TOOLKIT) sync --check --env $(ENV)
```

### 3. SOPS CI recipient (Nivel 2)

`sync_oidc_hashes` requires SOPS decryption. To enable full validation in CI, add a dedicated CI AGE key as a second SOPS recipient.

**Setup (one-time, documented here for reproducibility):**

```bash
# 1. Generate CI-only AGE key
age-keygen -o ci-age-key.txt
# Public key: age1ci... (add to .sops.yaml)
# Private key: AGE-SECRET-KEY-... (store as GitHub Actions secret SOPS_AGE_KEY)

# 2. Update .sops.yaml — add CI recipient to all rules
creation_rules:
  - path_regex: infra/config/secrets/.*\.enc\.yaml$
    key_groups:
      - age:
          - "age166v8e..."   # human (workstation)
          - "age1ci..."       # CI (GitHub Actions)

# 3. Re-encrypt all secrets for both recipients
for f in infra/config/secrets/*.enc.yaml; do
    sops updatekeys --yes "$f"
done

# 4. Add private key to GitHub Actions
gh secret set SOPS_AGE_KEY < ci-age-key.txt
rm ci-age-key.txt  # never store locally

# 5. CI pipeline uses:
#    env:
#      SOPS_AGE_KEY: ${{ secrets.SOPS_AGE_KEY }}
```

**SSOT for keys:** `.sops.yaml` is the registry of who can decrypt. Human key = workstation. CI key = GitHub Actions. Both are AGE public keys, visible in Git. Private keys never touch Git.

**Graceful degradation:** If SOPS is unavailable (e.g., local dev without AGE key), `toolkit sync --check` validates homepage + images (2/3) and warns about skipped OIDC hash check. CI with the AGE key validates 3/3.

### 4. Makefile dependency: `deploy-k8s` requires `apply-secrets`

Separate from drift detection, K8s Secrets from SOPS must be applied before deploying manifests. `apply-secrets` is now a prerequisite of `deploy-k8s`:

```makefile
deploy-k8s: apply-secrets validate-sync
    @$(TOOLKIT) infra k8s deploy --env $(ENV)
```

This prevents the class of bug where a new secret key is referenced in a manifest but never applied to the cluster (e.g., Gitea `OIDC_CLIENT_SECRET` incident, 2026-03-27).

## Alternatives Considered

### A. Generate at deploy time (never commit)
Generate manifests to a tmpdir and apply from there. No drift possible.

**Rejected:** Breaks GitOps principle (Git must contain the deployed state). PRs lose visibility into what changes in the cluster. Two deploys from the same commit could diverge if common.yaml changed between them.

### B. Degradation graceful without CI key
Skip SOPS-dependent checks in CI, only enforce locally.

**Rejected (as sole strategy):** CI is the enforcement point. If CI can't validate, drift slips through PRs. Local-only validation depends on developer discipline. The CI AGE key solves this properly.

### C. KMS-based SOPS (AWS KMS)
Replace AGE keys with AWS KMS. CI authenticates via OIDC (GitHub Actions → IAM Role). Zero static keys.

**Deferred:** Correct long-term evolution (especially with AWS hub already in place), but premature for current scale. AGE multi-recipient is sufficient. Migration path: swap `.sops.yaml` key_groups from AGE to KMS when ready — SOPS supports both, no code changes needed.

### D. External Secrets Operator / Vault
Remove secrets from Git entirely. K8s pulls from Vault at runtime.

**Deferred:** Architectural shift beyond current scope. Tracked as a future evolution in ADR-026 (IDP Evolution).

## Implementation Plan

### Phase 1: `toolkit sync` CLI + `--check` mode
1. Create `toolkit/cli/sync.py` — unified CLI wrapping the three scripts
2. Add `--check` flag: generate to memory, compare with file on disk, exit 1 on diff
3. Conditional SOPS: try decrypt, skip with warning if unavailable
4. Makefile: add `validate-sync` target, wire into `check` and `deploy-k8s`
5. Unit tests for the check logic

### Phase 2: CI AGE key
1. Generate CI AGE keypair
2. Add public key to `.sops.yaml` as second recipient
3. Re-encrypt all SOPS files with `sops updatekeys`
4. Store private key as GitHub Actions secret `SOPS_AGE_KEY`
5. Update CI pipeline to set `SOPS_AGE_KEY` env var
6. Validate: CI runs `make check` with full SOPS access

### Phase 3: Cleanup
1. Deprecate direct script invocation (`python toolkit/scripts/sync_*.py`)
2. Update help text and documentation
3. Add `toolkit sync` to `make help` output

## Consequences

**Positive:**
- Zero drift between SSOT and tracked manifests — CI enforces on every PR
- Deploy can never apply stale manifests — pre-deploy validation blocks it
- Single CLI interface (`toolkit sync`) replaces three ad-hoc scripts
- SOPS fully validated in CI — no blind spots

**Negative:**
- CI AGE key is a secret to manage (rotation, access control)
- `make check` takes slightly longer (sync validation adds ~2s)
- Re-encrypting SOPS files after adding CI recipient is a one-time chore

**Risks:**
- If CI AGE key leaks, attacker can decrypt all SOPS secrets. Mitigation: GitHub Actions secrets are encrypted at rest, audit log tracks access, key can be rotated and old one revoked via `sops updatekeys`
- KMS migration later requires re-encrypting all files again. Mitigation: SOPS `updatekeys` makes this mechanical, not risky
