---
id: "AI-007-ollama-retirement"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-09"
issue: "kubelab#905"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# AI-007: Ollama retirement

> **Naming**: file lives at `<repo>/specs/<feature-id>/proposal.md`. `<feature-id>` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #905: AI-007: retire Ollama from ace2 (ADR-058 PR-2, multi-SSOT sweep) -->

[AGENT-DRAFT — review before archive]

ADR-058 justified retiring Ollama by "ace2's 12GB are effectively idle". **That argument expired when PR-1 shipped**: ace2 is now the dev-node, no longer idle, and Ollama coexists without cost (`keep_alive` does not consume at rest). The reason to retire it today is different and sharper — `ollama.kubelab.live` is a **public** endpoint (Cloudflare DNS record, prod API key in SOPS, Traefik middleware) whose backend is a node that is powered off most of the time. That is standing attack surface plus an Uptime Kuma monitor that reports on something nobody consumes, and 38 files of SSOT that every future refactor must keep coherent for a capability with zero consumers (`/v1/llm` per ADR-029 is decided but unbuilt).

If this is not shipped, nothing breaks — which is precisely the problem. It persists as quiet, unowned surface, and ADR-028/029 keep describing a local-inference capability that does not exist in practice.

## What

[AGENT-DRAFT — review before archive]

This is a **subtractive** change, so most of the "what" is absence. Observable after the PR:

1. `ollama.kubelab.live` no longer resolves — the Cloudflare record is destroyed via Terraform, and the prod IngressRoute, external Service/EndpointSlice, throttle and `api-key-ollama` middleware are gone from the cluster.
2. `make validate-sync` passes with no Ollama reference anywhere in generated output (ConfigMaps, homepage `custom.js`, image pins) — the drift gate becomes the completeness check for the sweep.
3. `toolkit secrets audit` reports no Ollama key in any environment, and `apps.services.ai.ollama.api_key` is **unset in SOPS**, not merely de-registered from `SECRET_CATALOG`.
4. ADR-028 and ADR-029 carry an explicit amendment recording that local inference is deferred until a GPU node exists, with OpenRouter as the interim path.

**Open for Manu:** whether anything positive is also required — e.g. a documented return path for when a GPU node arrives. Drafted as "no": the ADR amendment already states the deferral, and a speculative re-add runbook would rot.

## Out of scope

[AGENT-DRAFT — review before archive]

- **Building `/v1/llm` or any OpenRouter-backed replacement.** ADR-029 stays deferred; this PR removes a capability, it does not substitute one.
- **Removing Ollama from Beelink.** Already done. `beelink_services` keeps its cleanup tasks — only their stated rationale ("moved to ace2") expires.
- **ANSIBLE-030 (#858) D6 housekeeping timers.** Separate ADR-058 item, separate ticket.
- **The `dev_node` role itself.** Only its header comments about coexisting with `ace2_services` change.

## Risks / open questions

[AGENT-DRAFT — review before archive]

1. **Ordering is load-bearing, and prod self-heals.** Argo CD prod runs `selfHeal: true` (ADR-037), so merging the manifest deletion prunes prod the moment it syncs. If the Cloudflare record still exists at that point, `ollama.kubelab.live` resolves to an edge with no backend. **MUST be resolved before code:** decide the order — Terraform DNS destroy first, then manifests, or a single window.
2. **The API key must be unset, not just de-registered.** Dropping it from `SECRET_CATALOG` while leaving the value in `prod.enc.yaml` creates a secret no audit can see. This repo already carries exactly that debt (`users_admin_password_hash` orphaned in `staging.enc.yaml`), so it is a demonstrated failure mode, not a hypothetical.
3. **Uptime Kuma monitors a service that will stop existing.** Left in place it alerts forever; the monitor lives in `infra/config/uptime-kuma/monitors.json` on RPi3, outside the K8s sweep.
4. **e2e coupling.** `test_ollama_public.py` is a whole module, and `expectations.py` / `conftest.py` also carry entries. Deleting the module alone leaves dangling expectations.
5. **Terraform touches live public DNS.** Requires a reviewed `plan` showing exactly one record destroyed and nothing else — this is the only surface in the sweep that is not recoverable by re-running a generator.

## Acceptance criteria

[AGENT-DRAFT — review before archive]

- [ ] A tree-wide search for `ollama` (case-insensitive, excluding `docs/`, `specs/`, `CHANGELOG.md`) returns **zero** matches in tracked files.
- [ ] `make validate-sync` exits 0 with no Ollama reference in any generated artifact.
- [ ] `toolkit secrets audit --env prod` shows no Ollama entry, and decrypting `prod.enc.yaml` confirms `apps.services.ai.ollama` is absent — proving the value was unset, not orphaned.
- [ ] `terraform plan` for the DNS module shows exactly one resource destroyed (the `ollama` record) and no other change.
- [ ] `make test` and the prod e2e suite pass with no Ollama module, no skipped Ollama expectation, and no new failures.
- [ ] ADR-028 and ADR-029 each carry an amendment note referencing AI-007 and #905.

## References

- Bitácora board: the GitHub issue / Project item tracking this spec (see the `issue:` frontmatter field)
- Related ADR: `<repo>/docs/adr/adr-XXX.md` (if any)
- Related patterns: `00_meta/patterns/<pattern>.md` (if any)
