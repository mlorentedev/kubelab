---
tags: [spec, tasks, templates]
created: "2026-08-09"
---

# Tasks - AI-007-ollama-retirement

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers:** `[P]` = safe to run in parallel; `[AC<n>]` = helps satisfy acceptance criterion #`<n>` from `proposal.md`.
>
> **This spec's sections are not interchangeable.** They are ordered by *what triggers the surface*, per the RESOLVED sequence in `proposal.md`. Argo CD is the only actor that fires by itself, so every operator-triggered removal happens before the merge that lets it prune. Reordering across sections breaks the guarantee that no intermediate state is ever "reachable and broken".

## Setup

- [x] Branch created from main: `feat/AI-007-ollama-retirement`
- [ ] `proposal.md` acceptance criteria confirmed by Manu (currently `[AGENT-DRAFT]`)
- [ ] Risks 2 and 3 answered — both are task-level/scope, neither blocks PR-A

## Implementation

### PR-A — spec + public DNS (merging is inert; the apply is the first real act)

- [ ] [AC4] Remove the `ollama` record from `infra/terraform/dns/services.json`
- [ ] [AC4] `make tf-dns-plan` — confirm **exactly one** resource destroyed and no other change
- [ ] Open PR-A; merge only on explicit authorization (public DNS)
- [ ] [AC4] `make tf-dns-apply`, then confirm `ollama.kubelab.live` no longer resolves

### Manual window — requires ace2 powered on; nothing here fires on merge

- [ ] [AC5] Delete the live `Middleware/api-key-ollama` **and its Secret** from prod. Argo never tracked them (ADR-035 Stage 1, applied over stdin), so no merge will ever remove them
- [ ] [P] Remove Ollama from ace2: strip it from the `ace2_services` role/compose, then `make provision NODE=ace2 ENV=staging`
- [ ] Remove the Uptime Kuma monitor from `infra/config/uptime-kuma/monitors.json` and deploy to RPi3 — **same window as the container**, since the monitor targets the Tailscale IP and only trips when the container dies

### PR-B — the sweep (merging fires the Argo prune)

- [ ] [AC3] `toolkit secrets unset` the prod `apps.services.ai.ollama.api_key` **first**, then drop its `SECRET_CATALOG` entry. The reverse order leaves a value no audit can see
- [ ] [AC1] [AC5] Delete `infra/k8s/overlays/prod/middlewares/api-key.yaml.tpl` and its `MIDDLEWARE_CATALOG` entry
- [ ] [AC1] Delete `infra/k8s/base/external/ollama.yaml` and `infra/k8s/overlays/prod/ollama-throttle.yaml`; drop the references from both `kustomization.yaml` files and prod `patches.yaml`
- [ ] [AC1] Remove `apps.services.ai.ollama.*` from `common.yaml` and `staging.yaml`
- [ ] [AC1] Drop `ollama` from `SERVICES_AI` in `toolkit/config/constants.py`
- [ ] [AC1] Remove the DNS entries from `deploy-dns.yml`, `provision-rpi4.yml` and the CoreDNS `Corefile.j2`
- [ ] [AC2] Regenerate the homepage config; `make validate-sync` green
- [ ] [AC6] Delete `tests/e2e/test_ollama_public.py`; clean the entries in `expectations.py`, `conftest.py` and `tests/test_k8s_middlewares.py`
- [ ] [AC1] Correct the rationale comments that outlive the service: `dev_node/tasks/main.yml` (coexistence header), `beelink_services` + `provision-bee.yml` ("moved to ace2"), `headscale/policy.hujson.j2` (the `tag:hermes → vps:443` justification — the **rule stays**, it also covers Gitea)
- [ ] [AC7] Amend ADR-028 and ADR-029; fold in the two `CLAUDE.md` doc-drift fixes named in ADR-058 D4
- [ ] [AC8] Delete `docs/runbooks/ollama-api-key-rotation.md` — a 118-line runbook for a service that will not exist
- [ ] [AC8] Clear the present-tense claims from `docs/architecture/{service-catalog,architecture-overview}.md`, `docs/runbooks/{monitoring,operations,dns-homelab,hardware-setup,energy-consumption,non-admin-workstation-access}.md` and `docs/troubleshooting/docker-containers.md`
- [ ] [AC8] **Do NOT touch** the other 15 ADRs, `docs/audits/*`, `current-state-2026-03-22.md`, or `components/kubelab-*.md`. They are historical records or unbuilt-product design positions; erasing Ollama from them would falsify the record. Verify by re-reading, not by grepping them clean
- [ ] [AC1] Run the survivor check and confirm only the deliberate matches remain

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` following [[pattern-feature-list-as-primitive]]. Each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state`, and `evidence`.

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where `features.json` contains `passing` entries with empty `evidence`.

**Note on f5:** it is the only probe that queries the live cluster rather than the repo. That is deliberate — the objects it checks were never in git, so a repo-only check would report success while they keep running.
