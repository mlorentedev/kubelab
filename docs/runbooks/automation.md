---
id: "kubelab-runbook-automation"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-08"
owner: manu
---

# Automation

## Overview

Run automated tasks for KubeLab: validate configuration, generate configs from templates, perform audits (config drift, broken links, Traefik config), run security scans, and produce operational summaries.

## Prerequisites

- Access to the `mlorentedev/kubelab` repository
- `gh` CLI installed and authenticated
- Git with Conventional Commits history
- Toolkit installed (`make setup`)
- SOPS + age keys for secret decryption

## Steps

### 1. Configuration validation

Validate that all configuration values and compose overlays resolve correctly:

```bash
# Validate configuration integrity
make validate

# Generate configs for a specific environment
ENVIRONMENT=dev toolkit config generate
ENVIRONMENT=staging toolkit config generate
ENVIRONMENT=prod toolkit config generate
```

Configuration is sourced from `infra/config/values/*.yaml` (common.yaml + environment overlay) and secrets from `infra/config/secrets/{env}.enc.yaml` (SOPS encrypted).

### 2. Configuration drift audit

Check that values files are consistent across environments:

```bash
# Compare config keys across environments
diff <(grep -E '^\w' infra/config/values/dev.yaml | sort) \
     <(grep -E '^\w' infra/config/values/staging.yaml | sort)

diff <(grep -E '^\w' infra/config/values/staging.yaml | sort) \
     <(grep -E '^\w' infra/config/values/prod.yaml | sort)
```

### 3. Compose overlay validation

Verify that compose.base.yml + compose.{env}.yml resolve correctly for each stack:

```bash
# Validate a specific app stack
docker compose -f infra/stacks/apps/web/compose.base.yml \
  -f infra/stacks/apps/web/compose.dev.yml config --quiet

# Validate a specific service stack
docker compose -f infra/stacks/services/observability/grafana/compose.base.yml \
  -f infra/stacks/services/observability/grafana/compose.dev.yml config --quiet
```

### 4. Common documentation tasks

```text
# Normalize READMEs
Task: Normalize and improve README.md for module {{path}}.
Output: unified diff only

# Generate indexes
Task: Sync READMEs to wiki/docs and generate indexes with tables.
Output: markdown in docs/AUTOMATION/indexes

# Generate CHANGELOG
Task: Generate CHANGELOG from Conventional Commits since last tag.
Output: docs/AUTOMATION/changelogs/CHANGELOG-<date>.md
```

### 5. Security scans

```text
# Secret scanning
Task: Run secret scan and review .gitignore coverage.
       Verify no plaintext secrets outside infra/config/secrets/*.enc.yaml.
Output: docs/AUTOMATION/security/secrets-scan.md

# License check
Task: Check license headers in .go, .sh, .astro files.
Output: docs/AUTOMATION/reports/license-check.md

# CI workflow audit
Task: Audit GitHub Actions workflows (permissions, tags, cache).
Output: docs/AUTOMATION/reports/ci-audit.md
```

### 6. Maintenance scripts

```text
# Service inventory
Task: Extract services from infra/stacks/ compose overlay files.
Output: docs/AUTOMATION/indexes/services-inventory.md

# Makefile targets
Task: Parse Makefiles and generate documentation of targets.
Output: docs/AUTOMATION/indexes/make-targets.md

# Ansible health
Task: Validate Ansible playbooks syntax and variables.
Output: docs/AUTOMATION/reports/ansible-health.md
```

### 7. Summaries and ADRs

```text
# Weekly Ops Digest
Task: Summarize weekly ops (PRs, issues, docs, next steps).
Output: docs/AUTOMATION/digests/ops-digest-YYYY-WW.md

# ADRs (stored in vault, not repo)
Task: Create ADR with context, decision, consequences.
Output: ~/Projects/knowledge/10_projects/kubelab/adrs/ADR-<n>-<slug>.md
```

## Verification

Check the generated output file exists and has non-empty content:

```bash
ls -la docs/AUTOMATION/<subfolder>/<output-file>.md
```

For configuration validation, a zero exit code confirms success:

```bash
make validate && echo "OK"
```

For idempotency verification, run the same task twice and confirm the diff is empty.

## Rollback

Automation outputs are generated files. To rollback, discard the generated file:

```bash
git checkout -- docs/AUTOMATION/<subfolder>/<output-file>.md
```

Or delete the file if it was newly created:

```bash
rm docs/AUTOMATION/<subfolder>/<output-file>.md
```

For configuration generation rollback, regenerate from the previous commit:

```bash
git stash
ENVIRONMENT=dev toolkit config generate
git stash pop
```

## Last tested

2026-02-09
