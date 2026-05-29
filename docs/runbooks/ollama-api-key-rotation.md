---
id: ollama-api-key-rotation
type: runbook
status: active
created: "2026-05-23"
---

# Ollama API Key Rotation

> Runbook for rotating the X-API-Key that gates `ollama.kubelab.live` (ADR-035 Stage 1, AI-001). Single shared key model; per-user keys deferred to SEC-AI-001 follow-up.

## When to rotate

- **Periodic**: every 90 days (calendar reminder).
- **On suspicion**: any logged 200 from an unexpected source IP, unusual usage spikes in Grafana, key shared outside trusted clients.
- **On termination**: client that held the key no longer needs access.
- **After incident**: any key disclosure (commit-leak, log-leak, shoulder-surf).

## Mechanism recap

- Key lives encrypted at `apps.services.ai.ollama.api_key` in `infra/config/secrets/prod.enc.yaml` (SOPS / age).
- Toolkit `apply_middleware_secrets()` reads SOPS → renders generic template `infra/k8s/overlays/prod/middlewares/api-key.yaml.tpl` → writes audit copy to gitignored `.rendered/` → `kubectl apply -f -` via stdin. Plaintext **never on persistent disk** outside the gitignored audit dir.
- Plugin `dtomlinson91/traefik-api-key-middleware` v0.1.2 hot-picks new key on next request (no Traefik restart needed — it watches the Middleware CRD).
- Traefik returns HTTP 403 for any rejected request (per plugin README, unconditional — no 401).

## Rotation steps

> All commands run from a clean kubelab worktree on master.

### 1. Generate a fresh key

```bash
NEW_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
echo "len=${#NEW_KEY}, prefix=${NEW_KEY:0:6}..."   # confirm 43 chars
```

### 2. Write to SOPS (overwrites the old value)

```bash
poetry run toolkit secrets set apps.services.ai.ollama.api_key "$NEW_KEY" --env prod
```

This re-encrypts `prod.enc.yaml` with age. Only your workstation's age key can decrypt.

### 3. Apply to the cluster

```bash
make apply-middleware-secrets ENV=prod
```

What happens:
- Toolkit reads new value from SOPS.
- Renders Middleware CRD with new key.
- `kubectl apply` updates `middleware.traefik.io/api-key-ollama` in `kubelab` namespace.
- Traefik plugin hot-picks the new key within ~1s (CRD watch).

### 4. Smoke verify

```bash
# Wait ~5s for plugin to pick up the new key
sleep 5

# Old key MUST now return 403 (assumes you saved OLD_KEY before step 2)
curl -sk -o /dev/null -w "old key: %{http_code}\n" \
  -H "X-API-Key: $OLD_KEY" https://ollama.kubelab.live/api/tags
# Expected: HTTP 403

# New key MUST return 200
curl -sk -o /dev/null -w "new key: %{http_code}\n" \
  -H "X-API-Key: $NEW_KEY" https://ollama.kubelab.live/api/tags
# Expected: HTTP 200
```

If old key still returns 200 after >10s, force middleware re-apply: `make apply-middleware-secrets ENV=prod` again. Plugin will pick up on next CRD reconciliation.

### 5. Commit the SOPS diff (audit trail)

```bash
git checkout -b chore/rotate-ollama-api-key-$(date +%Y%m%d)
git add infra/config/secrets/prod.enc.yaml
git commit -m "chore(secrets): rotate ollama api_key (scheduled / incident YYYY-MM-DD)"
git push -u origin chore/rotate-ollama-api-key-$(date +%Y%m%d)
gh pr create --base master --title "chore(secrets): rotate ollama api_key" \
  --body "Routine rotation per runbook ollama-api-key-rotation.md. Old key invalidated $(date -u +%FT%TZ). Active key prefix: ${NEW_KEY:0:6}..."
```

Diff is encrypted ciphertext only — safe to push. Merge after CI passes.

### 6. Distribute the new key

- Update all downstream clients (OpenClaw config, scripts, CI secrets, browser extensions).
- For scripts: `gh secret set OLLAMA_API_KEY -b "$NEW_KEY"` if any GH Action uses it.
- For local dev: store in workstation keychain (NOT shell history).
- For the future OpenClaw integration (WEBUI-001): update its compose env when implemented.

## Rollback

If new key causes outage (extremely unlikely — plugin is stateless):

1. Re-run `toolkit secrets set apps.services.ai.ollama.api_key "$OLD_KEY" --env prod`.
2. `make apply-middleware-secrets ENV=prod`.
3. Smoke verify with OLD_KEY → 200.
4. Investigate root cause before retrying.

## What NOT to do

- **Do not** `kubectl edit middleware api-key-ollama` directly — toolkit will overwrite on next deploy chain.
- **Do not** commit the plaintext key anywhere — only the encrypted SOPS file.
- **Do not** rotate on Friday afternoon if you don't have time to validate.
- **Do not** skip the smoke step — silent failures are how outages start.

## Related

- [adr-035-api-auth-strategy](../adr/adr-035-api-auth-strategy.md) — Why X-API-Key was chosen.
- `feedback_always_toolkit_makefile.md` — Why we go through `toolkit secrets set` instead of raw `sops edit`.
- SEC-AI-001 ticket — When this single-key model evolves to per-user keys, this runbook gets a "rotate one key in N" appendix.
- SEC-AI-002 ticket — `kubectl apply --server-side` will eliminate the duplicate plaintext key in the `last-applied-configuration` annotation. Until then, after rotation, the old key remains visible in that annotation for one cycle.
- ANSIBLE-025 (closed by PR #199) — host networking fix so ace2 ollama doesn't die during the rotation window if Tailscale flaps.
