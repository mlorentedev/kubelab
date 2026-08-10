---
id: "AI-007-ollama-retirement"
type: spec
status: archived # draft | implementing | verifying | archived
created: "2026-08-09"
issue: "kubelab#905"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# AI-007: Ollama retirement

> ADR-058 PR-2. Retires Ollama across 38 SSOT surfaces, ordered by **what triggers
> each surface** rather than by file type — Argo CD is the only actor that fires by
> itself, so it goes last and the ordering is enforced by merge order.

## Why

<!-- from issue #905: AI-007: retire Ollama from ace2 (ADR-058 PR-2, multi-SSOT sweep) -->

ADR-058 justified retiring Ollama by "ace2's 12GB are effectively idle". **That argument expired when PR-1 shipped**: ace2 is now the dev-node, no longer idle, and Ollama coexists without cost (`keep_alive` does not consume at rest). The reason to retire it today is different and sharper — `ollama.kubelab.live` is a **public** endpoint (Cloudflare DNS record, prod API key in SOPS, Traefik middleware) whose backend is a node that is powered off most of the time. That is standing attack surface plus an Uptime Kuma monitor that reports on something nobody consumes, and 38 files of SSOT that every future refactor must keep coherent for a capability with zero consumers (`/v1/llm` per ADR-029 is decided but unbuilt).

If this is not shipped, nothing breaks — which is precisely the problem. It persists as quiet, unowned surface, and ADR-028/029 keep describing a local-inference capability that does not exist in practice.

## What

This is a **subtractive** change, so most of the "what" is absence. Observable after the PR:

1. `ollama.kubelab.live` no longer resolves — the Cloudflare record is destroyed via Terraform, and the prod IngressRoute, external Service/EndpointSlice, throttle and `api-key-ollama` middleware are gone from the cluster.
2. `make validate-sync` passes with no Ollama reference anywhere in generated output (ConfigMaps, homepage `custom.js`, image pins) — the drift gate becomes the completeness check for the sweep.
3. `toolkit secrets audit` reports no Ollama key in any environment, and `apps.services.ai.ollama.api_key` is **unset in SOPS**, not merely de-registered from `SECRET_CATALOG`.
4. ADR-028 and ADR-029 carry an explicit amendment recording that local inference is deferred until a GPU node exists, with OpenRouter as the interim path.

**Open for Manu:** whether anything positive is also required — e.g. a documented return path for when a GPU node arrives. Drafted as "no": the ADR amendment already states the deferral, and a speculative re-add runbook would rot.

## Out of scope

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

