---
id: lesson-080-secrets-leaked-in-k8s-configmaps-blocklist-ap
type: lesson
status: active
created: "2026-02-28"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# Secrets leaked in K8s ConfigMaps — blocklist approach is fragile

**Context**: Reviewing the K8s overlays before B6 migration. Found real secrets committed in `infra/k8s/overlays/staging/configmaps.yaml`: Gmail app password, Beehiiv pub ID, Zoho client ID. Also `secrets.yaml` had real values instead of placeholders.

**Root cause**: The K8s generator uses `ConfigurationManager.get_env_vars()` which merges values YAML + SOPS decrypted secrets into a single flat dict. The generator filters secrets via a blocklist (`SECRET_PATTERNS`), but `PASS` was not in the list (only `PASSWORD`), so `EMAIL_PASS` leaked. Similarly, `CLIENT` and `ID` weren't blocked, so `ZOHO_CLIENT_ID` and `BEEHIIV_PUB_ID` leaked.

**Impact**: Gmail app password, API identifiers, and OAuth client IDs committed in plaintext to Git history. Requires credential rotation and git history cleanup.

**Fix applied**:
1. Added `PASS` and `CLIENT` to `SECRET_PATTERNS` in `constants.py`
2. Cleaned staging `configmaps.yaml` — removed all SOPS-sourced values
3. Replaced staging `secrets.yaml` real values with `REPLACE_WITH_SOPS_VALUE` placeholders (matching prod pattern)
4. Removed `secrets.yaml` from staging `kustomization.yaml` — toolkit-managed via `apply-secrets` (ADR-014)
5. Extended `api-secrets` mapping in `k8s_secrets.py` with all SOPS API keys (EMAIL_FROM, BEEHIIV_*, ZOHO_*)

**Rule**: Blocklists for secret filtering are inherently fragile — one missing pattern and secrets leak. Prefer:
1. **If a value comes from SOPS, it is a secret by definition** — never put it in a ConfigMap
2. Generated files that COULD contain secrets should be gitignored or reviewed before commit
3. `secrets.yaml` placeholders only — real values injected at deploy time via toolkit
4. Pre-commit hooks (gitleaks) are a safety net, not a guarantee — they match patterns, not intent

---
