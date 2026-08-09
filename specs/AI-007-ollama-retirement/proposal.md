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

## Retirement sequence — RESOLVED 2026-08-09

The 38 surfaces do not divide by file type. They divide by **what triggers them**:

| Actor | Surfaces | Fires |
|---|---|---|
| **Argo CD** | K8s manifests (IngressRoute, external Service/EndpointSlice, `ollama-throttle.yaml`) | **by itself, on merge** (`prune: true`, `selfHeal: true`) |
| **Operator** | Terraform public DNS, Ansible on ace2, Uptime Kuma monitor on RPi3, the out-of-band `api-key-ollama` Middleware | when run by hand |
| Nobody | toolkit catalogs, tests, homepage, docs, ADR amendments | when the code next runs |

Exactly one actor moves on its own, and it is the one that cannot be held back. **So Argo goes last.** Every operator-triggered surface is removed while the cluster still serves, so each intermediate state is *unreachable*, never *reachable and broken* — and each step reverts on its own (re-apply Terraform, re-run the provision).

The order is enforced by **merge order, not by a runbook step someone has to remember** — the principle ADR-058 D6 already applies to housekeeping ("automation, not willpower").

### Implementation split (2 PRs, linear deps)

| PR | Scope | Trigger semantics |
|----|-------|-------------------|
| **PR-A** (this spec + DNS) | `proposal.md` sequence + `tasks.md` + `features.json`, and the `ollama` record removed from `infra/terraform/dns/services.json` | Merging is inert — the record only dies on a manual `make tf-dns-apply`, the deliberate first act |
| **manual window** | `make provision NODE=ace2` (container gone), Uptime Kuma monitor removed, out-of-band Middleware + Secret deleted from prod | Needs ace2 powered on |
| **PR-B** (the sweep) | manifests, SOPS key, toolkit catalogs, tests, homepage, Ansible role, docs, ADR-028/029 amendments | Merging fires the Argo prune — safe, because by then nothing points at anything |

## Risks / open questions

[AGENT-DRAFT — review before archive]

1. **Argo will not prune the `api-key-ollama` Middleware — it never tracked it.** Per ADR-035 Stage 1 the Middleware is deliberately outside Kustomize/git: the toolkit renders it from `infra/k8s/overlays/prod/middlewares/api-key.yaml.tpl` and applies it over stdin. Verified — no `kustomization.yaml` references it. Deleting the `.tpl` and the `MIDDLEWARE_CATALOG` entry therefore leaves the live object **and its Secret** running in prod. The sweep needs an explicit live-object deletion step; a git-only sweep looks complete and is not.
2. **Open, task-level:** whether to also deregister the `api-key:` plugin from `traefik-helmconfig.yaml.j2`. That is an Ansible change implying a prod Traefik restart, and the plugin is generic rather than Ollama-specific. Drafted as "leave it" — ADR-035 Stage 2 may want it.
3. **Open, scope:** `beelink_services` keeps idempotent tasks that strip a bare-metal Ollama binary. They are harmless and guard a re-imaged node, so this spec keeps them and only corrects their stated rationale. Confirm that rather than full removal is wanted.
4. **The API key must be unset, not just de-registered.** Dropping it from `SECRET_CATALOG` while leaving the value in `prod.enc.yaml` creates a secret no audit can see. This repo already carries exactly that debt (`users_admin_password_hash` orphaned in `staging.enc.yaml`), so it is a demonstrated failure mode, not a hypothetical.
5. **Uptime Kuma monitors a service that will stop existing.** The monitor targets `http://100.64.0.5:11434/api/tags` — the Tailscale IP directly, **not** the public FQDN — so removing the DNS record does not trip it; removing the container does. It must therefore go in the same manual window as the container, or it pages. It lives in `infra/config/uptime-kuma/monitors.json` on RPi3, outside both the K8s sweep and the Argo prune.
6. **e2e coupling.** `test_ollama_public.py` is a whole module, and `expectations.py` / `conftest.py` also carry entries. Deleting the module alone leaves dangling expectations.
7. **Terraform touches live public DNS.** Requires a reviewed `plan` showing exactly one record destroyed and nothing else — the only surface in the sweep not recoverable by re-running a generator.

## Acceptance criteria

[AGENT-DRAFT — review before archive]

- [ ] **AC1** — A case-insensitive search for `ollama` across tracked files matches **only** the deliberate survivors: `docs/`, `specs/`, `CHANGELOG.md`, `CLAUDE.md`, and the `beelink_services` / `provision-bee.yml` legacy-cleanup tasks kept by Out of scope. No match anywhere else.
- [ ] **AC2** — `make validate-sync` exits 0, and no generated artifact (ConfigMaps, homepage `custom.js`, image pins) contains an Ollama reference.
- [ ] **AC3** — `toolkit secrets audit --env prod` reports no Ollama entry, and decrypting `prod.enc.yaml` shows `apps.services.ai.ollama` absent — proving the value was unset, not merely de-registered into an orphan.
- [ ] **AC4** — `make tf-dns-plan` shows exactly one resource destroyed (the `ollama` record) and no other change; after apply, `ollama.kubelab.live` does not resolve.
- [ ] **AC5** — In prod, no `Middleware/api-key-ollama` and no backing Secret remain — the out-of-band objects Argo never tracked are gone, verified against the live cluster rather than against git.
- [ ] **AC6** — `make test` and the prod e2e suite pass with no Ollama module, no skipped Ollama expectation, and no new failures.
- [ ] **AC7** — ADR-028 and ADR-029 each carry an amendment note referencing AI-007 and #905.
- [ ] **AC8** — No operational document still describes Ollama as a running service: `docs/runbooks/` and `docs/troubleshooting/` are clean, `docs/architecture/service-catalog.md` and `architecture-overview.md` are clean, and `docs/runbooks/ollama-api-key-rotation.md` (118 lines, a runbook for a service that will not exist) is deleted.

  **Deliberate survivors, untouched by AC8** — the same allowlist discipline AC1 needs, for the same reason:
  - **The 17 ADRs.** An ADR records a decision taken at a time; rewriting it to remove Ollama falsifies the record. ADR-035 *did* use Ollama as its first consumer. Only ADR-028 and ADR-029 change, and only by the amendment notes in AC7 — "amended, not superseded", per ADR-058 itself.
  - **`docs/audits/*` and `docs/architecture/current-state-2026-03-22.md`** — dated snapshots. Same argument as ADRs.
  - **`docs/architecture/components/kubelab-*.md`** — design positions for unbuilt L1 products, not claims about running infrastructure.

## References

- Bitácora board: the GitHub issue / Project item tracking this spec (see the `issue:` frontmatter field)
- Related ADR: `<repo>/docs/adr/adr-XXX.md` (if any)
- Related patterns: `00_meta/patterns/<pattern>.md` (if any)