1. **Argo will not prune the `api-key-ollama` Middleware — it never tracked it.** Per ADR-035 Stage 1 the Middleware is deliberately outside Kustomize/git: the toolkit renders it from `infra/k8s/overlays/prod/middlewares/api-key.yaml.tpl` and applies it over stdin. Verified — no `kustomization.yaml` references it. Deleting the `.tpl` and the `MIDDLEWARE_CATALOG` entry therefore leaves the live object running in prod. The sweep needs an explicit live-object deletion step; a git-only sweep looks complete and is not. **Verified 2026-08-09 and one detail corrected:** there is no backing Secret — the API key is inline in the Middleware spec, so the live object *is* the plaintext-at-rest surface, and deleting it is what removes the key from etcd. The toolkit has an apply path and **no delete path**, so this step was a supervised one-off; the gap is filed separately.
2. **RESOLVED 2026-08-09 — the `api-key:` plugin stays registered** in `traefik-helmconfig.yaml.j2`. Only the Ollama-specific Middleware, its `.tpl` and its `MIDDLEWARE_CATALOG` entry go. The restart cost was raised and dismissed (development phase, restarting prod Traefik is acceptable), so the binding reason is the other one — and the original draft stated it wrongly. It said "ADR-035 Stage 2 may want it"; Stage 2 in fact **replaces** the plugin with an Authelia ForwardAuth introspection middleware. The real reason is **Stage 1**: ADR-035's "Anchored decisions" table names two further consumers of *this same plugin* — `widget-proxy` (DT-004, "pending spec impl") and `Pollex public` (AI-004, "pending"), the latter live as #914. Deregistering now means re-registering for both.
3. **RESOLVED 2026-08-09 — `beelink_services` keeps its cleanup tasks.** They are idempotent, they guard a re-imaged node, and only their stated rationale ("moved to ace2") expires. Correct the comment, keep the tasks.
4. **Landmine, do not sweep on the string `api-key`.** The `api-key` key in `infra/k8s/overlays/{staging,prod}/secrets.yaml` belongs to **CrowdSec**, not Ollama — a naive grep-and-delete over that token breaks the bouncer. Match on `ollama`, never on `api-key`.
5. **`infra/k8s/overlays/prod/middlewares/.rendered/api-key-ollama.yaml` is untracked and holds the real prod key.** Per ADR-035 Stage 1 the `.rendered/` directory is a gitignored audit copy, so it is invisible to every git-based check in this spec — the same failure mode as the live Middleware in Risk 1, in a second place. It must be deleted explicitly on the operator's machine.
6. **The API key must be unset, not just de-registered.** Dropping it from `SECRET_CATALOG` while leaving the value in `prod.enc.yaml` creates a secret no audit can see. This repo already carries exactly that debt (`users_admin_password_hash` orphaned in `staging.enc.yaml`), so it is a demonstrated failure mode, not a hypothetical.
7. **The Uptime Kuma monitor must be removed BEFORE the container, and it was never ace2-gated.** It targets `http://100.64.0.5:11434/api/tags` — the Tailscale IP directly, **not** the public FQDN — so destroying the DNS record does not trip it; destroying the container does. With `interval: 300`, `maxretries: 3` and `notificationIDList: [1]`, doing the container first lights a fuse to a real notification, while doing the monitor first costs nothing: a monitor watching a service you are about to delete has no diagnostic value. The original draft put it "in the same window as the container", which is necessary but not sufficient — order inside the window is what decides whether it pages. It also does not need ace2 at all: it lives in `infra/config/uptime-kuma/monitors.json` and deploys to **RPi3, which is always-on**, via `make monitoring-apply`. It is outside both the K8s sweep and the Argo prune.
8. **e2e coupling.** `test_ollama_public.py` is a whole module, and `expectations.py` / `conftest.py` also carry entries. Deleting the module alone leaves dangling expectations.
9. **Terraform touches live public DNS.** Requires a reviewed `plan` showing exactly one record destroyed and nothing else — the only surface in the sweep not recoverable by re-running a generator. **Done 2026-08-09**: plan showed `0 to add, 0 to change, 1 to destroy`, applied, and `ollama.kubelab.live` no longer resolves at the authoritative NS.

## Acceptance criteria

**CONFIRMED by Manu 2026-08-09.** All eight stood as written and all eight are met.
Two of them — AC1 and AC8 — were **rewritten during implementation** because as
originally phrased they could never have passed; the reasoning is kept inline below
rather than silently corrected, since it is the most transferable thing this spec
produced. The narrative sections above (Why / What / Out of scope / Risks) carried
agent-draft review markers throughout implementation; they were reviewed and cleared
at archive, with Risks 2, 3 and 9 answered by Manu in-session and recorded in place.

- [x] **AC1** — No **live wiring** for Ollama survives in tracked files. ✓ 2026-08-09.

  **Rewritten during implementation, because the original was unsatisfiable.** It asked for a case-insensitive search for the *word* `ollama` to match only an allowlist of paths. That check can never pass, for two independent reasons discovered while running it:
  - **`videollamada`** — the Calendly URL in `common.yaml`, and therefore both generated ConfigMaps — contains the substring `ollama`. Nothing about the retirement can remove it.
  - After a complete sweep, **every remaining match is either the ace2 teardown or an explanation of the retirement**. The teardown in `dev_node` must name `/opt/ollama` and port `11434` to remove them; the comments say things like "empty since AI-007 retired Ollama", and deleting them would leave an empty catalog with no explanation.

  So the criterion now asserts the **identifiers that would make the service reachable** — `ollama.kubelab.live`, `apps.services.ai.ollama`, `api-key-ollama`, `ollama/ollama`, `:11434` — rather than the word. Prose about a retirement never matches an identifier that would make it live, so the check is stable rather than needing a growing allowlist. Deliberate survivors: `docs/`, `specs/`, `CHANGELOG.md`, `CLAUDE.md`, the `dev_node` teardown, and the `beelink_services` / `provision-bee.yml` cleanup kept by Out of scope.
