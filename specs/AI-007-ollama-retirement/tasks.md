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

- [x] Branch created from main: `feat/AI-007-ollama-sweep` ✓ 2026-08-09 (the earlier
      `feat/AI-007-ollama-retirement` was discarded — it had fallen behind master and a PR
      from it would have reverted #903, #911 and #913)
- [x] `proposal.md` acceptance criteria confirmed by Manu ✓ 2026-08-09 — all eight stand
- [x] Risks 2 and 3 answered ✓ 2026-08-09 — plugin **stays** registered (ADR-035 Stage 1 has
      two further anchored consumers, DT-004 and AI-004/#914); `beelink_services` cleanup
      tasks **stay**, only their rationale comment is corrected

## Implementation

### PR-A — spec + public DNS (merging is inert; the apply is the first real act)

- [x] [AC4] Remove the `ollama` record from `infra/terraform/dns/services.json` ✓ 2026-08-09
- [x] [AC4] `make tf-dns-plan` — confirm **exactly one** resource destroyed and no other change ✓ 2026-08-09 (`0 to add, 0 to change, 1 to destroy`)
- [x] Open PR-A; merge only on explicit authorization (public DNS) ✓ 2026-08-09 — #915, plus #919 for AC8
- [x] [AC4] `make tf-dns-apply`, then confirm `ollama.kubelab.live` no longer resolves ✓ 2026-08-09

### Manual window — nothing here fires on merge

> **The monitor goes FIRST and is not ace2-gated.** Only the container and the live cluster
> objects need ace2 powered on. Removing the monitor after the container lights a fuse to a
> real notification (`interval: 300`, `maxretries: 3`, `notificationIDList: [1]`); removing it
> first costs nothing. See Risk 7.

- [x] Remove the Uptime Kuma monitor from `infra/config/uptime-kuma/monitors.json` and deploy with `make monitoring-apply` ✓ 2026-08-09 — 31 live monitors, 0 duplicates, no Ollama. The apply's own log claimed "Removed 32 (32 remaining)" and proceeded anyway; the result was correct but the check is a race, filed as MON-003 (#925)
- [x] [AC5] Delete the live `Middleware/api-key-ollama` from prod ✓ 2026-08-09 — supervised one-off, authorized. Argo never tracked it (ADR-035 Stage 1, applied over stdin), so no merge would ever have removed it. **There was no backing Secret**: the key is inline in the Middleware spec, so this deletion is what took the plaintext key out of etcd. The toolkit has an apply path and no delete path — gap filed separately. Edge smoke after: api and auth both 200
- [x] [AC5] Delete the untracked local render `infra/k8s/overlays/prod/middlewares/.rendered/api-key-ollama.yaml` ✓ 2026-08-09 — held the real prod key and was invisible to every git-based check here (Risk 5)
- [x] [P] Remove Ollama from ace2 ✓ 2026-08-09. **Scope was larger than this line implied**: `ace2_services` was not a role containing Ollama, it *was* the Ollama role (single service in its compose, every task deploying it or cleaning up the MinIO/GH-Runner stack it replaced), so it was deleted rather than edited and ace2 is now a pure dev-node. Because Ansible is additive, deleting a role does not undo its work — the teardown was moved into `dev_node`, the role that now owns the node, mirroring the two existing precedents (`ace2_services` stripping legacy MinIO/runner, `beelink_services` stripping bare-metal Ollama). Ran with `TAGS=cleanup`: `changed=4`, then `changed=0` on re-run, so it is idempotent. Verified on the node — no container, `/opt/ollama` gone, 11434 not listening, no UFW rules, disk 30G -> 21G. Model data deleted per Manu (8.8 GB, qwen2.5:7b + qwen2.5-coder:7b); local inference stays deferred to a hosted API per ADR-029

### PR-B — the sweep (merging fires the Argo prune)

- [x] [AC3] `toolkit secrets unset` the prod `apps.services.ai.ollama.api_key` **first**, then drop its `SECRET_CATALOG` entry. The reverse order leaves a value no audit can see ✓ 2026-08-09
- [x] [AC1] [AC5] Delete `infra/k8s/overlays/prod/middlewares/api-key.yaml.tpl` and its `MIDDLEWARE_CATALOG` entry. **Leave the `api-key:` plugin registered** in `traefik-helmconfig.yaml.j2` — resolved Risk 2. **Sweep on `ollama`, never on `api-key`**: the `api-key` in `infra/k8s/overlays/{staging,prod}/secrets.yaml` is CrowdSec's bouncer key, and deleting it breaks the bouncer (Risk 4) ✓ 2026-08-09
- [x] [AC1] Delete `infra/k8s/base/external/ollama.yaml` and `infra/k8s/overlays/prod/ollama-throttle.yaml`; drop the references from both `kustomization.yaml` files and prod `patches.yaml` ✓ 2026-08-09
- [x] [AC1] Remove `apps.services.ai.ollama.*` from `common.yaml` and `staging.yaml` ✓ 2026-08-09
- [x] [AC1] Drop `ollama` from `SERVICES_AI` in `toolkit/config/constants.py` ✓ 2026-08-09
- [x] [AC1] Remove the DNS entries from `deploy-dns.yml`, `provision-rpi4.yml` and the CoreDNS `Corefile.j2` ✓ 2026-08-09
- [x] [AC2] Regenerate the homepage config; `make validate-sync` green ✓ 2026-08-09
- [x] [AC6] Delete `tests/e2e/test_ollama_public.py`; clean the entries in `expectations.py`, `conftest.py` and `tests/test_k8s_middlewares.py` ✓ 2026-08-09
- [x] [AC1] Correct the rationale comments that outlive the service: `dev_node/tasks/main.yml` (coexistence header), `beelink_services` + `provision-bee.yml` ("moved to ace2"), `headscale/policy.hujson.j2` (the `tag:hermes → vps:443` justification — the **rule stays**, it also covers Gitea) ✓ 2026-08-09
- [x] [AC7] Amend ADR-028 and ADR-029; fold in the two `CLAUDE.md` doc-drift fixes named in ADR-058 D4 ✓ 2026-08-09
- [x] [AC8] Delete `docs/runbooks/ollama-api-key-rotation.md` — a 118-line runbook for a service that will not exist ✓ 2026-08-09
- [x] [AC8] Clear the present-tense claims from `docs/architecture/{service-catalog,architecture-overview}.md`, `docs/runbooks/{monitoring,operations,dns-homelab,hardware-setup,energy-consumption,non-admin-workstation-access}.md` and `docs/troubleshooting/docker-containers.md` ✓ 2026-08-09
- [x] [AC8] **Do NOT touch** the other 15 ADRs, `docs/audits/*`, `current-state-2026-03-22.md`, or `components/kubelab-*.md`. They are historical records or unbuilt-product design positions; erasing Ollama from them would falsify the record. Verify by re-reading, not by grepping them clean ✓ 2026-08-09
- [x] [AC1] Run the survivor check and confirm only the deliberate matches remain ✓ 2026-08-09

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by at least one test ✓ 2026-08-09
- [x] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command ✓ 2026-08-09
- [x] Type checks pass ✓ 2026-08-09
- [x] Lint passes ✓ 2026-08-09
- [x] No unrelated changes in the diff (no scope creep) ✓ 2026-08-09
- [x] `verification.md` filled in ✓ 2026-08-09
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` following [[pattern-feature-list-as-primitive]]. Each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state`, and `evidence`.

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where `features.json` contains `passing` entries with empty `evidence`.

**Note on f5:** it is the only probe that queries the live cluster rather than the repo. That is deliberate — the objects it checks were never in git, so a repo-only check would report success while they keep running.
