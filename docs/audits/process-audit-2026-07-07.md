# Process Audit — End-to-End Workflows (2026-07-07)

> Process-level audit of kubelab's documented journeys: does every promised workflow
> compose into a complete, walkable path — for a first-time human following only the
> docs, and for an autonomous agent chaining commands via exit codes?
> Audited empirically from a **Windows non-admin workstation** (the exact persona of
> `docs/runbooks/operate-from-new-workstation.md` / ADR-052), local commands only:
> no cluster, VPN, or node was mutated; cluster-dependent behavior was traced from
> source and is marked accordingly. Findings marked **CONFIRMED** were reproduced
> (command + output captured) or verified by direct source/`--help`/`make -n`
> evidence; **PLAUSIBLE** were traced only.

---

## 1. Summary table

| ID | Severity | Process | One-line issue | Status |
|----|----------|---------|----------------|--------|
| P1 | Critical | Deploy gate (`validate-sync` → `deploy-k8s`/`check`) | False drift + crash on Windows: CRLF rewrite in `sync images --check` and `charmap` crash in homepage sync make the gate exit 1 on a clean tree, blocking the documented ADR-052 workstation journey at step 3 | CONFIRMED |
| P2 | High | Onboarding (contributor) | CONTRIBUTING.md is from the pre-K3s "mlorente.dev" era — most prescribed commands don't exist (`make dev`, `toolkit tools env-init/env-validate/env-examples`, `make deploy-staging/prod`) | CONFIRMED |
| P3 | High | Onboarding (README + `make help`) | README Quick Start ends in phantom `make dev`; README documents `apps/web` (removed) and omits `apps/wiki`; `make help` advertises `dev-app`/`build-app` which have no rule, and omits ~25 real targets | CONFIRMED |
| P4 | High | Operations master reference | `operations.md` ("when in doubt, check here first") contradicts the current GitOps model (claims `git push` auto-syncs staging+prod) and prescribes phantom `make fetch-kubeconfig-hub` (×2, also `k3s-upgrade.md:202`) | CONFIRMED |
| P5 | High | Incident response (troubleshooting/*) | The troubleshooting suite prescribes ~12 phantom commands (`make status/up/down/restart/clean/restore/env-validate/emergency-rollback/verify-dns/api-build/web-dev`, `ENV=production`) — a responder's first command fails at incident time | CONFIRMED |
| P6 | Medium | K8s deploy (agent chain) | `toolkit infra k8s deploy` exits **0** when the rollout fails (warning only) — an agent cannot distinguish a broken deploy from a good one | CONFIRMED (source) |
| P7 | Medium | Deploy/new-service/DR runbooks | Six runbooks marked `status: active` describe retired flows: Gitflow `develop→master`, 3-node staging, `toolkit deployment deploy`, `blog`/`portainer`, `~/.kube/kubelab-config`, plus phantom `make sops-check`, `generate-config`, `provision-rpi4`, `backup-vps`, `deploy-dns` | CONFIRMED |
| P8 | Medium | Agent instructions (CLAUDE.md, README CI) | CLAUDE.md tells agents to run phantom `make deploy-vps`/`make deploy-dns`, and its "manual image pin" gotcha is superseded by the `deployment promote` lane; the RC-tag vs `sha-*` delivery narrative is split across docs with no reconciliation | CONFIRMED |
| P9 | Medium | Provisioning / Ansible deploys | The generated inventory pins mesh IPs (`tailscale_ip`) with no bastion/ts-bridge lane — every `make provision`/`make deploy TARGET=…` is unreachable from a non-mesh controller (and Ansible itself is unavailable on native Windows); no runbook states the controller prerequisite (known: kubelab#818 / TOOL-016) | CONFIRMED (source) |
| P10 | Medium | Agent ergonomics (output contract) | All logs go to **stdout** (Rich console), no `--raw`/`--json` anywhere; the Makefile itself parses `secrets show … \| tail -1` to inject Helm secrets — one added log line silently feeds garbage into the Argo CD admin password | CONFIRMED (source) |
| P11 | Low | Fix suggestions | `infra.py:945` prints a literal `{env}` (missing f-string) — the suggested recovery command is not executable verbatim; homepage sync **crash** is reported as generic "sync failure" indistinguishable from drift | CONFIRMED |
| P12 | Low | Concurrency | `sync all --check` mutates tracked files in place then restores (snapshot window); no lock anywhere in the toolkit — concurrent check+deploy or check+check can race the restore | PLAUSIBLE |
| P13 | Low | Local validation | `make validate` fails (exit 1) on any box without the `terraform` binary even when only non-TF config is being validated — missing-tool conflated with invalid-config | CONFIRMED |
| P14 | Low | Automation traps | `make dev-full-reset` blocks on interactive `read -p` mid-recipe (undocumented as interactive); fetch-kubeconfig/connect interactivity IS documented (good) | CONFIRMED |
| P15 | Info | Repo hygiene | Empty untracked `master/` directory at repo root (likely a stray redirect/worktree artifact) | CONFIRMED |

Where flows hold (verified, one line each):

- Exit codes are correct for `toolkit config validate` (1 on failure), `secrets show` (1 on missing key), `sync all --check` (1 on drift) — probed without pipes.
- `sync all --check` restores the tree: `git status --porcelain` clean after a failing check run.
- `docs/runbooks/gitops-delivery-promotion.md` is accurate and current — it matches `staging-deploy.yml` (`sha-${GITHUB_SHA::7}`), the kustomization comments, and ADR-046/056.
- `make worktree-init`, `make fetch-kubeconfig ENV=…`, `make connect/disconnect/connect-status` exist as the ADR-052 runbooks document.
- `tests/e2e` + `tests/infra` lanes exist with `--env` plumbing; 330/438 tests collect cleanly (unit lane) on this box.
- CI drift gates exist as the Makefile comments claim (`check-config-drift.yml` runs `make config-check-drift` + `toolkit sync images --check`).

---

## 2. Process map — the real state machine

### 2.1 A code change (app: api / web / errors)

```mermaid
stateDiagram-v2
    [*] --> FeatureBranch : worktree + make worktree-init
    FeatureBranch --> PR_Open : push + open PR
    PR_Open --> PR_Green : ci.yml (lint/type/test) + check-config-drift.yml
    PR_Green --> Master : squash merge (human)
    Master --> StagingPR : staging-deploy.yml builds sha-&lt;short&gt;, promote --env staging, auto-PR
    StagingPR --> StagingSynced : human merges → Argo CD staging sync
    StagingSynced --> ReleasePR : release-please cuts semver (fix/feat only)
    ReleasePR --> Released : merge → release.yml re-tags staging sha → X.Y.Z (api build-once)
    Released --> ProdPR : promote-prod.yml (workflow_dispatch, one app/run)
    ProdPR --> ProdSynced : human merges → Argo CD prod sync (selfHeal true)
    ProdSynced --> [*]
    ProdSynced --> Master : rollback = git revert merge commit

    StagingSynced --> OutOfBand : make deploy-k8s ENV=staging (worktree preview)
    OutOfBand --> StagingSynced : next merged PR re-aligns (selfHeal false, documented)
```

Owning commands per transition are all real and current (verified against
`.github/workflows/` and the Makefile). **Dead ends / broken transitions:**

- **`OutOfBand` is unreachable from a Windows workstation** — `make deploy-k8s`
  hard-depends on `validate-sync`, which false-fails there (P1). The ADR-052
  journey promises exactly this transition.
- **`OutOfBand` can silently land in a broken state** — `infra k8s deploy` exits 0
  when the rollout fails (P6); the only detection is a later `make pods`/`test-e2e`.
- The `Released` state has a documented precondition (api pinned to a real `sha-*`
  in staging) that fails fast — good, not a dead end.

### 2.2 An infra/config change (SSOT lane)

```
edit common.yaml/<env>.yaml ──► toolkit config generate / sync ──► commit generated/
        │                                                            │
        ▼                                                            ▼
   K8s-shaped values ──► PR ──► CI drift gates ──► merge ──► Argo CD reconciles
   Ansible-shaped values ──► make deploy TARGET=vps|dns ENV=… ──► [MESH-ONLY controller — P9]
   DNS (prod) ──► make tf-dns-plan / tf-dns-apply
```

**Dead end:** the entire Ansible branch (provision, deploy TARGET=vps/dns/k3s,
maintain, backup) has no transport lane for a controller that is not on the
Headscale mesh — the inventory pins `100.64.0.0/10` addresses
(`generator_ansible.py:75-105`). From the very workstation the ADR-052 runbooks
onboard, these targets cannot run at all (P9).

### 2.3 Operator access (per ADR-052)

`make fetch-kubeconfig ENV=x` (once) → `make connect ENV=x` (per session) →
kubectl / `make apply-secrets` / `make deploy-k8s` → `make disconnect`.
Walkable as documented **except** the final `deploy-k8s` step on Windows (P1).
Re-run semantics are explicitly documented and correct (`connect` idempotent,
statefile for `disconnect`).

### 2.4 Journey status overview

| Documented journey | Entry doc | Walkable? |
|---|---|---|
| Contributor onboarding | CONTRIBUTING.md | **No — breaks at step 3** (P2) |
| README quick start | README.md:111-126 | **No — final command phantom** (P3) |
| Operate from new workstation | operate-from-new-workstation.md | Steps 1-2 yes; **step 3 breaks on Windows** (P1) |
| Non-admin fleet SSH access | non-admin-workstation-access.md | Yes (current, accurate) |
| GitOps delivery & promotion | gitops-delivery-promotion.md | Yes (current, accurate) |
| Daily ops reference | operations.md | **Misleads** — model contradiction + phantoms (P4) |
| Incident triage | troubleshooting/* | **No — first commands phantom** (P5) |
| Deploy new K3s service | deploy-new-k3s-service.md | Partially — stale prereqs/flow (P7) |
| Deployment (env promotion) | deployment.md | **No — describes retired Gitflow/Compose flow** (P7) |
| Provision/maintain nodes | Makefile + hardware runbooks | Only from a mesh-connected Linux controller; prerequisite undocumented (P9) |
| Secrets lifecycle | sops-and-secrets.md, Makefile | Yes locally (edit/show/audit exit codes correct); cross-env parity is manual (docs admit, TOOL-001/002) |

---

## 3. Prior-fix verification

Not applicable to this repository. The audit spec's "previous audit" context
(ingest preview, `documents/index.jsonl`, review sidecars, `publication.status`,
vault manifests) describes a different product; none of those artifacts exist in
kubelab (verified by repo-wide grep). Per maintainer instruction, the audit target
is this repository; no prior code-level audit ledger exists here to re-verify.
The empirical spirit of that section was redirected to §1's "where flows hold" list.

---

## 4. Gaps and errors by process (severity order)

### P1 — CRITICAL: the deploy gate false-fails on every Windows workstation — CONFIRMED

**Repro (clean tree, current master-based branch):**

```bash
poetry run toolkit sync all --check --env staging   # exit 1
# [ERROR] homepage sync crashed: 'charmap' codec can't encode character '→'
# [ERROR] images: drift detected in 1 file(s):
# [ERROR]   infra\k8s\base\kustomization.yaml
```

Isolated on scratchpad copies (injectable paths of
`toolkit/scripts/sync_k8s_images.py:sync()`):

```
orig CRLF count: 0  LF: 94
new  CRLF count: 94 LF: 94
bytes equal: False
equal after normalizing newlines: True
```

**Mechanisms (two, same class):**

1. `sync_k8s_images.py:140` — `kustomization.write_text(content)` without
   `newline=` → Python translates `\n`→`\r\n` on Windows. The comparator
   (`toolkit/cli/sync.py:108-119`) diffs raw bytes with no newline
   normalization → **every Windows run reports drift on identical content**.
2. Homepage sync crashes encoding `→` (U+2192) under the cp1252 default before
   the comparison even runs (`toolkit/cli/sync.py:84-92` catches, restores,
   re-raises).

**Blast radius (Makefile):** `validate-sync` (l.747) is a prerequisite of
`deploy-k8s` (l.830) and part of `check` (l.886). So on Windows:
`make check` is permanently red, and `make deploy-k8s ENV=staging` —
**step 3 of `operate-from-new-workstation.md:75-81`, the runbook written for this
exact machine profile** — aborts before touching the cluster.

**Stranded-user scenario:** operator follows the ADR-052 runbook on the corporate
laptop, everything works until `make deploy-k8s`, which reports image drift on a
tree they just cloned. The printed remediation ("Run 'toolkit sync images' to
update, then commit", `sync.py:129`) instructs them to **commit a CRLF-rewritten
`kustomization.yaml`**, which would then show as a whole-file diff and/or invert
the false drift onto Linux/CI.

**Direction:** `write_text(content, newline="\n")` in every sync writer;
normalize `\r\n`→`\n` in `_normalize_content` as defense-in-depth; force UTF-8
output (`PYTHONUTF8=1` in the toolkit entry point or `encoding=` on writes);
add a `windows-latest` CI job that runs `toolkit sync all --check`. Note
`tests/test_sync_k8s_images.py` exists but only ever runs on Linux CI — a
platform blind spot, not a coverage gap.

### P2 — HIGH: CONTRIBUTING.md onboards into a repo that no longer exists — CONFIRMED

Walk of the prescribed sequence (file:line → result):

| Step | Doc | Reality |
|---|---|---|
| `git clone …/mlorente.dev` | CONTRIBUTING.md:10-11 | repo is `kubelab` |
| `poetry run toolkit tools env-init dev` | :26 | `toolkit tools` contains **only** `certs` (verified `--help`) |
| `make dev` | :32 | no rule (verified `make -n dev`) |
| `toolkit tools env-validate` / `env-examples` | :181, :209, :248-250, :332-333 | commands don't exist |
| `toolkit config generate traefik dev` | :329 | real signature is `toolkit config generate --env dev` (no positionals) |
| `make deploy-staging` / `make deploy-prod` | :307-310 | no rules; real lane is the GitOps runbook |
| `.env` files as the config workflow | :61-65, :237-251 | contradicts the repo doctrine "values/*.yaml, never .env files" (CLAUDE.md) |
| `blog`, `portainer` services; Docker Hub flow | :323-326, :74-77 | apps are api/web(own repo)/errors; blog retired |

**Scenario:** a newcomer (or agent told to "follow CONTRIBUTING") is stranded at
the third command with `No such command 'env-init'` and has no pointer to the
real path (`make setup` → `make worktree-init` → GitOps runbook).

**Direction:** rewrite CONTRIBUTING.md against the current Makefile + gitops
runbook, or reduce it to a thin pointer at README/`docs/runbooks/developer-guide.md`.

### P3 — HIGH: README quick start and `make help` advertise phantom targets — CONFIRMED

- README.md:123 — Quick Start's final command is `make dev`: no rule. The real
  dev-up target is `make up-dev` (Makefile:267).
- README.md:78, :92 — documents `apps/web/` (Astro): `apps/` contains only
  `api/` and `wiki/` (web extracted to its own repo per ADR-048/053).
  `apps/wiki` is documented nowhere in README.
- Makefile:52-53 — `make help` advertises `dev-app APP=x` and `build-app APP=x`;
  neither exists (`make -n dev-app APP=site` → "don't know how to make dev-app").
- `make help` omits ~25 real targets, including the ADR-052 access lane
  (`connect`/`disconnect`/`connect-status`), `pods`, `logs`, `bootstrap-k8s`,
  `restart-service`, `import-n8n`, `notify-smoke`, `config-check-drift`,
  `sync-app`, `recover-argocd`, `watch-argocd`, `tf-*`, `aws1-*`,
  `check-headscale-policy` — discovery is broken in both directions.

**Direction:** fix Quick Start; either delete or implement `dev-app`/`build-app`;
consider generating help from target comments (`##` convention) so it can't drift.

### P4 — HIGH: the operations master reference contradicts the delivery model — CONFIRMED

`docs/runbooks/operations.md` (header: "Master reference for all KubeLab deploy
flows … check here first", updated 2026-03-28):

- :15-21 — "ArgoCD auto-syncs from master. No manual deploy needed. `git push` →
  syncs staging + prod automatically." Reality (gitops-delivery-promotion.md:3,
  ADR-037/046): master is protected, nothing is pushed directly, staging deploys
  via an auto-opened PR that a human merges, staging `selfHeal: false`. Two
  *active* runbooks disagree about the single most-used flow; the one labeled
  "master reference" is the wrong one.
- :57 and :203 — `make fetch-kubeconfig-hub` doesn't exist; real:
  `make fetch-kubeconfig ENV=hub` (Makefile:371-373). Same phantom at
  `k3s-upgrade.md:202`.

**Scenario:** after an aws1 replace, the operator follows the recovery table at
operations.md:203 and the first command fails; under stress they must
reverse-engineer the Makefile.

**Direction:** update operations.md to defer to the GitOps runbook for delivery
and fix the target names; add "see gitops-delivery-promotion.md" as the daily lane.

### P5 — HIGH: incident-time troubleshooting prescribes a retired CLI — CONFIRMED

Phantom commands with locations (existence checked against Makefile/toolkit):

- `docs/troubleshooting/quick-diagnostics.md:18` `make status`, `:24` `make env-validate`
- `docs/troubleshooting/deployment.md:56` `make status ENV=production`, `:66`
  `make restart APP=api ENV=production`, `:69,:136` `make emergency-rollback
  ENV=production`, `:125` `make down && make up`, `:130` `make clean && make up`,
  `:142` `make restore BACKUP=… ENV=production`
- `docs/troubleshooting/build-failures.md:35,:92` `make clean`, `:65`
  `make api-build`, `:85,:96` `make build`
- `docs/troubleshooting/development.md:35` `make web-dev`, `:68` `make dev`
- `docs/troubleshooting/networking-dns.md:198`, `ssl-certificates.md:156`
  `make verify-dns ENVIRONMENT=prod`
- `docs/troubleshooting/environment-configuration.md:43,:56` `make env-validate`

None exist; `ENV=production` is not even a valid env value (dev/staging/prod).
The real diagnostic surface (`make pods ENV=…`, `make logs SVC=…`,
`toolkit infra status`, `make check-spokes`, `make check-apps`) appears nowhere
in these docs.

**Scenario:** 3 AM prod incident; responder opens quick-diagnostics.md; the first
two commands fail; time-to-mitigate grows exactly when it matters most.

**Direction:** sweep `docs/troubleshooting/` against the current Makefile;
replace the command inventory with the real observability targets; archive what
described the Compose era.

### P6 — MEDIUM: `infra k8s deploy` exits 0 on rollout failure — CONFIRMED (source)

`toolkit/cli/infra.py:673-682` — generate failure → exit 1; dry-run failure →
exit 1; apply failure → exit 1; **rollout failure → `logger.warning`, exit 0**.

**Scenario:** agent (or CI step) runs
`make deploy-k8s ENV=staging && <next step>`; pods CrashLoop; the chain proceeds
and reports success. The documented validation flow (CLAUDE.md ADR-037: deploy →
apply-secrets → restart → test-e2e) only catches it two steps later, and an
agent doing deploy alone never does. This inverts the spec question "can an agent
distinguish 'my operation failed' from an unrelated warning" — here a failure is
*presented as* a warning.

**Direction:** exit non-zero on rollout timeout by default (or add `--strict`
and use it in `deploy-k8s`); at minimum print the failing deployments and a
`make logs SVC=…` pointer.

### P7 — MEDIUM: six `status: active` runbooks describe retired flows — CONFIRMED

- `deployment.md` — Gitflow "PR develop→master" (:18) in a trunk-based repo;
  3-node staging (:14); `ENVIRONMENT=x toolkit config generate` (:44-46, real:
  `--env`); `toolkit deployment deploy/status` as the deploy lane (:62-65,
  :100-110); `blog` app and `portainer` (:74-77); `make deploy-prod` (:103);
  `~/.kube/kubelab-config` (real: `kubelab-<env>-config`).
- `pre-prod-verification.md` — a one-shot B6-migration checklist (3 nodes, blog,
  `kubelab-config`) still presented as a live runbook.
- `deploy-new-k3s-service.md` — `make sops-check` phantom (:17), stale kubeconfig
  path (:18), pre-Argo flow, references vault-era `90-lessons.md` (:59); the
  current three-SSOT-touch pattern (SECRET_CATALOG/MIDDLEWARE_CATALOG/.tpl) and
  the Argo CD lane appear nowhere.
- `rollback-k3s-to-compose.md:79` — `make generate-config` (real: `config-generate`).
- `rpi4-sd-card-provisioning.md:75` — `make provision-rpi4` (real:
  `make provision NODE=rpi4 ENV=staging`).
- `runbook-disaster-recovery.md:126` — `make backup-vps` (real: `make backup ENV=prod`).
- `dns-homelab.md:226` — `make deploy-dns` (real: `make deploy TARGET=dns ENV=staging`).

**Direction:** a runbook-lifecycle pass: archive (with a banner) what documents
history; fix target names in what stays; the frontmatter already has a `status:`
field — use it.

### P8 — MEDIUM: the agent-facing instructions themselves drift — CONFIRMED

CLAUDE.md is loaded by every agent session, so its drift strands agents directly:

- CLAUDE.md:68 "Deploy via `make deploy-vps`" and :88 "Deploy via
  `make deploy-dns`" — neither target exists (real: `make deploy TARGET=vps|dns
  ENV=…`). Also `docs/lessons.md:1192,:3056` repeat them.
- CLAUDE.md "Custom app images need manual pin in kustomization.yaml …
  `sync_k8s_images.py` only handles third-party images" — superseded:
  `infra/k8s/base/kustomization.yaml:36-37` states web/api are per-env via
  `toolkit deployment promote` and errors is synced from `edge.errors.version`
  (DELIVERY-003); an agent following the gotcha edits the wrong file in the
  wrong lane.
- CLAUDE.md key-paths block lists `apps/ — Application source (api, web, blog)`;
  reality: `api`, `wiki`.
- README.md:143 + CLAUDE.md:100 tell the RC-tag story; the delivery runbook
  tells the `sha-*`→semver story (ADR-046/056). Both lanes exist in CI
  (`ci-publish.yml` still builds `-rc.` tags; `staging-deploy.yml` builds
  `sha-*`), but no document reconciles when each applies — two sources of truth
  mid-drift.

**Direction:** fix the two phantom targets and the pin gotcha in CLAUDE.md now
(one-line edits); add a "tag lanes" paragraph to the GitOps runbook and point
README/CLAUDE.md at it.

### P9 — MEDIUM: Ansible journeys are mesh-only, and nothing says so — CONFIRMED (source)

`toolkit/features/generator_ansible.py:75-105`: homelab nodes get
`ansible_host = tailscale_ip` (or `lan_ip` with `--bootstrap`); vps gets
`public_ip`; aws gets `tailscale_dns`/`tailscale_ip`. There is no ProxyJump /
bastion / ts-bridge lane, so **every** Ansible-backed target (`make provision`,
`make deploy TARGET=vps|dns|k3s|harden-nodes`, `make maintain`, `make backup`)
requires the controller to be a mesh node (or on the home LAN for bootstrap).
ADR-052 solved exactly this problem for kubectl but not for Ansible; the
non-admin runbooks document SSH `*-ext` bastion aliases that the inventory does
not use. Native Windows additionally lacks `ansible` entirely (verified:
`ansible: MISSING`); no runbook states either prerequisite.

**Scenario:** operator on the ADR-052-onboarded laptop runs
`make provision NODE=ace1 ENV=staging` → unreachable host (or no ansible at
all), with no documented alternative. Already tracked as kubelab#818 (TOOL-016);
this audit confirms the doc-side gap: the provisioning runbooks never say
"controller must be on the mesh (Linux/WSL)".

**Direction:** short-term, one sentence of prerequisites in the provisioning
runbooks + Makefile usage strings; medium-term, TOOL-016 (`--transport
{mesh,bastion,lan}` or a ProxyJump seam via `vps-pub`).

### P10 — MEDIUM: no machine-readable output; the Makefile parses its own logs — CONFIRMED (source)

- `toolkit/core/logging.py:86,103` — the Rich console (stdout) backs **all**
  logging; `secrets.py:329` prints secret values with bare `print()` to the same
  stream. No command in the CLI offers `--json`/`--raw` (grep: none).
- Makefile:413-416 (`_deploy-argocd-helm`) extracts four secrets via
  `toolkit secrets show … 2>/dev/null | tail -1` and feeds them to `helm --set`.
  The `2>/dev/null` is a no-op (logs are on stdout); correctness rests entirely
  on "the value happens to be the last stdout line". Any future post-value log
  line (deprecation notice, cleanup message) silently injects garbage as the
  Argo CD admin password hash / OIDC secret — a lockout, not an error.
- DEBUG-level lines appear in default local runs (observed in `sync`/`validate`
  output), further polluting the only data channel.

**Direction:** `secrets show --raw` (value only, everything else to stderr) and
use it in the Makefile; route Rich logging to stderr; add `--json` to
`status`/`health`/`check`-style commands agents chain on.

### P11 — LOW: remediation strings not executable verbatim — CONFIRMED

- `toolkit/cli/infra.py:945` — `logger.info("Run 'toolkit infra ansible generate
  --env {env}' first")`: missing `f` prefix, prints a literal `{env}`. Pasting it
  runs the wrong command.
- A homepage sync **crash** surfaces as `[ERROR] Sync failures: homepage` — the
  same shape as drift; the operator can't tell "regenerate and commit" from
  "the tool is broken on this platform" (compare P1).

**Direction:** add the `f`; distinguish `CRASHED` from `DRIFTED` in the sync-all
summary line.

### P12 — LOW: unguarded concurrency around the sync/check window — PLAUSIBLE

`toolkit/cli/sync.py:80-104` (`_run_with_check`) mutates the real tracked files,
compares, then restores. During the window, a concurrent `git add`/commit,
`kubectl kustomize`, or a second `--check` sees (or snapshots) mutated content;
two concurrent checks race the restore, and the loser can persist the rewritten
file. No lock exists anywhere in the toolkit (grep `flock|FileLock|lockfile`:
zero hits), including around `infra k8s deploy` (two concurrent deploys are
last-writer-wins at the kubectl level). Low likelihood single-operator, but the
gate runs inside `deploy-k8s` where parallel invocations are plausible (agent +
human).

**Direction:** compare against a rendered string instead of mutating in place
(the sync functions already build the full content in memory); or a trivial
lockfile around `_run_with_check`.

### P13 — LOW: `make validate` conflates missing tool with invalid config — CONFIRMED

Observed: `[ERROR] Terraform not found. Please install Terraform first.` →
`4/5 configuration validations passed` → exit 1, even when the operator's task
touches nothing under `infra/terraform/`. The message is clear (good), but a
newcomer cannot get a green `make validate` without installing Terraform they may
never use. **Direction:** skip-with-visible-warning when the binary is absent
(exit 0), or a `--only <component>` flag.

### P14 — LOW: interactive traps in automation-shaped targets — CONFIRMED

`make dev-full-reset` (Makefile:300) blocks on `read -p` mid-recipe with manual
copy-paste-secrets instructions — nothing marks it interactive in `make help`, so
an agent invoking it hangs. (Counter-example done right: the ADR-052 runbook
explicitly says `fetch-kubeconfig`/`connect` need an interactive shell.)
**Direction:** label interactive targets in help text, or gate on `[ -t 0 ]` and
fail fast with a message when stdin is not a TTY.

### P15 — INFO: stray `master/` directory at repo root — CONFIRMED

Empty, untracked (invisible to `git status` because git ignores empty dirs).
Likely a stray `> master/` redirect or worktree artifact. Delete casually.

---

## 5. Missing-process backlog (by unblocking value)

1. **Windows-safe sync lane** (unblocks P1, and with it the ADR-052 end-to-end
   journey): `newline="\n"` on all generated-file writers, UTF-8 output, newline
   normalization in the comparator, `windows-latest` CI smoke of
   `toolkit sync all --check`.
2. **Preflight doctor** (`toolkit doctor` / `make doctor`): verify per-flow
   prerequisites (age key + SOPS, terraform, ansible, kubectl, helm, transport
   state per env) and print the real fix per gap. Three docs already *reference*
   such a command in phantom form (`make env-validate`, `make sops-check`) —
   the need is documented; the command was never built.
3. **Ansible transport for non-mesh controllers** (TOOL-016 / kubelab#818):
   `--transport {mesh,bastion,lan}` on `infra ansible generate/run` or a
   ProxyJump seam via `vps-pub`; plus one prerequisites line in every
   provisioning runbook meanwhile.
4. **Docs truth sweep + runbook lifecycle**: rewrite CONTRIBUTING.md (P2); fix
   README Quick Start (P3); reconcile operations.md with the GitOps runbook
   (P4); sweep troubleshooting/* (P5); archive retired runbooks using the
   existing `status:` frontmatter (P7). A CI grep gate ("every `make <target>`
   mentioned in docs exists in the Makefile") would keep this fixed — the
   phantom-target check in this audit is a 10-line script.
5. **Machine-readable CLI contract** (P10): `secrets show --raw`, logs to
   stderr, `--json` on status/health; migrate the Makefile's `tail -1` parses.
6. **Strict deploy exit semantics** (P6): `--strict` rollout gate wired into
   `make deploy-k8s`.
7. **`make help` generation** from annotated targets so help can't drift (P3).
8. **Tag-lane reconciliation doc**: one paragraph in the GitOps runbook covering
   when `-rc.*` vs `sha-*` vs semver applies; point README/CLAUDE.md at it (P8).
9. **Promised-but-missing wrappers**: `make argo-preview`/`argo-revert`
   (docs/lessons.md:2888 promises them; only `argo-set-revision` exists).
10. **Secrets cross-env parity automation** (TOOL-001/002, already acknowledged
    in CLAUDE.md as manual): `secrets audit` exists and exits correctly — wire
    it into CI as a scheduled check.

---

## 6. Open questions (maintainer)

1. **Is Windows a supported operator platform for the *deploy* lane?** ADR-052's
   runbooks strongly imply yes (they onboard a non-admin Windows box through
   `make deploy-k8s`). If yes, P1 is a release-blocker-class bug; if no, the two
   runbooks need an explicit "kubectl only from Windows; sync/deploy from
   Linux/WSL" statement.
2. **Is the `toolkit deployment` group (deploy/status/backup/restore/rollback)
   still a supported lane**, or legacy pending removal? `deployment.md` routes
   users there; `promote`/`image-tag` clearly are current — the rest is unclear.
3. **Which pre-K3s runbooks are intentionally kept as historical record**
   (e.g., `pre-prod-verification.md` B6 checklist, `rollback-k3s-to-compose.md`)
   vs. should be archived? The frontmatter `status:` field exists but everything
   says `active`.
4. **RC lane future**: `ci-publish.yml` still builds `-rc.*` tags. Is the RC lane
   deprecated in favor of `sha-*` previews, or serving a distinct purpose worth
   documenting?
5. **DEBUG logging in default runs**: intended default or leftover setting?
6. `master/` empty dir at repo root — safe to delete?