- [x] **AC2** — `make validate-sync` exits 0, and no generated artifact (ConfigMaps, homepage `custom.js`, image pins) contains an Ollama reference. ✓ 2026-08-09 (f2). The generated output was a **second, independent read** of the sweep and earned its place: the first pass looked clean in source and `custom.js` still carried four homepage references (topology tables, DNS diagram).
- [x] **AC3** — `toolkit secrets audit --env prod` reports no Ollama entry, and decrypting `prod.enc.yaml` shows `apps.services.ai.ollama` absent — proving the value was unset, not merely de-registered into an orphan. ✓ 2026-08-09 (f3). Unset **before** the `SECRET_CATALOG` entry was dropped; the reverse order is what produced this repo's existing orphan (#910).
- [x] **AC4** — `make tf-dns-plan` shows exactly one resource destroyed (the `ollama` record) and no other change; after apply, `ollama.kubelab.live` does not resolve. ✓ 2026-08-09 (f4) — plan `0 to add, 0 to change, 1 to destroy`, applied, NXDOMAIN at the authoritative NS with `api.kubelab.live` still resolving.
- [x] **AC5** — In prod, no `Middleware/api-key-ollama` remains — the out-of-band object Argo never tracked is gone, verified against the live cluster rather than against git. ✓ 2026-08-09. **Correction:** there is no backing Secret and there never was. The API key is inline in the Middleware spec (`keys: [${API_KEY}]`), so deleting the Middleware is what removes the plaintext key from etcd. The Secret named in ADR-035 belongs to the CrowdSec bouncer, a different object.
- [x] **AC6** — `make test` and the prod e2e suite pass with no Ollama module, no skipped Ollama expectation, and no new failures. ✓ 2026-08-09 (f6) — **393 passed, 98 deselected**. 394 before; the net −1 is two ollama-coupled catalog tests replaced by one generic invariant that no longer depends on which services are registered.
- [x] **AC7** — ADR-028 and ADR-029 each carry an amendment note referencing AI-007 and #905. ✓ 2026-08-09 (f7) — amended, not superseded: ADR-029's local-inference tier is deferred until a GPU node exists, ADR-028 records ace2's new role. No speculative re-add runbook, deliberately.
- [x] **AC8** — No operational document still describes Ollama as a running service, and `docs/runbooks/ollama-api-key-rotation.md` (118 lines) is deleted. ✓ 2026-08-09. Checked by live wiring rather than by word, for the same reason as AC1: `docs/runbooks/hardware-setup.md` deliberately keeps its 2026-02-19 setup log under an explicit "Historical record" banner — it documents how the Beelink was *built*, which remains true — while its verification `curl`s were removed, because a copy-pasteable probe for a dead endpoint is worse than none.

  **Deliberate survivors, untouched by AC8** — the same allowlist discipline AC1 needs, for the same reason:
  - **The 17 ADRs.** An ADR records a decision taken at a time; rewriting it to remove Ollama falsifies the record. ADR-035 *did* use Ollama as its first consumer. Only ADR-028 and ADR-029 change, and only by the amendment notes in AC7 — "amended, not superseded", per ADR-058 itself.
  - **`docs/audits/*` and `docs/architecture/current-state-2026-03-22.md`** — dated snapshots. Same argument as ADRs.
  - **`docs/architecture/components/kubelab-*.md`** — design positions for unbuilt L1 products, not claims about running infrastructure.

## References

- Bitácora board: kubelab#905
- PRs: **#915** (spec + DNS record removal, PR-A), **#919** (AC8 documentation surface), **#935** (the sweep, PR-B — merging fired the Argo prune)
- Amended ADRs: `docs/adr/adr-028-operational-topology.md`, `docs/adr/adr-029-intelligence-layer.md`
- Parent decision: ADR-058 (ace2 repurposing, D4 splits PR-1/PR-2). Unchanged: ADR-035 (Stage 1 middleware injection — the `api-key:` plugin stays registered for DT-004 and AI-004/#914)
- Filed during implementation: **MON-003 (#925)**, **TOOL-025 (#926)**, **CI-GATE-007 (#933)**
- Lesson promoted at archive: `docs/lessons.md` — "A check that has never been observed failing is a claim in executable syntax"
- Related patterns: `00_meta/patterns/pattern-feature-list-as-primitive.md` (this spec's `features.json`)
