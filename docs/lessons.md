---
id: "kubelab-lessons"
type: lesson
status: active
tags: [kubelab, project]
created: "2026-02-21"
owner: manu
---

# KubeLab - Lessons Learned

> This file documents patterns learned, errors avoided, and best practices discovered during development.
>
> **Protocol**: Update after every important correction or discovery.

---

## Format

```markdown
### [DATE] Lesson Title

**Context**: What I was doing

**Problem**: What went wrong or what I discovered

**Solution**: How I resolved it

**Rule**: Pattern to follow going forward
```

### [2026-08-17] `gh pr edit` fails on a Projects-classic field, applies nothing, and blames Projects

**Context**: Three separate tasks across two sessions needed `gh pr edit` — setting a PR body (#1112), adding an assignee (#1122), adding a label (#1119-#1121). All three failed the same way, and in the first case the failure was not noticed until much later: #1112 shipped with the wrong body.

**Problem**: The command prints

```
GraphQL: Projects (classic) is being deprecated in favor of the new Projects experience,
see: https://github.blog/changelog/2024-05-23-sunset-notice-projects-classic/.
(repository.pullRequest.projectCards)
```

and exits 1. It is easy to read that as deprecation noise about a feature you were not using — the message names `projectCards`, not the field you were editing. It is not noise. `gh pr edit` **reads the PR before mutating it**, and its read query requests `repository.pullRequest.projectCards`, which the API now refuses. So it dies at the read step and **your edit never happens**. Measured on `gh 2.46.0`: `gh pr edit <n> --add-assignee <user>` → exit 1 with that message, then `gh pr view <n> --json assignees` → `0`. The same applies to `--body` and `--add-label`.

The scope is narrower than "the `gh` porcelain is broken", and the narrowing matters because it decides what you may still use. **`gh issue edit` is unaffected** — verified in the same session, `gh issue edit <n> --add-label debt` → exit 0 — because its query does not ask for `projectCards`. So do not route issue edits through the API on account of this; only PR edits.

**Solution**: use the REST endpoint for the specific field.

| Instead of | Use |
|---|---|
| `gh pr edit <n> --body ...` | `gh api -X PATCH repos/OWNER/REPO/pulls/<n> -F body=@body.md` |
| `gh pr edit <n> --add-assignee <user>` | `gh api -X POST repos/OWNER/REPO/issues/<n>/assignees -f 'assignees[]=<user>'` |
| `gh pr edit <n> --add-label <label>` | `gh api -X POST repos/OWNER/REPO/issues/<n>/labels -f 'labels[]=<label>'` |

A PR is an issue for these two endpoints, hence `/issues/<n>/` for both.

**Rule**: **An error that names a subsystem you were not using is still an error about your command.** The instinct to classify it as unrelated noise is what let #1112 ship with an unchanged body — the operation looked like it had failed harmlessly, when it had failed *and* left the thing you wanted undone. When a write tool errors, read the field back before believing anything about what landed; a non-zero exit tells you something went wrong, never which half.

**Tags**: `#gh-cli` `#github` `#tooling` `#projects-classic` `#verify-after-write` `#pr-1112` `#pr-1122`

### [2026-08-17] `Burstable` QoS proved the wrong container had a request (IDP-031)

**Context**: IDP-031's final phase had to show that `apprise` and `crowdsec` — the two pods whose **initContainers** declare no `resources` — come up with the `LimitRange` defaults applied. Both pods showed `qosClass: Burstable` in prod immediately after `selfHeal` landed the `LimitRange` and `ResourceQuota`. Burstable means "has requests, requests < limits", so the criterion looked met without touching anything.

**Problem**: It was met by the wrong container. Both pods' **main** containers carried explicit `resources` that pre-dated this spec entirely, and QoS class is computed over the whole pod — so `Burstable` was true before the `LimitRange` existed and would have stayed true if it never applied. Reading the object underneath showed `spec.initContainers[*].resources` was still `{}`. Neither pod had actually restarted since the manifests landed, and container resource attributes are fixed at *create* time: nothing about an existing pod changes when a `LimitRange` appears. An explicit `make restart-service` was needed before the initContainers picked up `128Mi/256Mi`.

The tell was available and ignored: a derived field that was already true for an unrelated reason cannot distinguish the state you are claiming from the state you had. `qosClass` is a summary over containers; the claim was about one specific container list.

**Solution**: assert on `spec.initContainers[*].resources` directly, and restart the workload first, because a `LimitRange` is an admission mutation and admission only runs on create. `tests/infra/test_k3s.py::TestNamespaceGovernance` reads the resource blocks, not the QoS class.

**Rule**: **A derived field is not evidence for a claim about its inputs.** QoS class, `Ready`, `Up`, an aggregate count — each summarises several things, so it can be true because of any one of them. When the claim names one specific input, read that input. And when the mechanism is admission-time — `LimitRange`, defaulting webhooks, injected sidecars — remember that existing objects are never revisited: an unrestarted pod is evidence about the past, not about the manifest you just applied. Same family as the drift gate whose green meant "nothing to compare" and the container limits that were declared but never in force (#1104, #1117).

**Tags**: `#kubernetes` `#limitrange` `#qos` `#admission` `#false-green` `#idp-031` `#proxy-signal`

### [2026-08-16] The drift gate's own usage guard was unreachable, so it checked the one environment nobody deploys

**Context**: BACKUP-044. The R2 offsite destination needed four non-secret values (account id, bucket, endpoint, repo prefix) in `common.yaml`. `infra.*` is the shared-services namespace (ADR-036), and a backup destination is shared infrastructure, so `infra.backup_r2` looked like the right home. Locally I ran `make config-check-drift`, saw `✓ No drift`, and pushed. CI failed on **both** `Drift / staging` and `Drift / prod`.

**Problem**: Two independent defects, and the second is what let the first reach CI.

1. **`infra.*` is not a namespace for arbitrary shared values — it is an injection point.** `generator_k8s.py:_extract_app_env_vars` flattens everything under `infra.` into `INFRA_*` keys and emits them into *every* component's ConfigMap, verbatim. Four backup-destination keys therefore rewrote the ConfigMap of every app in both overlays. The values were correct, the placement was not: ADR-036's contract is "values consumed by more than one *component*", and a restic destination consumed by an Ansible role on four nodes is not that. Fix was a one-line move to a top-level `backup.r2`.

2. **`make config-check-drift` with no `ENV` checked `dev` and reported green.** The target opened with `@test -n "$(ENV)" || (echo "Usage: ..." && exit 1)`, which reads as a guard. It is not one: `ENV ?= dev` lives ~700 lines further down the same Makefile, and a `?=` assignment is global regardless of position, so `$(ENV)` expanded to `dev` and `test -n "dev"` always passed. The usage message had never been printed. Verified after the fact: `make -n config-check-drift` emits `test -n "dev"`. Dev generates Docker Compose configs — it does not produce the K8s overlays CI diffs — so a dev-only run is structurally incapable of seeing the failure, and prints the same `✓` as a real one. `CONTRIBUTING.md` cited the bare form twice.

**Solution**: two attempts, and the first is the more instructive. #1118 replaced the guard with `@test "$(origin ENV)" = "command line"` — the only make construct that distinguishes "the caller passed this" from "it has a value" — and deliberately kept `ENV=dev` working. That moved the hole rather than closing it: `ENV=` also has command-line origin, and `ENV=dev` still routed straight into the vacuous case, because `git diff --quiet` over a pathspec that matches nothing exits 0. Provenance was never the property that mattered. 1122 validates the *value* instead, against a declared `DRIFT_ENVS := staging prod`, with `$(words)` rejecting the empty and multi-word forms that `$(filter)` alone would wave through. A static test asserts the recipe still guards through that variable, so the allow-list cannot be quietly widened back. CI already passed `ENV` per matrix env, so it was unaffected throughout. `CONTRIBUTING.md` now spells out both commands and the `INFRA_*` fan-out.

The same shape has a third instance in this very target, found while fixing the second and already filed as #1048: one of the three paths it diffs, `infra/ansible/generated/<env>/hosts.yml`, is gitignored and has never been tracked, so `git diff` cannot see it and CI-GATE-002's Ansible half was born vacuous. It stays in place, annotated rather than silently removed, because how inventory drift *should* be detected is a separate decision.

**Rule**: A guard on a variable that has a repo-wide default is not a guard, and tightening it to *where the value came from* is not enough either — validate the value against the set the gate can actually check, and declare that set as a variable a test can assert on. More generally: **when a gate can run against a target that cannot exhibit the failure, its green is not evidence.** Ask what the check ran *against*, not whether it passed; `✓ No drift` is a claim about one environment, and the default environment is the one that ships nowhere. In a `git diff`-based gate the specific trap is that a pathspec matching nothing — a wrong env, an untracked file — exits 0, which is indistinguishable from agreement. And before putting a value under `infra.*`, check ADR-036's actual contract: that prefix has a consumer (every ConfigMap), not just a meaning.

**Tags**: `#makefile` `#drift-gate` `#adr-036` `#ssot` `#false-green` `#ci-gate-002` `#backup-044` `#pr-1118` `#pr-1122`

### [2026-08-10] "No matching data" is not zero — it is NoData, and the default acts on it

**Context**: OBS-007 phase 2/3. A Grafana alert rule over a Loki query that counts ACME failures in Traefik's logs. The healthy state is "no failures", which felt like it should evaluate to zero.

**Problem**: It does not. `sum by (domain) (count_over_time({...} |~ "..." [10m]))` over a selection that matches nothing returns **no series at all**, not a series with value 0. Grafana therefore evaluates the rule as **NoData**, and Grafana's default `noDataState` is to alert on it.

Left at that default, this rule would have fired continuously in prod *while certificates were renewing perfectly*, and it would have fired into the `page` tier. The inversion is total: the alert would be loudest exactly when nothing was wrong, which is the fastest way to get an alert channel muted permanently.

This was confirmed in production rather than reasoned about. Every prod evaluation logs `framesLength=0`, because prod has no ACME failures.

**Solution**: `noDataState: OK` on any rule whose healthy state is an empty result set — which is every log-matching alert, as opposed to a metric-threshold alert where the series exists continuously and only its value moves. Give it its own test; it is one word in a manifest and it inverts the entire behaviour of the alert.

**Rule**: Before writing the condition, ask **what the query returns when everything is fine**. That question — not the query's type — decides `noDataState`:

- Healthy result is **empty** (alerting on the *presence* of bad lines: errors, failures, rejections) → NoData is the healthy state → `noDataState: OK`. This rule.
- Healthy result is **non-empty** (alerting on the *absence* of expected lines: a missing heartbeat, a job that stopped reporting) → NoData is precisely the failure → leave it alerting, and `noDataState: OK` would blind you to the exact outage you built it for.

Both are log-based alerts, and they need opposite settings, so "log query" is not the discriminator. Getting it backwards is silent in both directions: one alerts forever while healthy, the other stays quiet through the outage.

**Corollary on proving a negative.** The criterion "the rule must not fire on the periodic heartbeat" was written as "leave it enabled across at least one heartbeat and confirm it stays Normal". That is the weaker test: it shows the rule was quiet, without ever establishing that a heartbeat was inside an evaluated window — 24 hours of silence over an absent input proves nothing. Constructing the case is stronger and instant: evaluate the alert expression at a timestamp one minute *after* a known heartbeat, so the heartbeat is provably inside the `[10m]` range, then assert the result is empty. Prefer constructing the condition you want to disprove over waiting for it to occur.

### [2026-08-10] A config that provisions cleanly can still fail at delivery

**Context**: OBS-007 phase 1 — building the Grafana -> Apprise -> Telegram path before writing any alert query. The spec ordered it that way deliberately: "the substrate is the work; the rule is the easy part."

**Problem**: The contact point provisioned without a single warning. `GET /api/v1/provisioning/contact-points` returned it, Grafana logged `finished to provision alerting`, and the test asserting a non-empty contact-point list went green. Everything that could be checked *before sending anything* said the configuration was correct.

It was not. The first alert produced `notify retry canceled due to unrecoverable error: template: :1: unexpected ":=" in command`. Grafana's custom webhook **payload** parser rejects variable assignment (`{{ $type := "success" }}`), which ordinary Go templates accept and which is accepted inside a `templates.yaml` `define`. The restriction applies only to the payload template, and only at send time.

Two further traps sat behind it. Grafana applies a newly provisioned alerting config roughly **60 seconds after the pod starts**, not at startup — so for the first minute after a rollout the *old* config is still notifying, and a fix looks like it did not work. And Grafana's stock webhook body (`title`/`message`/`alerts[]`) has neither the `body` nor the `tag` field Apprise requires, so the default payload would have been rejected regardless.

**Solution**: Move any conditional logic out of the payload template into a named `define` in the provisioned templates file, and call it with `tmpl.Exec`. Build the JSON with `coll.Dict | data.ToJSON` rather than by hand, so quotes inside an alert annotation are escaped instead of producing a malformed body — Traefik's ACME errors do contain quotes. Then read the *Apprise* access log for `POST /notify/kubelab 200` and `Delivered Notification(s) - Tags: <tier>`, and compare timestamps against the `Applying new configuration to Alertmanager` line to be sure you are looking at the config you just deployed.

**Rule**: For anything that *sends*, provisioning success is not delivery success — the only check that counts is an artifact observed at the far end. Order the work so the transport is proven by a trivial always-firing rule before any query exists; otherwise a silent alert has two candidate causes and no way to separate them. This one paid immediately: written in the other order, a payload-template parse error would have presented as "my LogQL matches nothing."

### [2026-06-26] A Trivy image failure has two independent sources — base-OS *and* the Go binary

**Context**: The `api` image build (Trivy step in `ci-publish.yml`, gate = `CRITICAL,HIGH`, `ignore-unfixed: true`) started failing on the release PR. First read: the base was `alpine:3.18`, which had reached EOL — its apk packages no longer get security backports, so ~18 fixed-elsewhere HIGH/CRITICAL CVEs tripped the scanner. Bumped the runtime base to the current stable `alpine:3.24`.

**Problem**: The base bump cleared every OS CVE — and Trivy *still* failed. Trivy scans a container image with **two independent scanners**: the OS package DB (apk/apt — the alpine layer) **and** `gobinary`, which reads the dependency versions baked into the compiled Go binary. The remaining HIGHs were all the second kind: stale *transitive* Go modules (`golang.org/x/crypto` 0.40, `golang.org/x/net` 0.42, `golang.org/x/sys`, `quic-go` 0.54) — untouched by any base-image change because they live in the binary, not the rootfs. A multi-stage Dockerfile makes this easy to miss: the runtime layer looks clean, but the `COPY`d binary carries its own vuln surface. Bonus trap: bumping the deps raised the `go` directive (1.23→1.25), and the newer toolchain's `vet` then failed the build on a **pre-existing** non-constant format string (`fmt.Errorf(x)` where `x` is a runtime value) that the older vet had ignored.

**Solution**: Fixed both sources in one PR — `alpine:3.24` for the OS half, and `go get golang.org/x/crypto@latest golang.org/x/net@latest golang.org/x/sys@latest github.com/quic-go/quic-go@latest && go mod tidy` for the gobinary half (all are `// indirect`, so forcing the higher version + tidy is the patch). Then fixed the vet diagnostic the go-directive bump surfaced (`fmt.Errorf("%s", x)`).

**Rule**: When an image fails Trivy, read the finding's **package type before reaching for the base image**: an apk/deb name (`libssl3`, `ca-certificates`) is an **OS** CVE → bump/patch the base; a module path (`golang.org/x/...`, `github.com/...`) is a **gobinary** CVE → bump the Go dep (`go get @latest` + `go mod tidy`, even for `// indirect`). A green base does not mean a green image. Because the gate is `ignore-unfixed: true`, every failure is by definition *actionable* (a fix exists upstream). And expect a `go` directive bump to activate newer `vet` checks on old code — budget for a small follow-up fix. Two prevention hooks now exist: Dependabot `docker` (base EOL) + `gomod` security updates (binary deps).

**Tags**: `#trivy` `#security` `#docker` `#golang` `#gobinary` `#supply-chain` `#ci` `#sec-scan-001`

### [2026-06-23] A CLOSED twin issue in the `knowledge` repo is not evidence the work shipped — verify master

**Context**: Reconciling the double-board (the kubelab bitácora vs. the mirror issues in the `knowledge` repo). `knowledge#100` (NOTIFY-007, kubelab #686) and `knowledge#102` (APP-CONFIG-003, kubelab #688) were both **CLOSED**. On a single-board project that reads as "done", so the first instinct was to close the kubelab duplicates #686/#688 as already-shipped.

**Problem**: The two boards track the same work but transition independently. A CLOSED state on the `knowledge` twin records only that *someone marked the mirror issue closed* — it says nothing about whether the deliverable exists in `kubelab` master. Checking the code showed neither NOTIFY-007 nor APP-CONFIG-003 was actually implemented: the close was bookkeeping drift, not a shipped feature. Closing the kubelab issues on the strength of the twin would have buried two unimplemented features as "done" — no code, no test, and gone from the backlog where the remaining work was visible.

**Solution**: Kept #686/#688 open, commented the discrepancy on the board as double-board debt (CONSOLE-003), and made "verify in master" a gate before closing any issue as a duplicate. The twin's status became a hint to investigate, never proof of completion.

**Rule**: Before closing an issue as a duplicate of a CLOSED twin — or trusting any second board's "done" — verify the deliverable exists in `master`: grep the code, run the test, check the artifact. A CLOSED issue is a claim about a *tracker*, not about the *codebase*; on a multi-board setup the two drift, and "done" on the mirror can mask "never built". Trust the code, not the gemelo.

**Tags**: `#governance` `#bitacora` `#double-board` `#duplicates` `#verification` `#console-003`

### [2026-06-20] From the non-admin workstation, "can't reach the node" has three independent causes — not "node down"

**Context**: Validating the new K3s upgrade runbook (OPS-002 #429) against staging needed read-only pre-flight commands on ace1. ace1 was powered on, yet every SSH attempt from this Windows non-admin box (EGW-LEN029) failed — first read as "the on-demand node is off", which was wrong.

**Problem**: Three distinct, stacked blockers, each masquerading as "node down":

1. **Mesh IPs are not locally routable here.** This box runs no native Tailscale, so `ssh ace1` (→ `100.64.0.11:22`, the alias's `Hostname`) just times out — there is no kernel route to `100.64.0.0/10`.
2. **The `-ext` bastion alias fails as a fallback.** `ace1-ext` (ProxyJump via the public VPS) dies with `deployer@162.55.57.175: Permission denied (publickey)` — the VPS jump host authenticates as user **`deployer`**, and this workstation's key isn't authorized for `deployer` on the VPS. The `-ext` aliases are *not* a drop-in transport from this box.
3. **ts-bridge + passphrase key block automation.** `ts-bridge connect` tunnels a **single target** (`ace1:22 → 127.0.0.1:33389`), not a general mesh router. And the local key `~/.ssh/id_ed25519` (`dell-egw-len029`) has a **passphrase** with **no ssh-agent** in the automation shell, so non-interactive SSH (the agent harness, Ansible) cannot authenticate even though an interactive shell can. Ansible-over-the-mesh is further blocked because the generated inventory targets the non-routable mesh IPs.

**Solution**: Deferred the empirical validation (tracked as OPS-011 #722) and shipped the runbook on doc-level review only. For interactive single-node access from here: `ts-bridge connect`, then SSH to `127.0.0.1:<bridge-port>` using the node's own user + key. For automation: run it from a native-Tailscale node, or expose a persistent `SSH_AUTH_SOCK` to the automation shell.

**Rule**: From a non-admin / non-native-Tailscale box, diagnose fleet-access failures against all three causes before concluding "node down" — mesh non-routability, the `-ext` bastion authenticating as `deployer` (not your user), and a passphrase key with no agent. `ts-bridge` solves only single-target *interactive* SSH; *automation* needs a native-Tailscale node or an inherited ssh-agent. Procedure: `docs/runbooks/non-admin-workstation-access.md`.

### [2026-06-20] SOPS matches `.sops.yaml` path_regex against the basename on Windows

**Context**: Provisioning `infra.postgres.password` for staging + prod (#720/#721) from the Windows workstation. Every `toolkit secrets {init,apply,show,audit}` call failed with `no matching creation rules found`, blocking all secret operations.

**Problem**: `.sops.yaml` anchored its rule on a directory prefix — `path_regex: infra/config/secrets/.*\.enc\.yaml$`. On Windows, sops applies `path_regex` to the file **basename** (`staging.enc.yaml`), not the repo-relative path, so a prefix-anchored regex never matches there. On Linux/CI the same rule matched (full path), so the breakage was effectively Windows-only and invisible in CI. Worse second-order effect: the false "no rule" made the toolkit read every secret as **missing** (decryption silently failing), so `toolkit secrets init` was about to *rotate the 12 existing secrets*. Stopped before running it.

**Solution**: Match by extension only — `path_regex: .*\.enc\.yaml$` and `.*\.pem(\.enc)?$`. The only encrypted files in the repo live under `infra/config/secrets/`, so an extension match is equivalent on Linux/CI and also works on Windows. After the fix a dry-run confirmed only `infra.postgres.password` would be generated (no rotation).

**Rule**: Never anchor a `.sops.yaml` `path_regex` on a directory prefix if the workflow ever runs on Windows — sops matches the basename there, not the path. Use a basename-stable pattern (extension). And: when a secret tool reports a secret "missing", verify *decryption itself works* before any `generate`/`init`/rotate — a decrypt failure masquerades as absence, and rotation is destructive.

**Tags**: `#sops` `#windows` `#cross-platform` `#secrets` `#toolkit` `#pr-721`

### [2026-06-20] Keep SOPS ciphertext out of gitleaks, and YAML/Markdown out of CRLF, on Windows

**Context**: After wiring pre-commit in this clone (#721), commits touching `infra/config/secrets/*.enc.yaml` were slow enough to be unsustainable, and YAML files kept failing yamllint with `wrong new line character`.

**Problem**: Two independent Windows/tooling frictions. (1) gitleaks (`useDefault`) was scanning SOPS **ciphertext** — SOPS rotates the data key on every edit, so the whole high-entropy file changes each commit; scanning age ciphertext is slow and only yields false positives, because it is not plaintext. (2) `core.autocrlf=true` with no `.gitattributes` override checked YAML out as CRLF; yamllint rejects CRLF, and the toolkit (writing in text mode) re-emitted CRLF — a churn loop.

**Solution**: `.gitleaks.toml` allowlist `infra/config/secrets/.*\.enc\.yaml$` (+ `.*\.pem(\.enc)?$`) — real plaintext leaks are still caught by the toolkit and the `detect-private-key` hook *before* a value ever reaches SOPS. `.gitattributes` pin `*.yaml`/`*.yml` (and now `*.md`) to `eol=lf`.

**Rule**: A secret scanner must never scan SOPS-encrypted stores — allowlist them by path and rely on a pre-SOPS plaintext guard for real leaks. On any repo edited from Windows, pin every text format that tooling parses (YAML, Markdown) to `eol=lf` in `.gitattributes`; autocrlf otherwise produces CRLF that breaks linters and churns diffs.

**Tags**: `#gitleaks` `#sops` `#pre-commit` `#windows` `#crlf` `#gitattributes` `#pr-721`

### [2026-06-20] A broken language-toolchain launcher silently un-wires the dev setup

**Context**: Resuming work, `poetry` failed with `did not find executable at ...python-313...python.exe`, and pre-commit had clearly never run — `.git/hooks` held only `.sample` files and `core.hooksPath` was unset.

**Problem**: A Poetry console launcher (like venv shebangs) embeds the **absolute path** of the interpreter that created it. The Python 3.13 install had been removed (OneDrive relocation), orphaning the launcher. Because `poetry` itself was broken, `make setup` had never completed in this clone → `pre-commit install` never ran → no git hooks were wired, and nothing surfaced the gap at the time. The breakage stayed invisible until a hook was finally expected to fire.

**Solution**: Reinstall Poetry against a present, CI-parity interpreter — `py -3.12 -m pip install --user --force-reinstall poetry`, then copy the fresh `Python312\Scripts\poetry.exe` over the stale launcher — and `poetry run pre-commit install`. Reinstalled on 3.12.8 (CI parity), not the freshly-installed 3.14.

**Rule**: A toolchain whose launcher pins an absolute interpreter path breaks silently when that interpreter moves or is deleted, and a broken package manager can leave downstream setup (git hooks, venv) half-wired with no error. After any Python relocation/upgrade, re-run `make setup` and verify the chain end-to-end (`poetry --version`, hooks actually present under `core.hooksPath`) — a green shell prompt does not mean the dev environment is wired.

**Tags**: `#poetry` `#python` `#pre-commit` `#dev-setup` `#windows`

### [2026-06-20] Argo CD never creates imperative Secrets — "secret not found" after sync is expected

**Context**: After merging the Postgres manifest (#720), Argo CD reported the Postgres app **Degraded**: `secret "postgres-secrets" not found`.

**Problem**: K8s Secrets in this repo are not in git — the overlay `secrets.yaml` carries only `REPLACE_WITH_SOPS_VALUE` placeholders. Real values are applied imperatively at deploy time via `toolkit secrets apply` (SOPS → rendered Secret → `kubectl apply`). Argo CD syncs only what is committed, so it never creates these Secrets; a freshly-synced workload that consumes one is *expected* to report Degraded until the apply step runs. Here the apply was deferred (no kubeconfig reachable from the workstation — the single `~/.kube/kubelab.config` points at a LAN IP, `172.16.1.10`, unreachable over Tailscale), tracked as #723 (build `make fetch-kubeconfig ENV=staging|prod`) → #724 (apply the secrets).

**Solution**: None needed on the manifest — the Degraded state is the secret-apply step pending, not a defect. Ticketed #723/#724 so the apply is not lost.

**Rule**: In a GitOps repo where Secrets are applied imperatively (not committed), `secret not found` immediately after a sync is expected, not a regression — the secret-apply is a separate, out-of-band action. Track it as a follow-up and don't debug the manifest. Corollary: provisioning a secret in SOPS and applying it to the cluster are two distinct steps; merging the manifest performs neither.

**Tags**: `#argocd` `#gitops` `#secrets` `#sops` `#toolkit` `#adr-037` `#issue-723` `#issue-724`

### [2026-06-15] A generated artifact's content must not depend on whether secrets are decrypted

**Context**: First gated prod promotion (`api` → `1.1.0`, #664) put the new pod in `CrashLoopBackOff` — `panic: SMTP credentials required in production`. The api Deployment's `envFrom` referenced only `configMapRef: api-config`, never `secretRef: api-secrets`, so `INFRA_SMTP_PASS` (present in the cluster Secret for 86 days) was never injected. `:dev` had no such guard; `1.1.0` added one. No outage — the rolling update held the old `:dev` pod Ready while the new one never became Ready.

**Problem**: The K8s generator's `_has_secret_vars` scanned `APPS_PLATFORM_<APP>_*` env vars for secret-name patterns to decide whether to mount `<app>-secrets`. Those keys come from SOPS, so the decision depended on whether SOPS was decrypted at generation time. The prod overlay had been committed from a SOPS-less `generate` → the keys were absent → `has_secrets=False` → no `secretRef`. Staging had been generated with SOPS → it had the mount all along. Same source, two outputs. The ADR-027 drift check runs in CI **without** SOPS, so it regenerated the same secret-less output and went green — the gate shared the generator's blind spot (false green). The heuristic was also blind to *shared* `INFRA_*` secrets (`INFRA_SMTP_PASS` lives under the `INFRA_` prefix, not `APPS_PLATFORM_API_`).

**Solution**: #666 — tie the mount to the secrets SSOT: `_has_secret_vars(component)` returns true iff a `<component>-secrets` mapping exists in `SECRET_DEFINITIONS`. No `env_vars` input → deterministic and SOPS-independent. CI and local now emit identical overlays, so the drift gate means something again. Regression test asserts the mount decision equals registry presence for every platform app, and that `web` (no secret) never mounts. Validated on staging: `api:1.1.0` boots Ready with `INFRA_SMTP_PASS` injected.

**Rule**: A generator's output must be a pure function of *committed* inputs — never of ambient state like "are secrets decrypted right now". To decide "does this thing exist", read the static SSOT (the definition/registry list), not a side effect of the environment. Corollary: an equality/drift gate is only as strong as the conditions it runs under — if generation can vary with SOPS, either run the gate with SOPS or (better) make generation SOPS-independent. And: *provisioning* a secret (it exists in the cluster) and *consuming* it (the workload references it) are two facts that can silently diverge — bind them at one source.

**Tags**: `#generator` `#determinism` `#sops` `#drift-gate` `#secrets` `#adr-046` `#adr-027` `#pr-666`

### [2026-06-15] Staging must run the same artifact AND mode as prod, or it is not a gate

**Context**: The `api:1.1.0` CrashLoop above reached prod despite staging existing. Staging ran the mutable `:dev` tag, not the `1.1.0` artifact promoted to prod; and staging runs `ENVIRONMENT=staging`, while the guard that fired was `required in production`.

**Problem**: Two independent axes of divergence each defeat the gate. (1) **Artifact**: staging on `:dev` never executes the image being shipped, so image-level regressions pass straight through. (2) **Mode**: even if staging ran `1.1.0`, the `production`-gated guard would not fire under `ENVIRONMENT=staging`, so production-only code paths stay dark. The ADR-027 drift gate verifies overlay *consistency*, not that the *container boots* — a different guarantee. A pre-prod environment that differs from prod in artifact or correctness-affecting behavior validates nothing about what actually ships.

**Solution**: Immediate cause fixed in #666. The parity gaps are tracked: knowledge#105 (staging runs the candidate immutable build, not `:dev`) and knowledge#106 (staging exercises production-mode guards — run prod-equivalent strictness, or de-gate *required-infra* guards in the app source `mlorente-backend` `internal/services/beehiiv.go`).

**Rule**: A staging/pre-prod environment may differ from prod ONLY in environment-specific values (domains, scale, `selfHeal`) — never in the artifact (run the same immutable tag you will promote) nor in correctness-affecting mode. If a guard is `if production`, staging won't catch it: make *required-infra* guards unconditional and keep only side-effectful behavior (live email, real charges) environment-gated.

**Tags**: `#staging` `#parity` `#promotion` `#gates` `#adr-046` `#adr-037` `#issue-105` `#issue-106`

### [2026-06-15] A mutable image tag needs an explicit `imagePullPolicy: Always` or it never re-pulls

**Context**: Both prod and staging ran the mutable `:dev` tag with `imagePullPolicy` never declared in the manifests. Staging silently defaulted to `IfNotPresent` and never re-pulled a freshly-pushed `:dev` — WEB-011 changes were not appearing on staging.

**Problem**: Kubernetes defaults `imagePullPolicy` to `IfNotPresent` for any tag other than `latest`. A mutable tag like `:dev` therefore sticks to whatever image the node first cached; new pushes to the same tag are ignored until the node forgets the image. The 2026-03-16 lesson about this had been learned but never enforced in the generator.

**Solution**: #657 (PR-B) — the generator now sets `imagePullPolicy` tag-aware: mutable tags (`dev`/`latest`/`*-rc.*`) → `Always`; immutable tags (`sha-*`/semver) → `IfNotPresent`. This unblocked the staging refresh and is the foundation for the ADR-046 model (immutable tags everywhere, so a tag change is always a real pull Argo reconciles).

**Rule**: Never run a mutable tag without `imagePullPolicy: Always`, and never leave `imagePullPolicy` to the default. Better still: prefer immutable tags (`sha-<short>`, semver) so the desired state *is* the tag — a change always forces a pull, `IfNotPresent` is correct, and `Always` is unnecessary.

**Tags**: `#kubernetes` `#imagepullpolicy` `#mutable-tags` `#adr-046` `#pr-657`

### [2026-06-15] Under `enforce_admins` branch protection, delivery must be PR-per-update opened with a PAT

**Context**: Both Argo CD apps (staging, prod) watch `master`, which is protected with `enforce_admins` → nobody, not even admins or automation, can push directly. Every deploy is a change to `master`, so every deploy must be a reviewed PR. (Same rework also dropped a broken RC version predictor.)

**Problem**: A delivery mechanism that assumes it can `git push` to the deploy branch breaks under `enforce_admins`. And a CI-opened PR using the default `GITHUB_TOKEN` does **not** trigger `on: pull_request` workflows, so its required checks never run and it can never merge — a silent deadlock. Separately, maintaining an RC version predictor alongside release-please created two semver authorities that drifted (RC behind stable, mis-nested staging override).

**Solution**: ADR-046 PR-per-update — staging auto-opens a deploy PR on each merge (`staging-deploy.yml`); prod opens a gated PR on `workflow_dispatch` (`promote-prod.yml`); both via `toolkit deployment promote`. The PRs are opened with a PAT (`RELEASE_PLEASE_TOKEN`), not `GITHUB_TOKEN`, so their checks run. release-please is the sole semver authority; the RC predictor was deleted.

**Rule**: When the deploy branch is `enforce_admins`-protected, delivery automation must **open PRs, not push** — and open them with a PAT so `on: pull_request` checks fire (a `GITHUB_TOKEN`-opened PR is un-mergeable by design). Keep exactly one semver authority (release-please); never run a parallel predictor that can disagree with it.

**Tags**: `#gitops` `#branch-protection` `#pr-per-update` `#github-token` `#release-please` `#adr-046`

### [2026-06-14] Merge Dependabot config changes BEFORE closing its PRs

**Context**: Added `.github/dependabot.yml` (#618) where none existed; on merge Dependabot opened a 14-PR burst of version updates. To cut churn I started closing the *grouped* PRs (#614 security group, #628 web-minor-patch group) before the follow-up calibration PR (#644 — sets `open-pull-requests-limit: 0` on departing ecosystems) was merged.

**Problem**: Closing a grouped Dependabot PR while the live config still permits that update makes Dependabot re-evaluate and recreate the group's members as **individual** PRs. Closing #614 + #628 exploded ~12 grouped updates into ~17 individual PRs (15 → 27 open), each queuing CI on the single self-hosted runner — a cleanup turned into a recreation storm. Separately, the version-update `ignore` (astro major) does **not** suppress **security** updates: astro 5.x had 3 advisories fixed only in astro 6, so astro→6 PRs reappeared regardless of the ignore.

**Solution**: Stopped closing. Cancelled the queued Dependabot CI runs (`gh run list ... | while read id; do gh run cancel "$id"; done`, filtered to `headBranch` starting `dependabot/`) to free the runner for #644. Correct order: (1) merge the config that disables the updates, (2) then close the stragglers — once `limit: 0` is live they do not recreate. For the security-driven astro PRs the lever is dismissing the Dependabot alert (accept-risk, tracked) or doing the upgrade — `ignore` won't stop them.

**Rule**: Change Dependabot's *config* first, close its *PRs* second. Never close a grouped Dependabot PR while the live config still permits that update — it ungroups into individual PRs. And remember `ignore: version-update:semver-major` does not block security updates; suppress those by dismissing the alert, not via ignore rules. Bonus (runner): a single on-demand self-hosted runner has no autoscaling/fallback headroom — a flood (or a powered-off host) blocks the whole queue. Tracked as OPS-005 (GitHub-hosted fallback); K8s HPA does not apply (runner is a Docker Compose service on Beelink, not a pod — ARC would be the K8s-native autoscaler).

**Tags**: `#dependabot` `#ci` `#gotcha` `#ordering` `#self-hosted-runner` `#pr-618` `#pr-644`

### [2026-06-14] caronc/apprise OOMKilled on k8s — cap APPRISE_WORKER_COUNT, don't inherit the host-core default

**Context**: Deploying the Apprise delivery gateway (NOTIFY-001, ADR-044) as a cluster-internal `Deployment` on staging (ace1, a multi-core k3s node) with a 256Mi memory limit.

**Problem**: The pod CrashLooped — `OOMKilled` (exit 137), 4 restarts, readiness `/status` never came up (connection refused → EOF → timeout). The `caronc/apprise` (apprise-api) image runs gunicorn with `APPRISE_WORKER_COUNT` defaulting to `(2 * CPUS_DETECTED) + 1`. On a multi-core node that spawns ~9-17 workers, each loading the Apprise library, blowing past 256Mi before the app can serve `/status`. The cgroup memory limit (256Mi) is tiny relative to what the node's core count implies, so the image default is wrong for k8s.

**Solution**: Set `APPRISE_WORKER_COUNT: "2"` in the ConfigMap (the image docs explicitly recommend lowering it for lightweight use) and sized the memory limit to 384Mi for 2 workers + startup headroom. Re-applied the manifest declaratively (`kubectl apply -f`, no live-pod patching); the fresh pod reached Ready in ~20s and `/status` returned 200 OK.

**Rule**: For container images whose worker/process count auto-scales with detected CPUs (gunicorn, uwsgi, `nginx worker_processes auto`, etc.), pin the worker count explicitly in the manifest — never inherit the host-core default under a k8s memory limit. Then right-size memory to the *pinned* worker count, not the image default.

### [2026-05-26] Comment-vs-implementation drift — pair "auto-filled" comments with executable tests

**Context**: This session surfaced the same pattern twice. (1) `infra/config/values/common.yaml:477` had the comment `# admin_email auto-filled from apps.contact.email by the config loader (SSOT-014c)`, but `toolkit/features/configuration.py:_inject_contact_email_derivations` only filled 3 consumers (acme_email, uptime_kuma, Authelia admin) — Gitea was missing. Result: `make apply-secrets ENV=prod` warned `Missing values: ADMIN_EMAIL`, and the prod gitea pod entered `CreateContainerConfigError` for 76 minutes after the first restart that touched the new SECRET_CATALOG entry. (2) `toolkit/scripts/sync_oidc_hashes.py` docstring promises "Sync OIDC client_secret hashes from SOPS into Authelia K8s ConfigMap YAMLs", but its `FILE_PATHS` dict still points to `infra/k8s/overlays/prod/patches.yaml` after PR #225 moved the OIDC clients block to `infra/k8s/overlays/prod/authelia-config/configuration.yml`. The regex misses, the script reports `"OK: gitea hash already current in patches.yaml"` and exits 0 — false success.

**Problem**: Documentation comments are written at the moment a behavior is intended; implementation can drift around them and the comment becomes a false promise. There is no mechanism (linter, test, ADR review) that forces comment-vs-code alignment. The "auto-filled", "synced", "validated" verbs in particular are dangerous because they invite the reader to trust an invariant that is not enforced anywhere. Both bugs above had **zero CI signal** until manual smoke caught them.

**Solution**: For SSOT-019 (PR #226) added explicit parametrized tests in `tests/test_credentials_reconcile.py::TestSSOTContactEmail` that assert each derivation (`acme_email`, `uptime_kuma.admin_email`, `gitea.admin_email`, Authelia admin user) literally equals `apps.contact.email`. The test is the executable form of the comment — if someone removes the derivation later, the test fails before the comment lies. For OIDC-SYNC-001 (tracked) the corresponding fix is `RuntimeError` when the script's regex misses entirely, plus a regression test that `FILE_PATHS` points to a file containing the expected pattern.

**Rule**: Every comment that asserts a behavior ("X is auto-filled from Y", "Z is synced via this script", "field W is validated at load") MUST have a sibling test that asserts that exact behavior. Treat the comment as a hypothesis and the test as its proof. The cost is one test per assertion; the value is that the comment becomes self-verifying — future contributors who break the invariant will see a failing test before they see a misleading comment. Anti-pattern: writing the comment alone and trusting future readers to enforce it.

**Tags**: `#patterns` `#testing` `#documentation` `#drift` `#ssot-019` `#oidc-sync-001`

### [2026-05-26] OIDC `token_endpoint_auth_method` must be declared explicitly on every client

**Context**: Discovered during manual OIDC smoke after PR #225/#226/#227. Browser flow `gitea.kubelab.live → Sign in via Authelia` returned `invalid_client` with the message: *"The request was determined to be using 'token_endpoint_auth_method' method 'client_secret_post', however the OAuth 2.0 client registration does not allow this method."* Root cause: Authelia 4.39.x defaults the per-client `token_endpoint_auth_method` to `client_secret_basic` when the field is absent, but Gitea 1.25.x sends credentials in the POST body (`client_secret_post`). The server rejected the token request. Pre-existing bug, latent for at least one release cycle — no automated test exercises the interactive OIDC code flow (the existing `auth_flow.py` only exercises ForwardAuth via cookie sessions, never the `/token` endpoint).

**Problem**: OIDC client registrations rely on implicit defaults that differ between (a) the identity provider's version, (b) the relying party's version, and (c) the OAuth 2.0 spec's "default to whatever". Authelia and Gitea picked different defaults; the mismatch only manifests at the token exchange step, which automated ForwardAuth tests never reach. Worse, the same shape applies to other fields with version-dependent defaults: `id_token_signed_response_alg`, `userinfo_signed_response_alg`, `response_types`. Any of them could break silently in a future bump.

**Solution**: PR #227 declared `token_endpoint_auth_method` explicitly on all 4 clients in both staging and prod `configuration.yml`: `gitea → client_secret_post` (the fix), `minio | grafana | argocd → client_secret_basic` (the current implicit default, declared explicitly so a future Authelia upgrade that changes the default cannot silently break them too). Inline comment on the gitea client documents why it differs.

**Rule**: For any OIDC client registration, declare every field whose default has differed historically across versions of the IdP — even when the implicit default works today. The cost is 3-5 lines per client; the value is that a version bump (Authelia 4.39 → 4.40 → 5.x) cannot silently break the integration. Generalizes to any client/server protocol with negotiable defaults: HTTP/2 settings, TLS cipher suites, JWT algorithms. The principle is "declare your intent, do not rely on implicit defaults". Pairs with OIDC-E2E-001 (programmatic code-flow tests) which catches the runtime failure even when the declaration is missing.

**Tags**: `#authelia` `#oidc` `#gotcha` `#version-defaults` `#pr-227`

### [2026-05-26] Silent-success anti-pattern in regex-based mutation tooling

**Context**: `toolkit/scripts/sync_oidc_hashes.py` uses a regex to find/replace `client_secret:` lines in Kubernetes YAML files. When PR #225 moved the OIDC clients block from `patches.yaml` to a new `authelia-config/configuration.yml`, the script's `FILE_PATHS` dict was not updated. The regex now matches **nothing** in the targeted file. But the script's caller compares `if new_content != content:` — when the regex misses entirely, `new_content == content` (the function returns the input unchanged) and the script prints `"OK: gitea hash already current in patches.yaml"`. Indistinguishable from "no change needed".

**Problem**: The "no change needed" path and the "I could not find anything to change" path collapse into the same observable behavior. The operator sees green, assumes sync was successful, and moves on. Drift accumulates invisibly. In this case it caused a multi-hour debug session because the symptom (`invalid_client` from Gitea OIDC) was 3 hops removed from the cause (script silently no-op'd → SOPS plaintext didn't propagate → Gitea stored a stale plaintext → token verification failed). The same shape applies to any mutation tool that uses pattern-matching without explicit assertion of "I found the target".

**Solution**: Tracked as OIDC-SYNC-001 in `11-tasks.md`. Fix has two parts: (a) update `FILE_PATHS` to point to the new authelia-config files, (b) raise `RuntimeError` if `update_client_secret()`'s regex does not match the input — never silently return unchanged content. Also added a regression test that asserts `FILE_PATHS` values exist and contain the expected `client_secret:` pattern, so a future refactor that moves the file will fail fast at test time, not at production debug time.

**Rule**: For any tool that does pattern-based mutation (regex find-replace, AST modification, YAML key edits), the "I could not find the target" path MUST be a hard failure with a distinct exit code, never the same code path as "no change needed". Explicit assertion: `assert match, f"Pattern {pattern} not found in {file_path}"`. The cost is one line; the value is that path drift caused by refactors elsewhere in the codebase cannot silently break the tool. Bonus: when the tool's output is "X updated" vs "FAILED: pattern not found", the operator gets actionable signal immediately instead of false reassurance.

**Tags**: `#anti-pattern` `#tooling` `#silent-failure` `#oidc-sync-001`

### [2026-05-23] Fail-closed fixtures in security E2E suites

**Context**: AI-002 PR #201 added `ollama_api_key` fixture in `tests/e2e/conftest.py` that returned `None` when SOPS decryption failed or `apps.services.ai.ollama.api_key` drifted. Three prod auth-path tests (`health_authenticated`, `bearer_forward_compat`, `no_key_leak_in_403_body`) handled the None with `if not ollama_api_key: pytest.skip(...)`.

**Problem**: Codex flagged P1. The skip semantics ("this condition doesn't apply") is wrong for a missing-input scenario that should ALWAYS be present in prod. A broken SOPS pipeline = silent green CI run, exactly the regression the suite was supposed to catch. `pytest.skip` ≠ fail-closed; in security suites, skipping = false reassurance.

**Solution**: Moved the policy into the fixture itself (PR #202): `pytest.fail(...)` when `env == "prod"` and key is missing/unresolved. Staging/dev keep returning None — auth-gated tests already gate themselves out via the `env != "prod"` check. Tests dropped the duplicate skip guards and `assert key is not None` instead.

**Rule**: For security E2E fixtures with env-dependent invariants, the FIXTURE owns the invariant — never the test body. "If condition X must hold in env Y, the fixture must `pytest.fail` (not `pytest.skip`) in env Y when X fails." Skips are reserved for "this test doesn't apply here", never "this input is missing but I don't want to fail". Centralizing the invariant in one place prevents future contributors from re-introducing fail-open behavior via duplicated checks.

### [2026-05-23] Generated-then-committed configs drift silently — regen-and-diff periodically

**Context**: SEC-AUDIT-003 (closed 2026-03-28) ensured prod IngressRoutes use the `secure-headers` middleware. Two months later (2026-05-23), AI-002 E2E verification surfaced 3 failures — `test_security_headers_present[api|web]` + `test_hsts_header[web]`. Root cause: `infra/k8s/overlays/prod/generated/ingress.yaml` had only `[error-pages]` on api+web routes; the toolkit generator always emits `[secure-headers, error-pages]`. The committed prod file was stale relative to the generator code.

**Problem**: Two failure modes for "generator-emitted, committed-to-repo" files: (a) generator code evolves but stale committed files were never regenerated, (b) someone hand-edits a generated file. Either way, `kubectl apply -k` uses the stale file, the live cluster diverges from generator-implied invariants, and tests that assert on those invariants fail months after the original closure. The discrepancy is invisible unless someone reruns the generator.

**Solution**: `make config-generate ENV=prod` produced a clean 2-line diff (PR #204) — secure-headers added to api+web. Only `ingress.yaml` had drifted; deployments, services, configmaps, terraform, traefik, ansible, authelia configs all matched current generator output.

**Rule**: For any generator-emitted file committed to repo, schedule periodic regen-and-diff. Either: (a) manual review monthly (low cost, high friction, susceptible to skipping), or (b) **CI gate that runs `config-generate` in dry-run and fails if `git diff` is non-empty** (eliminates human-discipline tax, makes committed-generated files trustworthy by construction). Backlog: CI-GATE-002 in `11-tasks.md`. The trigger for prioritizing the CI gate is "this pattern surfaced once" — drift-detection-by-accident does not scale.

### [2026-05-23] Auth-boundary E2E pattern: positive + sentinel-negative + leak-grep triple

**Context**: AI-002 introduced 5 E2E cases for the X-API-Key-gated `ollama.kubelab.live` endpoint (Traefik api-key plugin, prod-only). The auth-validation cases resemble a cheap-but-comprehensive proof harness for any plugin-protected service. Same shape applies to AI-004 (Pollex) and DT-004 (widget-proxy) when those land.

**Problem**: Naive auth tests check only `with key → 200`. That proves "plugin happy on correct input" but doesn't prove rejection — a misconfigured plugin that accepts ANY key passes the test. Adding `without key → 403` is the obvious second case but still has a blind spot: a plugin that accepts header *presence* (regardless of value) passes both. And neither catches the rare-but-catastrophic regression where the plugin echoes the candidate key in its error body.

**Solution**: Three orthogonal cases per protected endpoint:

1. **Positive**: `with correct-key → 200` (backend reachable + happy path).
2. **Sentinel-negative**: `with hardcoded-wrong-key → 403`. Sentinel string is HARDCODED in the test (`_WRONG_KEY_SENTINEL = "definitely-not-the-real-key"`), NEVER sourced from SOPS — that decoupling makes the test invariant under key rotation. Proves the middleware validates the *value*, not just header presence.
3. **Leak-grep**: `with hardcoded-wrong-key, assert real-key-from-SOPS not in response body`. Catches the rare echo-the-candidate-key regression.

**Rule**: For every plugin-gated public endpoint, codify the triple. The sentinel-negative is the "test-of-the-test" — its only failure mode is the middleware regressing to accept arbitrary keys, no manual security drill needed. The leak-grep is dirt-cheap (one string comparison) but catches a class of mistake that's invisible to positive+negative testing alone.

### [2026-05-06] Argo CD hub OOM cascade on aws1 (t4g.small Spot)

**Context**: aws1 (Argo CD hub on AWS, t4g.small Spot, 2 GB RAM with 2 GB swap) became unreachable after 12h uptime. `argo.kubelab.live` returned timeouts then 502. Tailscale showed aws1 as offline ~6h. SSH refused.

**Problem**: EC2 status `running / impaired`. Console output showed `Out of memory: Killed process 19332 (coredns)`. CoreDNS death cascaded: cluster DNS dead → controllers retry-loop → memory pressure → systemd unable to create cgroup slices for new pods → kubelet stuck → Tailscale heartbeat starved → instance marked impaired by AWS. Underlying enabler: hundreds of zombie `argocd-applicationset-controller` pods (statuses `Completed`/`ContainerStatusUnknown`/`ContainerCreating` from 9-14 days ago) inflating etcd and apiserver list bandwidth. K3s default `terminated-pod-gc-threshold=12500` never triggered cleanup on a 1.8 GB node. No resource `limits` on Argo CD components — OOM Killer picked CoreDNS at random.

**Solution**: (1) Reboot via `aws ec2 reboot-instances` to clear wedged kernel. (2) Scale all Argo CD Deployments + StatefulSet to `replicas=0` to relieve immediate memory pressure (persists in etcd, survives reboot). (3) Second reboot on the now-quiet system for a clean K3s baseline. Argo CD remained at 0 replicas overnight; `argo.kubelab.live` returning 502 was the accepted trade-off until the permanent fix lands as RELIAB-009.

**Rule**: For undersized nodes (< 4 GB) running Helm-managed control planes, three configuration changes are non-optional:
1. Explicit resource `requests` + `limits` on every Deployment. Without them, OOM Killer chooses victims at random and kernel-critical pods (CoreDNS, kubelet daemonsets) die first instead of the offender.
2. `revisionHistoryLimit: 1` on all Deployments to bound the ReplicaSet graveyard. Default 10 multiplies pod-object pressure on etcd.
3. Override K3s `--kube-controller-manager-arg=terminated-pod-gc-threshold=N` to ≤ 200. The 12500 default assumes large clusters.

Operational note: for "always-on" workloads on Spot, design for the fact that AWS will reclaim. Stable identity comes from Tailscale MagicDNS (`<host>.kubelab.internal`), never public IPs. The first proximate signal of a wedged spot is `tailscale status` showing the node as `offline, last seen Nh ago` while EC2 still reports `running / impaired` — combined, that pair is diagnostic.

### [2026-03-22] show_secret must bypass ConfigurationManager for env='common'

**Context**: Building `toolkit secrets show cloudflare.api_token --env common` for the `tf-dns-apply` Makefile target. Cloudflare API token lives in `common.enc.yaml`, not in any env-specific file.

**Problem**: `show_secret` used `ConfigurationManager._decrypt_sops()` which only supports real environments (dev/staging/prod). `env='common'` isn't a valid environment — it's a cross-env secrets file. Additionally, the CLI's `validate_environment()` call rejected "common" before `show_secret` was even reached.

**Solution**: Refactored `show_secret` to use direct `sops -d` subprocess call, building the path explicitly as `secrets_path / f"{env}.enc.yaml"`. The `set` command already used its own validation tuple `("common", "dev", "staging", "prod")` — the `show` command needs the same pattern.

**Rule**: When toolkit commands need to operate on `common.enc.yaml`, bypass `ConfigurationManager` and use direct SOPS CLI. Always include "common" in environment validation for secrets commands. The set command got this right from the start — show was the oversight.

### [2026-03-19] Toolkit kubeconfig path must be env-parameterized

**Context**: Running `toolkit infra k8s deploy --env staging` after Ansible generates per-env kubeconfigs at `~/.kube/kubelab-{env}-config`.

**Problem**: `_get_kubeconfig()` in `toolkit/cli/infra.py` used a hardcoded path `~/.kube/kubelab-config` (no env suffix). Ansible generates `kubelab-staging-config`, `kubelab-prod-config`, etc. The toolkit could never find the right kubeconfig for any env unless `KUBECONFIG` env var was set manually.

**Solution**: Replaced hardcoded `_K8S_DEFAULT_KUBECONFIG` with `_K8S_KUBECONFIG_PATTERN = "~/.kube/kubelab-{env}-config"`. `_get_kubeconfig()` now requires an `env` argument. `KUBECONFIG` env var still takes precedence.

**Rule**: Any path that varies by environment must be parameterized with `{env}`, not hardcoded. When Ansible generates env-specific outputs, the toolkit must use the same naming convention. Check path alignment whenever adding a new env-aware resource.

### [2026-03-15] Docker network names must be project-namespaced

**Context**: VPS Docker network was named `"proxy"` — copied from a common Traefik tutorial pattern. Homelab used `"kubelab"` (from `network_name` in common.yaml).

**Problem**: Generic name `"proxy"` risks collision with other tools, is not project-namespaced, and is inconsistent across environments. During ADR-020 Ansible migration, the inconsistency caused confusion about which network config was canonical.

**Solution**: Renamed to `"kubelab"` everywhere. The network's purpose (connecting services to Traefik) is implied by architecture, not the name. Rename was done during Ansible rebuild (requires stopping all containers).

**Rule**: Docker network names must be project-namespaced (e.g., `"kubelab"`, not `"proxy"`). Never use generic tutorial names in production. Align naming across all environments via the SSOT config (`common.yaml`).

### [2026-03-19] Uptime Kuma container caches DNS — restart after DNS changes

**Context**: After migrating staging DNS from Cloudflare to Headscale split DNS + CoreDNS, Uptime Kuma monitors showed staging services as "down" (404) despite `curl` from RPi3 host returning 200.

**Problem**: Docker containers inherit `/etc/resolv.conf` at start time. Uptime Kuma's Node.js runtime caches DNS and HTTP connections. After DNS infrastructure changes (new zones, IP changes), the container keeps using stale resolution until restarted.

**Solution**: `docker restart uptime-kuma` on RPi3. All monitors recovered immediately.

**Rule**: After any DNS infrastructure change (split DNS zones, CoreDNS config, IP changes), restart monitoring containers. Add to ANSIBLE-018 maintenance playbook.

### [2026-03-19] Jetson Nano loses IP on DHCP failure — use static nmcli config

**Context**: Jetson Nano (`kubelab-jet1`) went offline. No LAN or Tailscale response despite being powered on.

**Problem**: `eth0` was UP but had no IPv4 address — only link-local IPv6. NetworkManager connection `cubelab` was stuck in "connecting (getting IP configuration)" state. DHCP from RPi4 Pi-hole wasn't responding (reservation exists but DHCP server didn't assign).

**Solution**: `sudo nmcli connection modify cubelab ipv4.method manual ipv4.addresses 172.16.1.4/24 ipv4.gateway 172.16.1.1 ipv4.dns 172.16.1.1 && sudo nmcli connection up cubelab`. Survives reboot.

**Rule**: Jetson Nano (Ubuntu 18.04, NetworkManager) should use static IP via nmcli, not DHCP. DHCP reservations are fragile on this hardware. Document in ANSIBLE-014.

### [2026-03-19] deploy-dns.yml must read from common.yaml, not merged config

**Context**: RPi4 CoreDNS serves DNS for ALL environments (staging + prod zones). Running `make deploy TARGET=dns ENV=staging` loaded staging.yaml override which sets `base_domain: staging.kubelab.live`.

**Problem**: The playbook derived `staging_domain = "staging." + base_domain` → `staging.staging.kubelab.live` (double prefix). The prod zone block also got `staging.kubelab.live` instead of `kubelab.live`. Services appeared to work because the wildcard `template` plugin caught queries despite the wrong zone name.

**Solution**: Read `base_domain` and all node IPs from `common` (raw common.yaml vars) instead of `config` (merged env override). RPi4 is env-independent — it serves all zones from a single config.

**Rule**: Multi-env DNS gateways must not depend on `--env` config merging. Use `common.*` for values that are env-independent (base domain, node IPs, service domains).

### [2026-03-19] Pi-hole conditional forwarding must include all CoreDNS zones

**Context**: Added `staging.mlorente.dev` zone to CoreDNS Corefile. DNS queries from Tailscale MagicDNS resolved correctly, but queries from inside Docker containers on RPi3 returned NXDOMAIN.

**Problem**: Pi-hole sits in front of CoreDNS on RPi4. `pihole-forwarding.conf` only had `server=/kubelab.live/...` — no forwarding for `staging.mlorente.dev`. Queries for non-kubelab domains went to upstream DNS (1.1.1.1) instead of CoreDNS.

**Solution**: Add `server=/staging.mlorente.dev/172.17.0.1#5353` to pihole-forwarding.conf. Now driven by `staging_zones` loop in template.

**Rule**: Every CoreDNS zone must have a matching Pi-hole forwarding entry. Use the `staging_zones` SSOT list to generate both in lockstep.

### [2026-03-19] nftables `flush ruleset` is incompatible with Docker/UFW/Tailscale

**Context**: RPi4 gateway role uses nftables for NAT masquerade. Template had `flush ruleset`.

**Problem**: `systemctl restart nftables` triggers ExecStop which runs `flush ruleset`, destroying ALL iptables-nft rules from Docker, UFW, and Tailscale. CoreDNS containers lose port mappings, LAN nodes lose internet, VPN routing breaks. Even removing `flush ruleset` from our template doesn't help — the systemd unit's ExecStop still flushes.

**Solution**: (1) Use a named table (`inet kubelab`) instead of generic `inet nat`/`inet filter` — avoids collision with Docker's `ip nat`. (2) Use `systemctl reload` (ExecReload = `nft -f`), NEVER `restart` (ExecStop = `flush ruleset`). (3) Atomic idempotent pattern in nftables.conf: `table inet kubelab` (create if missing) → `delete table inet kubelab` → `table inet kubelab { ... }` (recreate fresh).

**Rule**: Never use `flush ruleset` in nftables configs on hosts running Docker. Never `restart` nftables — always `reload`. Use named tables to isolate your rules from other services.

### [2026-03-19] UFW FORWARD policy must be ACCEPT on gateway nodes

**Context**: RPi4 acts as LAN gateway (NAT + DHCP + DNS). base_system role installs UFW with default FORWARD DROP.

**Problem**: LAN nodes could resolve DNS (goes to RPi4 INPUT chain, Pi-hole/CoreDNS containers) but couldn't reach internet (requires FORWARD through RPi4 to uplink, dropped by UFW).

**Solution**: Gateway role sets `DEFAULT_FORWARD_POLICY="ACCEPT"` in `/etc/default/ufw` + reload. This is standard for routers — filtering happens at INPUT (perimeter), not FORWARD.

**Rule**: Any node acting as a router/gateway must have UFW forward policy ACCEPT. Add this to the gateway role, not base_system (only gateway nodes need it).

### [2026-03-19] Docker GPG key: never delete .asc on re-runs

**Context**: Docker role migrated from deprecated `apt_key` (.gpg) to `get_url` (.asc). Role deleted BOTH .gpg and .asc on every run, then re-downloaded .asc.

**Problem**: Delete-and-recreate cycle leaves apt in inconsistent state. `apt_repository` sees conflicting Signed-By values (ghost .gpg reference in cached source vs new .asc). Fails with `E:Conflicting values set for option Signed-By`.

**Solution**: Only delete legacy .gpg (and .gpg~ backup). Leave .asc untouched. Only clean source files when migrating (`.gpg` was changed → old sources need cleanup). `get_url` is naturally idempotent — doesn't re-download if file exists.

**Rule**: When migrating key formats, only remove the OLD format. Never delete-and-recreate the current format — it breaks idempotency.

### [2026-03-19] apt_repository on Ubuntu 24.04 generates non-obvious filenames

**Context**: Docker role cleaned `rm -f /etc/apt/sources.list.d/docker*` to remove old Docker sources.

**Problem**: `apt_repository` on Ubuntu 24.04 generates filenames based on the repo URL, not the package name. Docker's source file is named `download_docker_com_linux_ubuntu.list`, not `docker.list`. The glob `docker*` missed it.

**Solution**: Use Ansible `find` module with pattern `*docker*` (matches substring) instead of shell glob `docker*` (matches prefix only).

**Rule**: When cleaning apt sources, search by substring (`*docker*`), not prefix (`docker*`). Better yet, use `find` module for reliable matching.

---

## Registry

### [2026-03-15] Headscale v0.28 works with HTTP proxy (not TCP passthrough)

**Context**: VPN health endpoint broken, Uptime Kuma alerting. TCP passthrough config routed to headscale:443 where nothing listened.

**Problem**: Blog note said TCP passthrough was required for Noise protocol. Testing showed HTTP proxy (Traefik terminates TLS, forwards HTTP to headscale:8080) works perfectly with v0.28. The original TCP passthrough failure was likely a port mismatch, not a protocol incompatibility.

**Solution**: Changed Traefik dynamic config from TCP passthrough to HTTP proxy. Health endpoint (`/health`), control plane, and all Tailscale clients work correctly.

**Rule**: Don't treat past workarounds as permanent truths. Re-test assumptions when debugging — the original constraint may no longer apply. Headscale v0.28 docs explicitly recommend HTTP proxy with WebSocket upgrade support.

### [2026-03-15] Headscale extra_records only work for domains under its zones

**Context**: Trying to add `staging.mlorente.dev` as Headscale extra_record for VPN-only DNS resolution.

**Problem**: `extra_records` in Headscale only serves records for domains under its configured zones (`kubelab.live`, `kubelab.vpn`). External domains like `mlorente.dev` are delegated to global nameservers (1.1.1.1) — the extra_record is ignored.

**Solution**: Use Cloudflare DNS A record pointing to Tailscale IP (100.64.0.4). Non-routable from internet, works for VPN clients. Managed via Terraform.

**Rule**: For VPN-only staging domains on external zones, use Cloudflare DNS (not Headscale extra_records). Headscale extra_records only for `*.kubelab.live` bare-metal services.

### [2026-03-15] Strategy pivot: single lead magnet, build-in-public, execution over planning

**Context**: After 7 days of strategy sessions (2026-03-08 to 2026-03-15), 25 decisions locked, 130+ emails analyzed, 8 competitors studied, dual lead magnet designed (NODO + ROMPE), full copy written and implemented — but 0 content published, 0 videos recorded, web not deployed.

**Problem**: Honest assessment revealed critical gaps between plan assumptions and reality:
- 0 subscribers, 0 certs, 0 published content, 0 video experience
- Plan assumed "expert teaches" positioning but reality is "experienced engineer starting from scratch in content"
- Dual lead magnet (NODO + ROMPE) from day 1 is overengineering with 0 audience data
- NODO's pitch ("everything you see here is documented") points to an empty site
- YouTube as single discovery channel (LinkedIn blocked by employer) = fragile SPOF
- Every additional strategy session delays the first published video

**Solution**:
1. **Single lead magnet**: ROMPE T1 only at launch. NODO deferred until 15+ videos + organic demand.
2. **Build-in-public positioning**: Not "expert teaches" nor "beginner learns" — "practitioner who builds and shows." Honest, no impostor syndrome, proven audience model (Mischa/KubeCraft pattern).
3. **ES homepage CTA**: Points to ROMPE-T1 or DIRECT tag, not NODO.
4. **Execution priority**: Deploy web → configure Beehiiv → record first video → publish. Everything else is Day 2.
5. **NODO activation criteria**: 15+ videos published, notes visible on site, organic demand detected.

**Rule**: Planning without publishing is procrastination with extra steps. The vault, the strategy docs, the copy — all of it is worthless until the first video is live. Set a hard date for first publish and work backwards from it. One lead magnet at launch. Scale when you have data.

### [2026-02-03] Task System Initialization

**Context**: Setting up the project after a period of inactivity.

**Problem**: 655 files staged without committing, documentation misaligned with reality.

**Solution**: Create task system per global CLAUDE.md, detailed plan before executing.

**Rule**: Always keep `tasks/todo.md` up to date. Never accumulate more than 1 sprint of uncommitted changes.

### [2026-02-05] Code Bugs Masked as Documentation Issues

**Context**: Full project audit before Sprint 0.

**Problem**: The previous plan treated everything as "align documentation" but there were real code bugs:
- Toolkit references `docker-compose.{env}.yml` in 6 files, but actual files are `compose.{base|dev|staging|prod}.yml`
- `toolkit edge` imported but never registered in CLI
- `toolkit apps` removed but documented as active
- `pre-push.sh` runs `task lint` without an existing Taskfile

**Solution**: Split Sprint 0 into 0A (fix code) → 0B (align docs) → 0C (validate+commit).

**Rule**: Always audit executable code before touching documentation. A `grep -rn` of critical patterns is worth more than 14 documentation tasks.

### [2026-02-05] ConfigurationManager vs Direct File References

**Context**: Discovering why some toolkit operations would work and others wouldn't.

**Problem**: `configuration.py:144-168` has the correct logic (compose.base.yml + compose.{env}.yml with legacy fallback), but 4 CLI modules build filenames directly without using ConfigurationManager.

**Solution**: Identify and migrate all modules to use ConfigurationManager.get_compose_files().

**Rule**: Single source of truth for file resolution. Never build compose paths in more than one place. If an abstraction exists, use it.

### [2026-02-05] Plan Scope vs Execution Capacity

**Context**: Project with 655 uncommitted files and a 6-month roadmap including K3s, CKA, 60 ADRs.

**Problem**: Previous plan included K3s migration, certification, newsletter targets, GitHub org migration — all while the project couldn't even commit its code.

**Solution**: Reduce horizon to 3 executable months, move all aspirational items to tiered backlog.

**Rule**: A plan you can't execute within 2 sprints is fantasy, not engineering. Trim aggressively.

### [2026-02-09] Docker Anonymous Volumes Inherit Image Ownership

**Context**: Building Docker images for web apps (Astro, Jekyll).

**Problem**: The build stage runs as root, creating `node_modules/`, `.vite/`, `.astro/` with root ownership. Even though compose has `user: "1000:1000"`, anonymous volumes created during build retain root ownership, causing permission errors at runtime.

**Solution**: Use `USER node` in the Dockerfile build stage, not just the `user:` directive in compose. Volumes must be created with the correct user from the start.

**Rule**: Always verify ownership of anonymous volumes in multi-stage images. `docker compose exec <svc> ls -la /app/` before looking for code bugs.

### [2026-02-09] Staging Must Mirror Prod Architecture

**Context**: Designing a staging environment on homelab with Raspberry Pis.

**Problem**: If prod is a single-VPS with Docker Compose, staging must be single-node with Docker Compose. Using RPis as stack nodes introduces architectural differences that invalidate staging→prod validation.

**Solution**: MiniPC B = staging (VPS mirror). RPis = cross-cutting infrastructure (VPN, DNS, external monitoring), NOT stack nodes.

**Rule**: staging == prod in architecture. Auxiliary infra (VPN, DNS, monitoring) lives on separate nodes to avoid contaminating validation.

### [2026-02-09] Tailscale Over WireGuard When No Port Forwarding

**Context**: Configuring VPN for remote access to the homelab.

**Problem**: WireGuard requires an open UDP port on the router. Without router access (NAT without port forwarding) → WireGuard is impossible. Headscale requires a public node.

**Solution**: Tailscale (or Headscale via public relay). Network constraints dictate the technology, not preference.

**Rule**: Before choosing a VPN, verify: do I have port forwarding? Yes → WireGuard. No → Tailscale/Headscale. Network architecture decides.

### [2026-02-09] Ansible Templates Drift from Code

**Context**: Auditing Ansible templates after major refactoring (infra/compose → infra/stacks).

**Problem**: Templates in `infra/ansible/templates/` still reference `infra/compose`, K3s ports (6443), wiki, n8n, wireguard. Templates silently diverge when the repo is refactored without updating Ansible.

**Solution**: Audit templates every time the project structure changes. Include Ansible in the refactoring checklist.

**Rule**: Ansible templates are first-class citizens. A refactoring is not complete until Ansible templates are aligned.

### [2026-02-09] OS Choice Matters for Staging

**Context**: Choosing the OS for the staging node in the homelab.

**Problem**: If staging runs Arch Linux (rolling release) and prod runs Ubuntu Server (LTS), there's an entire class of "works in staging, fails in prod" bugs caused by kernel, libc, and package differences.

**Solution**: Staging OS == Prod OS. Both Ubuntu Server 24.04 LTS.

**Rule**: Staging must be identical to prod in OS, version, and base configuration. OS differences are bugs waiting to manifest.

### [2026-02-10] Always Verify Hardware Specs Against Physical Devices

**Context**: Planning the homelab architecture (Stream B) using documented hardware specifications.

**Problem**: Documented specs were incorrect: 16GB for staging (actual: 12GB Acemagic), 4GB for RPi 4 (actual: 8GB). Additionally, devices were missing: RPi 3 with Pi-hole, Beelink with Proxmox. All planning was based on wrong data.

**Solution**: Physically verify each device (`free -h`, `lsblk`, model labels) before documenting or planning. Update all documentation (vault, todo.md, Ansible templates) with actual specs.

**Rule**: Before planning infrastructure, ALWAYS verify hardware specs against physical devices. Documents lie; `free -h` doesn't. A plan based on incorrect specs is worse than no plan.

### [2026-02-14] YAML Duplicate Keys Silently Overwrite

**Context**: Adding gitea domain override to dev.yaml under `apps.services.core`.

**Problem**: Created a second `core:` block instead of adding to the existing one. YAML silently uses the last occurrence, wiping traefik/portainer/n8n overrides. Portainer started routing to `kubelab.live` instead of `kubelab.test`.

**Solution**: Always search for existing key before adding new entries. YAML does NOT merge duplicate keys.

**Rule**: When editing YAML overrides, verify with `python3 -c "import yaml; print(yaml.safe_load(open('file.yaml')))"` that keys aren't duplicated.

### [2026-02-14] Docker Bind Mounts Resolve from Compose File Directory

**Context**: web and blog containers in restart loop, `package.json` / `Gemfile` not found.

**Problem**: Containers were created from `/home/manu/Projects/mlorente.dev/` (old project path). Relative bind mount paths (`../../../../apps/web/`) resolved to non-existent location.

**Solution**: Recreate containers from the correct working directory (`/home/manu/Projects/kubelab/`).

**Rule**: After renaming project directories, always recreate (not just restart) containers that use relative bind mounts.

### [2026-02-20] Proxmox Hostname Rename Breaks VM Visibility

**Context**: Renaming hostnames from `cubelab-*` to `kubelab-*` as part of the global project rename.

**Problem**: After `hostnamectl set-hostname kubelab-ace1`, `qm list` returns empty. VMs appear to have vanished. Proxmox ties VM `.conf` files to the directory `/etc/pve/nodes/{hostname}/qemu-server/`. When the hostname changes, Proxmox creates a new directory but configs remain in the old one.

**Solution**: Move the `.conf` files from the old directory to the new one:
```bash
ls /etc/pve/nodes/                    # You'll see old-name and new-name
mv /etc/pve/nodes/{old}/qemu-server/*.conf /etc/pve/nodes/{new}/qemu-server/
qm list                               # VMs reappear
qm start <vmid>
```

**Rule**: NEVER rename a Proxmox host with just `hostnamectl`. Always check `/etc/pve/nodes/` and move VM configs. Also documented in the `proxmox-setup.md` runbook in the vault.

### [2026-02-21] Tailscale DNS Chicken-and-Egg on Pi-hole Nodes

**Context**: RPi 4 as subnet router for Headscale VPN mesh. After reboot, VPN mesh was down.

**Problem**: Dual cause: (1) Tailscale can rewrite `/etc/resolv.conf` with `100.100.100.100` → circular dependency. (2) Even with `--accept-dns=false`, `tailscaled.service` starts before Docker (Pi-hole) → `nameserver 127.0.0.1` fails because Pi-hole isn't ready → Tailscale enters retry loop and never recovers.

**Solution**: Four measures: (1) `--accept-dns=false` on `tailscale up`, (2) dual nameserver in resolv.conf: `127.0.0.1` (Pi-hole) + `8.8.8.8` (boot fallback), (3) `chattr +i /etc/resolv.conf`, (4) systemd drop-in: `After=docker.service` for tailscaled.

**Rule**: On DNS nodes without `systemd-resolved`: ALWAYS `--accept-dns=false` + public fallback nameserver + order boot sequence. Only affects RPi 4 — all other nodes have `systemd-resolved` and need no changes.

### [2026-02-21] Pi-hole v6 Ignores dnsmasq.d by Default

**Context**: Configuring Pi-hole to forward `*.staging.kubelab.live` to CoreDNS (port 5353) via a file in `/etc/dnsmasq.d/`.

**Problem**: Pi-hole v6 uses FTL as its own resolver, not dnsmasq. By default `etc_dnsmasq_d = false` in `pihole.toml`, so any file in `/etc/dnsmasq.d/` is completely ignored. Also, `pihole restartdns` no longer exists in v6 — the command is `pihole reloaddns`.

**Solution**: Edit `pihole.toml` → `etc_dnsmasq_d = true`, then `docker restart pihole`. The conditional forward: `server=/staging.kubelab.live/172.17.0.1#5353` (use Docker bridge gateway IP, not 127.0.0.1 — inside the container, localhost is the container itself).

**Rule**: Pi-hole v6 ≠ Pi-hole v5. Always check `pihole.toml` for features that used to be automatic. And inside a Docker container, `127.0.0.1` ≠ host — use `172.17.0.1` to reach the host.

### [2026-02-21] Avahi Blocks Port 5353 on Ubuntu Server

**Context**: Deploying CoreDNS on port 5353 on RPi4 (port 53 occupied by Pi-hole).

**Problem**: `avahi-daemon` (mDNS) listens on port 5353 by default on Ubuntu. Docker can't bind the port. Also, disabling just the service isn't enough — the socket (`.socket` unit) restarts it.

**Solution**: `sudo systemctl disable --now avahi-daemon avahi-daemon.socket`. On a headless server, Avahi serves no purpose.

**Rule**: Before assigning an alternative port, check `ss -ulnp | grep <port>`. On headless Ubuntu Server, proactively disable Avahi.

### [2026-02-21] Headscale v0.28 CLI Route Commands

**Context**: Trying to approve subnet routes in Headscale v0.28.

**Problem**: Online documentation and project memory referenced `headscale routes list` and `headscale routes enable -r <ID>` — neither exists in v0.28. The `routes` command was moved under `nodes`.

**Solution**: Correct CLI: `headscale nodes list-routes`, `headscale nodes approve-routes -i <NODE_ID> --routes <CIDR>`. The `--routes` flag is a SET operation (replaces all approved routes, not additive).

**Rule**: Always check `--help` before running Headscale CLI. The API changes between minor versions. Running without `--routes` can clear existing approved routes.

### [2026-02-21] pihole reloaddns Does NOT Reload dnsmasq Config Files

**Context**: Adding conditional forwarding in Pi-hole for `kubelab.live` → CoreDNS.

**Problem**: After creating/modifying files in `/etc/dnsmasq.d/`, running `pihole reloaddns` doesn't reload them. The query kept returning NXDOMAIN. `pihole reloaddns` only reloads blocklists (gravity), not dnsmasq configuration files.

**Solution**: `docker restart pihole` (or `pihole-FTL --config dns.restart` in Pi-hole v6). Only a full restart reloads `/etc/dnsmasq.d/` files.

**Rule**: For dnsmasq config changes (`/etc/dnsmasq.d/`), always `docker restart pihole`. `pihole reloaddns` is ONLY for gravity/blocklists. Verify with `dig @127.0.0.1 <domain>` after restart.

### [2026-02-21] Headscale Split DNS: Use Parent Domain for Full Coverage

**Context**: CoreDNS resolved `*.staging.kubelab.live` but not `status.kubelab.live` (bare-metal).

**Problem**: Headscale split DNS was configured only for `staging.kubelab.live`. Bare-metal subdomains (`status.kubelab.live`, `ollama.kubelab.live`) didn't go through the internal DNS chain — they went directly to Cloudflare (which doesn't have those records) and returned NXDOMAIN.

**Solution**: Change split DNS from `staging.kubelab.live` → `kubelab.live` in Headscale config. This covers ALL internal subdomains. CoreDNS uses zone precedence: `staging.kubelab.live` (more specific) wins over `kubelab.live` for staging queries.

**Rule**: Configure split DNS on the parent domain (`kubelab.live`), not on specific subdomains. This way any new internal subdomain works automatically without touching Headscale.

---

### [2026-02-21] Operational Notes Go in Runbooks, Not the Roadmap (repeated error 2x)

**Context**: When marking MON-002 and HW-019 as completed, I added operational notes (flags, root cause, fix) directly in roadmap.md. Both times I had to be corrected.

**Problem**: The roadmap is for tasks (state, progress). Operational notes (flags, config, troubleshooting, root causes) belong in the corresponding runbook. The urge to annotate context next to the `[x]` is strong but wrong.

**Solution**: Remove the note from the roadmap. Document in the runbook (40-runbooks/hardware-setup.md, headscale-setup.md, etc.).

**Rule**: **BEFORE adding any note to roadmap.md, ask: "Is this WHAT TO DO or HOW TO DO IT?"** If "how" → it goes in the runbook. The roadmap only has: task ID, title, status, date. Nothing else.

---

### [2026-02-21] Docker Compose Prefixes Volumes with the Project Name

**Context**: Migrating Pi-hole from `docker run` to Docker Compose on RPi 4.

**Problem**: The original volumes were named `pihole_data` and `pihole_dnsmasq`. Compose prefixed them with the directory name → created empty `pihole_pihole_data` and `pihole_pihole_dnsmasq`. Pi-hole started without config → DNS broken.

**Solution**: Mark volumes as `external: true` in compose.yml. Compose reuses them without prefix.

**Rule**: Whenever migrating from `docker run` to compose with existing volumes, use `external: true`. Verify with `docker volume ls` that no duplicate volumes were created.

---

### [2026-02-22] K3s TLS SAN Must Be Set Before First Start

**Context**: kubectl from workstation via Tailscale required `insecure-skip-tls-verify: true`.

**Problem**: K3s generates the API server cert on first start. By default it only includes LAN IP + localhost. The Tailscale IP (100.64.0.4) was not in the SAN → TLS validation fails → insecure workaround needed.

**Solution**: Create `/etc/rancher/k3s/config.yaml` with `tls-san: ["100.64.0.4"]` and restart K3s. Then update kubeconfig: replace `insecure-skip-tls-verify` with `certificate-authority-data` using the server CA cert.

**Rule**: Always configure `tls-san` with ALL access IPs (LAN, Tailscale, public) BEFORE the first `curl | sh` of K3s. If already running, requires restart (regenerates certs). Document in k3s-setup runbook.

---

### [2026-02-22] LAN DNS Dependency Breaks Tailscale Reconnection

**Context**: Jetson Nano lost Tailscale connectivity and could not reconnect.

**Problem**: All LAN nodes use Pi-hole (RPi4) as DNS. If RPi4 goes down → DNS fails → nodes can't resolve `vpn.kubelab.live` (Headscale control server) → Tailscale can't reconnect → nodes become VPN-unreachable. Failure chain: RPi4 down → Pi-hole down → DNS down → Tailscale down → everything unreachable.

**Solution**: Ansible role `dns_resilience` manages a block in `/etc/hosts` with `blockinfile` on all homelab nodes. Entry: `162.55.57.175 vpn.kubelab.live`. Static inventory with Tailscale IPs at `infra/ansible/inventories/homelab.yml`.

**Rule**: Every domain critical for VPN connectivity must have a fallback in `/etc/hosts` managed by Ansible. Never depend on a DNS chain that can cascade-fail.

---

### [2026-02-24] Authelia on K8s: Service Links Inject Conflicting Env Vars

**Context**: Deploying Authelia 4.39.15 on K3s. Pod entered CrashLoopBackOff immediately after start.

**Problem**: K8s auto-injects service discovery env vars for every Service in the namespace. Because the Service is named `authelia`, K8s creates `AUTHELIA_PORT_9091_TCP_PORT`, `AUTHELIA_SERVICE_HOST`, etc. Authelia treats ALL `AUTHELIA_*` env vars as configuration → `AUTHELIA_PORT_9091_TCP_PORT` maps to the deprecated `port` key → conflicts with `server.address` in config → fatal error.

**Solution**: Add `enableServiceLinks: false` to the pod spec. Also added `automountServiceAccountToken: false` since Authelia doesn't need K8s API access (the image has a read-only `/run` that prevents mounting the SA token).

**Rule**: For any application that uses its own name as env var prefix (Authelia, Vault, Consul), ALWAYS set `enableServiceLinks: false` in the K8s pod spec. Check container logs for unexpected env var warnings.

---

### [2026-02-24] Kustomize configMapGenerator for Binary Assets

**Context**: Needed to deploy custom branding assets (logo.png, favicon.ico) for Authelia's sign-in page.

**Problem**: First attempt: inline binaryData in YAML → base64 blob got corrupted during editing (13KB+ strings are fragile in YAML). Second attempt: `kubectl create configmap --from-file` → imperative, breaks IaC principle.

**Solution**: Use kustomize `configMapGenerator` with `files:` directive. Kustomize automatically handles binary files as `binaryData`. Same pattern already used for `grafana-dashboards` ConfigMap.

**Rule**: Never inline large base64 blobs in YAML. Never use imperative `kubectl create` for reproducible resources. Use `configMapGenerator` with file references — it's declarative, in Git, and handles binary encoding automatically.

---

### [2026-02-24] Toolkit K8s Deploy Misses configMapGenerator Binary Resources

**Context**: `tk infra k8s deploy` applied all resources except the `authelia-assets` ConfigMap generated by kustomize `configMapGenerator`.

**Problem**: The toolkit's deploy command didn't apply the binary ConfigMap even though `kubectl kustomize` generates it correctly. Workaround: pipe kustomize output directly to kubectl (`kubectl kustomize | kubectl apply -f -`).

**Solution**: Temporary workaround with direct kustomize pipe. Root cause in toolkit needs investigation — likely a buffering or encoding issue with large binaryData in the kustomize output.

**Rule**: After adding binary assets via configMapGenerator, verify the ConfigMap appears in the actual apply output (not just dry-run). If missing, use `kubectl kustomize | kubectl apply -f -` as fallback.

---

### [2026-02-25] Dev TLS cert generator missed custom root domains

**Context**: Bringing up the full dev stack for the first time after the cubelab→kubelab rename. `blog.kubelab.test` loaded fine but `mlorente.test` showed a cert error.

**Problem**: `*.kubelab.test` wildcards only cover one DNS level — they do not cover sibling root domains like `mlorente.test`. The cert generator (`_get_default_domains` in `toolkit/cli/tools.py`) only included `BASE_DOMAIN` + `*.BASE_DOMAIN`, ignoring the web app's domain when it uses a different root.

**Solution**: Extended `_get_default_domains` to read `APPS_PLATFORM_WEB_DOMAIN` from the env config and append it to the cert SANs if it differs from the base domain. `make regen-certs` now handles the full workflow (regenerate + reinstall CA + restart Traefik).

**Rule**: Any dev domain that doesn't end in `.$BASE_DOMAIN` must be explicitly included in the mkcert SAN. When adding new apps with custom root domains, update `_get_default_domains` or pass `--domain` to `toolkit tools certs generate`.

---

### [2026-02-25] CrowdSec acquis.yaml Cannot Be Comment-Only

**Context**: Deploying CrowdSec agent on K3s. Pod entered CrashLoopBackOff immediately.

**Problem**: The `acquis.yaml` ConfigMap contained only comments (no active datasource entries). CrowdSec treats this as "no datasource enabled" and exits fatally on startup — it requires at least one active acquisition source to start.

**Solution**: Add a `filePath` datasource entry pointing to a log file path (e.g., `/var/log/traefik/access.log`) and mount an `emptyDir` volume at that path. This satisfies the startup requirement even if no logs exist yet. CrowdSec will begin processing logs once Traefik writes them.

**Rule**: `acquis.yaml` must always have at least one active (non-commented) datasource. Use a `filePath` source + `emptyDir` volume as a safe default. Empty-config startup failures are not intuitive — always check agent logs for "no datasource enabled".

---

### [2026-02-25] n8n Container Has No curl or wget for Healthchecks

**Context**: Adding a healthcheck to the n8n service in Docker Compose.

**Problem**: The `n8nio/n8n` image does not include `curl`, `wget`, or any HTTP client. Standard Docker healthcheck patterns (`CMD curl -f http://localhost:5678`) fail immediately with `exec: "curl": executable file not found`.

**Solution**: Use the Node.js runtime that is already present in the image:
```yaml
healthcheck:
  test: ["CMD-SHELL", "node -e \"require('http').get('http://localhost:5678/healthz', (r) => { process.exit(r.statusCode === 200 ? 0 : 1) })\""]
  interval: 30s
  timeout: 10s
  retries: 3
```

**Rule**: Before writing a healthcheck, verify which HTTP clients are available in the image (`docker run --entrypoint sh image which curl wget node`). For Node.js-based images without curl, use the built-in `require('http').get(...)` pattern.

---

### [2026-02-25] SOPS path_regex Blocks Encrypting Files Outside Defined Paths

**Context**: Trying to encrypt a secrets file created in `/tmp/` for testing before moving it to the repo.

**Problem**: `.sops.yaml` has `path_regex: infra/config/secrets/.*\.enc\.yaml$` — SOPS refuses to encrypt any file whose path doesn't match this pattern. Files in `/tmp/` or any path outside the repo fail with "no matching creation rules".

**Solution**: Either: (a) create and encrypt the file in-place at the correct repo path, or (b) use `sops set` to edit an existing file. Never create secrets files in `/tmp/` and expect to encrypt them afterward.

**Rule**: SOPS `path_regex` is absolute-path matched. Always create new secrets files directly at their final repo path (`infra/config/secrets/`). Do not draft secrets in temp locations.

---

### [2026-02-25] Double Auth Anti-Pattern: Own-Auth Services Behind Authelia

**Context**: Deciding whether to put portainer, gitea, minio, and n8n behind the Authelia ForwardAuth middleware.

**Problem**: Services with their own authentication system (portainer, gitea, n8n) placed behind Authelia result in two sequential login screens — users authenticate with Authelia, then authenticate again with the service. This is confusing UX and provides no security benefit since both auth systems protect the same resource.

**Solution**: Two patterns depending on the service:
- **Own auth only (dev/infra tools)**: bypass Authelia entirely. Use Authelia only at the network perimeter. Example: portainer, gitea.
- **OIDC SSO**: configure the service as an OIDC client against Authelia. Single login flow. Example: minio (supports OIDC natively), grafana.

**Rule**: Before wiring a service to Authelia ForwardAuth, check if it has native OIDC/OAuth2 support. If yes → configure SSO (single login). If no native SSO → bypass Authelia for that service. Never layer ForwardAuth on top of a service that has mandatory own-auth login.

---

*More entries will be added as the project progresses.*

---

### 2026-02-25 — MinIO console 503: MINIO_SERVER_URL must be internal in dev

**Problem:** MinIO console login returns 503 / "unable to login due to network error" in Docker Compose dev.

**Root cause:** `MINIO_SERVER_URL=https://minio.kubelab.test` causes the embedded console (port 9001) to call the MinIO API at that public URL from inside the container. Port 443 (Traefik) only exists on the host — it is not reachable from inside Docker networks.

**Fix:** Override `MINIO_SERVER_URL` in `compose.dev.yml`:
```yaml
MINIO_SERVER_URL: "http://localhost:9000"      # internal — console→API call
MINIO_BROWSER_REDIRECT_URL: "https://console.minio.kubelab.test"  # external — browser redirect
```

**Rule:** Any service that embeds an admin console which calls its own API internally must use an internal URL for `*_SERVER_URL`, not the public HTTPS reverse-proxy URL.

---

### 2026-02-25 — Grafana dashboard provisioning: ConfigMaps ≠ Docker Compose volumes

**Problem:** Custom Grafana dashboards visible in K8s staging were not showing in Docker Compose dev.

**Root cause:** K8s uses ConfigMaps mounted as volumes for Grafana provisioning. Docker Compose has no equivalent automatic mechanism — the compose.base.yml only mounted `grafana_data:/var/lib/grafana` with zero provisioning files.

**Fix:** Create provisioning files and mount them explicitly:
```
infra/stacks/services/observability/grafana/provisioning/dashboards/provider.yaml
infra/stacks/services/observability/grafana/provisioning/datasources/loki.yaml
```
Mount in compose.base.yml:
```yaml
- ./provisioning/dashboards:/etc/grafana/provisioning/dashboards:ro
- ./provisioning/datasources:/etc/grafana/provisioning/datasources:ro
- ../../../../../infra/k8s/base/services/grafana-dashboards:/var/lib/grafana/dashboards:ro
```

**Rule:** K8s and Docker Compose use different mechanisms for config injection. When a service is deployed in both environments, provisioning files must exist for both.

---

### 2026-02-26 — Traefik Cannot Proxy Headscale: Custom HTTP Upgrade Not Supported

**Context:** Testing ts-bridge v1.3.0 `TS_CONTROL_URL` against Headscale (`vpn.kubelab.live`) behind Traefik v3.0.4.

**Problem:** tsnet v1.60.0 fetches `/key` successfully but `/machine/register` via Noise protocol fails:
```
all connection attempts failed (HTTP: 308 Permanent Redirect, HTTPS: reading response header: EOF)
```

**Root cause (corrected after 3 failed attempts):**
1. ~~HTTP/2 incompatible with Upgrade headers~~ — `maxConcurrentStreams: 0` does nothing (means "unlimited", not "disable")
2. ~~TLS ALPN forcing HTTP/1.1~~ — Confirmed HTTP/1.1 via ALPN, error persisted
3. **Real cause: Traefik strips non-WebSocket `Upgrade` headers** ([traefik#12609](https://github.com/traefik/traefik/issues/12609), OPEN). Traefik only recognizes `Upgrade: websocket`. The `Upgrade: tailscale-control-protocol` header is removed as a hop-by-hop header per RFC 7230. Headscale never receives the Noise handshake → connection fails. Headscale's own docs don't list Traefik as a supported reverse proxy.

**Fix:** TCP passthrough with SNI routing — Traefik forwards raw TCP based on SNI, Headscale handles TLS itself:
```yaml
# /opt/traefik/dynamic/app-headscale.yml
tcp:
  routers:
    headscale:
      rule: "HostSNI(`vpn.kubelab.live`)"
      entryPoints:
        - websecure
      service: headscale-tcp
      tls:
        passthrough: true
  services:
    headscale-tcp:
      loadBalancer:
        servers:
          - address: "headscale:443"
```
Headscale config changes: `listen_addr: 0.0.0.0:443` + TLS cert via certbot DNS-01 (Cloudflare).

**Rule:** Before putting a service behind Traefik HTTP reverse proxy, check if it uses custom HTTP Upgrade protocols. If yes → use TCP passthrough with SNI routing. Traefik only supports `Upgrade: websocket`, nothing else. This affects Headscale, Tailscale control servers, and any custom binary protocol over HTTP Upgrade.

---

### 2026-02-27 — tsnet Version Must Meet Headscale minimum_version

**Context:** After fixing all Traefik routing issues (TCP passthrough, certbot TLS, DNS), ts-bridge still failed with identical `308 Permanent Redirect / reading response header: EOF` error. Native Tailscale clients worked fine.

**Problem:** Headscale v0.28.0 enforces `minimum_version=v1.74`. ts-bridge used `tailscale.com v1.60.0` — 14 minor versions below the minimum. The Noise handshake fails server-side due to version rejection, manifesting as EOF on the client.

**Diagnosis clues:**
- curl and native Tailscale clients (>= v1.74) worked through the same TCP passthrough
- Headscale logs showed: `Clients with a lower minimum version will be rejected minimum_version=v1.74`
- ts-bridge reported: `IPNVersion: 1.60.0-dev`

**Fix:** `go get tailscale.com@v1.80.0 && go mod tidy`. tsnet API surface (`tsnet.Server`, `Up()`, `Dial()`, `Close()`) is stable across v1.60→v1.80; no code changes needed.

**Rule:** When integrating with Headscale, check its `minimum_version` log entry and ensure the tsnet Go module exceeds it. Pin to minimum + 6 minor versions for safety. Add this check to the pre-release validation for any Headscale-compatible tool.

---

### 2026-02-27 — Headscale Ephemeral Nodes Require `--ephemeral` on the Pre-Auth Key

**Context:** ts-bridge sets `tsnet.Server{Ephemeral: true}`, but after Ctrl+C the node persisted as `Ephemeral: false` / offline in `headscale nodes list`.

**Problem:** Headscale controls ephemeral behavior via the **pre-auth key**, not the client-side setting. `tsnet.Server.Ephemeral=true` is a Tailscale SaaS feature; Headscale ignores it. If the key was created without `--ephemeral`, the node is permanent regardless of what the client requests.

**Fix:** Create the key with `--ephemeral`:
```bash
headscale preauthkeys create --user <ID> --reusable --expiration 8760h --ephemeral
```

**Rule:** For any headless/tsnet service that should auto-cleanup on disconnect, the Headscale pre-auth key MUST include `--ephemeral`. Don't rely on client-side `Ephemeral: true` — it's Headscale's key, not the client, that controls this behavior.

---

### 2026-02-27 — Cloudflare Terraform Import: Use FQDN for Root Records, Not @

**Context:** Importing existing Cloudflare DNS records into Terraform state (`terraform import`).

**Problem:** Defined root records as `name = "@"` in `.tf` files. After import, `terraform plan` showed `forces replacement` on both root records — name changed from `kubelab.live` → `@`. Cloudflare stores the FQDN in the API/state, not the `@` alias. The replacement would delete and recreate the record, causing a brief DNS outage.

**Solution:** Use the FQDN in the Terraform config:
```hcl
resource "cloudflare_record" "kubelab_root" {
  name = "kubelab.live"  # NOT "@"
}
```

**Rule:** When importing existing Cloudflare records, always use the FQDN for root records (not `@`). Check the imported state with `terraform state show` to see what Cloudflare actually stores, then match your `.tf` to that.

---

### 2026-02-27 — Terraform: One-Time Setup vs Day-to-Day Automation Are Different Problems

**Context:** Completing PREP-001 (Terraform DNS automation for K3s migration).

**Problem:** Confused the import/bootstrap phase (inherently manual: API calls, record ID lookups, state imports) with the day-to-day operations (fully automated: edit JSON → plan → apply). Tried to make the one-time setup "automatable" which added no value since it runs once.

**Solution:** Accept that Terraform has two modes:
1. **Bootstrap** (one-time): manual imports, credential setup, zone ID discovery → requires human judgment
2. **Steady-state** (repeatable): edit `services.json` → `toolkit infra terraform plan` → `toolkit infra terraform apply` → fully automated via toolkit

**Rule:** Don't try to automate one-time setup operations. Spend automation effort on the operations that repeat (add service, change IP, toggle proxy). Document the bootstrap procedure in a runbook for disaster recovery.

---

### [2026-02-28] Secrets leaked in K8s ConfigMaps — blocklist approach is fragile

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

### [2026-02-28] Stale Tags and Releases Accumulate from CI Renames and Deleted Branches

**Context**: After repo rename (cubelab → kubelab) and multiple CI pipeline iterations, 7 stale git tags and 4 stale GitHub releases accumulated. Tags had inconsistent naming (with/without `v` prefix), pointed to deleted branches, and confused the SemVer action.

**Problem**: Three interrelated issues:
1. **Old CI** created global tags (`v0.1.0`, `0.1.0-feature-*`) but **new CI** creates per-app tags (`api-v1.0.0`). Old tags polluted the namespace.
2. Feature/hotfix branch tags (`*-feature-static-jekyll.0`, `*-hotfix-ci-cd-pipeline-fix.0`) survived branch deletion — zombie artifacts.
3. DockerHub had old `mlorente-*` image repos alongside current `kubelab-*` repos from the rename.

**Solution**: Clean slate approach:
1. Deleted all 7 stale tags (local + remote) and 4 GitHub releases
2. Deleted old `mlorente-*` DockerHub repos (manual)
3. Documented versioning convention: per-app SemVer (`{app}-v*`) + global CalVer (`v{YYYY.MM.DD}`)
4. Version baseline resets to `0.0.0` — first stable release on next master merge

**Rule**: After any repo rename or CI pipeline restructuring:
1. Audit and delete all tags/releases from the old convention
2. Verify DockerHub repos match current `REGISTRY_PREFIX`
3. Document the versioning convention in vault (not just in CI yaml comments)
4. Verify `paulhatch/semantic-version` tag_prefix matches only the new convention

---

### [2026-02-28] E2E Audit: Gitea Staging Uses Prod Domain (No Override)

**Context**: E2E test suite expansion — cross-checking service domains across environments.

**Problem**: `infra/config/values/staging.yaml` has no domain override for Gitea. The base config (`common.yaml`) uses the production domain `gitea.kubelab.live`. In staging, Gitea is accessible at `gitea.staging.kubelab.live` via Traefik IngressRoute, but the config-generated domain doesn't match. Tests targeting the Gitea domain from the merged config would hit the wrong environment.

**Solution**: Add `domain: gitea.staging.kubelab.live` to the Gitea section in `staging.yaml`.

**Rule**: Every service deployed in staging must have an explicit domain override in `staging.yaml`. Never rely on the base config domain for non-prod environments — it defaults to prod.

---

### [2026-02-28] E2E Audit: API /health Endpoint Is Fully Mocked

**Context**: E2E test suite writing API health structure tests. Inspected `healthchecks.go`.

**Problem**: All four health check functions (`checkDatabaseConnection`, `checkExternalServices`, `checkEmailConfiguration`, `checkRedisConnection`) are mocked — they always return `"healthy"` regardless of actual dependency state. The only real check is `checkEmailConfiguration` which validates non-empty config values, but doesn't actually test SMTP connectivity. Result: `/health` always returns `200 healthy` even if the database is unreachable or Redis is down.

**Solution**: Track as a backlog item. For now, E2E tests validate the JSON structure (correct keys, component names), not the accuracy of the health status. Real health checks should be implemented before production: actual DB ping, Redis ping, SMTP EHLO.

**Rule**: Health check endpoints MUST perform actual connectivity checks, not return hardcoded "healthy". A mocked health endpoint gives false confidence and defeats the purpose of readiness probes in K8s.

---

### [2026-02-28] E2E Audit: CORS Wildcard Origin + Credentials Is Invalid

**Context**: E2E test suite examining API middleware. Inspected `middleware.go`.

**Problem**: The CORS middleware sets `Allow-Origin: *` AND `Allow-Credentials: true`. Per RFC 6454 and the Fetch specification, this combination is invalid — browsers will refuse to send cookies with cross-origin requests when the server responds with `*` as the origin. This means any browser-based client using cookies (e.g., authenticated API calls from the web frontend on a different domain) will silently fail.

**Solution**: Either: (a) set `Allow-Origin` to the specific frontend domain(s) instead of `*`, or (b) remove `Allow-Credentials: true` if cookies aren't needed. Option (a) is correct for the web app.

**Rule**: Never combine `Access-Control-Allow-Origin: *` with `Access-Control-Allow-Credentials: true`. If you need credentials, explicitly list allowed origins.

---

### [2026-02-28] Authelia Prod VPN Network Uses /24 Instead of /10

**Context**: Auditing hardcoded values in K8s manifests after E2E test expansion.

**Problem**: `infra/k8s/overlays/prod/patches.yaml` defines the Authelia VPN network as `100.64.0.0/24` but Headscale allocates from the `100.64.0.0/10` range. With `/24` Authelia only recognizes IPs 100.64.0.0-255 as VPN traffic. All current nodes fit within `/24` so it works today, but future nodes could get IPs outside this range and bypass VPN-specific access rules.

**Solution**: Changed to `100.64.0.0/10` to match the Headscale allocation range. Added `networking.tailscale_cidr` to common.yaml as the single source of truth.

**Rule**: The Tailscale/Headscale CIDR must be consistent everywhere: Authelia access rules, CrowdSec whitelists, and any IP-based filtering. Reference `networking.tailscale_cidr` from common.yaml; don't hardcode CIDRs in individual K8s manifests.

---

### [2026-02-28] Infrastructure Configuration SSOT Pattern

**Context**: Audited all hardcoded values in the repo during E2E test expansion. Found 16 critical hardcoded IPs, ports, and image versions across K8s manifests, Ansible inventory, Corefile, tests, and toolkit code.

**Problem**: The toolkit generates Docker Compose and Traefik configs from `common.yaml`, but K8s manifests, Ansible inventory, CoreDNS Corefile, and toolkit monitoring code hardcode the same values independently. When an IP or port changes, it must be updated in 3-7 places manually. The DNS Corefile wildcard (`*.staging.kubelab.live → 100.64.0.4`) points domains to K3s even for services not deployed there, causing self-signed cert errors.

**Solution applied**:
1. Added `networking` section to common.yaml with all node Tailscale IPs, VPS IPs, and the Tailscale CIDR
2. Updated tests to read from common.yaml instead of hardcoding IPs/domains
3. Added CrowdSec whitelist ConfigMap referencing the common.yaml CIDR
4. Fixed Authelia prod overlay VPN CIDR (`/24` → `/10`)

**Remaining gaps** (tracked as future tasks):
- Ansible inventory IPs still hardcoded (needs inventory generation from config)
- CoreDNS Corefile IPs hardcoded (needs Corefile generation from config)
- K8s image versions diverge from common.yaml (needs image pinning review)
- `toolkit/cli/monitoring.py` Uptime Kuma IP hardcoded

**Rule**: Follow the SSOT → Generator → Consumer pattern. Every IP, port, domain, and image version should have exactly ONE canonical location in `infra/config/values/common.yaml`. K8s manifests, Ansible, Terraform, and Corefile should either be generated from common.yaml or have a comment noting which common.yaml key they mirror. When adding a new hardcoded value, ask: "Can I read this from config instead?"

---

### [2026-02-28] Docker-Compose-Only Services and K3s DNS Wildcard Gap

**Context**: E2E staging tests returning self-signed TLS cert errors for portainer, gitea, n8n, minio, and uptime_kuma.

**Problem**: CoreDNS Corefile has a wildcard template `*.staging.kubelab.live → 100.64.0.4` (K3s server). This routes ALL staging subdomains to K3s. But portainer, gitea, n8n, minio, and uptime_kuma only exist as Docker Compose stacks — they have no K3s Deployments or IngressRoutes. Traefik receives requests for these domains, finds no matching IngressRoute, and returns its default self-signed certificate.

**Solution**: Added `skip_in_envs=("staging",)` in expectations.py for these services. They're legitimately not on K3s staging.

**Rule**: If a DNS wildcard covers a domain but no corresponding backend exists, Traefik returns a self-signed cert. When adding a service to the config, either: (a) deploy it on K3s with an IngressRoute, or (b) mark it with `skip_in_envs` in the test registry. The DNS wildcard is correct (forward-looking), but tests must reflect what's actually deployed.

---

### [2026-03-01] K3s Traefik Middleware Parity: Dev Has It, Staging Must Too

**Context**: E2E tests discovered staging was missing `secure-headers` and `error-pages` middlewares on individual IngressRoutes.

**Problem**: Docker Compose dev stack applies `secure-headers@file` and `error-pages@file` middlewares to ALL 15+ service routes via generated dynamic config. K3s staging had zero middleware on api/web/blog IngressRoutes (only crowdsec-bouncer), and grafana/loki only had authelia. The nginx-errors Middleware CRD existed but was only referenced by the catch-all IngressRoute, not by individual service routes. No `secure-headers` Middleware CRD existed at all.

**Impact**:
- HSTS headers missing on staging → security risk
- Custom error pages not triggered on individual routes → Traefik returns plaintext 404 instead of custom HTML
- Tests correctly caught this: 15 failures on first staging run

**Solution**:
1. Created `infra/k8s/base/edge/secure-headers.yaml` — Middleware CRD replicating the dev `secure-headers@file` config
2. Added `secure-headers` + `error-pages` to ALL IngressRoutes: api, web, blog (staging overlay), grafana, loki (base), authelia (base)
3. Middleware ordering: `secure-headers → error-pages → authelia/crowdsec-bouncer → service`

**Rule**: When adding middleware to Docker Compose routes, ALWAYS verify the equivalent Middleware CRD exists and is referenced in K3s IngressRoutes. Maintain a cross-environment middleware checklist. The E2E security headers + error pages tests are the automated guard against this drift.

---

### [2026-03-01] CrowdSec Bouncer LAPI Registration Lost After Pod Recreation

**Context**: CrowdSec bouncer returning 403 for ALL requests on staging. `cscli bouncers list` showed zero registered bouncers despite `BOUNCER_KEY_crowdsec-bouncer` env var being correctly set.

**Problem**: CrowdSec's Docker image auto-registers bouncers from `BOUNCER_KEY_*` env vars via the entrypoint script — but only on **initial setup** (first run with empty config). When the pod was recreated (new image, config changes), the config PVC already had data from the previous run. The entrypoint detected "not a first run" and skipped bouncer registration, even though the DB PVC may have been fresh or the registration was lost.

**Impact**: Every request to api/web/blog returned 403 — the bouncer couldn't authenticate to the LAPI. The LAPI returned 403 to the bouncer's decision queries, and the bouncer fail-closed.

**Solution**: Manual registration with the existing API key:
```bash
kubectl exec -n kubelab deployment/crowdsec -- cscli bouncers add crowdsec-bouncer --key "$(kubectl get secret crowdsec-bouncer -n kubelab -o jsonpath='{.data.api-key}' | base64 -d)"
```
The registration is stored in the DB PVC and survives pod restarts.

**Rule**: After any CrowdSec pod recreation (deployment update, node migration, PVC issue), verify `cscli bouncers list` shows the registered bouncer. If empty, manually re-register with `cscli bouncers add --key`.

**Automated fix (2026-03-19)**: Added `postStart` lifecycle hook to CrowdSec deployment that waits for LAPI health then runs `cscli bouncers add --key ... || true`. Idempotent — succeeds on first run, no-ops if already registered. Manual intervention no longer needed.

---

### [2026-03-01] K3s Traefik HTTP→HTTPS Redirect: CLI Args, Not Helm Values

**Context**: Adding HTTP→HTTPS redirect to the K3s Traefik via HelmChartConfig.

**Problem**: First tried `ports.web.redirectTo.port: websecure` in HelmChartConfig values — this is the documented Traefik Helm chart approach. Applied successfully but Traefik deployment showed no redirect args. The K3s-managed Traefik chart may not support this value path, or it requires a specific chart version.

**Solution**: Use `additionalArguments` in HelmChartConfig to pass CLI args directly:
```yaml
additionalArguments:
  - "--entrypoints.web.http.redirections.entryPoint.to=websecure"
  - "--entrypoints.web.http.redirections.entryPoint.scheme=https"
  - "--entrypoints.web.http.redirections.entryPoint.permanent=true"
```

**Rule**: For K3s-managed Traefik, prefer `additionalArguments` over nested Helm values for configuration that maps to CLI flags. Always verify with `kubectl get deployment traefik -n kube-system -o yaml | grep -A5 args` that the flag actually appears.

---

### [2026-03-01] HSTS Test Failure Through Auth Redirect Chain

**Context**: E2E HSTS test passing for api/web/blog but failing for grafana/loki.

**Problem**: Grafana and Loki are behind Authelia ForwardAuth. Unauthenticated requests get 302 redirected to `auth.staging.kubelab.live`. The E2E test uses `http_client_follow` (follows redirects) and checks headers on the **final** response — which is the Authelia login page. Authelia's IngressRoute didn't have `secure-headers` middleware, so the final response lacked HSTS.

**Solution**: Added `secure-headers` middleware to the Authelia IngressRoute. Now HSTS is present on all responses in the redirect chain.

**Rule**: When testing response headers on services behind SSO, the entire redirect chain must apply the same middleware. Either: (a) add the middleware to all IngressRoutes in the chain (including the auth service), or (b) test with `follow_redirects=False` to check only the initial response. Option (a) is more secure — users see HSTS regardless of which redirect step they're on.

---

### [2026-03-01] OIDC Client Secret: Authelia Config vs Service Config

**Context**: Deploying MinIO with Authelia OIDC on K3s staging.

**Problem**: Authelia needs the client_secret as a hash (argon2id) in its configuration.yml, while MinIO needs the plaintext secret in its MINIO_IDENTITY_OPENID_CLIENT_SECRET env var. Storing both in SOPS with different keys, or using env var injection, creates complexity.

**Solution**: Store the plaintext in SOPS at the service path (`apps.services.data.minio.oidc_client_secret`) and the hash at the Authelia path (`apps.services.security.authelia.oidc_client_secret_minio_hash`). The hash goes directly in the ConfigMap (it's irreversible, not sensitive). The plaintext goes in a K8s Secret via k8s_secrets.py. Use `make secrets-hash-minio` to generate the hash from the plaintext.

**Rule**: For OIDC client secrets, always store plaintext + hash separately in SOPS. The hash in the Authelia ConfigMap is acceptable (irreversible). Never put plaintext secrets in ConfigMaps. Use Makefile targets to automate hash generation.

---

### [2026-03-01] N8N Community Edition Has No Native OIDC

**Context**: Planning centralized auth via Authelia OIDC for all services.

**Problem**: N8N community edition does not support OIDC/OAuth2 authentication natively. Only enterprise N8N has SAML/LDAP support.

**Solution**: Use Authelia forward-auth middleware (`one_factor` policy) on N8N's IngressRoute. Users authenticate at the Authelia gate before reaching N8N. N8N itself still requires its own initial account setup, but the Traefik layer ensures only authenticated users reach it.

**Rule**: When a service doesn't support OIDC, use Authelia forward-auth as a security gate. This isn't true SSO (the service still has its own session), but it provides centralized access control. Check the service's auth capabilities BEFORE planning the OIDC integration.

---

### [2026-03-01] MINIO_SERVER_URL Must Be Internal K8s URL

**Context**: Deploying MinIO to K3s with OIDC.

**Problem**: If `MINIO_SERVER_URL` is set to the public HTTPS URL (`https://minio.staging.kubelab.live`), MinIO tries to connect to itself through the external URL, causing redirect loops and TLS issues inside the cluster.

**Solution**: Set `MINIO_SERVER_URL=http://minio:9000` (internal K8s service name). The public URL goes in `MINIO_BROWSER_REDIRECT_URL` for the console redirect.

**Rule**: Internal service-to-service communication MUST use K8s service names (`http://service:port`), NEVER public HTTPS URLs. Public URLs are only for browser redirects and external-facing configuration.

---

### [2026-03-01] sops --set Quoting: Special Characters Break JSON Parsing

**Context**: Automating SOPS secret injection via Makefile targets.

**Problem**: `sops --set '["path"] "value!"'` fails with "Value for --set is not valid JSON" when the value contains `!` (bash history expansion) or other special characters.

**Solution**: Avoid special characters in passwords passed via `sops --set`. For passwords with special chars, use `sops --edit` (interactive) or pipe through environment variables with proper escaping. Created `make secrets ENV=staging` for interactive editing and `make secrets-init` for automated generation of random hex secrets (no special chars).

**Rule**: `sops --set` values must be valid JSON. Use hex-encoded random values for automated injection. Reserve interactive `sops --edit` for human-chosen passwords with special characters.

---

### [2026-03-01] Authelia OIDC JWKS: `_FILE` Env Vars Don't Work for Array-Indexed Keys

**Context**: Deploying Authelia with OIDC provider config for MinIO SSO on K3s staging. Used `identity_providers.oidc.jwks[0].key` with `AUTHELIA_IDENTITY_PROVIDERS_OIDC_JWKS_0_KEY_FILE` env var to inject the RSA PEM from a K8s Secret file mount.

**Problem**: Authelia v4.39 does NOT support `_FILE` env var injection for array-indexed config keys. The env var `AUTHELIA_IDENTITY_PROVIDERS_OIDC_JWKS_0_KEY_FILE` is logged as "not expected", and the empty `key: ''` placeholder in the YAML is treated as a symmetric key, causing fatal error: `symmetric keys are not permitted for signing`.

**Solution**: Use the deprecated but still-functional `issuer_private_key` field instead of the `jwks` array. Changed to `AUTHELIA_IDENTITY_PROVIDERS_OIDC_ISSUER_PRIVATE_KEY_FILE=/run/secrets/oidc_jwks_key`. Authelia auto-maps `issuer_private_key` to `jwks` internally with a deprecation warning (acceptable until Authelia 5.x).

**Rule**: For Authelia OIDC JWKS key injection via K8s Secrets, use `issuer_private_key` (not `jwks[0].key`) with `_FILE` env var. The `_FILE` suffix only works for flat config keys, NOT array-indexed ones. When Authelia 5.x drops `issuer_private_key`, find the new file-based mechanism for `jwks`.

---

### [2026-03-01] CoreDNS on RPi4 Is Completely Outside K3s and Ansible Automation

**Context**: Added new services (gitea, n8n, minio) to the Corefile and needed to deploy changes to the RPi4 DNS gateway.

**Problem**: The CoreDNS deployment on RPi4 has no automation whatsoever. No Ansible role, no toolkit command, no CI/CD. The RPi4 is not in the K3s cluster — it's a standalone Docker Compose host. Changes to `edge/dns-gateway/Corefile` only take effect after manual SCP + container restart. This is a genuine automation gap, not a missing discovery.

**Solution**: Manual deployment: `scp edge/dns-gateway/Corefile manu@100.64.0.5:~/coredns/` then `ssh manu@100.64.0.5 "cd ~/coredns && docker compose -f compose.base.yml restart coredns"`. The runbook `dns-homelab.md` documents this procedure.

**Rule**: Always know the deployment mechanism for every component before referencing "apply changes" in any plan. The DNS gateway is a manual-deploy component — plan accordingly. Automated via `make deploy-dns` (SCP + restart). Future: consider Ansible role for `gateway_nodes`.

---

### [2026-03-01] CoreDNS `template` Overrides `hosts` When Both Are in Same Zone

**Context**: The `kubelab.live` zone had both a `hosts` block (bare-metal services at individual Tailscale IPs) and a `template` wildcard (K3s services at VPS Tailscale IP). Expected hosts to take priority.

**Problem**: CoreDNS `template` plugin overrides `hosts` plugin responses even when the hosts entry explicitly matches. `status.kubelab.live` resolved to `100.64.0.2` (template wildcard) instead of `100.64.0.6` (hosts entry). This is because CoreDNS plugin ordering makes `template` respond after `hosts`, and the template's answer replaces the hosts answer.

**Solution**: Remove the `template` wildcard from `kubelab.live` zone. Use explicit `hosts` entries for ALL prod services (both bare-metal and K3s). This avoids the template-hosts conflict entirely. The staging zone's template wildcard works fine because ALL staging IPs are the same (`100.64.0.4`).

**Rule**: Never mix `hosts` and `template` plugins in the same CoreDNS zone when they resolve to different IPs. Use explicit hosts entries instead. The `template` wildcard is safe ONLY when all entries resolve to the same IP (like staging).

---

### [2026-03-01] Unified Secrets CLI Replaces Scattered sops/openssl Commands

**Context**: Multiple Makefile targets used raw `sops --set`, `openssl rand`, `sops --edit` with different patterns. No single entry point for secret operations.

**Problem**: Inconsistent secret management. Some targets used `sops --set` (broke with special chars), others used interactive `sops --edit`, and generation used various `openssl` invocations. No catalog of what secrets exist, no audit capability, no standard rotation procedure.

**Solution**: Created `toolkit secrets` CLI with 8 unified commands: `edit`, `init`, `jwks`, `hash`, `apply`, `audit`, `show`, `catalog`. All secret metadata centralized in `SECRET_CATALOG` (25 entries) in `toolkit/features/secrets_manager.py`. Makefile reduced to 5 thin wrappers. Comprehensive documentation in vault `40-runbooks/secrets-reference.md`.

**Rule**: Secret operations MUST go through `toolkit secrets *`. Never use raw `sops` or `openssl` in Makefile or scripts. The `SECRET_CATALOG` is the authoritative registry — every new secret must be registered there with its kind, services, and rotation notes.

---

### [2026-03-01] Tailscale Bootstrap Circular Dependency on RPi4

**Context**: RPi4 rebooted and Tailscale failed to reconnect. All `*.kubelab.live` DNS resolution from VPN clients broke because RPi4 is the DNS gateway.

**Problem**: Circular dependency — Tailscale on RPi4 needs to reach Headscale at `vpn.kubelab.live`, but `vpn.kubelab.live` was resolved by RPi4's own CoreDNS to `100.64.0.2` (VPS Tailscale IP), which is only reachable with Tailscale already connected. Error: `dial tcp 100.64.0.2:443: connect: connection timed out`. RPi4 stuck in `unexpected state: NoState`.

**Solution**: Three-layer fix:
1. **Corefile**: Changed `vpn.kubelab.live` from Tailscale IP (`100.64.0.2`) to public IP (`162.55.57.175`). Headscale is the bootstrap service — MUST always be reachable without VPN.
2. **`/etc/hosts` on RPi4**: Added `162.55.57.175 vpn.kubelab.live` as permanent fallback (works even if CoreDNS is down).
3. **Systemd watchdog timer**: `tailscale-watchdog.timer` runs every 5 min, checks if Tailscale is connected, auto-reconnects with correct flags (`--accept-dns=false --advertise-routes=172.16.1.0/24`).

**Rule**: Bootstrap services (Headscale, Cloudflare DNS) must NEVER resolve to VPN-only IPs. Always use public IPs for services that are required to establish the VPN itself. Any node that is part of the DNS/VPN bootstrap chain must have `/etc/hosts` entries as fallback.

---

### [2026-03-01] External Service Proxying Through K3s Traefik (Uptime Kuma)

**Context**: Uptime Kuma runs on RPi3 (standalone Docker, port 3001). Accessing `status.kubelab.live` gave ERR_CONNECTION_REFUSED because there was no reverse proxy — just a raw port on a Tailscale IP.

**Problem**: RPi3 has no Traefik/Caddy. Accessing `https://status.kubelab.live` hits port 443, but Uptime Kuma only listens on 3001. No HTTPS termination, no security headers.

**Solution**: Use K3s Traefik as the reverse proxy via the "external service" pattern:
1. Create a headless `Service` (no selector) + `EndpointSlice` pointing to RPi3's Tailscale IP (`100.64.0.6:3001`)
2. Create an `IngressRoute` for `status.staging.kubelab.live` with `secure-headers`, `error-pages`, `crowdsec-bouncer` middlewares
3. Prod overlay patches the domain to `status.kubelab.live`
4. Pattern matches existing `external/ollama.yaml` — same label `kubelab.live/location: external`

**Rule**: Bare-metal services that need HTTPS/security headers should be proxied through K3s Traefik using the Service + EndpointSlice pattern in `infra/k8s/base/external/`. No need to run a reverse proxy on every bare-metal host.

---

### [2026-03-03] Headscale Split DNS Must Target `staging.kubelab.live`, Not `kubelab.live`

**Context**: Uptime Kuma on RPi3 (`status.kubelab.live`) unreachable from workstation browser. K3s cluster and RPi4 were intentionally off. `nslookup status.kubelab.live` timed out — DNS resolver was `100.100.100.100` (Tailscale MagicDNS) routing to RPi4 which was down.

**Problem**: Headscale split DNS was configured as `kubelab.live → 100.64.0.5` (RPi4). This captured ALL `*.kubelab.live` queries, including prod domains that have public Cloudflare A records (`status.kubelab.live → 162.55.57.175`). When RPi4 is off, Tailscale's MagicDNS has no fallback for split DNS routes — queries simply timeout. Prod domains become unreachable from any VPN client despite having valid public DNS records.

**Impact**: Any VPN client cannot reach prod services (`status.kubelab.live`, `grafana.kubelab.live`, etc.) when RPi4 is down. The external monitoring page (Uptime Kuma) — whose entire purpose is to work when the lab is off — was unreachable from the primary workstation.

**Solution**: Narrowed split DNS from `kubelab.live` to `staging.kubelab.live` in Headscale config (both VPS live config and repo IaC at `infra/stacks/services/core/headscale/config/config.yaml`). Now:
- `*.staging.kubelab.live` → RPi4 CoreDNS (requires RPi4 up — expected for staging)
- `*.kubelab.live` (prod) → global resolvers (1.1.1.1) → Cloudflare → VPS (works always)

**Rule**: Headscale split DNS routes have NO fallback — if the target DNS server is unreachable, queries timeout with no retry to global resolvers. Only route domains that genuinely need internal resolution (staging). Prod domains with public Cloudflare records must NOT be captured by split DNS. For VPN-only bare-metal services without public DNS (ollama, jetson), use Headscale `extra_records` instead of split DNS — they inject A records directly into MagicDNS without depending on any external DNS server.

---

### [2026-03-01] yamllint Directives Don't Work Inside YAML Literal Block Scalars

**Context**: Pre-commit yamllint failed on argon2 hash lines (126 chars > 120 max) inside Authelia's `configuration.yml: |` block in K8s ConfigMaps.

**Problem**: Added `# yamllint disable rule:line-length` / `# yamllint enable rule:line-length` comments inside the `|` block. yamllint still reported errors. Root cause: inside a YAML literal block scalar (`|`), everything is string content — `#` comments are part of the string, not YAML comments. yamllint can't parse directives embedded in string content.

**Solution**: Bumped yamllint `line-length.max` from 120 to 130 in `.pre-commit-config.yaml`. This accommodates standard argon2 hash output (typically ~126 chars) without disabling line-length checking entirely.

**Rule**: yamllint inline directives (`# yamllint disable/enable`) only work in actual YAML comment positions, not inside literal block scalars (`|`), folded scalars (`>`), or quoted strings. For long lines inside `|` blocks, adjust the global `line-length.max` config.


### [2026-03-06] Astro i18n Type Safety — ES-Only Keys Need EN Stubs

**Context**: Rewrote portfolio landing page with newsletter CTA only on Spanish pages. Added `newsletter.*` keys only to the `es` object in `ui.ts`.

**Problem**: The `t()` function is typed against `defaultLang` (EN) keys: `keyof (typeof ui)[typeof defaultLang]`. ES-only keys like `newsletter.placeholder` cause TypeScript error TS2345 — the key doesn't exist in the EN type.

**Solution**: Add the keys to EN as well with English translations. They won't be displayed on EN pages, but the type system needs them present in the default locale.

**Rule**: In Astro i18n with `defaultLang` as the type source, ALL keys must exist in the default locale object. Language-specific display logic belongs in components, not in the type system.

### [2026-03-06] Strategic Positioning Pivot — Builder Over Consultant

**Context**: Competitive analysis of 14 developer personal sites revealed unique positioning gap.

**Problem**: Original portfolio was positioned as a consultant selling services (Hormozi-style). This conflicted with the actual goal: building authority as an engineer for employment/freelance opportunities + growing a Spanish newsletter audience.

**Solution**: Pivoted to "builder who documents — from hardware to cloud". Removed Services, ContactCTA, "Work with me" page entirely. Landing simplified to Hero → Projects → Latest Notes → GitHub chart. Newsletter CTA only on ES pages.

**Rule**: Personal site positioning must match the actual business model. "Selling services" requires case studies and testimonials. "Building authority" requires projects and content. Don't mix the two.

---

### [2026-03-07] Static Site Font Optimization — woff2, Unused Weight Removal, Preloading

**Context**: Full audit of the mlorente.dev portfolio site found 5 Roboto `.woff` font files (468KB total), one of which (Roboto-Light) was loaded by CSS but never used by any Tailwind class.

**Problem**: Three compounding issues: (1) `.woff` format is ~30% larger than `.woff2`; (2) Roboto-Light (93KB) was declared in `@font-face` but no component used `font-light` or `font-thin`; (3) No `<link rel="preload">` for critical fonts caused FOUT (Flash of Unstyled Text) on initial load.

**Solution**: Converted 4 active weights to `.woff2` via fontTools (`TTFont` with `flavor='woff2'`). Deleted all `.woff` files and the unused Light weight entirely. Added `<link rel="preload" href="..." as="font" type="font/woff2" crossorigin>` for Regular and Bold in `<head>`. Result: 468KB → 265KB (-43%), 5 files → 4 files, no FOUT.

**Rule**: For self-hosted fonts on static sites: (1) always use `.woff2` — `.woff` is legacy; (2) audit actual CSS class usage before loading font weights — unused weights are pure waste; (3) preload the 1-2 most critical weights (body + bold) in `<head>` with `crossorigin` attribute (required even for same-origin fonts); (4) `font-display: swap` alone is not enough — preload eliminates the swap flash.

---

### [2026-03-07] nginx Security Headers Lost in Location Blocks

**Context**: Audit of the portfolio nginx.conf found security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) defined in the `server` block, with a separate `location` block for static assets that had its own `add_header Cache-Control`.

**Problem**: nginx does NOT inherit `add_header` directives from parent blocks when a child `location` block contains ANY `add_header` directive. The static assets location had `add_header Cache-Control "public, immutable"` — this silently dropped all three security headers from the `server` block. Static assets (CSS, JS, fonts, images) were served without security headers.

**Solution**: Duplicate all security headers in every `location` block that has its own `add_header`. Added `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Permissions-Policy` to the static assets location alongside the `Cache-Control` header.

**Rule**: In nginx, if any `location` block needs its own `add_header`, it MUST redeclare ALL security headers from the parent `server` block. This is a well-known nginx footgun. Always verify headers per-location with `curl -I`. Consider using `include snippets/security-headers.conf` to avoid duplication in larger configs.

### [2026-03-14] RPi4 SD reflash — /etc/hosts VPN fallback missing

**Context:** Reflashed RPi4 SD card. Pre-config script (`configure-sd.sh`) wrote netplan, nftables, dnsmasq, sysctl — but `/etc/hosts` VPN fallback (`162.55.57.175 vpn.kubelab.live`) was missing on final verification.

**Root cause:** The `grep -q` guard checked for the entry but the `cat >>` append ran under sudo which failed silently in the non-interactive shell. The script reported OK but didn't write.

**Fix:** Added manually via `sudo bash -c 'cat >> /etc/hosts'`.

**Rule:** After ANY RPi4 SD reflash, ALWAYS verify `/etc/hosts` contains `162.55.57.175 vpn.kubelab.live` before booting. Without it, Tailscale can't bootstrap (circular dependency: DNS → Tailscale → DNS). This is the most critical single line on the RPi4.

**Related:** `40-runbooks/dns-homelab.md` §RPi4 Tailscale bootstrap circular dependency.
"

### [2026-03-14] RPi4 full SD card reflash — recovery procedure

**Context:** RPi4 SD card failed. Required full reflash of Ubuntu Server 24.04 LTS arm64 and complete reprovisioning.

**Issues encountered during recovery:**

1. **SSH key mismatch:** Raspberry Pi Imager stored a different SSH key (`mlorentedev@deployment`) than the workstation key (`manu@msi`). Both keys must be in `authorized_keys`. See `40-runbooks/ssh-keys.md`.

2. **Netplan globbing not supported:** `enx*` wildcard in netplan causes `Error in network definition: must not use globbing`. Use the exact interface name (`enx00249b1b0d6b`). nftables DOES support `enx*` — netplan does NOT.

3. **WiFi SSID parsing bug in configure-sd.sh:** The `awk`/`grep` extraction of WiFi credentials from the Imager's `50-cloud-init.yaml` parsed incorrectly, putting `"access-points"` as SSID. Manual edit required.

4. **regulatory-domain matters:** US vs ES affects which WiFi channels are scanned. Set to match your country.

5. **dnsmasq kills WiFi default route:** After `systemctl restart dnsmasq`, the wlan0 default route disappears. Root cause unclear — possibly dnsmasq interferes with DHCP client on wlan0. Fix: `sudo netplan apply` restores the route.

6. **Docker + nftables iptables conflict:** Docker expects iptables chains (`DOCKER-FORWARD`) that nftables flush removes. Fix: `sudo systemctl restart docker` after nftables is loaded — Docker recreates its chains.

7. **resolv.conf chicken-and-egg:** If `resolv.conf` points to `127.0.0.1` (Pi-hole) before Pi-hole is running, DNS fails and nothing can be installed. Set to `8.8.8.8` during provisioning, switch to `127.0.0.1` after Pi-hole is up.

8. **Headscale assigns new IP on re-registration:** Reflashed node gets a new Tailscale IP (`.10` instead of `.5`). Must update: Headscale split DNS config, CoreDNS Corefile, and all references to the old IP. Delete the old node in Headscale.

9. **Headscale route approval syntax (v0.28):** `headscale routes list` doesn't exist. Use `headscale nodes approve-routes -i <ID> --routes <CIDR>`.

10. **`/etc/hosts` VPN fallback critical:** `162.55.57.175 vpn.kubelab.live` MUST exist or Tailscale bootstrap fails (circular dependency). Verify this FIRST on any reflash.

**Correct provisioning order:**
1. Flash Ubuntu Server 24.04 LTS arm64 with Imager (set hostname, user, WiFi, SSH key)
2. Mount SD on PC → add second SSH key + pre-write configs (netplan, nftables, dnsmasq, sysctl, /etc/hosts)
3. Boot RPi4 → verify WiFi IP
4. SSH in → `apt install nftables dnsmasq` → enable services
5. Install Docker → install Tailscale → register with Headscale
6. Approve subnet routes on VPS
7. Deploy Pi-hole + CoreDNS containers
8. Lock resolv.conf → install watchdog timer
9. Update Headscale split DNS if IP changed
10. Force Tailscale re-sync on all clients

**New Tailscale IP:** `100.64.0.10` (was `100.64.0.5`). Updated everywhere: Headscale split DNS, CoreDNS, common.yaml, ansible inventory, Makefile, vault runbooks (dns-homelab, headscale-setup, monitoring, hardware-setup).

**Scripts:** `infra/provisioning/rpi4/` (configure-sd.sh, part1-base-system.sh, part2-services.sh)

**Rule:** This entire process should be an Ansible playbook. Next reflash MUST be automated. See ANSIBLE-004/005 in backlog.

### [2026-03-14] nftables masquerade must include wlan0 (not just enx*)

**Context:** After RPi4 reflash, LAN nodes (172.16.1.0/24) had no internet. Ping to 8.8.8.8 from k3s-server returned 100% packet loss.

**Root cause:** nftables NAT rule only had `oifname "enx*" masquerade`. When USB ETH has no IP (DHCP from router not working), traffic exits via wlan0 — but wlan0 had no masquerade rule. Result: packets leave the RPi4 via WiFi but with source IP 172.16.1.x → router drops them (not its subnet).

**Fix:** Add `oifname "wlan0" masquerade` alongside the `enx*` rule. Both can coexist — Linux chooses the exit interface by route metric (enx* metric 100, wlan0 metric 600). The matching masquerade rule activates automatically.

**Updated `/etc/nftables.conf`:**
```
table inet nat {
    chain postrouting {
        type nat hook postrouting priority 100; policy accept;
        oifname "enx*" masquerade
        oifname "wlan0" masquerade
    }
}
```

**Rule:** RPi4 nftables MUST masquerade on ALL WAN interfaces, not just the primary. If a new WAN interface is added, add its masquerade rule too.

### [2026-03-14] Tailscale reconnection causes brief LAN flaps

**Context:** After 5 days offline, all homelab nodes (bee, jet1, k3s-server/agents) reconnected to Tailscale simultaneously. Uptime Kuma reported intermittent DOWN on LAN monitors (172.16.1.x).

**Root cause:** Tailscale modifies routing tables when reconnecting. During the 5-30 second reconnection window, packets may be dropped or misrouted. With all nodes reconnecting at once, the flapping compounds.

**Resolution:** Self-heals within 2-5 minutes. No action needed. Uptime Kuma will show brief outages.

**Rule:** After a mass reconnection event (power outage, Headscale restart), expect 2-5 minutes of Uptime Kuma flapping. Do not troubleshoot individual nodes until the mesh stabilizes.

### [2026-03-14] USB ETH RPi4 — router DHCP not responding

**Context:** After RPi4 SD reflash, USB ETH adapter (enx00249b1b0d6b, ASIX AX88179) is link UP but receives no DHCP lease from router. WiFi (wlan0) works fine on the same router.

**Status:** UNRESOLVED. L2 block confirmed — not L3/DHCP. DHCP Discover packets leave the adapter (tcpdump confirmed) but router never responds. ARP also fails with static IP. MAC `00:24:9b:1b:0d:6b` appears in Xfinity panel as "Offline", not blocked/paused.

**Ruled out:** driver, link layer, netplan config, MAC filtering in router panel, bridge mode, DHCP client-ID type.

**Hypothesis:** Router port dead OR Xfinity firmware silently filtering the MAC at L2 switching level.

**Impact:** Non-blocking. WiFi provides full connectivity. USB ETH is redundancy + speed (Gigabit vs WiFi ~50Mbps).

**Next step:** Connect a different device to the same cable + same router port. If it gets IP → MAC-specific filtering (try MAC spoofing + contact Xfinity). If not → dead port (try different port).

### [2026-03-14] Headscale IP change requires updates in 6+ locations

**Context:** RPi4 reflash caused Headscale to assign new IP (100.64.0.10, was 100.64.0.5). Required updating references in 6 files + VPS config + SSH config.

**Files updated:**
- `infra/config/values/common.yaml` (networking.nodes.rpi4.tailscale_ip)
- `infra/ansible/inventories/homelab.yml` (ansible_host)
- `infra/stacks/services/core/headscale/config/config.yaml` (split DNS)
- `Makefile` (RPI4_HOST)
- VPS `/opt/headscale/config/config.yaml` (split DNS, applied manually)
- `~/.ssh/config` on workstation (alias rpi4)
- MEMORY.md (network reference)

**Files NOT updated (content, historical):**
- Blog notes (.mdx files referencing old IP in examples)

**Rule:** When a Headscale node changes IP, grep for the old IP across the entire repo (`grep -r "100.64.0.OLD"`). Also update VPS config and workstation SSH config manually.

### [2026-03-15] Headscale v0.28 has no HTTP /health endpoint
**Context:** Implementing Ansible health check for Headscale role (ADR-020 Phase 2)
**Problem:** Ansible uri module checking http://127.0.0.1:8080/health returned 404. The Headscale container's own Docker healthcheck uses `headscale version` (CLI), not HTTP. There is no HTTP health endpoint in Headscale v0.28.
**Solution:** Use `docker inspect --format '{{.State.Health.Status}}' headscale` to check container health status instead of HTTP endpoint. The docker-compose healthcheck already verifies Headscale is working via CLI.
**Tags:** `#ansible` `#headscale` `#healthcheck` `#docker`

### [2026-03-15] VPS Docker network rename requires atomic migration
**Context:** ADR-020 Phase 2 — deploying Headscale via Ansible with docker_network=kubelab (renamed from proxy)
**Problem:** Changing docker_network from 'proxy' to 'kubelab' in common.yaml broke Headscale connectivity. Traefik and 10 other VPS containers remain on 'proxy' network. Headscale recreated on 'kubelab' network couldn't communicate with Traefik — vpn.kubelab.live went down.
**Solution:** Reverted common.yaml to docker_network: proxy. Network rename deferred to Phase 2b (traefik_vps role) which will migrate ALL VPS containers atomically. Rule: never rename a shared Docker network piecemeal — all consumers must move together.
**Tags:** `#docker` `#networking` `#ansible` `#vps` `#outage`

### [2026-03-15] Toolkit command.run must stream output for Ansible
**Context:** Running Ansible playbooks via toolkit infra ansible run command
**Problem:** command.run() with capture_output=True buffers all stdout until the command finishes. For Ansible playbooks that take 30-60s with per-task output, the CLI appears hung with no feedback.
**Solution:** Pass capture_output=False to command.run() in the ansible_run CLI command. This streams Ansible output directly to the terminal in real-time. Trade-off: can't inspect result.stdout/stderr after, but for interactive commands like Ansible this is the correct behavior.
**Tags:** `#toolkit` `#ansible` `#cli` `#ux`

### [2026-03-15] Traefik v3.6 does not support maxBackups/maxSize in accessLog config
**Context:** Upgrading Traefik from v3.0 to v3.6 via Ansible traefik_vps role
**Problem:** Added maxSize and maxBackups fields to accessLog config in traefik.yml template. Traefik v3.6 crashed with 'field not found, node: maxBackups'. These fields don't exist in Traefik's static config schema.
**Solution:** Removed maxSize and maxBackups from traefik.yml template. Log rotation for Traefik access logs should be handled externally (logrotate on the host, or a Docker logging driver). The accessLog config only supports filePath, format, and fields.
**Tags:** `#traefik` `#ansible` `#config`

### [2026-03-15] Traefik certResolver name vs ACME DNS provider are different concepts
**Context:** Templating Traefik static config for VPS — entrypoint TLS certResolver
**Problem:** Used dns_provider variable ('cloudflare') as the certResolver name in entrypoint config. Traefik errored 'Router uses a nonexistent certificate resolver' because the resolver is NAMED 'letsencrypt' in certificatesResolvers block, while 'cloudflare' is the DNS challenge provider within that resolver.
**Solution:** Hardcode 'letsencrypt' as the certResolver name in entrypoint config. The dns_provider variable ('cloudflare') is only used inside the resolver's dnsChallenge.provider field. certResolver name ≠ DNS provider name.
**Tags:** `#traefik` `#acme` `#tls` `#ansible`

### [2026-03-15] Never delete infrastructure components during cleanup without verifying dependencies
**Context:** VPS cleanup after Traefik migration — removed nginx container and error-pages config
**Problem:** Removed nginx container and nginx.yml from Traefik dynamic config because the container was in 'Exited' state. All routes referenced 'error-pages' middleware (defined in nginx.yml), causing Traefik to reject all routers. The 'Exited' state was incidental — the container was needed.
**Solution:** Restarted nginx container and restored nginx.yml. Rule: before removing ANY component, grep for references across all config files. An 'Exited' container is not necessarily unused — it may need to be restarted, not deleted.
**Tags:** `#docker` `#traefik` `#cleanup` `#outage`

### [2026-03-15] Traefik api.insecure=false disables port 8080 dashboard access
**Context:** Migrating Traefik VPS config from manual to Ansible-templated
**Problem:** After templating traefik.yml with api.insecure: false, the dashboard became inaccessible on port 8080. The old config had insecure: false too but the dashboard was accessed directly. With the new config, the dashboard only works via the Traefik router (HTTPS on 443 with Host rule), which requires a valid TLS cert for the dashboard domain.
**Solution:** This is correct behavior — insecure: false means dashboard is only available through a proper router with TLS + auth. The ACME wildcard cert for *.kubelab.live covers traefik.kubelab.live. Dashboard now requires basicAuth credentials to access.
**Tags:** `#traefik` `#security` `#dashboard`

### [2026-03-15] K3s tests should use local kubeconfig not SSH+sudo
**Context:** Running infra tests against K3s cluster from workstation
**Problem:** K3s tests SSH'd to k3s-server and ran `sudo kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml`. This fails in BatchMode SSH because sudo requires a terminal for password input. All 4 K3s tests failed.
**Solution:** Use local kubeconfig (`~/.kube/kubelab-config`) with kubectl directly from workstation. No SSH needed — kubectl connects to K3s API via Tailscale. Simpler, faster (0.66s vs 44s), no sudo issues.
**Tags:** `#testing` `#k3s` `#kubectl` `#ssh`

### 2026-03-16: CI/CD and Branching Simplification

**Lesson: release-please replaces custom semantic-version logic**
- **Problem**: Custom versioning with `paulhatch/semantic-version` + baseline tags + RC calculation produced bugs (0.0.0-rc.0, missing baseline tags, fragile `change_path` per app)
- **Solution**: Adopted `googleapis/release-please-action` with manifest mode for monorepo. Config-driven (`release-please-config.json`), zero custom logic. Creates Release PRs on master push, auto-generates changelogs and tags.
- **Impact**: Removed ~150 lines of custom CI logic. Eliminated baseline tag management, semantic-version action, GitOps update job, and manual tag creation.

**Lesson: trunk-based development > gitflow for single developer**
- **Problem**: `develop` branch added merge ceremony without value — extra merge step, merge conflicts, CI duplication, no real review gate for solo dev
- **Solution**: Eliminated `develop`. Master is the only permanent branch. Feature branches squash-merge directly to master. Environment separation via values files, not branches.
- **Impact**: Simpler CI (one target branch), cleaner git history (squash merge), GitOps-ready (ArgoCD works from single branch + values)

**Lesson: HelmChartConfig must include ALL Traefik config, not just ports**
- **Problem**: Ansible k3s_server role deployed a HelmChartConfig with only port customization, overwriting the existing one that had ACME certResolver + HTTPS redirect + Cloudflare token. Result: staging TLS certificates broke.
- **Root cause**: K3s only supports one HelmChartConfig per chart — deploying a new one replaces the entire config, not just the changed fields.
- **Fix**: Template includes ACME config conditionally (`k3s_traefik_acme_enabled`). All Traefik config in one template.
- **Rule**: When managing K3s HelmChartConfig via Ansible, the template MUST be the complete desired state. There is no merge — it's a full replace.

**Lesson: Pattern C ports (8080/8443) belong in prod.yaml, not common.yaml**
- **Problem**: Setting alternate Traefik ports in common.yaml applied them to ALL environments including staging, breaking staging routing.
- **Fix**: common.yaml has standard ports (80/443). prod.yaml overrides to 8080/8443 for Pattern C (ADR-015 side-by-side validation).
- **Rule**: Environment-specific overrides go in env files. common.yaml = safe defaults that work everywhere.

**Lesson: Ansible role defaults should be empty for SSOT-sourced values**
- **Problem**: Roles had hardcoded defaults (e.g., `headscale_domain: "vpn.example.com"`, `traefik_image: "traefik:v3.6"`) that masked SSOT values and could cause silent failures if playbook vars weren't passed.
- **Fix**: Changed SSOT-dependent defaults to empty strings (`""`). Roles now fail explicitly if playbook doesn't provide values.
- **Rule**: Role defaults should be either empty (forcing playbook to provide) or safe generic values (timeouts, retry counts). Never environment-specific values.

### 2026-03-16: Helm Migration Strategy (ADR-021)

**Lesson: Hybrid Helm — official charts for third-party, generic chart for custom apps**
- **Problem**: 15+ services with hardcoded K8s manifests (domains, IPs, versions). Kustomize overlays duplicate values from common.yaml. No versioning, no rollback, no changelogs.
- **Decision**: ADR-021 — Helm replaces Kustomize entirely. Two chart types:
  - Official Helm charts (Grafana, Loki, Authelia, etc.) consumed as dependencies
  - One generic `kubelab-app` chart for custom apps (api, web, errors)
- **Key insight**: Writing Helm charts for Grafana/Loki is NIH. Official charts are battle-tested. Our value-add is values.yaml configuration only.
- **Migration**: Incremental, service by service. H1 (pilotos) → H2 (third-party) → H3 (cleanup + B6)

### 2026-03-16: CI/CD Release Pipeline Gotchas

**Lesson: release-please tag format — watch separator + include-v-in-tag**
- **Problem**: `tag-separator: "-v"` + `include-v-in-tag: true` produces double-v tags (`errors-vv0.0.0`)
- **Fix**: Use `tag-separator: "-"` with `include-v-in-tag: true` → produces `errors-v0.1.0`
- **Rule**: Test tag format with `release-please` docs before deploying. The tag format affects all downstream consumers (Docker publish, changelogs, Git tags).

**Lesson: GitHub Actions needs explicit write permissions for release-please**
- **Problem**: `startup_failure` on release.yml — GitHub Actions default permissions are `read`, release-please needs `write` to create PRs
- **Fix**: Settings → Actions → General → Workflow permissions → Read and write. Also `can_approve_pull_request_reviews: true`.
- **Rule**: When adding workflows that create PRs/releases, check repo-level Actions permissions first.

**Lesson: Trivy action versions are unstable — use continue-on-error or remove**
- **Problem**: `aquasecurity/trivy-action@master`, `@0.28.0`, `@0.31.0`, `@0.39.0` all failed with different errors
- **Fix**: Removed entirely. Will re-evaluate when action stabilizes or use CLI-based scanning instead.
- **Rule**: Never pin to `@master` for any GitHub Action. If a pinned version breaks, add `continue-on-error: true` rather than blocking builds.

**Lesson: Helm resource adoption requires clean delete + recreate**
- **Problem**: `kubectl apply`-managed resources have labels incompatible with Helm. Annotating for adoption works but patches fail if port specs differ.
- **Fix**: Delete the resource, let Helm recreate it from scratch. The brief downtime is acceptable for staging.
- **Rule**: When migrating from raw manifests to Helm, plan for resource recreation. Don't try to adopt and patch simultaneously.


### 2026-03-16: Helm + Docker Image Gotchas

**Lesson: Mutable tags (:dev) require imagePullPolicy Always + pod restart**
- K8s default `IfNotPresent` caches the image on the node. Even with `Always`, Helm won't restart pods if the tag doesn't change.
- Fix: Use immutable tags (1.0.0) in production. For dev, set `pullPolicy: Always` and accept that `rollout restart` may be needed.

**Lesson: Traefik error middleware serves HTML but assets resolve against original domain**
- Error page HTML from errors service references `/errors/404.webp`, but the browser requests it from the original domain (e.g., staging.mlorente.dev), which doesn't have the image.
- Fix: Base64 inline images in error pages. Zero external dependencies.

**Lesson: CI push + pull_request triggers cause duplicate runs**
- With both `push: branches` and `pull_request: branches` in ci.yml, every push to a branch with an open PR triggers TWO CI runs.
- Fix: Use only `pull_request` trigger. Branch protection ensures PRs are required anyway.

### [2026-03-17] K8s secrets: bootstrap vs application lifecycle
**Context:** ADR-023 Phase 1 provisioning review — discovered Cloudflare API token K8s Secret was missing from Ansible provisioning
**Problem:** Traefik HelmChartConfig referenced `cloudflare-api-token` Secret via secretKeyRef (no `optional: true`), but no Ansible task created it. Traefik would CrashLoopBackOff until secret was manually created. The question was: should this go through the existing `toolkit apply-secrets` pipeline or through Ansible?
**Solution:** Two secret categories with different lifecycles: (1) Bootstrap secrets — needed before pods start, deployed via Ansible templates to `/var/lib/rancher/k3s/server/manifests/` (same pattern as HelmChartConfig). Only 1 in the project: `cloudflare-api-token`. (2) Application secrets — 8 secrets, 23 keys, deployed via `toolkit apply-secrets` after K3s is running. K3s manifests dir is declarative, idempotent, and avoids chicken-and-egg. Future: Sealed Secrets (SEAL-001..004) replaces both mechanisms.
**Tags:** `#k8s` `#secrets` `#ansible` `#k3s` `#architecture`

### [2026-03-17] Ansible role variables: dead code from playbook-side flags
**Context:** ADR-023 Phase 1 provisioning review — auditing tailscale role usage in provisioning playbooks
**Problem:** Both provisioning playbooks passed `tailscale_extra_flags: "--accept-routes"` to the tailscale role, but the role never uses that variable. The role has its own `tailscale_accept_routes` variable (default: false). Result: nodes would silently NOT accept routes from other VPN peers.
**Solution:** Always verify role defaults/main.yml to confirm which variables the role actually consumes before passing vars from playbooks. Fix: replace `tailscale_extra_flags` with `tailscale_accept_routes: true`. Prevention: pre-provisioning review of role interface (defaults + tasks) against playbook vars.
**Tags:** `#ansible` `#tailscale` `#code-review`

### [2026-03-17] Pre-flight SSH validation prevents ssh_hardening lockout
**Context:** ADR-023 Phase 1 provisioning review — ssh_hardening role disables password auth
**Problem:** The ssh_hardening role disables password authentication and enables key-only auth. If the SSH key isn't already authorized on the target, the operator gets locked out with no recovery path. On fresh Ubuntu 24.04 installs, this is a real risk.
**Solution:** Add a pre-flight play (Play 0) at the start of provisioning playbooks. No become, no gather_facts. Three checks: (1) ansible.builtin.ping — verifies SSH+Python, (2) sudo -n true — verifies become works, (3) stat on SSH key file — verifies key exists on controller. If any fails, playbook stops before touching anything. Standard professional practice for hardening playbooks.
**Tags:** `#ansible` `#ssh` `#security` `#provisioning`

### [2026-03-17] tailscale up hangs without --timeout waiting for DERP mesh
**Context:** ADR-023 Phase 1 provisioning — ace2 first Tailscale registration via Ansible
**Problem:** tailscale up --authkey registered the node in Headscale successfully (confirmed in logs: node.id=15 connected), but the command hung indefinitely waiting for full DERP mesh connectivity. This blocked the Ansible playbook and made ace2 unreachable via SSH. Had to power cycle.
**Solution:** Add --timeout=30s to the tailscale up command and timeout: 60 to the Ansible task. Registration completes fast; it's the mesh handshake that can hang. Also: /ts2021 returns 500 to curl (no WebSocket Upgrade header) — this is expected, not a real error. Smart plug didn't reliably power-cycle the MiniPC (BIOS auto-power-on needs hard power cut).
**Tags:** `#tailscale` `#headscale` `#ansible` `#provisioning` `#debugging`

### [2026-03-17] Tailscale subnet routes intercept LAN traffic from workstation
**Context:** ADR-023 Phase 1 — after ace2 joined Tailscale mesh, workstation lost LAN connectivity to 172.16.1.0/24
**Problem:** RPi4 advertises 172.16.1.0/24 via Tailscale (--advertise-routes). Workstation's Tailscale intercepts ALL traffic to that subnet via tailscale0 (table 52) instead of the physical LAN route. ace1 (not in mesh) worked because Tailscale routed it via RPi4→LAN→ace1. ace2 (new peer) failed because Tailscale tried direct peer routing before mesh was stable. Result: `ip route get 172.16.1.5` → `dev tailscale0`, not `dev wlp1s0`.
**Solution:** Pending investigation. Options: (1) Remove RPi4 subnet route advertisement if all LAN nodes join Tailscale directly, (2) Configure Tailscale exit node or split routing, (3) Add direct LAN route with higher priority than Tailscale table 52. Must fix before ace1 provisioning — BOOTSTRAP mode needs LAN connectivity.
**Tags:** `#tailscale` `#networking` `#routing` `#provisioning`

### [2026-03-17] Tailscale up disrupts SSH during Ansible provisioning
**Context:** ADR-023 Phase 1 — running tailscale up via Ansible on fresh node
**Problem:** tailscale up modifies routing table immediately, killing SSH connection. Synchronous Ansible command task hangs forever waiting for response. Node becomes unreachable via LAN. --timeout=30s flag didn't help because network broke before timeout could trigger.
**Solution:** Use async Ansible task: async: 60 + poll: 0, then async_status with retries. This launches tailscale up in background so Ansible doesn't depend on SSH surviving. Still may fail retries if LAN routing is broken (see subnet route issue). Real fix: ensure LAN fallback works independently of Tailscale routing.
**Tags:** `#tailscale` `#ansible` `#ssh` `#async` `#provisioning`

### [2026-03-17] Tailscale netfilter-mode flag location: tailscale up, NOT tailscaled daemon
**Context:** ADR-023 Phase 1 — debugging Tailscale blocking LAN connectivity on ace2
**Problem:** tailscaled daemon kills LAN connectivity on ace2 when it starts. Tried --netfilter-mode=nodivert as daemon flag (FLAGS in /etc/default/tailscaled) — INVALIDARGUMENT. Tried as TS_EXTRA_ARGS — wrong variable name (service uses $FLAGS). The flag belongs to `tailscale up`, not `tailscaled`. With FLAGS="--netfilter-mode=nodivert" the daemon appeared to start once but then crashed on restart due to ExecStopPost cleanup corruption.
**Solution:** UNSOLVED. The flag --netfilter-mode=nodivert goes on `tailscale up` (client), not `tailscaled` (daemon). When applied via `tailscale up`, LAN worked but mesh didn't connect (timeout). Root cause: tailscaled modifies iptables/routing at startup before `tailscale up` is called, breaking LAN. ExecStopPost=--cleanup also corrupts state (DNS route for missing interface). Workaround: disable ExecStopPost via systemctl edit. Full fix needs fresh investigation — possibly tailscale set --netfilter-mode=nodivert (persists in state) or userspace networking mode.
**Tags:** `#tailscale` `#networking` `#iptables` `#systemd` `#debugging`

### [2026-03-17] tailscaled ExecStopPost cleanup corrupts DNS state on crash
**Context:** ADR-023 Phase 1 — tailscaled wouldn't restart after crash/power-cycle on ace2
**Problem:** When tailscaled crashes or is killed (power cycle), ExecStopPost runs `tailscaled --cleanup` which tries to remove DNS routes for tailscale0 interface. If the interface doesn't exist (crash/unclean shutdown), cleanup fails with 'route ip+net: no such network interface' and corrupts state. Next start attempt also fails because it runs cleanup first.
**Solution:** Disable ExecStopPost via systemd override: `sudo systemctl edit tailscaled` → add `[Service]\nExecStopPost=` (empty value overrides). Also need `sudo systemctl daemon-reload`. This prevents cleanup from running. /etc/default/tailscaled uses PORT and FLAGS variables (not TS_EXTRA_ARGS). Default: PORT=0, FLAGS="".
**Tags:** `#tailscale` `#systemd` `#dns` `#debugging`

### 2026-03-17: Phase 1 Provisioning Session — Known Issues

#### Tailscale kills LAN connectivity on homelab nodes (UNSOLVED)
- **Symptom**: When `tailscaled` runs on ace2, all inbound LAN traffic is dropped. ace2 can ping out (172.16.1.1 OK) but nothing can ping in (172.16.1.5 unreachable from RPi4, ace1, workstation).
- **Proven not the cause**: iptables ts-input (0 references with nodivert), rp_filter (tested 0), UFW (22/tcp open from Anywhere).
- **Proven cause**: tcpdump shows ICMP requests arriving on enp1s0 but kernel never generates reply. Stopping tailscaled instantly fixes LAN.
- **Partial workaround**: `tailscale up --netfilter-mode=nodivert` restored LAN briefly but mesh didn't connect within 30s timeout.
- **To investigate**: `tailscale set --netfilter-mode=nodivert` (persists in state file), userspace networking mode (`--tun=userspace-networking`), or Tailscale version-specific bug.

#### Workstation Tailscale routing table 52 overrides LAN routes
- **Cause**: RPi4 advertises 172.16.1.0/24 via Tailscale. Workstation's table 52 takes priority over physical LAN route.
- **Fix (automated in Makefile BOOTSTRAP)**: `sudo ip rule add to LAN_CIDR lookup main priority 100` before provisioning, removed after.
- **WireGuard AllowedIPs asymmetry**: Outbound to 172.16.1.5 goes via RPi4 peer (subnet route), but ace2 responds directly (own peer). WireGuard drops response because 172.16.1.5 not in ace2's AllowedIPs — only 100.64.0.5/32 is.

#### tailscaled ExecStopPost corrupts state after crash
- **Cause**: `tailscaled --cleanup` tries to remove DNS routes for tailscale0 interface. After crash/power-cycle, interface doesn't exist → cleanup fails → next start fails.
- **Fix**: `systemctl edit tailscaled` → `[Service]\nExecStopPost=` (empty = disable cleanup). Must also `daemon-reload`.
- **/etc/default/tailscaled** uses `PORT` and `FLAGS` variables (NOT `TS_EXTRA_ARGS`). Default: `PORT=0`, `FLAGS=""`.

### [2026-03-18] Tailscale accept-routes=true on LAN nodes hijacks reply routing and kills inbound traffic
**Context:** Provisioning bare-metal homelab nodes (ace1, ace2) on 172.16.1.0/24. RPi4 advertises that subnet as a Tailscale subnet route. Ansible playbooks had tailscale_accept_routes: true for all nodes.
**Problem:** When tailscaled ran on ace2 (172.16.1.5) with --accept-routes=true, all inbound LAN traffic died. Outbound worked. Root cause: Tailscale installed 172.16.1.0/24 in routing table 52 via tailscale0 at priority 5270 (before main table). Reply packets to inbound LAN requests got routed through the Tailscale tunnel to RPi4 instead of directly out enp1s0. Asymmetric routing caused packet drops. Debugging was hard because outbound worked fine and iptables/rp_filter were red herrings.
**Solution:** Set --accept-routes=false on nodes that are physically on the advertised subnet. Live fix: `tailscale set --accept-routes=false`. Ansible fix: `tailscale_accept_routes: false` in provision-ace1.yml and provision-ace2.yml. Rule: accept-routes=true only for nodes NOT on the advertised subnet (workstation, VPS). Documented in CLAUDE.md gotchas and 30-architecture/infra/networking-topology.md with full 3-network topology diagram.
**Tags:** `#tailscale` `#networking` `#routing` `#ansible` `#bare-metal` `#debugging`

### [2026-03-20] Pattern C port 8080 conflict with Docker Compose Traefik dashboard
**Context:** VPS K3s migration — K3s Traefik Pattern C uses 8080/8443 alongside Docker Compose Traefik on 80/443
**Problem:** Docker Compose Traefik dashboard binds port 8080, same as K3s Pattern C HTTP port. Both can't listen on 8080 simultaneously.
**Solution:** Remap Docker Compose Traefik dashboard to 9080 via traefik_vps role re-deploy BEFORE installing K3s. Playbook checks port binding, remaps, verifies 8080 is free, then proceeds with K3s install.
**Tags:** `#traefik` `#k3s` `#pattern-c` `#ports`

### [2026-03-20] K8s IngressRoute port must match Service port, not container port
**Context:** Prod K3s deployment — web service returning 404 despite pod Running and healthy
**Problem:** Web IngressRoute had port: 8080 (container port) but Service exposed port: 4321. Traefik sends traffic to Service port, not container port. Request never reached the pod.
**Solution:** IngressRoute service port must match the Service spec.ports[].port (4321), not the container's containerPort (8080). Service targetPort handles the translation to container port.
**Tags:** `#k8s` `#traefik` `#ingressroute` `#debugging`

### [2026-03-20] Always validate security policies in staging before prod cutover
**Context:** Phase 2 VPS K3s migration — changing Authelia access_control policies for gitea and minio
**Problem:** Applied security policy changes directly to prod overlay without testing in staging first. Could have broken login flows or locked out services.
**Solution:** Policy changes must follow staging → prod flow. HTTP status codes (200/302) are not enough — functional validation (UI loads, login works, data visible) is required before cutover.
**Tags:** `#security` `#authelia` `#staging` `#process`

### [2026-03-21] OIDC client_secret flow: Authelia stores hash, client stores plaintext

**Context:** Configuring OIDC SSO between Authelia (IdP) and Gitea/Grafana (clients) on K3s.

**Problem:** Confused which side stores hash vs plaintext. Authelia docs show argon2 hash in configuration, but it wasn't clear the client service needs the raw plaintext secret (like a password).

**Solution:** Same as password hashing: Authelia stores the argon2 HASH in its ConfigMap. The client service (Gitea, Grafana) stores the PLAINTEXT in its env/config (from K8s Secret). `toolkit secrets hash` auto-generates missing OIDC client secrets and stores plaintext in SOPS, hash in Authelia config.

**Rule:** OIDC client_secret = password pattern. Hash in IdP config, plaintext in client config (sourced from SOPS). Never put plaintext in ConfigMaps.
**Tags:** `#oidc` `#authelia` `#secrets` `#sops`

### [2026-03-21] error-pages middleware must NOT intercept 400-404

**Context:** Custom error pages service deployed on K3s with Traefik errors middleware.

**Problem:** Error-pages middleware was intercepting ALL HTTP errors including 400-404. This swallowed application-level responses: API 401 = "not authenticated" became a generic error page, API 404 = "resource not found" became a generic 404 page. Clients couldn't distinguish between "endpoint doesn't exist" and "resource not found within a valid endpoint."

**Solution:** Only intercept infrastructure errors (408, 429, 500-503). Application responses (400-404) pass through to the client. The catch-all IngressRoute handles unknown domains directly via the errors service (no middleware needed there).

**Rule:** Error-pages middleware = infrastructure errors only (408, 429, 500+). Never intercept 4xx below 408 — those are application semantics.
**Tags:** `#traefik` `#error-pages` `#middleware` `#k8s`

### [2026-03-21] Hairpin DNS in K8s: CoreDNS forward to RPi4

**Context:** OIDC token exchange failing in K3s — pods couldn't resolve `*.staging.kubelab.live` to reach Authelia.

**Problem:** K3s pods use internal CoreDNS (10.43.0.10) which only knows K8s service names. External domains like `auth.staging.kubelab.live` fail with "no such host". This breaks any pod-to-pod communication using external domain names (OIDC token exchange, webhooks, API calls).

**Options evaluated:**
1. CoreDNS `rewrite` to Traefik ClusterIP — rejected: hardcodes dynamic ClusterIP, complex regex with answer rewriting
2. Service mesh (Istio/Linkerd) — rejected: ~2GB RAM overhead, overkill for 12 services on single node
3. **CoreDNS `forward` to RPi4 (100.64.0.10)** — chosen: reuses existing DNS infra, zero hardcoding, one line per zone

**Solution:** K3s `coredns-custom` ConfigMap forwards staging zones to RPi4 CoreDNS. Applied via `make deploy-k8s` through the `cluster_bootstrap` layer (ADR-047/TOOL-009, 2026-06-17): the toolkit renders the `RESOLVE_RPI4_TAILSCALE_IP` placeholder via MagicDNS and server-side applies it outside the Kustomize overlay. (Previously a hand-rolled `dig|sed|kubectl` step in the now-removed `deploy-external` target.)

**Rule:** For K8s hairpin DNS, prefer forwarding to existing authoritative DNS over rewriting to ClusterIPs. ClusterIPs are dynamic; DNS infrastructure is stable. Service mesh only when >50 services or multi-cluster.
**Tags:** `#k8s` `#coredns` `#dns` `#oidc` `#hairpin` `#rpi4`

### [2026-03-21] Kustomize images: transformer is SSOT for image versions

**Context:** Managing container image tags across base and overlay kustomization.yaml files.

**Problem:** Image tags hardcoded in base manifests diverged from common.yaml values. Manual updates across multiple files led to version drift.

**Solution:** The `images:` section in kustomization.yaml overrides any hardcoded tags in base manifests. `make sync-k8s-images` reads from common.yaml and updates kustomization.yaml `images:` entries. This is the single source of truth for image versions in K8s.

**Rule:** Never edit image tags in base manifests directly. Use `images:` transformer in kustomization.yaml, synced from common.yaml via `make sync-k8s-images`.
**Tags:** `#kustomize` `#images` `#ssot` `#make`

### [2026-03-21] Gitea admin auto-creation via postStart lifecycle hook

**Context:** Gitea deployment on K3s needs an admin user configured on first boot.

**Problem:** Manual `gitea admin user create` after every pod restart is fragile and forgettable. Needed an idempotent, declarative approach.

**Solution:** `postStart` lifecycle hook in the Gitea deployment creates admin from K8s Secret if not exists. Same pattern as CrowdSec bouncer auto-registration. Idempotent — skips if user already exists.

**Rule:** For services needing post-boot CLI initialization, use `postStart` lifecycle hooks with idempotent commands. Pattern: check-if-exists → create-if-not. Examples: CrowdSec bouncer, Gitea admin.
**Tags:** `#k8s` `#gitea` `#lifecycle` `#pattern`

### [2026-03-21] deploy-k8s must include apply-secrets as prerequisite

**Context:** Running `make deploy-k8s ENV=staging` without applying secrets first.

**Problem:** Pods fail to start with `CreateContainerConfigError` because K8s Secrets don't exist. Easy to forget the separate `apply-secrets` step, especially after cluster rebuilds.

**Solution:** Integrated apply-secrets into the deploy-k8s Makefile target as a prerequisite. Full pipeline: sync-k8s-images → sync-oidc-hashes → apply-secrets → kubectl apply.

**Rule:** Deploy targets must be self-contained. If a step is always required before deployment, make it a prerequisite, not a separate manual step.
**Tags:** `#make` `#k8s` `#secrets` `#deploy`

### [2026-03-21] OIDC hashes in ConfigMaps are NOT secrets

**Context:** Reviewing whether argon2 hashes of OIDC client secrets in Authelia ConfigMap are a security concern.

**Problem:** Initial instinct was to treat the hash as sensitive. But argon2 is a one-way hash — knowing the hash doesn't reveal the plaintext client_secret.

**Solution:** Hashes stay in ConfigMap (version-controlled, diff-able). Plaintext stays in SOPS → K8s Secret. `sync_oidc_hashes.py` automates hash extraction from SOPS to ConfigMap, eliminating manual copy-paste errors.

**Rule:** Argon2/bcrypt hashes are safe in ConfigMaps — they're one-way. Only the plaintext secret needs K8s Secret + SOPS protection. Automate the sync to eliminate manual errors.
**Tags:** `#security` `#oidc` `#configmap` `#sops`

### [2026-03-21] Service mesh assessment: overkill for single-node K3s

**Context:** Evaluating Istio/Linkerd for mTLS and traffic observability on K3s cluster.

**Problem:** Single-node K3s with 12 services. Service mesh adds ~2GB RAM overhead (sidecar per pod), operational complexity (CRDs, certificate rotation, upgrade path), and debugging difficulty (envoy proxy chain).

**Solution:** Defer service mesh. Current needs (hairpin DNS, basic auth) solved with CoreDNS rewrite + Authelia. Reconsider in Phase 4 (mTLS requirement), Phase 6 (traffic observability), or when multi-cluster.

**Rule:** Service mesh justified when: >50 services, multi-cluster, strict mTLS compliance, or traffic shaping needs. For <20 services on single node, simpler tools (CoreDNS, middleware, NetworkPolicies) suffice.
**Tags:** `#architecture` `#service-mesh` `#k3s` `#assessment`

### [2026-03-21] Portainer removed — K8s native tooling replaces it

**Context:** PROD-K3S-000f — Portainer was last Docker Compose management tool still running on VPS.

**Problem:** Portainer added attack surface, consumed resources, and duplicated functionality already covered by kubectl, k9s, and Grafana dashboards.

**Solution:** Removed from VPS Compose stack, DNS record, Traefik route. k9s for daily operations, Grafana for dashboards, Headlamp (future) for web UI.

**Rule:** Prefer native K8s tooling over third-party management UIs. Each additional UI is attack surface + maintenance burden.
**Tags:** `#portainer` `#cleanup` `#k8s` `#operations`

### [2026-03-21] Grafana OIDC is fully declarative via env vars

**Context:** Configuring Grafana as OIDC client for Authelia SSO.

**Problem:** Expected Grafana OIDC to require API calls or config file editing (like Gitea which needs CLI `gitea admin auth add-oauth`).

**Solution:** Grafana OIDC is entirely configurable via `GF_AUTH_GENERIC_OAUTH_*` env vars. No API calls, no post-boot scripts. Just set env vars in the K8s deployment and restart.

**Rule:** Check if a service supports declarative config (env vars, config file) before writing imperative setup scripts. Grafana = declarative (env vars). Gitea = imperative (CLI post-boot). CrowdSec = imperative (postStart hook).
**Tags:** `#grafana` `#oidc` `#declarative` `#pattern`

### [2026-03-21] Web service domain mismatch: staging.mlorente.dev vs web.staging.kubelab.live

**Context:** Web service (mlorente.dev portfolio) not loading on staging K3s.

**Problem:** IngressRoute used `staging.mlorente.dev` but common.yaml had the domain configured as `web.staging.kubelab.live`. Config mismatch caused Traefik to not match the incoming Host header.

**Solution:** Fixed to use `staging.mlorente.dev` consistently — this is the correct domain (mlorente.dev is an independent brand, not a kubelab subdomain).

**Rule:** Web/portfolio uses `staging.mlorente.dev` (independent brand domain), not `*.kubelab.live`. Always verify IngressRoute Host matches the actual DNS record.
**Tags:** `#dns` `#ingressroute` `#mlorente` `#config`

### [2026-03-21] Prod web container port: 8080 (Nginx) not 4321 (Astro dev)

**Context:** Prod K3s web deployment returning 502 Bad Gateway.

**Problem:** common.yaml `default_port: 4321` is the Astro dev server port (used in Docker Compose for local development). The production Docker image runs Nginx on port 8080. K8s Service targetPort pointed to 4321 — no process listening there.

**Solution:** Always check the actual containerPort in the Dockerfile/image, not the dev config. K8s containerPort = 8080 (Nginx). The `default_port` in common.yaml is for Docker Compose dev only.

**Rule:** `default_port` in common.yaml = Docker Compose dev port. K8s containerPort = what the production image actually serves on. These are often different (dev server vs production server). Always verify against the Dockerfile.
**Tags:** `#k8s` `#ports` `#docker` `#debugging`

### [2026-03-21] Gitea OIDC: CLI writes to DB but web process caches in memory

**Context:** Configured OIDC via `gitea admin auth add-oauth` CLI but browser still used old config.

**Problem:** Gitea CLI writes auth sources to SQLite. The running web process caches OIDC provider config in memory and does NOT watch the DB for changes. A `kubectl rollout restart` is required after any `gitea admin auth` CLI operation.

**Solution:** `configure-oidc` script includes automatic `kubectl rollout restart deploy/gitea` after configuring. Same pattern as any K8s app with config-in-DB.

**Rule:** Any CLI tool that writes to a running service's database needs a service restart to take effect. Add restart to automation scripts.
**Tags:** `#gitea` `#oidc` `#k8s` `#cache`

### [2026-03-21] Authelia ConfigMap changes require pod restart

**Context:** Added Grafana and Gitea OIDC clients to Authelia ConfigMap. Authelia still only showed MinIO client.

**Problem:** Authelia does NOT auto-reload `configuration.yml` when the ConfigMap changes. The file on disk updates (kubelet sync) but Authelia reads config only at startup.

**Solution:** Restart Authelia after ConfigMap changes. Long-term: convert to `configMapGenerator` with hash suffix — Kustomize auto-triggers rolling update when content changes.

**Rule:** Always verify services reload config after ConfigMap updates. Most don't (Authelia, Gitea). Some do (CoreDNS with `reload` plugin). Add restart to deploy pipeline or use configMapGenerator hash suffix.
**Tags:** `#authelia` `#k8s` `#configmap` `#oidc`

### [2026-03-21] OIDC first login requires account linking

**Context:** User logged in via Authelia OIDC to Gitea for the first time. Got "Sign In to Authorize Linked Account" page.

**Problem:** Not a bug — expected OIDC behavior. First login requires linking the external identity (Authelia) with a local account (Gitea). User enters local credentials once to establish the link.

**Solution:** Document this as expected first-login behavior. After linking, subsequent OIDC logins are automatic.

**Rule:** When onboarding users to OIDC, inform them about the one-time account linking step. Admin accounts created via postStart hook already exist — users link to them.
**Tags:** `#oidc` `#gitea` `#authelia` `#onboarding`

### [2026-03-21] Never expose secrets in chat or logs

**Context:** Accidentally pasted Gitea admin credentials in plaintext during debugging.

**Rule:** Always reference secrets via `toolkit secrets show <path> --env <env>`, never paste values. Applies to: chat, commit messages, PR descriptions, log output.
**Tags:** `#security` `#secrets` `#opsec`
### [2026-03-22] enableServiceLinks: false required for n8n on K8s

**Context:** n8n pod in K8s kept falling back to basic_auth mode despite proper configuration.

**Problem:** K8s injects `N8N_PORT=tcp://10.43.x.x:5678` (Service env var) into pods. n8n tries to parse this as a port number, fails, and falls back to broken defaults including basic_auth. Same root cause as the Authelia `AUTHELIA_PORT` issue.

**Solution:** Set `enableServiceLinks: false` in n8n Deployment spec. This prevents K8s from injecting service-derived environment variables that collide with application config.

**Rule:** Any application that uses `<APP>_PORT` as a config key needs `enableServiceLinks: false` in K8s. Check for this pattern in ALL new service deployments. Known affected: Authelia, n8n.
**Tags:** `#k8s` `#n8n` `#debugging` `#enableServiceLinks`

### [2026-03-22] Authelia ForwardAuth must filter Authorization headers

**Context:** After configuring Authelia ForwardAuth for n8n, users got stuck in a 403 loop.

**Problem:** Browser caches basic_auth credentials and sends `Authorization: Basic` header on every subsequent request. Authelia's ForwardAuth receives this header, tries to parse it, fails on the empty password, and returns 403. The browser then re-prompts, user enters creds, and the cycle repeats.

**Solution:** Configure ForwardAuth middleware with explicit `authRequestHeaders` whitelist: `Cookie`, `X-Forwarded-*` headers only. This strips `Authorization` headers before they reach Authelia. Without `authRequestHeaders`, Traefik forwards ALL headers.

**Rule:** ForwardAuth middlewares should ALWAYS specify `authRequestHeaders` to whitelist only the headers the auth service needs. Never forward `Authorization` headers unless the auth service explicitly handles them.
**Tags:** `#traefik` `#authelia` `#forwardauth` `#security` `#debugging`

### [2026-03-22] Traefik Helm chart api.dashboard values don't work in K3s HelmChartConfig

**Context:** Needed to enable Traefik dashboard on K3s for debugging routes.

**Problem:** Setting `api: { dashboard: true }` in HelmChartConfig valuesContent has no effect in K3s-managed Traefik. The values are silently ignored.

**Solution:** Use `additionalArguments` instead: `--api.dashboard=true` and `--api.insecure=true`. These are passed directly to the Traefik binary and always work.

**Rule:** For K3s HelmChartConfig, prefer `additionalArguments` for Traefik feature flags over nested values. Always verify via `kubectl -n kube-system describe pod traefik-*` that args are applied.
**Tags:** `#traefik` `#k3s` `#helm` `#debugging`

### [2026-03-22] Traefik exposedPort vs port — both must match for HTTP→HTTPS redirect

**Context:** HTTP→HTTPS redirect stopped working after port swap to 80/443.

**Problem:** In HelmChartConfig, `port` sets the container port and `exposedPort` sets the Service port. The HTTP→HTTPS redirect middleware uses the container port. If `exposedPort=80` but `port=8080`, the redirect targets port 8080 instead of 80, producing broken redirect URLs.

**Solution:** Set both `port` and `exposedPort` to the same value (80 for web, 443 for websecure). The redirect then works correctly.

**Rule:** When configuring Traefik entrypoints in K3s HelmChartConfig, always set `port = exposedPort` unless you have a specific reason for port mapping. Mismatched values break redirects.
**Tags:** `#traefik` `#k3s` `#helm` `#networking` `#redirect`

### [2026-03-22] Ansible inventory must be env-aware for k3s_servers group

**Context:** Deploying K3s HelmChartConfig to prod VPS but Ansible targeted ace1 (staging server).

**Problem:** `common.yaml` defines ace1 as the K3s server (correct for staging). Prod needs VPS as the K3s server. The Ansible inventory for `k3s_servers` group was not environment-aware.

**Solution:** Override `k3s_servers` group membership in `prod.yaml` via `networking.vps.ansible_groups`. The Ansible playbook resolves the correct target node based on `ENV` variable.

**Rule:** Any Ansible group that varies by environment must have overrides in the env-specific values file (staging.yaml, prod.yaml). common.yaml holds the default (staging).
**Tags:** `#ansible` `#k3s` `#inventory` `#environments`

### [2026-03-22] configure_oidc.py must use update-oauth (not delete + add-oauth)

**Context:** Re-running OIDC configuration after changing Authelia URLs failed with an error about linked users.

**Problem:** The original script used `gitea admin auth delete` + `gitea admin auth add-oauth` to ensure idempotency. This fails when users have already linked their accounts to the OIDC auth source — Gitea refuses to delete auth sources with linked users.

**Solution:** Changed `configure_oidc.py` to use `gitea admin auth update-oauth --id <ID>` instead. The script first lists auth sources to find the existing ID, then updates in place. This preserves user linkages.

**Rule:** For any service that links external auth to local accounts (Gitea, Grafana, etc.), always use update/upsert operations for auth source configuration, never delete+recreate.
**Tags:** `#gitea` `#oidc` `#toolkit` `#idempotency`

### [2026-03-22] Authelia OIDC issuer URL is request-dependent

**Context:** Gitea OIDC login failed with issuer mismatch after configuring with internal K8s URL.

**Problem:** Authelia returns the OIDC issuer based on the request URL. If you configure Gitea with the internal cluster URL (`http://authelia.kubelab.svc:9091`), the discovered issuer is internal. But the browser OIDC redirect goes through the external URL (`https://auth.kubelab.live`), which returns a different issuer. Token validation fails because issuers don't match.

**Solution:** Always configure OIDC clients with the EXTERNAL Authelia URL for OpenID Connect discovery. The browser handles all OIDC flows, so the discovery URL must be reachable and consistent from the browser's perspective.

**Rule:** OIDC discovery URLs must always be the external/public URL, even for services running in the same cluster. Internal URLs are only for direct API calls (health checks, token introspection).
**Tags:** `#oidc` `#authelia` `#k8s` `#networking` `#debugging`

### [2026-03-22] SQLite backup requires sqlite3 .backup API — tar alone risks corruption

**Context:** Designing PVC backup strategy (ADR-024) for Gitea and Authelia SQLite databases.

**Problem:** Running `tar` on a SQLite database file while the application is writing produces a potentially corrupted backup. SQLite uses WAL (Write-Ahead Logging) mode — the `.db`, `.db-wal`, and `.db-shm` files must be consistent. A tar snapshot can capture them at different points in time.

**Solution:** Use `sqlite3 /path/to/db.sqlite3 ".backup /backup/db.sqlite3"` which uses SQLite's built-in backup API. This creates an application-consistent snapshot even while writes are happening. The CronJob runs `sqlite3 .backup` BEFORE `tar` to get clean copies.

**Rule:** NEVER backup SQLite files by copying/tarring them directly. Always use `sqlite3 .backup` for consistent snapshots. This applies to: Gitea, Authelia, Uptime Kuma, any service using SQLite.
**Tags:** `#sqlite` `#backup` `#data-integrity` `#adr-024`

### [2026-03-22] Prod SOPS secrets must be manually synchronized with staging

**Context:** Deploying prod overlay failed because Gitea OIDC secrets (admin_password, oidc_client_secret, oidc_client_secret_hash) were missing from prod SOPS.

**Problem:** Staging and prod use separate SOPS files (`staging.enc.yaml`, `prod.enc.yaml`). When new secrets are added to staging during development, they must be manually copied to prod SOPS. There is no automated cross-environment secret propagation.

**Solution:** Manually ran `sops edit prod.enc.yaml` and added the missing Gitea secrets (copied values from staging where appropriate). Created backlog items TOOL-001 (secret drift detection) and TOOL-002 (secret sync tool) for automation.

**Rule:** After adding any new secret to staging SOPS, immediately add a placeholder or copy to prod SOPS. Use `toolkit secrets list --env staging` vs `--env prod` to compare. Automate this with TOOL-001/TOOL-002.
**Tags:** `#sops` `#secrets` `#environments` `#operations`

### [2026-03-22] Traefik ACME storage MUST persist — rate limit disaster

**Context:** During prod cutover, Traefik pod was restarted multiple times (port changes, HelmChartConfig updates). Each restart lost acme.json and requested new certificates from Let's Encrypt.

**Problem:** K3s Traefik Helm chart uses `emptyDir` by default for `/data`. Every pod restart = fresh acme.json = new certificate requests. Let's Encrypt rate limits to 5 certificates per identical domain set per 168 hours. After 5+ restarts → all certificate requests denied → self-signed certs served → browser warnings on production.

**Solution:** Add `persistence.enabled: true` to HelmChartConfig:
```yaml
persistence:
  enabled: true
  storageClass: local-path
  size: 128Mi
```

**Rule:** NEVER deploy Traefik to production without ACME persistence. This should be part of the k3s_server role defaults, not an afterthought. Applied to both staging and prod.
**Tags:** `#traefik` `#acme` `#tls` `#k3s` `#letsencrypt`

### [2026-03-22] enableServiceLinks: false required for n8n (same as Authelia)

**Context:** n8n pod showed basic_auth popup after Authelia login. Logs showed "Invalid number value for N8N_PORT".

**Problem:** K8s service links inject `N8N_PORT=tcp://10.43.X.X:5678`. n8n expects a number. The invalid port causes n8n to malfunction and trigger basic auth fallback.

**Solution:** Add `enableServiceLinks: false` to n8n Deployment spec. Same pattern as Authelia.

**Rule:** Any service whose name collides with K8s service link env var prefixes needs `enableServiceLinks: false`. Check: Authelia (AUTHELIA_*), n8n (N8N_*), Redis (REDIS_*).
**Tags:** `#n8n` `#k8s` `#enableServiceLinks`

### [2026-03-22] Authelia ForwardAuth must filter Authorization headers

**Context:** After logging into Authelia, browser kept showing basic_auth popup on subsequent requests.

**Problem:** Browser caches `Authorization: Basic` header from a previous 401 response. Traefik forwards ALL headers to Authelia ForwardAuth. Authelia tries to parse the Basic header, fails (empty password), returns 403.

**Solution:** Whitelist `authRequestHeaders` in the Authelia Middleware spec — only forward Cookie and X-Forwarded-* headers, explicitly exclude Authorization.

**Rule:** ForwardAuth middlewares should whitelist headers, not forward everything. The Authorization header is the most common source of loops.
**Tags:** `#authelia` `#traefik` `#forwardauth` `#security`

### [2026-03-22] POST-MORTEM: Prod cutover — cert loss + performance degradation

**Severity:** High — production served self-signed certs + 5s page loads

**What happened:**
1. Multiple Traefik restarts during cutover (port changes, HelmChartConfig updates)
2. Each restart lost acme.json (emptyDir, no persistence)
3. Let's Encrypt rate limit hit (5 certs/168h per domain set)
4. Production served self-signed certificates
5. CrowdSec bouncer adding 1-1.5s latency per request (no decision caching)

**Root causes:**
- ACME storage not persistent (K3s default: emptyDir)
- No pre-cutover checklist verifying TLS persistence
- CrowdSec bouncer queries LAPI per-request instead of caching
- Staging didn't catch it because we never restarted Traefik multiple times in staging

**What we should have done:**
1. Verify ACME persistence BEFORE first restart in prod
2. Use Let's Encrypt staging server (`acme-staging-v02`) for testing
3. Stress-test staging: restart Traefik 3+ times, verify certs persist
4. Benchmark response times in staging before declaring cutover-ready
5. Have a pre-cutover checklist (runbook)

**Fixes applied:**
- `persistence.enabled: true` in HelmChartConfig (both envs)
- CLAUDE.md gotcha added

**Fixes needed (next session):**
- CrowdSec bouncer caching (performance)
- Pre-cutover checklist (runbook)
- Let's Encrypt staging server for staging env
- Chaos test: automated Traefik restart + cert verification

**Rule:** Staging only protects you if you replicate prod OPERATIONS, not just deployments. Simulate restarts, reconfigs, and failure scenarios before cutover.
**Tags:** `#postmortem` `#traefik` `#acme` `#crowdsec` `#performance` `#cutover`

### [2026-03-22] Headscale override_local_dns must be false

**Context:** Headscale had `override_local_dns: true` in DNS config. This made Tailscale override all clients' system DNS with `100.100.100.100` (MagicDNS proxy). When Headscale/Tailscale was unreachable (e.g., after K3s cutover broke TLS), ALL DNS resolution failed on the workstation — not just VPN domains.

**Problem:** `override_local_dns: true` couples ALL DNS resolution to VPN control plane availability. Single point of failure.

**Solution:** Changed to `override_local_dns: false` in `infra/ansible/roles/headscale/templates/config.yaml.j2`. Split DNS still works for specific domains (staging.kubelab.live, kubelab.vpn) but system DNS stays independent.

**Rule:** VPN DNS should be additive (split DNS for specific zones), never override global system DNS.
**Tags:** `#headscale` `#dns` `#tailscale` `#vpn` `#reliability`

### [2026-03-22] VPS ansible_host must use public IP — bootstrap circular dependency

**Context:** Ansible inventory used Tailscale IP (100.64.0.2) as `ansible_host` for VPS. But VPS hosts Headscale (the VPN control plane). When Tailscale was down, we couldn't SSH to VPS via Ansible to fix Headscale — circular dependency.

**Problem:** `generator_ansible.py` always used `tailscale_ip` for VPS. VPS is the only node that MUST be reachable without VPN.

**Solution:** Changed generator to use `public_ip` for VPS: `vps.get("public_ip") or vps.get("tailscale_ip")`. Also updated kubeconfig to use public IP (162.55.57.175:6443).

**Rule:** Bootstrap infrastructure (Headscale host) must NEVER depend on the service it bootstraps (Tailscale) for management access.
**Tags:** `#ansible` `#vps` `#headscale` `#bootstrap` `#networking`

### [2026-03-22] K3s resolv-conf must point to real upstream on systemd-resolved hosts

**Context:** K3s pods couldn't resolve external domains (acme-v02.api.letsencrypt.org). CoreDNS forwarded to `/etc/resolv.conf` which contained `127.0.0.53` (systemd-resolved stub). From inside the pod, 127.0.0.53 is the pod's own loopback — no DNS server there.

**Problem:** K3s config.yaml had no `resolv-conf` setting. Defaulted to host `/etc/resolv.conf` which is the stub on systemd-resolved hosts.

**Solution:** Added `resolv-conf: "/run/systemd/resolve/resolv.conf"` to K3s config.yaml template. This file contains the real upstream DNS servers (Hetzner: 185.12.64.1, 185.12.64.2). Requires K3s restart + CoreDNS rollout restart.

**Rule:** On systemd-resolved hosts, K3s must use `/run/systemd/resolve/resolv.conf`, not `/etc/resolv.conf`.
**Tags:** `#k3s` `#dns` `#systemd-resolved` `#coredns` `#debugging`

### [2026-03-22] Docker containers need explicit DNS on systemd-resolved hosts

**Context:** Headscale Docker container couldn't resolve `controlplane.tailscale.com` — got "connection refused" on 127.0.0.53:53.

**Problem:** Same as K3s — Docker inherits host `/etc/resolv.conf` stub. Container's 127.0.0.53 is its own loopback.

**Solution:** Added `dns:` directive to Headscale docker-compose.yml.j2 with explicit DNS servers from common.yaml (1.1.1.1, 8.8.8.8). Parameterized as `docker_dns_servers` role variable.

**Rule:** All Docker Compose services on systemd-resolved hosts need explicit `dns:` in compose. Use role defaults with public DNS as fallback.
**Tags:** `#docker` `#dns` `#systemd-resolved` `#headscale` `#ansible`

### [2026-03-22] deploy-vps must be idempotent — skip Docker Compose Traefik when K3s is active

**Context:** Running `make deploy TARGET=vps ENV=prod` restarted Docker Compose Traefik, which stole ports 80/443 from K3s Traefik. This effectively reverted the K3s cutover.

**Problem:** deploy-vps.yml always ran traefik_vps role regardless of environment. No condition to detect K3s as active ingress.

**Solution:** Added `when: "'k3s_servers' not in group_names"` to traefik_vps and errors roles. In prod (VPS in k3s_servers group), these roles are skipped. In staging (VPS not in k3s_servers), they run normally.

**Rule:** Ansible playbooks must be environment-aware. Docker Compose services superseded by K3s must be conditional on the K3s deployment state.
**Tags:** `#ansible` `#traefik` `#k3s` `#idempotency` `#deploy`

### [2026-03-22] K3s IngressRoute needed for vpn.kubelab.live after cutover

**Context:** After K3s cutover (ports 80/443), Tailscale clients got `x509: certificate is valid for traefik.default, not vpn.kubelab.live`. All nodes disconnected from mesh.

**Problem:** Docker Compose Traefik previously proxied `vpn.kubelab.live` -> Headscale:8080. After cutover, K3s Traefik had no IngressRoute for this domain. Headscale stays in Docker Compose (ADR-015 bootstrap dependency), so it needs explicit K8s routing.

**Solution:** Created `infra/k8s/overlays/prod/headscale.yaml` with Service + EndpointSlice (162.55.57.175:8080) + IngressRoute + TLSOption (headscale-http11). Also exposed Headscale port 8080 on host in Docker Compose template.

**Rule:** When migrating from Docker Compose to K3s, services that STAY in Docker Compose (Headscale, by ADR-015) need explicit K8s external service routing (Service + EndpointSlice + IngressRoute pattern).
**Tags:** `#k3s` `#headscale` `#traefik` `#ingressroute` `#migration` `#adr-015`

### [2026-03-22] Error middleware: only intercept infrastructure errors (502/503/504)

**Context:** Error-pages middleware was intercepting 408, 429, 500-503 — breaking API JSON responses on 500s and swallowing rate-limit headers on 429s.

**Solution:** Industry standard is to intercept only 502 (Bad Gateway), 503 (Service Unavailable), 504 (Gateway Timeout) — pure infrastructure failures where the backend can't respond. Application-level errors (4xx, 500) must pass through.

**Rule:** Traefik error middleware = infrastructure errors only (502/503/504). Application error handling belongs in each app.
**Tags:** `#traefik` `#middleware` `#error-pages` `#api`

### [2026-03-22] Kustomize images section doesn't cover custom apps automatically

**Context:** `sync_k8s_images.py` syncs third-party image tags from common.yaml to kustomization.yaml `images:` section. But custom apps (errors, api, web) have their image in the base manifest (e.g., `kubelab-errors:dev`). After releasing `errors:1.1.1`, the pod kept running `:dev` because kustomize didn't override it.

**Solution:** Add custom app images to kustomization.yaml `images:` section manually. `kubectl apply -k` doesn't trigger rollout if the resolved image hasn't changed — need `rollout restart`.

**Rule:** After releasing a custom app image, update its tag in `kustomization.yaml images:` AND force rollout. Argo CD (Phase 3) solves this with image updater.
**Tags:** `#kustomize` `#docker` `#release` `#k8s`

### [2026-03-22] release-please only bumps on fix:/feat: commits — chore: is ignored

**Context:** Made changes to error pages HTML + middleware under a `chore:` commit. release-please didn't create a version bump. Had to add a separate `fix(errors):` commit touching `edge/errors/` for release-please to detect it.

**Rule:** If changes need a Docker image rebuild, use `fix:` or `feat:` prefix (not `chore:`). release-please ignores `chore:` for versioning.
**Tags:** `#ci` `#release-please` `#versioning`

### [2026-03-22] AWS Spot t4g.micro: 1GB RAM is NOT enough for K3s + Argo CD without swap

**Context:** K3s alone consumes ~750MB on t4g.micro (1GB total). Installing Argo CD (~576MB) caused OOM, killing sshd and making the instance unreachable.

**Solution:** Add 2GB swap via cloud-init `swap:` directive. Must be in cloud-init (not manual) so it survives Spot restarts.

**Rule:** Always provision swap on t4g.micro for K3s workloads. Monitor with `free -m`. Upgrade to t4g.small (2GB) if swap usage is consistently >50%.
**Tags:** `#aws` `#k3s` `#spot` `#memory` `#swap`

### [2026-03-22] Cross-cluster K3s proxy: ClusterIP is NOT reachable from outside — use NodePort

**Context:** EndpointSlice pointing to aws1's Tailscale IP:80 returned 502. Argo CD ran as ClusterIP inside aws1's K3s — only accessible within that cluster, not on the host network.

**Solution:** Change argocd-server service to NodePort (30080). EndpointSlice targets 100.64.0.4:30080. Prod Traefik proxies to that.

**Rule:** When proxying K8s services cross-cluster via EndpointSlice, the target service MUST be NodePort or hostNetwork. ClusterIP is cluster-internal only. Document port in common.yaml SSOT.
**Tags:** `#k8s` `#traefik` `#endpointslice` `#nodeport` `#cross-cluster`

### [2026-03-22] Hub ingress: don't install Traefik on management plane — proxy via prod

**Context:** aws1 has 1GB RAM. Installing Traefik + Authelia + CrowdSec would exceed capacity. Initially tried enabling Traefik on aws1 but reverted.

**Decision:** Argo CD UI proxied through VPS (prod) Traefik using the same EndpointSlice pattern as Headscale. Zero additional software on hub.

**Rule:** Management plane should be minimal. Reuse existing ingress from data plane for UI access. Document in ADR.
**Tags:** `#architecture` `#argocd` `#traefik` `#proxy`

### [2026-03-22] cloud-init YAML: colons in strings cause parse errors

**Context:** `echo "cloud-init complete: K3s ready"` in cloud-init runcmd was parsed as a YAML dict (`:` creates key-value). All runcmd commands failed silently.

**Solution:** Quote strings with colons, or use `>-` / `|` block scalars.

**Rule:** Always quote cloud-init runcmd entries that contain `:` characters. Test with `cloud-init schema --system` after boot.
**Tags:** `#cloud-init` `#yaml` `#gotcha`

### [2026-03-23] Argo CD spoke registration: scoped RBAC > cluster-admin

**Context**: Registering spoke clusters in Argo CD hub (ADR-023 Phase 3, ARGO-002).

**Problem**: `argocd cluster add` CLI creates a ServiceAccount with `cluster-admin` ClusterRoleBinding. If hub is compromised, attacker gets full admin on all spokes — unacceptable blast radius.

**Solution**: Declarative two-role RBAC pattern:
- `ClusterRole + ClusterRoleBinding` for cluster-scoped reads (namespaces, nodes, CRDs, events)
- `ClusterRole + RoleBinding` (in `kubelab` namespace) for workload CRUD

This limits Argo CD to managing only the `kubelab` namespace. No access to kube-system, no privilege escalation, no cluster-admin.

**Rule**: Never use `argocd cluster add` in production. Always define explicit scoped RBAC. Use two-role pattern: ClusterRoleBinding for cluster reads, RoleBinding for namespaced writes. SA lives in the managed namespace (not kube-system).

### [2026-03-23] K8s 1.24+ ServiceAccount tokens require explicit Secret

**Context**: Creating long-lived SA token for Argo CD spoke authentication.

**Problem**: K8s 1.24+ stopped auto-generating persistent SA tokens. Creating a ServiceAccount no longer creates a companion Secret with a token. Without the explicit Secret, there's no token to extract for hub registration.

**Solution**: Create a Secret of type `kubernetes.io/service-account-token` with annotation `kubernetes.io/service-account.name: <sa-name>`. K8s token controller detects this and populates `.data.token` and `.data.ca.crt`. The token is long-lived (doesn't expire) — suitable for service-to-service auth but requires manual rotation if compromised.

**Rule**: For K8s 1.24+, always create explicit token Secrets for ServiceAccounts that need persistent tokens. Never rely on auto-generation. Include a rotation mechanism (Makefile target or CronJob).

### [2026-03-23] Hub↔spoke traffic should use VPN, not public IPs

**Context**: Deciding whether Argo CD hub should connect to prod spoke via public IP or Tailscale VPN.

**Problem**: CLAUDE.md says "VPS must use public_ip" but that rule is for Ansible/bootstrap (circular dependency with Headscale). Applying it to Argo CD would expose K8s API traffic on the public internet unnecessarily.

**Solution**: Both spokes use Tailscale IPs in the hub cluster Secret. All Argo CD traffic stays on WireGuard mesh. The bootstrap rule only applies to tools that need to reach VPS when Tailscale is down (Ansible, user kubeconfig).

**Rule**: Distinguish bootstrap tools (Ansible, SSH — use public IP) from runtime services (Argo CD, monitoring — use VPN). Runtime services should always prefer VPN for security and consistency.

### [2026-03-23] t4g.micro Spot sizing: fits Argo CD, not Helm upgrades

**Context**: Running Argo CD hub on t4g.micro (1GB RAM, 2GB swap, 1 vCPU).

**Problem**: Multiple Helm upgrades, Redis flushes, and pod restarts in one session caused swap thrashing (925MB swap used), K3s API timeouts, and a 10+ min recovery cycle. T-series burst credits also exhausted — CPU throttled to 10%.

**Solution**: 1GB fits Argo CD in steady state (5 pods, ~600MB total). For heavy operations (Helm upgrades, bulk restarts), space them out. Never batch 3+ pod restarts on the micro. If recurring, temporary scale to t4g.small ($7/mo) during maintenance windows.

**Rule**: Treat the micro as a steady-state-only box. Maintenance operations are the risk, not normal operations. Plan upgrades as discrete, spaced events.

### [2026-03-23] Argo CD resource.exclusions selector may not work

**Context**: Trying to exclude only auto-managed EndpointSlices while allowing manual ones.

**Problem**: Set `resource.exclusions` with `selector.matchLabels` to filter by the `endpointslice.kubernetes.io/managed-by` label. Argo CD still excluded ALL EndpointSlices regardless of selector.

**Solution**: Set `resource.exclusions: ""` (empty string) to remove all default exclusions. Manual EndpointSlices for external services are safe because Argo CD's `prune: true` only deletes resources with its own tracking label — it won't touch auto-managed EndpointSlices created by K8s.

**Rule**: Don't rely on `selector` in `resource.exclusions` for fine-grained filtering. Use empty exclusions + prune safety instead.

### [2026-03-23] SOPS 3.11 removed --editor flag

**Context**: `make secrets ENV=prod` fails with `flag provided but not defined: -editor`.

**Problem**: SOPS 3.11 changed the editor flag. The `--editor` CLI flag was removed in favor of `SOPS_EDITOR` or `EDITOR` environment variables.

**Solution**: Use `sops edit <file>` (picks up `$EDITOR`) or `EDITOR=nano sops edit <file>`. Fix the toolkit `secrets edit` command to use env var instead of `--editor` flag.

**Rule**: Pin SOPS version in toolkit or check for breaking changes on upgrade. The `sops unset` command works for removing keys without opening an editor.

### [2026-03-23] Pi-hole v6 built-in auth conflicts with Authelia

**Context**: Exposing Pi-hole admin UI via Traefik IngressRoute with Authelia middleware.

**Problem**: Pi-hole v6 has built-in authentication that returns 302 to `/admin/login`. Authelia interprets Pi-hole's 302 as "unauthenticated" and redirects back to its own login. Result: infinite redirect loop.

**Solution**: Remove Authelia middleware from Pi-hole IngressRoute. Pi-hole v6 handles its own auth. Keep CrowdSec + secure-headers middlewares for bot protection. Same pattern as n8n (built-in auth, Authelia bypass).

**Rule**: Services with built-in auth (Pi-hole v6, n8n 2.x) must NOT have Authelia middleware. Check for redirect loops when adding new services behind Authelia.

### [2026-03-25] IMMUTABLE_SECRETS must be enforced in code, not just documented

**Context**: MEMORY.md documented `IMMUTABLE_SECRETS` (storage_encryption_key, session_secret, jwt_secret, oidc_hmac_secret) as protected. But `credentials.py` had no protection — `batch_update_secrets` blindly overwrites all keys.

**Problem**: Running `toolkit credentials generate` would overwrite storage_encryption_key with a new random value, making Authelia's SQLite DB unreadable (encrypted with old key). Session and JWT secrets would invalidate all active sessions. This was a data-loss bug hiding behind documentation.

**Solution**: Added `IMMUTABLE_SECRETS` set in `credentials.py`. New `_read_existing_secrets()` reads SOPS before generation. `_preserve_immutable()` replaces generated values with existing ones for immutable keys. First-run (empty SOPS) uses generated values.

**Rule**: Security-critical secrets that are used as encryption keys or session state MUST have code-level protection against accidental overwrite. Documentation alone is not a safeguard — enforce invariants in code.

### [2026-03-25] Imperative service registration is a silent failure vector

**Context**: CrowdSec bouncer was registered imperatively via `cscli bouncers add` in a postStart hook with `2>/dev/null || true`. Gitea OIDC was registered manually via `configure_oidc.py`.

**Problem**: CrowdSec LAPI lost bouncer registration after a pod restart (DB state lost). The postStart hook swallowed the error (`|| true`). Result: bouncer returned 403 to ALL traffic for 6 days, including Uptime Kuma monitoring. No alerts because the failure was silent. Gitea had the same pattern risk — OIDC provider stored only in SQLite, populated by a manual script.

**Solution**: (1) CrowdSec: replaced imperative `cscli bouncers add` generation in credentials.py with static `secrets.token_urlsafe(32)`. Both LAPI and bouncer read from same K8s Secret. PostStart does idempotent delete+add without swallowing errors. (2) Gitea: bootstrap script in ConfigMap handles admin user creation + migration (admin→manu via SQLite) + OIDC provider registration. All idempotent, all on every pod start.

**Rule**: Never use `|| true` or `2>/dev/null` in postStart hooks — silent failures cause cascading outages. Service registration must be: (1) declarative (shared secrets from SOPS), (2) idempotent (delete+add or update), (3) visible (errors propagate to pod status). If a service stores config in a runtime DB, the postStart hook must re-apply it on every start.

### [2026-03-25] busybox wget lacks HTTP method support — use sqlite3 for DB operations

**Context**: Needed to rename a Gitea admin user from "admin" to "manu". Gitea has no `rename` CLI command. Tried using `wget --method=PATCH` to call the Gitea API from within the Alpine-based container.

**Problem**: Gitea's image is Alpine/busybox. busybox `wget` does not support `--method=PATCH`, `--body-data`, or custom HTTP methods. The migration would fail silently.

**Solution**: Use `sqlite3` directly on Gitea's SQLite DB (`/data/gitea/gitea.db`) for the rename operation. SQLite3 is available in Alpine. Direct DB update is simpler and has no API dependency.

**Rule**: In Alpine/busybox containers, don't assume full `wget`/`curl` capabilities. For SQLite-backed services (Gitea, Authelia, CrowdSec), direct DB operations via `sqlite3` CLI are more reliable than HTTP API calls from within the container. Always verify available tools in the target container image.

### [2026-03-25] Authelia access_control networks must include Tailscale CIDR

**Context**: Authelia `access_control` had hardcoded RFC1918 ranges as "internal" networks. VPN clients use Tailscale IPs (100.64.0.0/10) which are not in RFC1918.

**Problem**: The catch-all rule `*.staging.kubelab.live` with `policy: one_factor` only applied to `internal` networks. Tailscale clients got `default_policy: deny` → Forbidden on all staging services.

**Solution**: Created `networking.trusted_cidrs` SSOT list in common.yaml (RFC1918 + Tailscale CIDR). Authelia template reads from context variable `trusted_cidrs` via a Jinja2 loop. Single source, N consumers.

**Rule**: Network CIDR lists must be SSOT-driven from common.yaml, not hardcoded in templates. Any service that makes network-based access decisions (Authelia, CrowdSec whitelist, firewall rules) must consume from the same `trusted_cidrs` list.

### [2026-03-25] AI knowledge persistence: vault is the record, MEMORY.md is cache

**Context**: During a long session with multiple fixes (IMMUTABLE_SECRETS, CrowdSec, Gitea, trusted_cidrs), detected 6 debt items and 5 lessons. Initially only wrote to MEMORY.md, not to the vault.

**Problem**: MEMORY.md is ephemeral — it gets truncated, compressed, or lost between machines. Tasks, lessons, and decisions written only to MEMORY.md are effectively lost. The vault (`~/Projects/knowledge/`) is synced via Obsidian and is the only durable record.

**Solution**: Write to vault immediately when detecting a task (`11-tasks.md`), lesson (`90-lessons.md`), or decision (`14-changelog.md`). Don't batch at session end. Treat MEMORY.md as index/cache only.

**Rule**: Every annotation = vault + MEMORY.md. Never just MEMORY.md. If it's not in the vault, it didn't happen. See also: `00_meta/patterns/pattern-decision-persistence.md`.

---

## Security posture divergence between domains (2026-03-25)

**Problem**: Security audit revealed kubelab.live has zero security headers (no HSTS, no x-frame-options, etc.) while mlorente.dev has full coverage. Both go through the same VPS Traefik, but kubelab.live routes through Cloudflare proxy which strips/doesn't add headers. Also TLS 1.0/1.1 still enabled on Cloudflare (Grade B). Port 8080 (K3s Pattern C) exposed publicly.

**Root cause**: mlorente.dev IngressRoute has `secure-headers` middleware attached. kubelab.live prod IngressRoutes may be missing it, or Cloudflare proxy overrides origin headers. No CAA records on either domain.

**Rule**: After any new domain/service goes to prod, run SSL Labs + Shodan audit. Security headers must be verified end-to-end (origin → CDN → client), not just at origin. Cloudflare TLS settings (min version, HSTS, OCSP) are separate from Traefik config and need explicit Terraform management.

---

## Homepage Dashboard (DASH-001) — 2026-03-23

> Source: [dash-001-homepage-cockpit](architecture/dash-001-homepage-cockpit.md) implementation session. 14 lessons from deploying gethomepage.dev on K3s.

### [2026-03-23] ConfigMap mount must use subPath for Homepage

**Context**: Deploying Homepage (gethomepage.dev) on K3s with ConfigMap-based configuration.

**Problem**: Homepage needs writable `/app/config/logs/`. Mounting the entire ConfigMap as a directory makes the whole path read-only, breaking the app.

**Solution**: Use `subPath` per config file instead of mounting the full directory.

**Rule**: When an app needs to write to its config directory (logs, cache, state), mount individual ConfigMap keys via `subPath` rather than the whole directory. Trade-off: subPath mounts don't auto-update (see RELIAB-002).

### [2026-03-23] HOMEPAGE_ALLOWED_HOSTS required for Next.js 15.x

**Context**: Homepage uses Next.js 15.x internally.

**Problem**: Next.js 15.x host validation rejects requests from unknown domains. Homepage pod crashes or returns errors without this env var.

**Solution**: Set `HOMEPAGE_ALLOWED_HOSTS` env var with all domains the dashboard serves.

**Rule**: Any Next.js 15+ app behind a reverse proxy needs explicit host allowlisting. Check the framework's host validation requirements before deploying behind Traefik/Nginx.

### [2026-03-23] Authelia catch-all rules don't cover new services automatically

**Context**: Adding `home.staging.kubelab.live` expected it to match the existing `*.staging.kubelab.live` catch-all in Authelia.

**Problem**: The catch-all was restricted to `networks: internal`. New services need explicit `one_factor` rules. (Related: Tailscale CIDR lesson — 2026-03-25.)

**Solution**: Add explicit Authelia `access_control` rule for each new service domain.

**Rule**: Don't assume Authelia wildcard rules cover new services. Always verify the network constraints on catch-all rules and add explicit rules when needed.

### [2026-03-23] Glances v4 API path is /api/4/

**Context**: Configuring Homepage Glances widget for node metrics.

**Problem**: Homepage defaults to `/api/3/`. Glances v4 moved to `/api/4/`. Widget silently returns no data.

**Solution**: Set `version: 4` in Homepage Glances widget config.

**Rule**: When integrating monitoring agents, always verify the API version path. Silent failures (200 OK, empty data) are harder to debug than 404s.

### [2026-03-23] Glances widget metric: info is broken

**Context**: Homepage Glances widget configuration.

**Problem**: `metric: info` causes a `forEach` JS error in Homepage. The `info` endpoint returns a different data structure than Homepage expects.

**Solution**: Use `cpu` or `memory` metric types instead.

**Rule**: Test each widget metric type individually. Homepage widget docs may list options that don't work with all Glances versions.

### [2026-03-23] Cross-namespace DNS fails from certain pods

**Context**: Homepage pod trying to reach `traefik.kube-system.svc.cluster.local`.

**Problem**: Cross-namespace DNS resolution fails from the Homepage pod. The FQDN doesn't resolve despite the service existing.

**Solution**: Use ClusterIP directly (fragile — IP changes on service recreation). Better fix: create an ExternalName Service in the same namespace.

**Rule**: When a pod needs to reach a service in another namespace and FQDN fails, prefer ExternalName Services over hardcoded ClusterIPs. Hardcoded IPs are a ticking time bomb.

### [2026-03-23] Homepage has no native GitHub/Cloudflare/DockerHub widgets

**Context**: Trying to add GitHub PRs, Cloudflare analytics, and DockerHub pull counts to Homepage.

**Problem**: These widgets don't exist natively. The `cloudflared` widget is for Cloudflare Tunnels, not analytics.

**Solution**: Use `customapi` widget type with direct API calls.

**Rule**: Verify widget availability in Homepage docs before planning dashboard sections. "80+ widgets" doesn't mean every SaaS has one.

### [2026-03-23] Uptime Kuma status page API is public

**Context**: Integrating Uptime Kuma status into Homepage.

**Problem**: Expected to need API auth for Uptime Kuma status data.

**Solution**: Status page API is public by design. Slug is `kubelab`. No auth token needed.

**Rule**: Check if monitoring tools expose public status endpoints before setting up authenticated API integrations.

### [2026-03-23] Authelia restart invalidates all browser sessions

**Context**: `make deploy-k8s` does a `rollout restart` on all deployments including Authelia.

**Problem**: Restarting Authelia invalidates all browser sessions. Users get 403 Forbidden and must clear the `authelia_session` cookie manually.

**Solution**: Short-term: added auto-restart in Makefile. Long-term: RELIAB-001 (initContainer wait-for-redis) ensures Authelia reconnects to Redis session store on restart, preserving sessions.

**Rule**: Stateful auth services (Authelia, Keycloak) must persist sessions externally (Redis). Restarting the pod should not invalidate user sessions. Test session persistence across restarts before going to prod.

### [2026-03-23] Glances Docker image tag 4-full doesn't exist

**Context**: Deploying Glances agent on nodes.

**Problem**: Used `4-full` tag which doesn't exist. Silent pull failure.

**Solution**: Correct tag is version-specific: `4.5.2-full`.

**Rule**: Always verify Docker image tags exist before deploying. Use exact version tags, not assumed patterns. `docker pull --dry-run` or check the registry directly.

### [2026-03-23] Homepage bookmarks don't support tabs

**Context**: Wanted to organize bookmarks into tabbed sections in Homepage.

**Problem**: Bookmarks section has no tab support. Only services support tab-based layout.

**Solution**: Move bookmark content to `services.yaml` to get tab layout support.

**Rule**: Read Homepage layout docs carefully. Features available for services may not exist for bookmarks/widgets. When layout matters, model everything as services.

### [2026-03-23] subPath ConfigMap mounts don't auto-update

**Context**: Using subPath mounts for Homepage config files (see lesson #1).

**Problem**: K8s only auto-updates full-directory ConfigMap mounts. subPath mounts are frozen at pod start time. Config changes require pod restart.

**Solution**: Use `configMapGenerator` with hash suffix in Kustomize. ConfigMap name changes on content change → triggers rolling update automatically (RELIAB-002).

**Rule**: If using subPath ConfigMap mounts, always pair with `configMapGenerator` hash suffix to get automatic rollouts on config change. Otherwise config drift is invisible.

### [2026-03-23] rollout restart is destructive for stateful services

**Context**: `make deploy-k8s` blanket-restarts all deployments after apply.

**Problem**: Restarting Authelia drops all sessions (403 for users). Restarting any service with in-memory state causes data loss.

**Solution**: RELIAB-001 (Authelia initContainer) + RELIAB-002 (configMapGenerator) eliminate the need for blanket restarts. Apply only restarts pods whose config actually changed.

**Rule**: Never use blanket `rollout restart` in deployment scripts. Use configMapGenerator hash suffix or similar mechanisms so only affected pods restart. Stateful services need session persistence verified before any restart strategy.

### [2026-03-23] K3s bundled Traefik API is port 9000

**Context**: Configuring Homepage Traefik widget to show route/service counts.

**Problem**: Assumed Traefik API on port 8080 (standard). K3s bundled Traefik exposes API on port 9000. Combined with cross-namespace DNS failure, required hardcoded ClusterIP.

**Solution**: Use port 9000 + ClusterIP (fragile). Better: ExternalName Service pointing to Traefik in kube-system.

**Rule**: K3s bundles its own Traefik with non-standard defaults. Always check K3s HelmChartConfig for port overrides before assuming standard Traefik config.

### [2026-03-26] Traefik plugins can't mount Secrets cross-namespace

**Context**: Migrating CrowdSec bouncer from ForwardAuth sidecar to native Traefik plugin (SEC-003).

**Problem**: Plugin reads API key via `crowdsecLapiKeyFile` from a volume mount. Traefik runs in `kube-system`, but the bouncer Secret lived in `kubelab`. K8s pods can only mount Secrets from their own namespace.

**Solution**: Duplicate the Secret in `kube-system` (`crowdsec-bouncer-traefik`). Added `namespace` field to `SecretMapping` dataclass so `apply-secrets` handles cross-namespace secrets generically. Precedent: `cloudflare-api-token` already follows this pattern.

**Rule**: When a workload in one namespace needs a secret from another, duplicate the Secret via toolkit (not reflector/replicator). Add a `SecretMapping` with explicit `namespace`. Keep the original Secret too if other consumers need it (e.g., LAPI postStart hook in `kubelab` still uses `crowdsec-bouncer`).

### [2026-03-26] cloud-init `#cloud-config` must be first line

**Context**: Recreating aws1 Spot instance via Terraform.

**Problem**: cloud-init.yml had `# yamllint disable-line rule:comments` before `#cloud-config`. Cloud-init requires `#cloud-config` as the absolute first line to identify the file format. With the yamllint comment first, cloud-init treated the entire file as unknown format and skipped all configuration (users, packages, runcmd, swap — everything).

**Solution**: Move `#cloud-config` to line 1. Use `# yamllint disable-file` as line 2 instead (disables all yamllint rules for the file, avoids per-line directives).

**Rule**: `#cloud-config` must ALWAYS be the first line. No comments, no whitespace, no BOM before it. yamllint directives go on line 2+.

### [2026-03-26] Spot `stop` behavior causes stale state — use `terminate` for cattle

**Context**: aws1 Spot instance with `instance_interruption_behavior = "stop"`.

**Problem**: When AWS reclaims and restarts a stopped Spot instance: new public IP, SSH daemon hangs (reverse DNS timeout), Tailscale tunnel broken (stale WireGuard context). Instance appears "running" but is completely inaccessible.

**Solution**: For stateless workloads (Argo CD hub), use `terminate` + ASG(1,1) instead of `stop`. Cloud-init rebuilds from scratch — no stale state. Added `UseDNS no` to sshd_config in cloud-init to prevent SSH hangs. Phase 2: migrate to ASG with auto-replacement.

**Rule**: If the architecture is stateless (reconstructable from Git/IaC), the infrastructure must match — destroy and recreate, don't preserve and resume. "Cattle not pets" applies to the interruption behavior, not just the deployment model.

### [2026-03-26] MagicDNS eliminates Tailscale IP hardcoding for cattle instances

**Context**: aws1 gets a new Tailscale IP on every Headscale re-registration.

**Problem**: Kubeconfig, spoke configs, and common.yaml referenced `100.64.0.4` (hardcoded). Every Spot replacement required updating these references.

**Solution**: Headscale MagicDNS was already enabled (`magic_dns: true`, `base_domain: kubelab.vpn`). `aws1.internal.kubelab.live` resolves to whatever IP Headscale assigns. Changed `base_domain` from `kubelab.vpn` (fake TLD) to `internal.kubelab.live` (owned subdomain, ADR-025). Cannot use `vpn.kubelab.live` — Headscale rejects base_domain sharing domain with server_url. Updated K3s TLS SAN, kubeconfig, and common.yaml to use DNS name instead of IP. Zero resource overhead — MagicDNS is built into Tailscale client.

**Rule**: For any node that can be destroyed and recreated (cattle), use `<hostname>.internal.kubelab.live` instead of hardcoded Tailscale IPs (ADR-025). For permanent hardware (pets), IPs are stable and acceptable. NET-001 tracks full migration.

### [2026-03-26] Headscale node cleanup required before Tailscale re-registration

**Context**: Destroying and recreating aws1 Spot instance.

**Problem**: Old Headscale node entry (offline) blocks clean registration. New instance registers as `aws1-<random>` with a new IP instead of reusing the `aws1` identity and IP.

**Solution**: Cloud-init calls Headscale API to delete stale node by hostname before `tailscale up`. Requires Headscale management API key (stored in SOPS `aws.headscale_api_key`, passed via Terraform variable to cloud-init).

**Rule**: Cloud-init for cattle instances must include a Headscale node cleanup step before Tailscale registration. Pattern: `curl DELETE /api/v1/node/{id}` for offline nodes matching the hostname, then `tailscale up`.


### [2026-03-26] Homepage Services Tab — SSOT-Driven Dashboard Tables

**Context**: Building an Endpoints/Services tab for Homepage to replace the individual Staging/Prod service card tabs with consolidated HTML tables.

**Problem**: Homepage's custom.js injection pattern (DOM manipulation via hash routing) requires careful coordination between settings.yaml (layout), services.yaml.j2 (placeholders), and the sync script (JS generation). The service cards with `ping:` use Homepage's built-in backend health check, but custom HTML tables need client-side health checks.

**Solution**:
- Services tab with 3 tables (Shared/Staging/Prod) injected via `injectServices()` in custom.js
- Health checks via `fetch(url, {mode: "no-cors"})` — detects reachability but can't distinguish 200 from 500
- Category tags with click-to-filter (toggles row visibility per category)
- Column resize via mousedown drag handler, synced across all tables with same column count
- Version column extracted from `image:` tags in common.yaml via `_ver()` helper
- Diagrams split into Topology (network/DNS) + Flows (GitOps/Request/Secrets/Deploy)

**Rules**:
1. Homepage deployment/ConfigMap is NOT in Kustomize overlay — deployed via manual `kubectl create configmap` + rollout restart. Must be added to Kustomize (DASH-DT-002).
2. `make sync-homepage` runs the sync script but there's no `make deploy-homepage` yet — deploy is manual kubectl.
3. `fetch(mode: "no-cors")` resolves for ANY HTTP response (even 500) — only network errors show as "down". Not a true health check.
4. Mermaid SVGs are cached at sync-time — if mermaid.ink is down, SVGs don't regenerate. Previously rendered SVGs persist in custom.js.
5. CrowdSec in Request Path diagram must show as Traefik plugin (integrated), not separate middleware hop.
6. ace2 is a "Platform Node" (not K3s agent) since ADR-023 Phase 1 — single-node K3s on ace1.

### NET-002: K8s Generator Overwrites Manual kustomization.yaml — Prod Outage (2026-03-27)

**What happened:** `make deploy-k8s ENV=prod` runs `generator_k8s.py` which overwrites `infra/k8s/overlays/prod/kustomization.yaml` with a template that only includes 4 generated resources. The prod file had 7 additional manual resources (argocd.yaml, headscale.yaml, backup.yaml, patches.yaml, etc.). After deploy, those resources were silently dropped from the Kustomize overlay — IngressRoutes for headscale proxy, uptime-kuma, traefik-dashboard disappeared. Combined with CrowdSec bouncer plugin loss, this caused a full prod outage.

**Root cause:** Mixing generated and manual files in the same directory without separation. The generator treats kustomization.yaml as generated, but operators add manual resources to it over time. Each deploy silently destroys manual additions.

**Fix (ADR-027 Phase 2):** Move generated files to `overlays/{env}/generated/` subdir. Make kustomization.yaml a manual committed file referencing `generated/*.yaml`. Generator stops generating kustomization.yaml. Gitignore `overlays/*/generated/`.

**Pattern:** Never mix generated and hand-maintained files in the same directory. Generated files go in `generated/` (gitignored). Entry points (kustomization.yaml) are always manual and committed.

### NET-003: CrowdSec Bouncer Plugin Loss is Recurrent (2026-03-27)

**What happened:** Traefik returned 404 for all routes using `crowdsec-bouncer` middleware. Logs showed `"plugin: unknown plugin type: bouncer"`. The HelmChartConfig on the cluster was missing the `experimental.plugins` section.

**Root cause:** The HelmChartConfig is managed by Ansible (`k3s_server` role template). If anything else modifies it (K3s upgrade, manual edit, or a generator that touches kube-system resources), the plugin registration is lost. Traefik restarts without the plugin → all middleware references fail → 404.

**Fix:** Always redeploy via `make deploy TARGET=k3s ENV=prod` to restore the full HelmChartConfig. Long-term: add a health check that verifies the plugin is registered (Traefik API `/api/plugins`).

**Pattern:** Critical Traefik plugins must be validated after any K3s/Traefik restart. If plugin is missing, all routes using that middleware fail silently (404, not 500).

### SEC-004: SOPS Multi-Recipient for CI (ADR-027 Phase 2, 2026-03-27)

**What:** Added a dedicated CI AGE key as second SOPS recipient. All 4 `.enc.yaml` files re-encrypted with `sops updatekeys`. CI private key stored as GitHub Actions secret `SOPS_AGE_KEY`. Human key stays on VeraCrypt USB.

**Why:** `toolkit sync oidc --check` needs to decrypt SOPS to validate OIDC hash drift. Without a CI key, this check is skipped in pipelines — drift goes undetected.

**How to reproduce:** See ADR-027 in vault for full setup steps. Keys: human = `age166v8e...`, CI = `age1wpqxa...`. Both public keys in `.sops.yaml`.

**Rotation:** Generate new CI key → update `.sops.yaml` → `sops updatekeys` on all files → update GitHub secret. Human key unaffected.

### [2026-03-27] Web CrashLoopBackOff: three root causes behind one symptom
**Context:** Deploying web service to prod after merging PR #136 (BUG-WEB-001 nginx PID fix). Pod kept crashing despite Dockerfile fix.
**Problem:** Three independent issues masked as one CrashLoopBackOff: (1) Image tag `dev` in prod — base kustomization.yaml had no image pin for custom apps web/api, only errors. (2) Container port 4321 (Astro dev server) instead of 8080 (nginx) — common.yaml default_port is for dev, staging/prod need override. (3) Missing error-pages middleware on generated IngressRoutes — users saw raw Traefik "no available server" instead of custom error page.
**Solution:** Pin custom app images in base/kustomization.yaml (web:1.0.1, api:1.0.0, errors:1.1.1). Override default_port: 8080 in staging.yaml and prod.yaml. Add error-pages as default middleware in K8s generator _build_middlewares(). All three fixes shipped in PRs #138 and #139.
**Tags:** `#k8s` `#kustomize` `#nginx` `#traefik` `#debugging`

### [2026-03-27] Authelia Secret changes require pod restart — RELIAB-002 only covers ConfigMaps
**Context:** After running credentials-generate to change the SSOT admin password, Authelia kept rejecting the new password.
**Problem:** RELIAB-002 (configMapGenerator hash suffix) auto-restarts pods when ConfigMaps change, but Authelia user passwords live in K8s Secrets (authelia-users, authelia-secrets). Secrets use fixed names — K8s updates content silently but pods don't restart. User sees "authentication failed" with correct new password because pod still has old hash in memory.
**Solution:** Manual `kubectl rollout restart deployment/authelia` + `make flush-sessions` to clear stale Redis sessions. Permanent fix: DEBT-006 (Secret hash annotation on deployment template) — when Secret content changes, annotation hash changes, triggering automatic rolling update.
**Tags:** `#authelia` `#k8s` `#secrets` `#credentials` `#debugging`

### [2026-03-27] aws1 t4g.micro disk-pressure blocks all pod scheduling
**Context:** Helm upgrade for Argo CD failed repeatedly with timeout. Pods stuck in Pending/ContainerCreating.
**Problem:** aws1 (6.8G disk) hit 84% usage → kubelet applied disk-pressure taint → NoSchedule on all new pods. Root cause: accumulated apt lists (247MB), apt cache (167MB), journal logs (77MB). Not images (only 527MB in containerd). Helm upgrade needs to run old+new pods simultaneously during rolling update, which requires scheduling new pods.
**Solution:** Immediate: `rm -rf /var/lib/apt/lists/*`, `journalctl --vacuum-size=20M`, `snap set system refresh.retain=2` — recovered ~400MB to 79%. Taint auto-cleared. Permanent: ANSIBLE-018 (maintenance playbook with systemd timer for weekly auto-cleanup on all nodes).
**Tags:** `#aws` `#k8s` `#disk` `#helm` `#maintenance`

### [2026-03-27] Helm pending-install state blocks all future upgrades
**Context:** Argo CD initial Helm install on t4g.micro timed out (OOM). All subsequent helm upgrade commands failed with "another operation in progress".
**Problem:** Helm revision 1 stuck in `pending-install` status. Helm refuses any operation when a release is in a transient state. Pods were actually running fine (K8s reconciled independently of Helm), but Helm's state was stuck.
**Solution:** `helm rollback argocd 1 -n argocd` — rollback to the pending revision marks it as deployed, unblocking future upgrades. Then re-run `helm upgrade` normally. This is safe because Helm rollback re-applies the same manifest.
**Tags:** `#helm` `#argocd` `#debugging` `#aws`

### [2026-03-27] Argo CD native OIDC without dex — pattern and gotchas
**Context:** Implementing ARGO-010: Argo CD SSO via Authelia OIDC on t4g.micro (1GB RAM)
**Problem:** Dex is disabled to save RAM on t4g.micro. Need OIDC without it. Also: hub credentials (OIDC secret) must live in common SOPS, not per-env. sync_oidc_hashes.py only read env-specific SOPS, missing common secrets. Deploy order matters: Authelia must have the OIDC client registered before Argo CD tries discovery.
**Solution:** Argo CD v2.5+ supports native OIDC via configs.cm.oidc.config (no dex). Secret referenced as $oidc.authelia.clientSecret from configs.secret.extra, injected at deploy time via Helm --set. sync_oidc_hashes.py now merges common SOPS as fallback. deploy-argocd Makefile target enforces order: _deploy-authelia-oidc → _deploy-argocd-helm. Admin local account restricted to apiKey only (CLI fallback). RBAC: admins group → role:admin, default readonly.
**Tags:** `#argocd` `#oidc` `#authelia` `#helm` `#sso`

### [2026-03-27] Hub singleton credentials must always write to common SOPS
**Context:** credentials-generate wrote Argo CD password to staging.enc.yaml but deploy-argocd read from common.enc.yaml — password mismatch.
**Problem:** credentials-generate writes ALL secrets to the env-specific SOPS file. But hub services (Argo CD) are singletons — their credentials must be in common SOPS regardless of which env runs the generator. This caused deploy-argocd to inject the old password hash.
**Solution:** Separate hub_secrets dict in credentials.py, written to common.enc.yaml via batch_update_secrets(secret_file_path=common_sops) in a second call. Pattern: any service that's not per-environment (hub, shared infra) gets its own write to common SOPS.
**Tags:** `#sops` `#credentials` `#architecture` `#ssot`

### [2026-03-27] Always persist API keys to SOPS immediately after generation
**Context:** Uptime Kuma API key was generated in the UI but never stored in SOPS. The plaintext was lost — only bcrypt hash remains in the DB.
**Problem:** API keys generated in service UIs are shown once. If not immediately persisted to SOPS, the plaintext is lost forever. The hash in the DB is irreversible. This breaks the SSOT principle — a credential exists in the system but not in the managed secret store.
**Solution:** Rule: any credential generated in a service UI MUST be immediately stored via `toolkit secrets set` before closing the dialog. Add to CLAUDE.md as a gotcha. For Uptime Kuma specifically, regenerate the API key and store it in SOPS under `apps.services.observability.uptime_kuma.api_key`.
**Tags:** `#sops` `#credentials` `#ssot` `#operational`

### [2026-03-27] External service credential reconciliation pattern
**Context:** Integrating Uptime Kuma into the SSOT credential system. Services with their own auth (not K8s Secrets) need API calls to update passwords.
**Problem:** credentials-generate writes new password to SOPS, but services like Uptime Kuma manage their own user DB. K8s pod restarts don't help — the service still has the old password. Need a reconciliation step that uses each service's API.
**Solution:** Added _reconcile_external_credentials() in credentials.py. Called after SOPS update. Logs in with OLD password (from existing_secrets), calls change_password(old, new). Falls back gracefully if service unreachable. Pattern is extensible — add a try/except block per service. Future: Gitea, Grafana admin APIs.
**Tags:** `#credentials` `#ssot` `#uptime-kuma` `#architecture` `#pattern`

### [2026-03-27] Docker Compose volume naming mismatch destroys data on migration
**Context:** Migrating RPi3 services from ad-hoc docker run to Ansible-managed Docker Compose
**Problem:** Ad-hoc containers used volume name `uptime-kuma_uptime_kuma_data`. Compose generated `uptime_kuma_data` (different naming convention). New empty volume was mounted, data appeared lost. Uptime Kuma showed setup wizard instead of existing dashboard.
**Solution:** Use `external: true` with the exact original volume name in compose template. For migration: copy data between volumes with alpine container, then restart. For future: always check `docker volume ls` before provisioning nodes with existing data.
**Tags:** `#docker` `#ansible` `#data-loss` `#volumes`

### [2026-03-27] GitHub API unauthenticated rate limit breaks Homepage widgets
**Context:** Homepage dashboard GitHub repo widgets showing API error
**Problem:** 3 GitHub API widgets at 60s refresh = 180 req/h. Unauthenticated limit is 60 req/h. Widgets show "API rate limit exceeded" error.
**Solution:** Increased refreshInterval to 300s (5 min) = 36 req/h. Long-term: add GitHub PAT to SOPS and pass as Authorization header in widget config.
**Tags:** `#dashboard` `#github` `#rate-limit`

### [2026-03-27] Homepage ConfigMap is ad-hoc — not in Kustomize, needs manual apply
**Context:** Dashboard not updating after sync-homepage + deploy-k8s
**Problem:** Homepage ConfigMap was created via kubectl apply (ad-hoc), not via Kustomize configMapGenerator. deploy-k8s only applies Kustomize overlays — the homepage ConfigMap content never updates. Rollout restart alone doesn't help because the ConfigMap itself has stale content.
**Solution:** sync-homepage now: (1) generates config files, (2) applies ConfigMap via kubectl create --from-file --dry-run=client | kubectl apply, (3) rollout restart. Long-term: migrate Homepage to Kustomize with configMapGenerator hash suffix.
**Tags:** `#k8s` `#configmap` `#homepage` `#kustomize`

### 2026-03-28: Never kubectl patch — always IaC (deploy-argocd, deploy-k8s, deploy TARGET=vps)

**Symptom:** ArgoCD RBAC policy.csv was empty in cluster despite being defined in Helm values. OIDC users could authenticate but saw no Applications.

**Root cause:** `make deploy-argocd` Helm upgrade failed or timed out on t4g.micro (OOM). The RBAC values in `infra/helm/argocd/values.yaml` were never applied. The quick-fix instinct was to `kubectl patch` — WRONG.

**Rule:** NEVER apply changes directly to the cluster via kubectl patch/apply for resources managed by Helm or Kustomize. Always use the IaC pipeline:
- ArgoCD config → `make deploy-argocd` (Helm upgrade)
- K8s workloads → `make deploy-k8s ENV=x` (Kustomize apply)
- VPS services → `make deploy TARGET=vps ENV=prod` (Ansible)
- DNS/Cloudflare → `make tf-dns-apply` (Terraform)

**Why:** Manual patches create drift. Helm doesn't know about them → next `helm upgrade` may revert or conflict. ArgoCD with selfHeal will revert manual changes. The whole point of IaC is that the cluster state matches Git.

**Fix pattern:** If a Helm value isn't applied, diagnose WHY the deploy failed (OOM, timeout, values error) and re-run the deploy — don't bypass it.

**Affected services to audit:** Any Helm-managed resource where values may not have been applied due to aws1 OOM:
- ArgoCD RBAC (confirmed missing)
- ArgoCD OIDC client secret (may need re-injection via `--set`)
- Any Helm chart on aws1 hub

### 2026-03-28: aws1 t4g.micro Helm upgrade always causes swap thrashing — mitigate before deploy

**Symptom:** Every `make deploy-argocd` on aws1 (1GB RAM) causes Helm upgrade timeout. K8s API becomes unresponsive for 10-15 minutes. Pods enter CrashLoopBackOff. Happened 2026-03-27 (disk-pressure) and 2026-03-28 (RBAC deploy).

**Root cause:** Helm upgrade loads all CRDs + current state into memory. ArgoCD has heavy CRDs (Applications, ApplicationSets, AppProjects). On 1GB RAM, this pushes into swap → all K8s processes slow → liveness probes fail → restart loops → more memory pressure.

**Mitigation pattern (add to deploy-argocd Makefile target):**
1. Pre-scale: `kubectl scale deploy argocd-applicationset-controller --replicas=0` (saves ~100MB)
2. Set Helm timeout: `--timeout 10m` (don't fail on slow API)
3. Post-scale: restore applicationset-controller after upgrade
4. Add `--wait` so Helm confirms pods are healthy before returning

**Long-term fix:** Upgrade to t4g.small (2GB RAM, ~$7/mo). The $3.40/mo delta eliminates the problem entirely.

**NEVER do during aws1 Helm upgrade:** kubectl patch, rollout restart, or any additional kubectl commands — they compound the memory pressure.

**Final pattern (2026-03-28b):** Pre-scale ALL to 0 (not just applicationset) + wait for termination + Helm upgrade with 5min timeout. Pods parados = Helm tiene toda la RAM disponible. Downtime ~2-3 min — acceptable for solo operator. Partial scale-down (only applicationset) was NOT enough — still OOM'd twice.

### 2026-03-28: Cloudflare API token consolidated — old "DNS mlorente.dev" revoked

**Action:** Replaced narrow-scope "DNS mlorente.dev" token (Zone:DNS:Edit + Zone:Read) with "kubelab-terraform" token (DNS:Edit + Zone:Read + Zone Settings:Edit). Old token revoked. New token stored in SOPS `cloudflare.api_token` (common.enc.yaml). Covers all Terraform operations (DNS records, zone settings, CAA records).

### 2026-03-28: t4g.micro cannot survive repeated Helm upgrade retries — stop after first failure

**Symptom:** 4 consecutive deploy-argocd attempts. Each one compounds memory pressure. By attempt 4, K3s API server was completely unresponsive (TLS handshake timeout). Required AWS console reboot.

**Rule:** After a failed Helm upgrade on t4g.micro:
1. Reboot the instance (AWS console or `aws ec2 reboot-instances`)
2. Wait for K3s to come back (~2-3 min)
3. `make recover-argocd` (clean Helm state)
4. ONE `make deploy-argocd` attempt
5. If that fails → upgrade to t4g.small, don't retry

**Never:** Retry Helm upgrade on an already-stressed t4g.micro. Each retry makes it worse.

### 2026-03-28: aws1 upgraded t4g.micro → t4g.small (+$3.14/mo) — eliminates all OOM issues

**Decision:** Upgrade aws1 from t4g.micro (1GB, ~$2.19/mo) to t4g.small (2GB, ~$5.33/mo). Delta: $3.14/mo.

**What it unblocks:**
- ApplicationSet controller re-enabled (ARGO-004)
- ArgoCD Notifications re-enabled (Slack/Telegram alerts)
- Image Updater (future — ARGO-004)
- Helm upgrades complete in ~2min without OOM
- Controller cold start ~2min vs 10-15min

**Resource budget (t4g.small, 2GB):**
- K3s + ArgoCD (7 pods): ~940MB
- Headroom: ~1GB (enough for Helm upgrades + node-exporter)

**Cost impact:** Cloud total: ~$18.39 → ~$21.53/mo

### 2026-03-28: ArgoCD Helm chart RBAC key is `configs.rbac`, NOT `configs.rbacConfig`

**Symptom:** RBAC policy.csv empty in argocd-rbac-cm ConfigMap despite being in Helm values. OIDC users authenticated but saw no Applications.

**Root cause:** Old key `server.rbacConfig` was migrated to `configs.rbac` in chart v5.7.0. The intermediate `configs.rbacConfig` never existed — it was a typo that Helm silently ignored.

**Fix:** `configs.rbac.policy.csv`, `configs.rbac.policy.default`, `configs.rbac.scopes`

**Always check Context7 docs before guessing Helm value paths.**

### 2026-03-28: Only Spot instances need dynamic IP resolve — physical nodes keep hardcoded IPs

**Symptom:** Removing uptime-kuma.yaml from Kustomize base (for dynamic IP resolve) broke prod overlay patches — `no matches for Id IngressRoute uptime-kuma.kubelab`.

**Root cause:** Overengineering. Physical nodes (RPi3, RPi4, Beelink) have stable Tailscale IPs that never change. Only Spot instances (aws1) get new IPs on recreation.

**Rule:**
- **Kustomize base**: resources with stable IPs (physical nodes). Hardcoded IPs are correct.
- **deploy-argocd**: resources with dynamic IPs (Spot). Placeholder + MagicDNS resolve at deploy time.
- **Deploy order**: `deploy-k8s` first (Kustomize), `deploy-argocd` last (overwrites EndpointSlice with resolved IP).
- Don't solve problems that don't exist. Placeholder pattern only for IPs that actually change.

### 2026-03-29: ArgoCD notifications — service.webhook not service.slack for incoming webhooks

**Symptom:** `invalid_auth` then `notification service 'webhook' is not supported`.

**Root cause:** Three separate issues:
1. `service.slack` needs a Slack Bot Token (`xoxb-...`), not a webhook URL. For incoming webhooks use `service.webhook.<name>`.
2. Recipients for webhook are just `<name>`, not `webhook:<name>`.
3. Templates use `webhook: <name>:` block, not `slack:` block.

**Correct config:**
```yaml
notifiers:
  service.webhook.slack: |
    url: $slack-webhook-url
templates:
  template.example: |
    webhook:
      slack:
        method: POST
        body: '{"text": "message"}'
subscriptions:
  - recipients: [slack]
```

**Always check Context7 docs for ArgoCD notification config — the patterns are non-obvious.**

### 2026-03-29: ArgoCD staging sync error after Helm upgrade — stale repo-server connection

**Symptom:** Staging stuck on ComparisonError "connection refused" to repo-server IP even though repo-server is Running 1/1.

**Root cause:** Controller caches repo-server Service ClusterIP. After Helm upgrade recreates pods, the old IP is stale in the controller's connection pool.

**Fix:** `kubectl rollout restart statefulset argocd-application-controller -n argocd`. Forces new connection to repo-server.

**Prevention:** This is inherent to the full scale-down upgrade pattern. Could add controller restart as post-step in deploy-argocd Makefile target.

### 2026-03-29: Generated IngressRoutes were missing secure-headers middleware

**Symptom:** E2E tests for `x-frame-options`, `x-content-type-options`, and HSTS failing on api and web.

**Root cause:** `generator_k8s.py _build_middlewares()` only added `error-pages`. The `secure-headers` Middleware CRD existed in the cluster but wasn't referenced in generated IngressRoutes.

**Fix:** Added `secure-headers` as first middleware in `_build_middlewares()` — applies to ALL generated IngressRoutes.

**Rule:** When adding a Traefik middleware CRD, also update the generator that produces IngressRoutes, not just the manually-crafted ones.

### 2026-03-29: Docker Tailscale-only port binding breaks K8s EndpointSlice + Ansible health checks

**Symptom:** Ollama health check `Connection refused` after provisioning. K8s IngressRoute returns `Gateway Timeout`.

**Root cause:** Binding Docker ports to Tailscale IP only (`{{ tailscale_ip }}:11434:11434`) means:
1. Ansible `uri` health checks on `localhost` fail — must use Tailscale IP
2. K8s EndpointSlice with LAN IP (172.16.1.x) fails — Traefik can't reach the Docker port on LAN
3. EndpointSlice must use Tailscale IP to match Docker bind

**Fix:** Health checks use `{{ tailscale_ip }}`, EndpointSlice uses Tailscale IP (100.64.0.5), not LAN IP.

**Rule:** When binding Docker to specific IP, ALL consumers (health checks, K8s EndpointSlice, monitoring) must use that same IP.

### 2026-03-29: ArgoCD selfHeal reverts manual kubectl apply instantly

**Symptom:** `kubectl apply -f ingress.yaml` says "configured" but `kubectl get` still shows old state.

**Root cause:** ArgoCD `selfHeal: true` detects drift within seconds and reverts to Git state. The `kubectl apply` succeeds momentarily but ArgoCD's reconciliation loop overrides it immediately.

**Rule:** With ArgoCD selfHeal enabled, NEVER test K8s changes via manual `kubectl apply`. Changes must go through Git → PR → merge → ArgoCD sync. For testing, either disable selfHeal temporarily or accept dry-run validation.

### 2026-03-29: Avoid rebase hell — one branch per file group, one PR at the end

**Symptom:** 4 consecutive PRs touching values.yaml, each needing rebase before merge.

**Root cause:** Squash merge changes master → next branch diverges from same file.

**Rule:** When iterating on the same file/component, accumulate all fixes in one branch. Create the PR only when done. Don't fragment into micro-PRs touching the same file.

### 2026-03-30: Docker buildx builder state corruption on ephemeral runners

**Symptom:** `docker buildx inspect multiarch` → "no builder found". `docker buildx create --name multiarch` → "existing instance, no append mode". `docker buildx rm multiarch` → "no builder found". All three commands fail.

**Root cause:** Builder was created with `become: false` (ansible_user) while Docker runs as root. The builder metadata split across user/root `.docker/buildx/instances/` directories — inspect sees root's empty state, create sees user's existing registration.

**Fix:** Clean both CLI state AND filesystem state before recreate:
```yaml
- shell: |
    docker buildx rm multiarch 2>/dev/null || true
    rm -rf /root/.docker/buildx/instances/multiarch 2>/dev/null || true
```

**Rule:** All Docker operations in Ansible must run with consistent privilege. Don't mix `become: true` and `become: false` for docker buildx commands in the same role.

### 2026-03-30: fromJSON repo variable pattern for hybrid runner fleets

**Pattern:** `runs-on: ${{ fromJSON(vars.RUNNER_DOCKER || '"ubuntu-latest"') }}`

- Variable unset → `fromJSON('"ubuntu-latest"')` → string `ubuntu-latest`
- Variable = `["self-hosted","linux","docker"]` → `fromJSON(...)` → array with labels

**Security:** Fork PRs MUST be forced to GitHub-hosted: `github.event.pull_request.head.repo.fork && 'ubuntu-latest' || fromJSON(...)`. Self-hosted runner with Docker socket = host-level access.

**Rule:** Use YAML `>-` folded scalars when `runs-on` expressions exceed yamllint line-length limits. GitHub Actions correctly evaluates folded expressions.

### [2026-05-09] Cloud-init bootstrap without Ansible day-2 path is invisible technical debt
**Context:** Investigating RELIAB-009 (Argo CD hub memory hygiene fix). The vault plan said 'Apply via make provision NODE=aws1 ENV=hub' but no such command existed. aws1 was bootstrapped via Terraform cloud-init (AWS-001..005, done 2026-03-22) which set up K3s on first boot. There was never an Ansible role applied to aws1 — only Terraform creating the instance and cloud-init running once on first boot.
**Problem:** When a node is bootstrapped purely via cloud-init (Terraform user-data) and the operator assumes an Ansible day-2 path exists for it, that assumption can persist undetected for weeks. Plans get written referencing `make provision NODE=X ENV=Y` style commands that look reasonable because they exist for other nodes — but the playbook (`provision-aws1.yml`), inventory group placement (`k3s_servers`), env config file (`hub.yaml`), and Makefile dispatcher case may all be missing. The gap only surfaces when a config drift fix needs to land (here: K3s `--kube-controller-manager-arg=terminated-pod-gc-threshold=100`). Risk: emergency fixes get applied via SSH/manual edits, creating drift between IaC and reality.
**Solution:** Two complementary rules: (1) Every node bootstrapped by cloud-init MUST also have an Ansible day-2 playbook before the bootstrap is considered complete. Even if the playbook is a thin wrapper that only invokes idempotent roles for config drift, it must exist. Acceptance criteria: `make provision NODE=<name> ENV=<env>` works on a freshly-bootstrapped node and reports 'ok' (no changes) on subsequent runs. (2) When writing remediation plans that reference automation, verify the automation exists before committing the plan to the vault. A plan that says 'apply via X' where X is hypothetical creates downstream churn — the next person reading the plan will discover the gap mid-execution. Pattern for new cloud-bootstrapped nodes (following AWS-001..005 + missing-now-RELIAB-009-9.0): Terraform cloud-init = bootstrap-only (install K3s, Tailscale, swap); Ansible playbook `provision-<node>.yml` = day-2 config (idempotent role invocation); env config `infra/config/values/<env>.yaml` = SSOT for that node's overrides; inventory group placement (`k3s_servers`, etc.) consistent with role expectations; Makefile dispatcher case for `make provision NODE=<node> ENV=<env>`. Validation: provision a node, then re-run the playbook → must report 0 changes.
**Tags:** `#ansible` `#terraform` `#cloud-init` `#iac` `#day-2-operations` `#argocd` `#aws` `#drift`

### [2026-05-10] Ansible apt module in --check mode reports stale-cache false positives
**Context:** Running `toolkit infra ansible run -p provision-aws1 -e hub --check` against aws1 during RELIAB-009 §9.0 pre-deploy validation. Goal: confirm idempotent convergence before applying to live K3s hub. The playbook had passed yamllint and `ansible-playbook --syntax-check` cleanly.
**Problem:** Dry-run failed on `base_system : Install base packages` with `No package matching 'unzip' is available`, despite unzip being a standard Ubuntu 24.04 package. The preceding `apt: update_cache: true` task reported `changed=true` but the package lookup still failed. The host was a freshly-cloud-init-bootstrapped t4g.small with whatever apt cache cloud-init left behind weeks ago.
**Solution:** In `--check` mode the `apt` module's `update_cache: true` is a no-op — it returns `changed=true` for reporting but does NOT execute `apt-get update`. Subsequent `apt: name=<pkg>` tasks then resolve names against whatever stale cache exists on the target, often missing packages added since the cache was last refreshed. Operational rule: treat --check failures inside `apt: name=...` tasks as artifacts of check-mode semantics, not real regressions. Validate the rest of the playbook in --check (pre-flight asserts, file templates, handlers), then run for real (without --check) to confirm package installation. Do NOT add `check_mode: no` to apt tasks — that defeats the purpose of dry-runs on the rest of the role. Optional improvement: run `apt-get update` via SSH against the target as a manual pre-step when --check coverage of the full role is needed (one-shot, doesn't pollute the playbook).
**Tags:** `#ansible` `#apt` `#check-mode` `#dry-run` `#gotcha` `#cloud-init`

### [2026-05-10] Absorbed specs need frontmatter alignment, not just body warnings
**Context:** During vault audit (2026-05-10), `kubelab/30-architecture/components/kubelab-gateway.md` and `kubelab-memory.md` were both found with `status: active` in YAML frontmatter while the body opened with `> Status: absorbed — Do not implement`. Both were rewritten on 2026-05-09 after being absorbed into ADR-029 on 2026-03-28.
**Problem:** When a spec is absorbed into another doc (e.g. ADR), keeping the file as historical reference is fine — but if frontmatter `status` stays `active`, the SSOT-detection tooling, validators, link-graph queries, and any agent reading metadata will treat it as live work. The body warning ("Do not implement") is invisible to programmatic readers. This produces silent drift: humans see "absorbed", machines see "active". A reader could mistakenly resurrect the spec or build dependencies against it.
**Solution:** When absorbing a spec, atomically update three things in the same commit: (1) frontmatter `status: absorbed` (or `archived`), (2) add `absorbed_by: <target-id>` and `absorbed_on: YYYY-MM-DD` fields so the dependency graph captures the link, (3) keep the body warning AND ensure `_ssot.md` reflects the absorption in its "Absorbed Specs" section. The vault `types.json` schema should include `absorbed_by` and `absorbed_on` as standard fields when this pattern recurs. Applied today: gateway.md and memory.md frontmatter corrected with `status: absorbed` + `absorbed_by` + `absorbed_on`.
**Tags:** `#vault-health` `#ssot` `#frontmatter` `#drift` `#adr`

### [2026-05-10] K3s server can deadlock on futex after bulk-delete; restart releases the lock
**Context:** RELIAB-009 §9.3 deployment: applied `terminated-pod-gc-threshold=100` to aws1 (hub, t4g.small) which had accumulated ~1000+ zombie pods over 10 months. Goal was bulk-reaping the historical backlog. K3s restart triggered the new threshold; GC controller fired aggressively for ~3 minutes (5 events/sec) then stopped logging GC events at all. But `kubectl get pods -n argocd` continued timing out for 20+ minutes after GC silence.
**Problem:** Diagnostics showed: K3s server process in `WCHAN=futex_` state (kernel mutex wait) at 17% CPU and 69% RAM. kube-controller-manager logs had stopped emitting `delete pods` events. Node went `NotReady`. kubectl could fetch nodes (small response) and even Deployments/StatefulSets, but `kubectl get pods` (a larger response with thousands of tombstoned records) timed out at any timeout (8s, 20s, 60s). Auto-compaction of kine (SQLite-backed embedded etcd) appeared not to be running. The K3s server held an internal goroutine lock — likely in kine's slow SQL path — that blocked the pod list endpoint despite the GC having completed.
**Solution:** `sudo systemctl restart k3s` released the deadlock immediately. Post-restart: K3s up in ~30 seconds, kubectl responsive in 0.8s, memory recovered from 75MB to 460MB available (swap drained from 1.9GB to 65MB used). The kine SQLite data persists across restart, so no data loss. Operational rule: when K3s server is stuck post-bulk-delete (GC events silent, kubectl get pods timing out, process in futex state, memory thrashing), restart K3s is the right intervention — it's not a destructive operation, it costs 1-2 min API downtime, and frees kine-related goroutine locks that don't otherwise unwind. Do NOT add this to scheduled maintenance — only run on-demand when the symptom triggers.
**Tags:** `#k3s` `#kine` `#sqlite` `#gc` `#deadlock` `#futex` `#argocd` `#incident`

### [2026-05-10] Activating aggressive GC threshold on a backlog cluster needs manual pre-cleanup
**Context:** RELIAB-009 §9.3 lowered `terminated-pod-gc-threshold` from K3s default 12500 to 100 on aws1 hub. The hub had ~1000 historical zombie pods (Completed/ContainerStatusUnknown/Error) accumulated since the 2026-05-06 OOM cascade. The expectation was: K3s restart with new threshold → kube-controller-manager auto-reaps backlog gradually → cluster settles.
**Problem:** Reality was: the bulk GC pass generated ~5 delete events/sec for ~3 minutes, which (a) blew out journald+apt logs pushing disk from 76% to 91% (kubelet disk-pressure threshold is 85% → NotReady), (b) saturated K3s server CPU at load 3.0 on a 2-vCPU instance, (c) eventually deadlocked K3s on a kine SQLite goroutine lock (separate lesson), and (d) bloated kine state.db from 168MB to 200MB (tombstones not yet compacted). Net effect: hub was effectively offline for 20+ minutes. The original RELIAB-009 plan called out "Immediate cleanup (one-shot, not part of the PR)" — but it was framed as cosmetic, not as a hard prerequisite.
**Solution:** When tightening GC threshold on a cluster with significant pod backlog, the order matters: (1) Manual chunked cleanup first — `kubectl delete pods -A --field-selector=status.phase=Succeeded` in batches (e.g. namespace by namespace, with brief waits between to let kine breathe), (2) THEN apply the new threshold via Ansible/Helm. The new threshold should never have to do the initial mass purge — it should only handle the trickle of post-cleanup zombies. Defense-in-depth: provision `make maintain NODE=<hub>` before the threshold change so disk has headroom for the unavoidable log spike, even with chunked cleanup. Document this as a runbook: "tightening etcd/GC thresholds on backlogged clusters" → vault 40-runbooks/. Also: keep `k3s_etcd_snapshot_retention: 2` on small-disk hubs to minimize baseline disk usage so a log spike doesn't trip pressure threshold.
**Tags:** `#k3s` `#gc` `#etcd` `#kine` `#backlog` `#ordering` `#runbook` `#disk-pressure`

### [2026-05-10] Helm upgrade on disk-constrained node creates pull-evict-prune-pull death loop
**Context:** Post-merge of RELIAB-009 (PR #163): ran `make deploy-argocd` on aws1 (t4g.small, 8GB EBS) to apply §9.2 revisionHistoryLimit:3. Pre-deploy disk was 82% (within healthy range). Helm upgrade scaled the 6 Argo CD components back from 0 to 1 replica. New pods started pulling images (argocd v3.4.1 = 185MB + redis 8.2.3-alpine 27MB).
**Problem:** Image pulls pushed disk from 82% → 96% in ~30 seconds. Kubelet applied `node.kubernetes.io/disk-pressure:NoSchedule` taint. New Argo CD pods (without disk-pressure toleration) were evicted with `The node was low on resource: ephemeral-storage`. Evicted containers freed their image references → `crictl rmi --prune` (run by `make maintain` to recover disk) deleted those "orphan" images → next pod schedule attempt re-pulled the same images → death loop. The 8GB EBS volume is structurally insufficient: OS+apt cache (~1G) + K3s baseline (~2G containerd cache + kine + binaries) + Argo CD steady state (~3G) leaves <2G headroom — any image pull during normal operation crosses the 85% disk-pressure threshold.
**Solution:** Two complementary defenses: (1) Structural: increase EBS to 16GB via Terraform `ebs_size_gb` + online `aws ec2 modify-volume` + `sudo growpart /dev/nvme0n1 1 && sudo resize2fs /dev/root` — no instance replacement needed (~$0.76/mo extra, gp3). (2) Operational: never run Helm upgrade on a node already above 80% disk; pre-flight cleanup BEFORE the upgrade not after; when disk-pressure taint is set, do NOT prune images (that worsens the loop) — instead let pods stay Pending while you free disk via logs/cache cleanup, taint clears automatically when disk drops below threshold. Detection: `kubectl describe node | grep -A2 Taints` and `df -h /` are the two signals to check before declaring a Helm upgrade healthy. Add Uptime Kuma alert at disk >75% as early warning.
**Tags:** `#aws` `#ebs` `#k3s` `#argocd` `#helm` `#disk-pressure` `#eviction` `#containerd` `#ephemeral-storage` `#incident`

### [2026-05-10] Rotated syslog files (un-gzipped) consume 200MB+ on busy nodes — maintain role missed it
**Context:** During aws1 RELIAB-009 incident response: diagnosed disk at 96% after Helm upgrade pull. `du -sh /var/log/*` showed `/var/log/syslog.1` = 201MB (single un-rotated current archive) plus `syslog.2.gz` 22MB, `syslog.3.gz` 12MB, `syslog.4.gz` 3.1MB — 238MB total. The 201MB syslog.1 came from a 20-minute window when K3s server was in a futex deadlock spamming `Sending HTTP/1.1 502 response to 127.0.0.1:NNNN: dial tcp 10.42.0.6:10250: connect: connection refused` every millisecond.
**Problem:** The `node_maintenance` Ansible role only handles `journalctl --vacuum-size=20M` (covers systemd journal). It does NOT touch the classic rsyslog-rotated files in `/var/log/syslog.*`, `/var/log/kern.log.*`, `/var/log/auth.log.*`. On Ubuntu with rsyslog, logrotate rotates these daily and keeps 7 copies (default `/etc/logrotate.d/rsyslog`). A pathological burst (futex deadlock spamming syslog) can fill the active syslog file to hundreds of MB BEFORE logrotate's nightly cron rotates it. Result: a low-disk node (8GB EBS) goes from healthy to disk-pressure in minutes, and maintain.yml can't recover it.
**Solution:** Extend the `node_maintenance` Ansible role with a task that prunes rotated log files older than N days (parametrized; default 3): `find /var/log -maxdepth 1 -regex '.*\.(log\.|[0-9]).*' -mtime +{{ rotated_log_retention_days }} -delete` (idempotent). Also consider configuring rsyslog/logrotate to enforce maximum file size before rotation (`size 50M` in /etc/logrotate.d/rsyslog) so a runaway logger can't bloat the active file. Add a separate task to truncate the ACTIVE syslog if it exceeds a threshold (defensive): `find /var/log -maxdepth 1 -name 'syslog' -size +100M -exec truncate -s 0 {} \;`. Document that node_maintenance should run BEFORE high-disk-impact operations (Helm upgrade, image pulls) not just on a weekly timer.
**Tags:** `#ansible` `#node_maintenance` `#syslog` `#rsyslog` `#logrotate` `#ubuntu` `#disk-pressure` `#automation` `#gap`

### [2026-05-10] Terraform data.aws_ami filter drift triggers Spot replacement on every plan
**Context:** Post-merge of feat/aws-002-ebs-resize-12gb (PR #165): ran `terraform plan` in `infra/terraform/aws/` to validate the EBS resize would be an in-place `ec2:ModifyVolume` action. Expected diff: 1 in-place change on root_block_device.volume_size 8 → 12. Reality: Terraform output `aws_spot_instance_request.argo_hub must be replaced` with the AMI attribute marked `# forces replacement` (`ami-023c2be60b92b00a3 → ami-050a364ece0d45bcd`).
**Problem:** `data "aws_ami" "ubuntu" { name_regex = "...ubuntu-noble-24.04-arm64-server-*" most_recent = true }` resolves to the LATEST matching AMI each time `terraform plan` runs. Canonical publishes new Ubuntu 24.04 ARM64 AMIs periodically (security updates). On a Spot/cattle infra design (ADR-026) where replacement IS the model, this means EVERY `terraform plan` for ANY unrelated attribute (EBS resize, tag change, security group rule, …) triggers a destroy+create of the instance — losing kine state, Headscale registration, etc. Replacement should be DELIBERATE, not a side effect of unrelated plans.
**Solution:** Add `lifecycle { ignore_changes = [ami, user_data] }` to the `aws_spot_instance_request` (or `aws_instance`) resource. AMI updates then require explicit `terraform apply -replace=<resource>` — codified as a Makefile target (e.g. `make aws1-replace`) that orchestrates the full cattle cycle: snapshot Headscale node entry → terraform apply -replace → wait cloud-init → re-run deploy-argocd. Also ignore `user_data` because Spot user_data embeds the tailscale_authkey (1h-lifetime) — its rotation should not trigger replacement; instead re-render and reboot if needed. Future automation: a scheduled `terraform plan -refresh-only` GH Action can detect AMI drift weekly and open an advisory PR. Generalisable rule: on any "cattle" cloud resource where the data source resolves to a moving target (latest AMI, latest VPC, etc.), ALWAYS pair with `lifecycle.ignore_changes` on the attributes driven by that data source.
**Tags:** `#terraform` `#aws` `#spot` `#cattle` `#ami` `#lifecycle` `#drift` `#iac-pattern`

### [2026-05-11] Persistent journald on Debian RPi needs 99- drop-in AND post-restart flush
**Context:** ANSIBLE-023 (2026-05-11): forcing `Storage=persistent` on rpi3 via `/etc/systemd/journald.conf.d/00-kubelab.conf` after the same-day outage that lost all crash forensics because journald was volatile.
**Problem:** Two independent failure modes stacked: (1) After applying the drop-in and restarting `systemd-journald`, `journalctl --header` still reported journals at `/run/log/journal/...` and `/var/log/journal/<machine-id>/` stayed empty. `systemd-analyze cat-config systemd/journald.conf` revealed Debian RPi images ship `/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf` with `Storage=volatile` (deliberate, to spare SD card life). systemd merges drop-ins **lexicographically across `/etc` and `/usr/lib` as one set**, so `00-kubelab.conf` from `/etc/` loses to the system's `40-` from `/usr/lib/`. (2) After renaming to `99-kubelab.conf` (which now wins), `journalctl --header` STILL pointed at `/run/log/journal/...`. The `restart systemd-journald` Ansible handler re-reads config but does not migrate the active journal file from `/run` to `/var` — that migration is a separate operation.
**Solution:** Both gotchas have a deterministic fix. (1) **Use `99-` prefix for any `/etc/systemd/*.conf.d/` drop-in that must override a vendor default on Debian RPi images.** The drop-in precedence model is "highest filename wins regardless of directory." Concretely: `99-kubelab.conf` in `/etc/systemd/journald.conf.d/` beats `40-rpi-volatile-storage.conf` from `/usr/lib/`. Verify with `systemd-analyze cat-config systemd/journald.conf` — the merged view shows each contributing file in order; the last `Storage=` line wins. (2) **`restart systemd-journald` is not sufficient; pair it with `journalctl --flush`.** Restart opens new journal files but does not move existing volatile state to the persistent path. In Ansible, chain two handlers: `restart systemd-journald` then `flush journald to persistent storage` (command: `journalctl --flush`, `changed_when: false`). Notify both from the config-template task. After this combo, the persistent dir starts populating immediately and `journalctl --disk-usage` reports a value matching `/var/log/journal/<machine-id>/`. Generalisable: any systemd unit with a vendor drop-in default on RPi/Debian (network, resolved, etc.) probably needs the same `99-` strategy. Always cross-check with `cat-config`, never assume `/etc/` always wins.
**Tags:** `#ansible` `#journald` `#systemd` `#drop-in` `#raspberry-pi` `#debian` `#gotcha` `#iac-pattern`

### [2026-05-11] aws_spot_instance_request silently drops root_block_device updates — migrate to aws_instance + instance_market_options
**Context:** AWS-003 (2026-05-11): After PR #167 added `lifecycle { ignore_changes = [ami, user_data] }` to `aws_spot_instance_request.argo_hub`, `make tf-aws-apply` reported success ("Apply complete! Resources: 0 added, 1 changed, 0 destroyed", "Modifications complete after 1s") for an EBS resize 8→12 GB. Terraform state showed `volume_size = 12`. But `aws ec2 describe-volumes --volume-ids vol-...` returned `Size: 8` and `describe-volumes-modifications` returned `InvalidVolumeModification.NotFound`. AWS was never called.
**Problem:** The legacy resource `aws_spot_instance_request` represents the Spot REQUEST, not the underlying EC2 instance. When `root_block_device.volume_size` changes, the AWS provider mutates the in-memory state of the spot request object but does NOT translate that into an `ec2:ModifyVolume` API call against the EBS volume attached to the launched instance. Behaviour is silent: terraform reports success, state lies, AWS untouched. Known issue: hashicorp/terraform-provider-aws#4252 (open for years). The 1-second "Modifying..." duration is a tell — a real `ModifyVolume` call takes ≥10s to enter `optimizing` state. This breaks any in-place lifecycle operation on Spot-backed resources (EBS resize, tag updates on the volume object, root device IOPS/throughput tuning). It also subverts the cattle pattern: forces operators to either use `terraform apply -replace` (destroy+recreate, loss of instance state) or operate outside IaC entirely (aws ec2 modify-volume + tfstate drift).
**Solution:** Migrate from `aws_spot_instance_request` to `aws_instance` with `instance_market_options { market_type = "spot"; spot_options { spot_instance_type = "persistent"; instance_interruption_behavior = "stop" } }`. The latter uses the modern unified `RunInstances` + `InstanceMarketOptions` API and correctly translates `root_block_device.volume_size` updates into `ec2:ModifyVolume` calls. **Zero-downtime migration recipe** (preserves the running instance, Tailscale machine key, Argo CD state, Headscale registration): (1) `cp terraform.tfstate terraform.tfstate.pre-aws-instance` as safety net; (2) edit `main.tf`: replace `resource "aws_spot_instance_request" "x"` block with `resource "aws_instance" "x"` adding `instance_market_options`; (3) edit `outputs.tf`: rewrite references — `aws_spot_instance_request.x.spot_instance_id` → `aws_instance.x.id`, `aws_spot_instance_request.x.id` → `aws_instance.x.spot_instance_request_id`, etc.; (4) `terraform state rm aws_spot_instance_request.x` (removes from state, AWS untouched); (5) `terraform import aws_instance.x i-<instance_id>` (re-adopts the same EC2 under the new resource type); (6) `terraform plan` — expected output: `~ root_block_device.volume_size: <old> → <new>` in-place + benign tag adds (the legacy resource put tags on the Spot Request object, not the instance — the new resource fixes this); (7) `terraform apply` performs the real `ec2:ModifyVolume`, durations of 30s+ confirm the difference vs the fake 1s; (8) on the host, `growpart` + online `resize2fs` (no reboot required for ext4). **Caveat**: the original Spot Persistent Request becomes orphaned from terraform after step 4. It still works for instance-replacement events triggered by AWS (Spot interruptions, hibernation wake) because `aws_instance.spot_instance_request_id` references it as a computed read-only output, but terraform will NOT cancel it on `terraform destroy`. Mitigate with a `make aws1-destroy` wrapper that runs `aws ec2 cancel-spot-instance-requests` first. **Generalisable**: any existing Terraform module using `aws_spot_instance_request` is technical debt — the resource is effectively deprecated for production use. Greenfield should always use `aws_instance` + `instance_market_options`.
**Tags:** `#terraform` `#aws` `#spot` `#ebs` `#modify-volume` `#iac-pattern` `#state-surgery` `#import` `#provider-bug`

### [2026-05-12] Ubuntu /etc/logrotate.d/rsyslog groups 6 syslog paths into ONE block — regex must match multi-path stanza
**Context:** ANSIBLE-025 validation on aws1 (Ubuntu 24.04). Replacing the buggy `lineinfile` `insertafter: '^/var/log/syslog$'` in `base_system` role with `ansible.builtin.replace` to inject `size 50M` INSIDE the logrotate block. Initial regex proposal: `(^/var/log/syslog\n\{\n)(?!\s*size\s)`.
**Problem:** First apply on aws1 reported `ok=11 changed=6` but BOTH the Scrub and Cap tasks were among the `ok=`, not `changed=`. The Cap regex silently no-opped. Investigation via `ssh aws1 "grep -A 10 '^/var/log/syslog$' /etc/logrotate.d/rsyslog"` revealed Ubuntu's stock rsyslog config groups SIX paths under ONE `{ ... }` block: `/var/log/syslog`, `/var/log/mail.log`, `/var/log/kern.log`, `/var/log/auth.log`, `/var/log/user.log`, `/var/log/cron.log` — only THEN comes the `{`. The mental model "one path per block" baked into the ticket text + the proposed regex shape (path immediately followed by `\n{\n`) does not match real-world Ubuntu/Debian logrotate layouts. The grep -A4 acceptance criterion from the original ticket also reflected this wrong assumption (4 lines wasn't enough to reach the block on Ubuntu).
**Solution:** Rewrite the regex to capture the WHOLE path group containing `/var/log/syslog` up to and including the opening brace: `(^(?:/var/log/\S+\n)*?/var/log/syslog\n(?:/var/log/\S+\n)*\{\n)(?!\s*size\s)` with replacement `\1    size {{ rsyslog_logrotate_size_cap }}\n`. Lazy quantifier `*?` before the syslog anchor handles paths listed before syslog; greedy `*` after handles paths after. The negative lookahead `(?!\s*size\s)` preserves idempotency. Validated end-to-end on aws1: first apply `changed=1` on Cap (Scrub `ok` because no prior contamination), `grep` confirms `size 50M` is the first directive after `{`, third apply `changed=0` across all 11 logging tasks. Also adjusted the Scrub regex from `(^/var/log/syslog\n)\s*size\s+\S+\n(\{)` → `(^/var/log/syslog\n)\s*size\s+\S+\n` to handle the real-world contamination shape (mis-inserted line lands between paths, not between syslog and `{`).
**Tags:** `#ansible` `#logrotate` `#rsyslog` `#regex` `#ubuntu` `#idempotence`

### [2026-05-12] journald SystemMaxUse only vacuums archived journals — active journal can briefly exceed cap
**Context:** ANSIBLE-024 propagation to kubelab-vps (Hetzner Cloud, prod K3s). After applying `base_system` role with `Storage=persistent` + `SystemMaxUse=20M` drop-in and restarting systemd-journald, `journalctl --disk-usage` reported 24.0M — 4M over the configured cap.
**Problem:** First reaction was to suspect the cap wasn't being honored. Tried `sudo journalctl --vacuum-size=20M` to force-trim, but it freed 0B from `/var/log/journal/<machine-id>`, `/var/log/journal`, and `/run/log/journal`. Other 5 nodes in the same rollout (aws1/rpi4/beelink/ace1/ace2) were all comfortably under 20M, so the cap clearly worked there — why not on VPS?
**Solution:** `SystemMaxUse` only governs the total size of **archived** (sealed/rotated) journal files. The **active** journal file (the one journald is currently writing to) grows until it hits journald's internal rotation threshold (~`SystemMaxFileSize`, default 1/8 of `SystemMaxUse` rounded up to file-system block boundaries, or 64MB max). When journald rotates the active file, it becomes archived, and then `SystemMaxUse` is enforced against the new archived set. So a freshly-restarted journald on a busy host can legitimately show usage above `SystemMaxUse` for hours/days until the first rotation. `--vacuum-size` confirms this — it returns 0B freed because there are no archived journals yet, all the bytes are in the still-active file. Action: do not panic. Either wait for natural rotation, or force with `systemctl kill -s SIGUSR2 systemd-journald` (intrusive on prod, brief interruption to logging). For ANSIBLE-024 acceptance, treat 24M post-restart as PASS and revisit on next maintenance window.
**Tags:** `#journald` `#logrotate` `#ansible-024` `#systemd` `#prod`

## 2026-05-12 — Argo CD `targetRevision` preview pattern for visual PR validation

> **Superseded for staging by ADR-037 (2026-05-23).** Staging now runs with `selfHeal: false` (ARGO-015 / PR #211), so `make deploy-k8s ENV=staging` from a feature worktree is again the natural test-before-merge path — no targetRevision repointing needed. The technique below remains useful for **prod** (where `selfHeal: true` is preserved by design) and for any future Application with auto-sync; keep this lesson for that narrower use case.

**Problem.** Staging on Argo CD GitOps (auto-sync + selfHeal) reverts any `kubectl apply` that doesn't match the configured `targetRevision` (master). The old loop "feature branch → `make deploy-k8s ENV=staging` → validate → PR" is dead. Trunk-based rule + visual-test-before-merge requirement become mutually exclusive without a preview mechanism.

**Discovered during** PR1 dashboard cosmetic (`fix/dash-ui-cosmetic`, PR #171, 2026-05-12). `make deploy-k8s ENV=staging` apparent-succeeded but the pod still served stale `custom.js` (footer date 2026-03-28 instead of 2026-05-12). Diagnosed via the `argocd.argoproj.io/tracking-id` annotation on the homepage Deployment plus comparing local `kubectl kustomize` ConfigMap name hash vs the deployed Deployment's `volumes.configMap.name`.

**Solution.** Temporarily point Argo at the feature branch:

```bash
# After commit + push of feature branch to GitHub:
kubectl --kubeconfig ~/.kube/kubelab-hub-config -n argocd patch application kubelab-staging \
  --type merge -p '{"spec":{"source":{"targetRevision":"fix/branch-name"}}}'

# Force immediate refresh (don't wait ~3min polling):
kubectl --kubeconfig ~/.kube/kubelab-hub-config -n argocd annotate application kubelab-staging \
  argocd.argoproj.io/refresh=hard --overwrite

# Validate in browser. Hard refresh (Ctrl+Shift+R) to bypass client cache.

# After merge PR to master, patch back:
kubectl --kubeconfig ~/.kube/kubelab-hub-config -n argocd patch application kubelab-staging \
  --type merge -p '{"spec":{"source":{"targetRevision":"master"}}}'
```

**Limitations.**

- One feature branch at a time per Application (staging mirrors one branch).
- Forgetting the patch-back leaves staging anchored to a deleted branch → no further master updates land. MUST track in MEMORY.md handoff + harness task.
- Browser cache: ConfigMap hash suffix changes the K8s ConfigMap NAME, NOT the URL served to the browser. `custom.js`/`custom.css` URLs are stable — hard refresh required for visual validation.
- `selfHeal: true` stays ON during preview: any ad-hoc `kubectl edit` during the test is reverted to the branch state. Good for clean tests, bad for ad-hoc patches.

**Future automation candidates.**

- ApplicationSet with PR generator for automatic per-PR ephemeral preview environments (multi-PR support).
- Argo CD Notifications + webhook to auto-revert `targetRevision` when the PR merges.
- Makefile wrappers: `make argo-preview APP=… REV=…` and `make argo-revert APP=…` to encapsulate the patches.

**When NOT to use.**

- Prod: changing `targetRevision` on prod would be a security incident.
- PRs touching non-K8s state (Ansible, Terraform): no Argo to redirect — use the regular apply workflow.
- PRs that fully validate locally and have no visual/UI component: trust kustomize, skip the preview ceremony.

### [2026-05-19] Ansible pre_tasks loading SSOT config MUST be tagged `[always]` for tag-selective deploys
**Context:** PR3a (DASH-DT-014a) wired the new `glances` Ansible role into `provision-ace1.yml` and `provision-ace2.yml`. Both playbooks have pre_tasks that load `common.yaml` + env override + merge them into a single `config` fact. The new role uses `config.networking.nodes.{ace1,ace2}.tailscale_ip` and `config.apps.services.observability.glances.*`. Live smoke was `make provision NODE=ace1 ENV=staging TAGS=monitoring` (tag-selective to avoid touching k3s/docker/tailscale roles).
**Problem:** First provision attempt failed immediately with `'config' is undefined`. Cause: ansible's `--tags monitoring` filter skips any task without a matching tag, including all pre_tasks that load `config`. Result: roles run before any config is loaded. Same playbooks (provision-bee, provision-vps, provision-rpi4) have the same bug latent — they have never been exercised with selective tags because nobody noticed.
**Solution:** Add `tags: [always]` to every pre_task that loads SSOT config (include_vars for common.yaml, env override, and the set_fact merge into `config`). Do NOT tag SOPS decrypt pre_tasks as always — those are only needed when the run actually consumes secrets (tailscale/k3s_server). With `tags: [always]`, `--tags monitoring` (or any tag) now correctly loads config before the role runs. Standard Ansible pattern; benefits all future tag-selective deploys, not just glances. Lesson: when adding a new role that depends on `config`, also verify the host playbook's pre_tasks are taggable.
**Tags:** `#ansible` `#playbooks` `#ssot` `#tags` `#gotcha`

### [2026-05-19] Revert ad-hoc commits in a feature branch to keep PR scope atomic (alternative to interactive rebase + force-push)
**Context:** During PR3a (DASH-DT-014a) the working branch had accumulated an earlier commit (`88cea7a`) that introduced ad-hoc `vps_services` and `rpi4_services` Ansible roles. That commit belonged to the planned PR3b (DASH-DT-014b) scope, not PR3a. Leaving it in PR3a would have meant ~190 LOC of code that PR3b would immediately delete — wasteful for the reviewer and confusing for the post-merge history.
**Problem:** Three options were on the table: (a) `git revert 88cea7a` adds a visible revert commit; (b) interactive rebase to drop the commit + `git push --force-with-lease`; (c) keep the commit and merge a bloated PR. Option (b) is the "cleanest" history but destructive on remote — requires force-push to an already-pushed branch. The default CLAUDE.md instructions discourage force-push without explicit user consent.
**Solution:** Use `git revert <commit>` (option a) as the non-destructive default. The branch ends with extra commits (original + revert) but the net diff vs master is identical to what option (b) would produce. Critically: when the PR is squash-merged (kubelab default), all branch-intermediate commits collapse into one — the final history in master is identical for both option (a) and option (b). For squash-merge workflows, revert is strictly better: zero force-push risk, no rewrite of pushed history, and the revert commit itself is a useful audit trail showing intent ("this code intentionally not in PR3a").
**Tags:** `#git` `#pr-hygiene` `#workflow` `#scope-management`

### [2026-05-19] GitHub "Squash and merge" can silently drop later commits on a PR — verify post-merge content, not just merge status
**Context:** During PR #177 (SSOT-005 build_node_list refactor), Codex left a P2 review flagging that the new `dashboard.ping_url` schema hardcoded `100.64.0.3:11434`, duplicating the node's `tailscale_ip`. A fixup commit `b0abbf1` was pushed to the same branch introducing a `ping_target` schema with hard-fail validation; that commit lived on `origin/refactor/ssot-005-build-node-list` and was push-verified before the merge.
**Problem:** After PR #177 was squash-merged, master commit `d8e3139` contained only the original commit `5e86848`. The fixup `b0abbf1` did not land. The Codex review comment thread still pointed at the original code, and the new ping_target validation logic was missing from `toolkit/scripts/sync_homepage_config.py`. The defect was only detected later when the Beelink cockpit flip PR re-read the file and found the old schema. Lost work was not catastrophic (the fixup could be re-applied), but the assumption that "squash merge captures everything pushed to the branch" was wrong in this case. Possible cause: merge mode mis-selected, or a race between the fixup push and the merge operation, or a manual UI choice to merge a specific commit.
**Solution:** After every merge, especially when a Codex / reviewer comment prompted a fixup commit, verify the actual file content on master matches the expected post-fixup state — do not trust the merge status alone. Concrete check: `git show origin/master -- <changed-file> | grep -E "<expected-symbol>"` for at least one symbol that the fixup introduced. If the fixup is missing, re-apply it as a new commit on a follow-up branch and PR with a clear `re-apply Codex fix that did not land in #NNN squash` note. The cheap habit of grepping for a fixup-introduced symbol on master immediately post-merge would have caught this in seconds instead of hours.
**Tags:** `#git` `#github` `#pr-hygiene` `#merge` `#review` `#verification`

### [2026-05-19] Pre-flight Plays need per-playbook tagging — blanket `tags: [always]` breaks playbooks designed for one-time installs
**Context:** PR #181 added `tags: [always]` at Play level to the Pre-flight Play 0 of every `provision-*.yml` so that `make provision NODE=X ENV=Y TAGS=Z` would actually run the SSH / sudo / VPS reachability checks (which were previously skipped under any `--tags` filter). The rule was applied uniformly to all 7 provision playbooks (ace1, ace2, bee, rpi3, jetson, vps, aws1).
**Problem:** `provision-vps.yml` Pre-flight Play 0 is special: it is designed for **one-time first K3s install on VPS** (Pattern C migration). It asserts "K3s not yet installed" (fails if `/usr/local/bin/k3s` exists) and "Docker Compose Traefik is running" (pre-cutover assumption). Both invariants stop holding once the K3s cutover is complete. After PR #181 merged, every `make provision NODE=vps ENV=prod TAGS=monitoring` (the path PR #182 needed for VPS Glances migration) crashed during the Pre-flight on "Verify Docker Compose Traefik is running" — exactly the wrong place to fail. The regression was caught immediately during PR #182 live smoke, but required PR #183 to revert the change just for `provision-vps.yml`.
**Solution:** When applying a blanket pattern (e.g. tag everything `[always]`) across a fleet of playbooks, audit each playbook's *intent* first. Generic Pre-flight Plays (SSH + sudo + internet + key check) are safe to tag `[always]`. Playbooks with one-time-install assertions (`fail if <binary> exists`, `verify <service> running`) need either `[preflight]` only (manual invocation) or a `when:` guard wrapping the destructive asserts (`when: not <binary>.stat.exists`). Document the per-playbook intent in a comment block at the Play header so the next blanket-rule sweep does not silently regress it. PR #183 added exactly this comment to `provision-vps.yml`.
**Tags:** `#ansible` `#playbooks` `#tags` `#regression` `#lessons-from-fix`

### [2026-05-22] Mutation testing requires an independent oracle
**Context:** Designing a "test-of-the-test" for the AI-001 X-API-Key middleware (Traefik plugin dtomlinson91/traefik-api-key-middleware). The first version of the acceptance criterion (PR #191) said: "temporarily rotate `apps.services.ai.ollama.api_key` in SOPS to a known-wrong value, re-apply, observe `test_ollama_health_authenticated` MUST fail with 403". The intent was to prove the test actually exercises the middleware (would catch a real auth break). Codex P1 review caught a logic flaw: the test fixture (`ollama_api_key` per `proposal.md:35`) ALSO reads from SOPS. Rotating SOPS rotates BOTH sides — the client sends the rotated value, the middleware expects the rotated value, the test still passes with 200. The "MUST fail" assertion cannot be satisfied under normal conditions. The drill is an unreliable regression detector.
**Problem:** If the actor (client) and the target (server under test) consult the same source of truth, a coordinated change is NOT a mutation — it's a consistent update. Most "mutation testing" patterns that rotate a shared secret silently devolve into rotation tests. The "test of the test" requires that the actor remain in a known *previous* or *adversarial* state while the target moves. Without that disjunction, you cannot prove the test catches a regression.
**Solution:** Use a hardcoded sentinel in the test that is *deliberately* not read from the shared source of truth. For AI-001: `test_ollama_rejects_invalid_key` sends `X-API-Key: definitely-not-the-real-key` (string literal in the test file, NOT a SOPS lookup). The client and the middleware no longer share a moving source of truth — the assertion (status_code == 403) holds independently of any SOPS rotation, and the test fails iff the middleware ever accepts arbitrary keys. Zero operational cost (runs on every CI pass), no manual drill, no IngressRoute touched, no SOPS tampering. Pattern is reusable: any auth-protected endpoint can ship a `test_<service>_rejects_invalid_key` companion to `test_<service>_health_authenticated` as a permanent test-of-the-test. Codified in `specs/AI-002-e2e-tests/proposal.md` acceptance criterion #3. Candidate for promotion to `00_meta/patterns/pattern-mutation-oracle.md` when the pattern recurs in AI-004 / DT-004 / RAG.
**Tags:** `#testing` `#security` `#mutation-testing` `#ai-001` `#adr-035`

### [2026-05-23] Docker port bind to interface-specific IP is fragile under interface flap
**Context:** ace2 ollama compose used `ports: ["100.64.0.5:11434:11434"]` to constrain the listener to Tailscale interface — implicit "VPN-only" via bind constraint. Worked fine in steady state.
**Problem:** tailscaled flapped briefly during AI-001 PR-C smoke (re-key / NAT rebind / health-check retry). The momentary loss of `100.64.0.5` from `tailscale0` broke dockerd's port binding. The container died, and `restart: unless-stopped` couldn't recover because `cannot assign requested address` — Linux IP-specific binds DO NOT auto-rebind after interface recovery; the container needs full recreation. Dockerd looped restarting for hours until manual intervention. Meanwhile public path returned HTTP 502. Discovered 2026-05-23 (ANSIBLE-025, closed by PR #199).
**Solution:** Use `network_mode: host` + listen on `0.0.0.0` + UFW restrict by source CIDR. The bind lives in the kernel's global port table, decoupled from any one interface. tailscaled flaps no longer break the listener. Security preserved by UFW `allow PORT/tcp from tailscale_cidr` + `from lan_cidr` (default-deny inherited from `base_system` role). Equivalent external reachability (VPN + LAN only), but resilient to flaps. **Implicit security via bind constraint is the worst kind of security — it breaks silently.** Always make it explicit (firewall, RBAC, etc.).
**Tags:** `#ansible` `#docker` `#tailscale` `#networking` `#ollama` `#ansible-025`

### [2026-05-23] Mutation drills require an independent oracle
**Context:** AI-002 spec originally proposed a "mutation drill" to test auth: SOPS-tamper the api_key, observe that the previously-working request now fails. Both the test fixture (client) and the middleware (target) read the same SOPS file via the same toolkit codepath.
**Problem:** Codex P1 review on PR #191: this isn't a mutation drill — it's a coordinated rotation. If you tamper SOPS, both actor and target see the new value; the test would PASS even when the middleware was broken (e.g., if it ignored the key entirely). The "test" was tautological — it proved SOPS reads work, not that auth works. False sense of security.
**Solution:** Hardcode a wrong-key sentinel in the test itself, completely independent of SOPS. `test_ollama_rejects_invalid_key` sends `X-API-Key: wrong-sentinel-XYZ` and expects 403. The actor (test) and target (middleware) draw from different sources; a real mutation in the middleware (e.g., accepting all keys) would surface immediately. Pattern: when validating a check, the validator and the checked subject MUST NOT share state. The "wrong-key sentinel" idiom is the cheapest way to break the coupling — zero infra, full coverage. Shipped in PR #192.
**Tags:** `#testing` `#security` `#mutation-testing` `#ai-001` `#ai-002`

### [2026-05-23] Argo CD selfHeal breaks "test-before-merge" workflow without explicit pause
> **Superseded by ADR-037 (2026-05-23, same day).** ARGO-015 / PR #211 institutionalized path (1) for staging (`selfHeal: false`) and kept path (2) as the only viable mode for prod (`selfHeal: true`). Solution section below is preserved for the prod-only case; staging no longer needs the patch dance.

**Context:** During AI-001 PR-C smoke, user wanted to test changes in prod BEFORE merging the PR — sensible test-before-merge discipline. Standard approach: deploy from feature branch worktree, smoke, then merge if good.
**Problem:** `kubelab-prod` Argo CD Application has `automated: {prune: true, selfHeal: true}`. Within seconds of `kubectl apply -k` from the feature worktree, Argo CD detected drift from master (which didn't yet have the change) and reverted the IngressRoute. The Middleware CRD `api-key-ollama` (NOT in git, lives only in `.rendered/` per ADR-035) survived because Argo doesn't manage it. Net effect: kubectl apply from feature branch is a no-op for git-tracked resources in this GitOps setup. "Test before merge" via kubectl is impossible without intervention.
**Solution:** Three viable paths for GitOps prod test-before-merge: (1) Temporarily disable `selfHeal` on the Application (`kubectl patch app kubelab-prod -p '...selfHeal:false'`), apply from feature worktree, smoke, re-enable. (2) Merge first, rely on Argo sync (~3min), smoke after. If broken, `git revert` + push triggers re-revert. (3) Trust local `kubectl kustomize` validation — for purely-declarative changes (manifest only, no migrations), the render output IS the cluster diff. We chose (2) for AI-001 PR-C — Argo synced within seconds of merge, smoke confirmed within minutes. For future high-risk changes, (1) is the safer pattern. Always know which mode you're in before testing in prod.
**Tags:** `#argocd` `#gitops` `#prod` `#workflow` `#ai-001`

### [2026-05-23] Don't put SOPS master key in CI provider secrets — use self-hosted-runner-local key
**Context:** CI-GATE-002 Phase 2 needed SOPS decryption in CI to extend the drift gate coverage to all generated paths. Default reflex was "add `SOPS_AGE_KEY` as a GitHub Actions secret". User pushed back: "no me siento cómodo poniendolo en internet".
**Problem:** A SOPS age key in GitHub Actions secrets is broader exposure than it looks: (a) anyone with repo admin can read it decrypted via the API; (b) a workflow with a subtle bug (e.g., `echo $SOPS_AGE_KEY`) leaks despite GH `***` masking only on direct env var references; (c) supply-chain attacks on third-party Actions in the same workflow get the key for free; (d) the key decrypts EVERY secret in the vault including prod credentials, not just the ones the gate needs. Drift validation does not need write authority — but the master key has it.
**Solution:** For projects that already use a self-hosted runner (ADR-030 in this repo), the proper pattern is: the age private key lives on the runner's host filesystem (`~/.config/sops/age/keys.txt`, the same location the user already maintains for local SOPS work). The workflow reads from disk; GitHub never sees the key. Fork PRs continue on `ubuntu-latest` and skip the SOPS-dependent steps — they don't have access to the runner's filesystem. This trades cloud-portability for sharply reduced exposure surface. Long-term alternatives worth considering when adding new infra: GitHub OIDC → cloud KMS for ephemeral key release; Sealed Secrets (Bitnami) for cluster-side-only decrypt with repo-safe CRDs (tracked as SEAL-001..004 + SEC-AGE-001). Don't default to "stuff it in provider secrets" without naming the exposure.
**Tags:** `#security` `#ci` `#sops` `#patterns`

### [2026-05-23] CI gates surface stack debt layer-by-layer — budget for cascading failures
**Context:** CI-GATE-002 (PR #207) hit 5 consecutive CI failures across one session. Each failure was diagnosed and fixed before the next was visible. The pattern was not "flaky" — each was a genuine, distinct issue surfacing only after the prior one was resolved.
**Problem:** The 5 layers, in order: (1) `pipx: command not found` — self-hosted runner had no pipx; assumed it was preinstalled. (2) `PackageNotFoundError: toolkit` — used `poetry install --no-root` to be "minimal", which doesn't install the project itself; `toolkit/__init__.py` calls `importlib.metadata.version("toolkit")` which then fails. (3) `Failed to get GitHub repository information` — `toolkit.features.github_secrets` instantiated a manager at module import time and shelled out to `gh repo view`; CI had no GH_TOKEN. (4) `Template variable error: BASIC_AUTH_CREDENTIALS` — Traefik middleware template reads SOPS-sourced value; CI without age key produces empty output → drift. (5) `Drift detected in configmaps.yaml` — `EMAIL_USER/EMAIL_FROM/BEEHIIV_PUB_ID` are non-secret values living in SOPS that leak into ConfigMaps via the merge order. Each was a distinct architectural assumption that broke in the new context (CI without SOPS, no auth, no Poetry root). Estimated time consumed: ~45 min of iteration.
**Solution:** Two rules to internalize: (1) **When installing a NEW CI workflow, budget for cascading failures**. Each failure exposes one layer of "this worked locally because [X] was implicit". Don't promise "this PR is ~50 LOC" — promise "this PR plus the stack debt it surfaces". The lazy-init refactor in `github_secrets.py` was a latent bug for months; the gate found it. (2) **Treat each cascade layer as informative, not flake**. Resist the urge to add `continue-on-error: true` or to scope-narrow until the gate is useless. The gate's value is precisely in catching what was hidden. The honest end state of CI-GATE-002 Phase 1 — narrow scope with explicit follow-up tickets (SSOT-012, CI-GATE-003) — is better than a wider gate that papers over the underlying SOPS pollution. Related pattern: regen-and-diff drift detection (2026-05-23 lesson) catches the same family of "committed file evolved past its generator" debt that the gate then enforces.
**Tags:** `#ci` `#process` `#patterns`

### [2026-05-23] Audit consumers BEFORE big-bang SSOT refactors — "move 3 values" hid 21 references
**Context:** SEC-K8S-001 cleanup surfaced that 3 non-secret values (`email_user`, `email_from`, `beehiiv_pub_id`) live in SOPS but leak into ConfigMaps via the merge. Initial estimate was "5 LOC, move them to common.yaml, done". User asked for a thorough check before changing anything: "hay que chequear también el código de las aplicaciones, manifiestos y helm charts y demás para que nada se rompa."
**Problem:** The audit revealed 21 references across 9 files — not 3. The "5 LOC move" was actually: (1) Go API source code reading the flattened env var (`apps/api/src/pkg/config/env.go`); (2) Docker Compose substitution (`infra/stacks/apps/api/compose.base.yml`); (3) Authelia Jinja template using `APPS_PLATFORM_API_EMAIL_USER` (`configuration.yml.j2:151,153,156` — for SMTP); (4) K8s overlay secrets placeholder (staging + prod); (5) Generated configmaps (staging + prod); (6) Toolkit `SecretSpec` + `SecretMapping` registry (`secrets_manager.py:318/332/346`, `k8s_secrets.py:101-104`). Authelia coupling was the surprise — moving `email_user` without re-sourcing Authelia's template would break OIDC SMTP at next reload.
**Solution:** For any "move this value" or "rename this key" refactor that touches the SSOT layer, **run a read-only consumer audit FIRST**, separate from the change itself. Cast a wide net: source code, templates (Jinja + Helm), generated outputs, Docker Compose substitutions, Ansible vars, tests, toolkit registries. Search for ALL forms of the name simultaneously: dotted path (`apps.platform.api.email_user`), flat snake_case (`email_user`), generator-flattened uppercase (`EMAIL_USER`, `APPS_PLATFORM_API_EMAIL_USER`), and any template `{{ ... }}` variants. Output a table of `file:line → reference form → breakage risk`. Decide PR structure FROM the audit, not the initial estimate. In this case, the audit recommended 3 sequenced PRs (smallest blast radius first: `beehiiv_pub_id` no-coupling → `email_from` no-coupling → `email_user` Authelia-coupled last) rather than one big-bang PR. The audit itself is ~10 minutes of grep; the cost of skipping it is a regression discovered post-merge.
**Tags:** `#ssot` `#refactor` `#process` `#patterns`

### [2026-05-23] Always `git pull` master before `make apply-secrets ENV=prod` — toolkit code runs from local checkout
**Context:** SSOT-012 PR #3 (#210) merge → validation flow. Ran `make apply-secrets ENV=prod` immediately after PR merge. The local master had not been re-pulled since the merge; an earlier `git pull` (pre-merge) returned "Already up to date" so I assumed local was current. It wasn't.
**Problem:** The toolkit (`toolkit/features/k8s_secrets.py`) runs from the local checkout's Python — whatever code is in the working tree IS the source of truth for the apply. Local master was at `6a4ef78` (pre-#210); origin/master had advanced to `094af52`. The apply used the OLD `SECRET_MAPPING` (still mapping `EMAIL_PASS` + `EMAIL_USER`), producing a K8s Secret with the OLD keys. The pods that just restarted to pick up the NEW ConfigMap (which has `INFRA_SMTP_*`) would have been crash-looping looking for `INFRA_SMTP_PASS` that wasn't in the Secret. Caught by `kubectl get secret api-secrets -o jsonpath='{.data}'` showing old keys, NOT by `make apply-secrets`'s success message (which only reports kubectl apply success, not "the keys I just applied match the latest master").
**Solution:** Three rules going forward: (1) Always `git pull` master before `make apply-secrets ENV=prod` — even if you just pulled. Especially after a merge to master, the auto-merge may have happened seconds after your last pull. (2) After `make apply-secrets`, verify the Secret keys with `kubectl get secret <name> -n kubelab -o jsonpath='{.data}' | python3 -c "import json,sys; print(sorted(json.load(sys.stdin).keys()))"`. The toolkit's success message only tells you kubectl didn't error, NOT that the apply matched the latest catalog. (3) Consider extending the toolkit `apply-secrets` to print `[INFO] toolkit at SHA <X> (master at <Y>) → applying N secrets` so the version mismatch is visible without manual verify. Captured during validation of SSOT-012 PR #3 — would have caused a prod outage if I'd done apply→restart without the explicit key verification step.
**Tags:** `#secrets` `#gitops` `#process` `#patterns`

### [2026-05-25] SSOT consolidation: category-inference by YAML position beats an explicit `category:` field
**Context:** SSOT-014a needed a per-category default for `ssh_user` (6 homelab nodes → "manu", 2 cloud nodes → "deployer"). Initial proposal had each node carry a `category: homelab|cloud` field so generators could group them. Alternative considered: infer category from the YAML structural position (under `networking.vps`/`networking.aws` → cloud; under `networking.nodes.*` → homelab).
**Problem:** Adding a `category:` field is schema overhead with zero discriminative value — the position in YAML already encodes the same information. Two declaration sites per node (position + category) invite future drift ("node moved to a different section but its category field wasn't updated"). The "category" was never really a property of the node — it was a property of the *bucket* the node lives in.
**Solution:** Use YAML position as the category signal. Generator (`generator_ansible.py:_resolve_ssh_user`) takes `category` as an arg passed by the calling loop — the loops over `networking.vps` / `networking.aws` / `networking.nodes.*` already know which bucket they're iterating, so they pass the right value at the call site. Per-node `ssh_user` override remains supported (unused today, free for future). Zero new schema fields, zero new tests for category drift. Lesson generalizes: before adding a discriminator field to a list of dicts, check if the list's *containing key* already encodes the discriminator — if it does, the field is duplication. Shipped in PR #218.
**Tags:** `#ssot` `#schema-design` `#ansible` `#ssot-014a`

### [2026-05-25] Loader-injection vs explicit-fallback: trade-off SSOT cleanliness vs grep-ability
**Context:** SSOT-014c had to derive 3 fields (`edge.traefik.acme_email`, `uptime_kuma.admin_email`, Authelia admin user email) from one SSOT (`apps.contact.email`). Two implementation approaches considered: (a) explicit fallback at each consumer site (`config.X | default(config.apps.contact.email, true)` in Jinja + `field or contact_email` in Python — repeated at ~6 call sites across Ansible playbooks and toolkit code); (b) loader injection — the config loader (`configuration.py:get_merged_config`) post-processes the merged config to fill empty fields from the SSOT. Consumer code unchanged.
**Problem:** Both achieve the SSOT goal (single declaration). Approach (a) is grep-friendly — reading the consumer code, you SEE the fallback. Approach (b) is consumer-friendly — adding a new derivation later (e.g., `notifier.from_email`) is one helper edit, not 6 consumer-site touches. But (b) introduces "magic" — a reader of `common.yaml` may not see why `edge.traefik.acme_email` is non-empty at runtime when removed from the file. Risk: future debugging confusion ("where does this value come from?").
**Solution:** Chose (b) loader injection because: (1) the project pattern (ADR-036 `infra.<service>.*` namespace) already establishes "config loader is allowed to derive cross-section values"; (2) consumer paths (`config.edge.traefik.acme_email` etc.) are spec interfaces consumed by Ansible/generators/K8s manifests — changing them is a much bigger blast than tucking the derivation in the loader; (3) **explicit documentation at TWO points neutralizes the "magic" risk** — inline comment in common.yaml at `apps.contact.email` listing the derived paths, and a docstring on `_inject_contact_email_derivations` mirroring the same list. Plus: 4 new regression tests that assert each derivation works (prevent silent loss of the helper in future refactors). Lesson generalizes: loader-injection patterns are professional iff (a) the injected fields are well-documented in BOTH the SSOT declaration site and the helper, and (b) regression tests enforce the derivation. Without those, prefer explicit fallback — debug cost dominates. Shipped in PR #220.
**Tags:** `#ssot` `#config` `#patterns` `#ssot-014c`

### [2026-05-25] Static registries (catalogs) tracking SSOT values need explicit lockstep markers
**Context:** Master plan SSOT-014 Phase B renamed `apps.auth.admin_username` from "manu" to "operator". The SOPS hash key was renamed in lockstep: `users_manu_password_hash` → `users_operator_password_hash`. Runtime read (`k8s_secrets._build_users_database`) resolves the resolved username via SSOT-014b's `is_admin` flag — works correctly. **Codex P1 review on PR #221 caught**: `SECRET_CATALOG` in `secrets_manager.py:121` still hardcoded `users_manu_password_hash`. `toolkit secrets audit/init/rotation` workflows would have silently targeted the dead key while runtime worked fine — admin password maintenance would have been silently ineffective.
**Problem:** A static Python registry that tracks an SSOT-derived value has no compile-time link to the SSOT — when the SSOT changes, the registry doesn't follow automatically. The grep for the rename FOUND the SOPS occurrence (`*.enc.yaml`) but not the Python catalog because the SOPS files are encrypted (not text-searchable without decrypt). Runtime tests passed because they exercise the runtime read path, NOT the catalog read path. Bug was invisible to the entire local test/drift-check loop — only catalog-consuming workflows (audit, rotation) would have surfaced it, and those weren't run in the smoke test.
**Solution:** Two patterns: (1) **For each SSOT-tracked entry in a static catalog, add an inline comment naming the SSOT and explicitly flagging the lockstep requirement** (`# Tracks apps.auth.admin_username SSOT — MUST be updated in lockstep on every rename`). This makes the dependency greppable for the next rename. (2) **Future refactor candidate**: derive the `key_path` dynamically from the SSOT at catalog-build time (`key_path=f"{_AUTH}.users_{admin_username}_password_hash"`), eliminating the manual lockstep. Tracked as future ticket. Cross-cutting lesson: **runtime tests do NOT cover catalog-consuming workflows**. If a value lives in a catalog AND is read at runtime via a different path, the smoke test alone is insufficient — explicitly exercise `audit`/`init`/`rotation` paths post-rename. Hotfix shipped in PR #222.
**Tags:** `#ssot` `#secrets` `#catalogs` `#testing` `#ssot-014b` `#codex-review`

### [2026-05-25] Kubernetes `subPath` mounts freeze content — silently breaks app-level watch and live Secret updates
**Context:** Phase B prod smoke (`make deploy-k8s ENV=prod`) updated the `authelia-users` K8s Secret to contain the renamed admin (`operator` instead of `manu`). Authelia config had `authentication_backend.file.watch: true` — designed precisely so users_database changes propagate without restart. But after deploy, Authelia kept serving the cached `manu` user. Pod AGE was 47h (no rotation), and the only options on the table were ad-hoc `kubectl rollout restart` (violating `feedback_no_manual_kubectl.md`) or a `secretGenerator` hash-suffix refactor (overkill for this case).
**Problem:** The mount used `subPath: users_database.yml`. **Kubernetes does not propagate Secret/ConfigMap updates to volumes mounted with `subPath`** — the file is frozen at mount time. This is a documented K8s limitation (https://kubernetes.io/docs/concepts/storage/volumes/#subpath) but easy to miss because: (1) the Secret IS updated in etcd / `kubectl get secret` shows new content; (2) `watch: true` works perfectly when the file changes — but the file never changes from the pod's filesystem perspective; (3) the symptom (cached value) looks like an app-level cache problem, not a mount problem. False root-cause hypotheses (Authelia cache, in-memory store, missing reload signal) waste time. The real diagnosis requires recognizing that the mount strategy itself is the bug.
**Solution:** **Mount the Secret as a directory** (no `subPath`). For a Secret with a single key `users_database.yml` mounted at `/config/users`, K8s materializes `/config/users/users_database.yml` and DOES refresh on update (~60s mount sync). Authelia config `path:` adjusted to the new location. The deploy that introduces this change causes ONE final rolling restart (deployment spec changes — mountPath + path); after that, every future `users_database` change propagates zero-downtime. Generalizes to any (Secret|ConfigMap) × app-with-file-watch combo: **if the data is meant to evolve at runtime, mount the volume as a directory, never with subPath**. Reserve `subPath` for truly static config that's tied to the deploy lifecycle (e.g., immutable scripts shipped with the image). Shipped in PR #224. Tracked follow-up: `SECRET-RELOAD-001a` (audit other subPath mounts) + `SECRET-RELOAD-001c` (ADR-039 reload-policy hierarchy: app-watch > directory mount > hash-suffix > Reloader > manual restart).
**Tags:** `#k8s` `#secrets` `#mounts` `#authelia` `#gotcha` `#secret-reload-001`

### [2026-05-30] OIDC secret has two consumer shapes — verify per delivery mechanism, not uniformly
**Context:** Designing ADR-040 (OIDC client-secret lifecycle) and OIDC-DRIFT-001 (token round-trip verification in configure-oidc). The instinct was to treat "the consumer side" of the OIDC secret as one thing that DRIFT-001's token round-trip would cover.
**Problem:** The OIDC secret reaches consumers via THREE structurally different mechanisms (updated 2026-05-30 after Codex P2 on PR #233 — initial draft said two), and neither a single verifier nor a single propagation step covers all of them. (1) Gitea: pushed imperatively into SQLite via `gitea admin auth update-oauth` (propagate: `configure-oidc`; verify: DRIFT-001 token round-trip). (2) MinIO/Grafana: env var from a K8s Secret, Path 1 (propagate: `apply-secrets`+restart; verify: OIDC-E2E-001). (3) Argo CD: Helm `--set configs.secret.extra.oidc.authelia.clientSecret` via `make deploy-argocd`, sourced from COMMON SOPS not per-env (propagate: `deploy-argocd`; verify: OIDC-E2E-001). Grouping consumers by what they are NOT (e.g. "not admin-API → env-var") put Argo CD in the wrong bucket; group by PROPAGATION mechanism instead. Gitea: pushed imperatively into its SQLite OAuth source via `gitea admin auth update-oauth` — verifiable by configure-oidc's token round-trip. MinIO/Grafana/Argo CD: delivered declaratively as an env var from a K8s Secret (ADR-038 Path 1, e.g. MINIO_IDENTITY_OPENID_CLIENT_SECRET) — configure-oidc NEVER runs for them, so DRIFT-001 says nothing about them. Describing consumer verification as "shipped/covers all consumers" would let OIDC-SYNC-002 be built to "reuse DRIFT-001" while stale MinIO/Grafana/ArgoCD secrets pass silently — the exact drift the work was meant to kill. (Caught by Codex P2 on PR #232.)
**Solution:** Scope every verification claim to its delivery mechanism. admin-API consumer (Gitea) -> token round-trip (DRIFT-001, shipped #231). env-var consumers (MinIO/Grafana/ArgoCD) -> programmatic OIDC flow test per client (OIDC-E2E-001, still required — they are UNVERIFIED until it lands). Invariant: no OIDC operation reports success for a consumer it cannot actually verify; an unverifiable consumer is reported as a gap, never green. Recorded in ADR-040; OIDC-E2E-001 reclassified required (not optional); new ticket PROVIDER-GEN-001 (fold argon2 hash gen into Authelia config render, retire sync_oidc_hashes). General principle: when a value is delivered by N different mechanisms, it needs N propagation steps and the right verifier per mechanism — "the consumer side" is rarely one thing, and Codex needed two rounds (PR #232 two-shapes, PR #233 three-shapes) to fully tease the categories apart. Categorize by HOW the value propagates, never by what it is not.
**Tags:** `#oidc` `#authelia` `#adr` `#verification` `#secret-lifecycle` `#kubelab`

### [2026-05-30] Codex adversarial PR review caught 4 real defects across the OIDC sprint — bias toward verification over self-trust
**Context:** Five-PR OIDC session (#229 SYNC-001, #230 SYNC-001b, #231 DRIFT-001, #232/#233 ADR-040). Codex (chatgpt-codex-connector bot) reviews every PR on this repo.
**Problem:** Codex flagged 4 distinct P2 issues, 3 of them in code/docs I had just written and believed correct: (1) #229 fixed path-drift in only one of two duplicated path constants — _get_oidc_output_files in cli/sync.py still pointed at the old files, so --check compared/restored the wrong files (#230 fixed). (2) #231 classify_token_response returned PASS for any JSON lacking invalid_client — an ingress/proxy JSON 404/403/502 would falsely report the secret matches; needed a 3rd INCONCLUSIVE verdict (fixed in #231). (3) #232 ADR over-claimed consumer verification as covering all consumers when DRIFT-001 only covers Gitea (#233 fixed). Each was a real latent bug invisible to my own tests as written — my tests covered what I designed them to cover, not the gap.
**Solution:** Treat adversarial machine review as a first-class part of the loop, not a formality: every Codex P2 this session was legitimate and worth a fix or follow-up PR. Reinforces the recurring KubeLab pattern (SSOT-019, OIDC auth_method, 22 orphan CMs): tests/claims cover what you design to cover; latent bugs hide where no test or no reviewer reaches. Concrete reinforcement for OIDC-E2E-001 (programmatic OIDC flow tests in CI) — it is the standing verifier that would catch this class before a human/bot has to. Practice: after writing a fix, ask "what second copy / what unhandled response / what unverified consumer did I just NOT cover?" before claiming done.
**Tags:** `#code-review` `#codex` `#verification` `#process` `#kubelab`

### [2026-05-31] Headscale policy check is syntax-only until v0.29 — don't base ACL rollout safety on the tests block in v0.28
**Context:** Designing ADR-041 (tag-based Headscale ACL for an agent fleet) on a SINGLE production control plane (Headscale v0.28.0, no staging). The rollout-safety argument leaned on the policy `tests` block (reachability assertions evaluated at apply/reload) to de-risk the deny-by-default flip.
**Problem:** The premise was wrong. Verified against the Headscale CHANGELOG: `headscale policy check` exists since v0.26.0 but is SYNTAX-ONLY; evaluation of the policy `tests` block (allow/deny reachability assertions) landed only in v0.29.0. So on v0.28.0 a policy can pass `policy check` while enforcing none of the reachability assertions — leaving the single prod mesh exposed to an untested deny-by-default flip. The error was in freshly-written work believed correct; an adversarial reviewer (Codex P2 on PR #234) caught it.
**Solution:** On v0.28, get rollout safety WITHOUT the tests block: (1) `policy check` as a syntax-only CI gate; (2) permissive-first baseline (replicate current allow-all + agent rules — cannot sever an existing flow by construction); (3) external active connectivity probe after each `systemctl reload` (reload, not restart — non-disruptive and reversible), with auto-revert to the prior known-good policy on failure; (4) upgrade to v0.29.0 BEFORE the deny-by-default tightening to gain in-engine `tests`, and author the external-probe assertions so they migrate into a `tests` block on upgrade. Meta: verify version-gated feature claims against the changelog before designing safety around them; adversarial review is load-bearing even on work you just wrote and believe correct.
**Tags:** `#headscale` `#acl` `#vpn` `#adr-041` `#rollout-safety` `#versioning`

### [2026-06-14] Apprise tags only resolve in stateful mode — Option B needs `simple` mode + a mounted config, not stateless
**Context:** NOTIFY-001 / ADR-044 chose Option B for the notification fabric: Apprise (`caronc/apprise`) owns the `tag → URL` routing table and n8n only sends a tag. Criterion #1 had proven delivery with the **stateless** endpoint (`POST /notify/` with `urls=tgram://…` in the request body, `APPRISE_STATEFUL_MODE=disabled`).
**Problem:** The stateless `/notify/` endpoint does **not** accept tags — tags are meaningless without a stored config to filter against. So Option B is impossible while Apprise stays stateless; the manifest had to change. Easy to miss because the stateless path "works" for a single hard-coded URL, masking that the whole point of Option B (one POST, tag selects the channel) is unavailable until the config is persisted.
**Solution:** Set `APPRISE_STATEFUL_MODE=simple`. In `simple` mode the API maps a `{KEY}` straight to a file `/config/{KEY}.yml`, so `POST /notify/{KEY}` with `{"tag":"page","title":…,"body":…,"type":…}` resolves the tag against that file. The file (a YAML `urls:` list, each entry a quoted `tgram://bot/chat` URL → `tag:`) holds secrets, so it is rendered from SOPS by the toolkit (`_build_apprise_config`, mirroring `_build_users_database`) into the `apprise-secrets` Secret as the single key `kubelab.yml`, mounted **read-only** at `/config`. Quote each URL key — Telegram bot tokens contain a colon that otherwise breaks the YAML mapping. Generalizes: for tag-based fan-out, the router must be stateful; pick the delivery topology (who holds the URLs) before proving delivery, or criterion #1 proves the wrong path.
**Tags:** `#apprise` `#notifications` `#notify-001` `#adr-044` `#k8s` `#sops` `#gotcha`

### [2026-06-14] n8n v2 blocks `$env` in expressions by default — use a native Header Auth credential for webhook secrets
**Context:** NOTIFY-001 criterion #4 needs the `/webhook/notify` ingress to reject unauthenticated POSTs. The instinct (pure IaC) was to keep the shared secret in SOPS, inject it as an env var into the n8n pod, and compare the inbound `Authorization` header against `$env.NOTIFY_SHARED_SECRET` in an IF node — so the auth logic lives in the exported workflow JSON.
**Problem:** The deployed n8n is `n8nio/n8n:2.12.3`, and **n8n v2 ships `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` by default** — `$env` is unavailable in expressions and Code nodes. Making the `$env` approach work would require flipping that flag to `false` on the Deployment, which re-opens environment-variable access to **every** workflow and Code node in the instance — the exact attack surface n8n v2 deliberately closed. A per-feature secret check would impose a cluster-wide security regression.
**Solution:** Use n8n's **native Header Auth credential** on the Webhook node: n8n rejects a missing/wrong header with 403 automatically (covers criterion #4 with zero custom logic) and the secret lives in n8n's encrypted credential store (`N8N_ENCRYPTION_KEY`), not an env var. Keep the canonical copy in SOPS (`apps.services.automation.notify.webhook_secret`) for recovery/rotation; the credential is created once via the UI by pasting that value. Trade-off accepted: the credential is not inside the exported workflow JSON (the JSON only references it), but that beats weakening the whole instance. Generalizes: prefer the platform's own credential primitive over `$env` for per-resource secrets; check the major-version security defaults before designing around env access.
**Tags:** `#n8n` `#notifications` `#notify-001` `#adr-044` `#security` `#webhooks` `#gotcha`

### [2026-06-16] Apprise `/status` 417 → CrashLoop: stateful mode write-tests `/config`, so the SOPS config can't be a read-only mount
**Context:** Finishing NOTIFY-001 Option B — `APPRISE_STATEFUL_MODE=simple` with the SOPS-rendered routing table `kubelab.yml` mounted read-only at `/config` (the 2026-06-14 lesson above). The pod then CrashLooped: `/status` returned HTTP 417 on every probe, the liveness probe killed it (14 restarts), apprise never reached Ready, so Telegram delivery silently failed even though `POST /webhook/notify` returned 200.
**Problem:** apprise-api 1.5.0's `/status` healthcheck (`healthcheck()` in `api/utils.py`) **write-tests all three storage dirs** — `APPRISE_CONFIG_DIR` (`/config`), `APPRISE_ATTACH_DIR`, and `APPRISE_STORAGE_DIR` (defaults to `/config/store`) — via `os.makedirs`/touch. Any non-writable dir adds a `*_PERMISSION_ISSUE` and drops `"OK"` from the response `details`; `/status` returns 200 **only if** `"OK" in details`, else 417. Mounting the Secret read-only at `/config` (the whole point of Option B) makes `CONFIG_PERMISSION_ISSUE` permanent. A first fix gave the store its own writable emptyDir at `/config/store` (STORE_OK) — necessary but **not sufficient**: `/config` itself was still read-only → still 417. Confirmed against the live pod (`Expectation Failed: /status/` looping) and the upstream source, not guessed.
**Solution:** Make `/config` a writable `emptyDir` and seed it with `kubelab.yml` via an **initContainer** that copies the file out of the (still read-only) `apprise-secrets` Secret mounted at `/seed`. Reuse the app image (`caronc/apprise:1.5.0`) for the initContainer so no extra image enters the SSOT. Result: CONFIG_OK + STORE_OK + ATTACH_OK → `/status` 200, pod 1/1. Chose the initContainer over a `subPath` Secret mount (which would also keep the parent dir writable) because subPath freezes content and doesn't propagate Secret updates (2026-05-25 subPath lesson) — and we re-render from SOPS + rollout-restart anyway. Generalizes: a healthcheck that write-tests its config dir is incompatible with a read-only config mount — seed a writable dir from the secret instead of mounting the secret AS the config dir. Codified as `make notify-smoke` so this regression (and the n8n 403 auth gate) is caught reproducibly.
**Tags:** `#apprise` `#notifications` `#notify-001` `#k8s` `#healthcheck` `#initcontainer` `#gotcha`

### [2026-06-17] A service in `base/` + Argo CD selfHeal + out-of-band Secrets = silent prod degradation
**Context:** PR #670 (notification fabric) squash-merged to master. The apprise Deployment lives in `infra/k8s/base/services/apprise.yaml` (so it deploys to ALL envs), but its `apprise-secrets` Secret was catalog-marked staging-only (`envs=("staging",)`). Argo CD prod runs `selfHeal: true` (ADR-037).
**Problem:** Argo CD auto-synced the apprise *manifest* to prod, but **Secrets are applied out-of-band** by the toolkit (`make apply-secrets`, which nobody ran for prod). The pod's initContainer hit `FailedMount: secret "apprise-secrets" not found` → stuck `Init:0/1` → Argo CD reported the app *Degraded*. (prod was never *down* — apprise is internal notify — but the board went red.) The same merge introduced a second latent break: #670 moved n8n `core`→`automation`, but `k8s_secrets.py` still mapped `APPS_SERVICES_CORE_N8N_ENCRYPTION_KEY` → `apply-secrets` skipped `n8n-secrets` and exited non-zero in *every* env. And the prod n8n IngressRoute applied the `authelia` middleware to the whole host, so the `/webhook/` ingress (n8n's own Header Auth) was 303-redirected to the Authelia login page — the fabric was unreachable end-to-end in prod, invisible because staging has no Authelia on n8n.
**Solution:** Two-surface rule for any new service added to `base/`: either (a) **gate it per-env** (move to the staging overlay) until deliberately promoted, OR (b) **ensure its Secret exists in every env it deploys to BEFORE the merge** (broaden the catalog `envs`, `secrets init`/`set`, run `apply-secrets`). When promoting a notify/webhook service to a prod host fronted by Authelia, add a higher-priority `Host(...) && PathPrefix(/webhook/)` route WITHOUT the authelia middleware (the app enforces its own auth there). General invariant: **manifests propagate via Argo CD, secrets via `apply-secrets` — nothing reconciles the two**, so a service can reach prod without its secret. Surfaced the need for catalog-driven secret application (ticket). Also: a catalog ref (`CORE` vs `AUTOMATION`) silently broke `apply-secrets` because runtime tests exercise the runtime path, not the catalog-apply path (recurring SSOT-catalog lesson). Shipped in PR #672.
**Tags:** `#argocd` `#gitops` `#secrets` `#apply-secrets` `#k8s` `#authelia` `#notify-001` `#gotcha`

### [2026-06-17] `notify-smoke` false-positive: `requests` follows the Authelia 303 to a 200 login page
**Context:** Validating the notify fabric end-to-end in prod (`make notify-smoke ENV=prod`). The smoke POSTs to `/webhook/notify` with a Bearer and expects 200 for authenticated probes, 403 for the unauthenticated one. It reported `page/log: 200 (ok)` and only `unauthenticated: 200 (expected 403) FAIL`.
**Problem:** The `200 ok` on the authenticated probes was a **false positive**. The prod webhook was behind Authelia ForwardAuth, which 303-redirects every request (Bearer or not — a Bearer is not an Authelia session cookie) to `auth.kubelab.live`. `requests.post` follows redirects by default, lands on the Authelia login page (HTTP 200), and the smoke reads 200 → "ok". The two TLS warnings per probe (`n8n.kubelab.live` AND `auth.kubelab.live`) were the tell. **No message ever reached n8n or Telegram**; the smoke looked half-green while the fabric was fully broken. Confirmed with `curl --max-redirs 0` → `303, location: auth.kubelab.live/?rd=...`.
**Solution:** Diagnose status codes with redirects DISABLED when an auth proxy may sit in front (`curl --max-redirs 0`, or `requests(..., allow_redirects=False)`). Hardening candidate for `notify_smoke.py`: disable redirect-following and treat any 3xx to the auth host as a FAIL, not a pass. General rule: a probe that follows redirects cannot distinguish "backend accepted" from "auth proxy bounced me to a 200 login page"; for auth-gated endpoints assert on the FIRST response, not the final one.
**Tags:** `#notify-001` `#testing` `#smoke` `#authelia` `#http` `#false-positive` `#gotcha`

### [2026-06-19] Edge/vendor placement: statefulness is the lock-in line — and audit collisions before persisting a decision

**Context:** ADR-049 architecture session — deciding how Cloudflare Workers + S3-compatible object storage (Backblaze B2 / Cloudflare R2) fit an IDP whose brand (ADR-031) sells "escape hyperscaler lock-in" while the infra itself is the client-replicable reference architecture (ADR-042). Strong prior art existed: a price-verified `research-cloudflare-fit.md` (2026-06-11, vault) and the prod-proven Hermes age+rclone backup (Hermes ADR-004).

**Problem:** Two traps. (1) Adopting a proprietary edge runtime wholesale silently contradicts the anti-lock-in pitch the architecture is meant to demonstrate. (2) Even a thorough, price-verified research doc recommended adoptions that **collided with already-locked decisions** — CF Email Routing needs Cloudflare MX, which cannot coexist with the live Zoho MX (MAIL-001 #268); and "host mlorente.dev on Workers static" contradicts ADR-045's locked Docker→nginx→K3s pipeline and the self-hosting showcase (the site running on its own K3s IS proof-surface PS1). Verified-pricing ≠ collision-checked: an upstream analysis written in isolation does not know your locked ADRs.

**Solution:** Two reusable rules. (1) **Placement doctrine** (ADR-049 D1–D5): the blueprint names *roles* (`tier-object-store` / `tier-edge-function` / `tier-offsite`); the substrate picks *vendors*; the lock-in line is *state* — commodity S3 (R2/B2) and stateless Workers are portable and admissible (S3 even inside the blueprint), but vendor *stateful* primitives (KV / Durable Objects / D1 / Queues) stay a mental model only and never load-bearing (the knowledge plane stays self-hosted on pgvector, ADR-043); and the single platform gateway (the Go API, ADR-029/048) is never cannibalized by edge functions. (2) **Conflict audit before persisting** (Phase E of an architecture session): before writing the ADR, run an explicit collision check against installed + planned + running systems — existing ADRs, open bitácora tickets, live config — and surface it as a table. Here it caught the two collisions above and reframed a third (CF AI Gateway overlaps the IDP-026 Grafana dashboard → demoted to a free cloud-leg supplement). Corollary: prefer the operator's newer evidence over a stale paper-decision — B2 was retired (superseding the B2 legs of ADR-023/024) for Hetzner Box + R2, per the 2026-06-11 research.

**Tags:** `#architecture` `#lock-in` `#cloudflare` `#object-storage` `#blueprint-substrate` `#decision-persistence` `#conflict-audit` `#adr-049`

### [2026-06-20] Read-write Traefik config GUIs are rejected: IaC/SSOT inversion + K3s CRD-incompatible

**Context:** Evaluating "Traefik Manager" (a Flask service with a web UI that "makes Traefik much easier") for adoption into the cluster, versus relying on the existing Traefik dashboard plus the planned ADR-050 console.

**Problem:** The tool's only net-new capability is point-and-click *mutation*: it owns and writes Traefik dynamic-config YAML via the file provider (and edits static `traefik.yml`). That directly inverts kubelab doctrine — VPS Traefik config is templated from `common.yaml` by the `traefik_vps` Ansible role ("Do NOT edit VPS files manually"), and `traefik_vps/tasks/main.yml` re-templates `middlewares.yml`/`tls.yml`/`errors.yml`/per-route files unconditionally on every `make deploy-vps`. So a GUI edit is either clobbered on the next deploy (templated files) or persists as permanent untracked drift git/SSOT never sees (new files) — two distinct failure modes, both breaking `version-controlled-config > declarative > automated > manual`. Independently, the **K3s** Traefik uses `providers.kubernetesCRD` only (no file provider), so a file-provider GUI literally cannot manage the cluster instance at all. Its read/visualize value is already covered by the native dashboard (`api.dashboard=true`) and the DASH-001 cockpit that ADR-050 absorbs.

**Solution / Rule:** Reject read-write Traefik (or any infra-config) GUIs that own config files — they fight IaC-from-SSOT and create a second source of truth for middlewares already declared in HelmChartConfig/overlays. Evaluate future "make Traefik easier" tools **read-only-only**; the operator surface is the native dashboard plus the ADR-050 console (federate-not-absorb, C4), never a click-to-mutate editor. Corollary: a config GUI is only safe where config is NOT templated from SSOT — which, in kubelab, is nowhere.

**Tags:** `#traefik` `#iac` `#ssot` `#k3s` `#crd` `#adr-050` `#tooling-rejection` `#gotcha`

### [2026-06-22] `make fetch-kubeconfig` from a non-admin Windows box fails silently from PowerShell — ssh-agent in Git Bash is mandatory

**Context:** TOOL-015 live smoke from EGW-LEN029 (corporate non-admin Windows, no native Tailscale). The toolkit's `fetch-kubeconfig` command auto-falls back to a transient ts-bridge SSH tunnel when the direct alias (mesh IP) is unreachable. First run was from PowerShell; it printed "Connection closed by 127.0.0.1 port N" and exited non-zero. The tunnel was up (ts-bridge had registered on Headscale); the failure was not a connectivity problem.

**Problem:** `make fetch-kubeconfig` in PowerShell invokes `ssh` with a passphrase-protected key. On a non-admin Windows box, the `ssh-agent` Windows Service is **Disabled** (enabling it requires admin). Without an agent, `ssh` must prompt for the passphrase interactively. But `fetch_kubeconfig` wraps the SSH call in `subprocess.run(capture_output=True)` — stdout and stderr are redirected, and the passphrase prompt never reaches the terminal. The user sees nothing; `ssh` sees a blank passphrase; the server sends "Connection closed" (not "Permission denied"), which is a connect-failure pattern and triggers the tunnel fallback, which also fails for the same reason. Neither error message points at passphrase auth as the root cause. Identical symptom could be confused with ts-bridge not routing correctly (wrong target, bad key, firewall), wasting diagnostic time.

**Solution:** Run `make fetch-kubeconfig` (and all kubelab SSH-based toolkit commands) from **Git Bash**, not PowerShell. Git Bash ships its own OpenSSH and `ssh-agent`. Load the agent once per shell session before the first toolkit call:

```bash
eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_ed25519   # one passphrase prompt
make fetch-kubeconfig ENV=staging
```

The agent stays alive for the shell session, so `make connect` + `kubectl get ns` can follow immediately without a re-prompt. **PowerShell works only if** the Windows SSH Agent service is enabled (requires admin) and the key is added to it. The Git Bash agent does NOT propagate to PowerShell (they are separate processes), and vice versa.

**Diagnostic tell:** `_is_connect_failure(255, "Connection closed by 127.0.0.1 ...")` returns True (exit 255 + connect-error substring), so the fallback fires again, masking the auth root cause. If the tunnel fetch ALSO closes the connection, suspect passphrase/agent before suspect ts-bridge routing. Confirm with `ssh -v -p <tunnel_port> <user>@127.0.0.1` — it will show "Authentications that can continue: publickey" and then "Disconnected: No supported authentication methods available (server sent: publickey)" when the agent is missing.

**Tags:** `#windows` `#ssh` `#ssh-agent` `#non-admin` `#fetch-kubeconfig` `#ts-bridge` `#tool-015` `#gotcha`

### [2026-06-22] Non-ASCII glyphs (-> em-dash) in Typer/Rich CLI help/log strings crash `--help` on the Windows cp1252 console

**Context:** TOOL-014 added the `infra k8s access {connect,disconnect,status}` sub-Typer, whose help text and INFO log lines originally used the Unicode arrow (U+2192) and em-dash (U+2014) for readability (e.g. `ts-bridge <arrow> 100.64.0.11:6443`).

**Problem:** On a Windows console using the legacy `cp1252` code page, Typer/Rich render `--help` (and emit log output) through a stream encoder that cannot represent those glyphs, raising `UnicodeEncodeError` and crashing the command before it does anything. It is not a font/display glitch — it is a hard exception at encode time. Same class as the SOPS-basename portability trap: a non-portable character silently embedded in a string that only fails on one OS.

**Solution:** Keep all CLI help text and log strings ASCII-only — use `->` for the arrow and `-` for the em-dash. Reserve non-ASCII for files that are always UTF-8 (vault markdown, this `docs/`), never for strings that pass through a Typer/Rich console renderer on Windows. A quick guard: grep new CLI/log strings for non-ASCII (`[^\x00-\x7F]`) before committing.

**Tags:** `#windows` `#cp1252` `#typer` `#rich` `#cli` `#unicode` `#tool-014` `#gotcha`

### [2026-06-13] Notification routing: converge the brain, specialize the egress
**Context:** NOTIFY-001 architecture session — unifying scattered alerts/notifications (Telegram/Discord/Slack/CI/webhooks) for a solo operator who also wants the design productizable for clients.
**Problem:** Notifications scattered with no routing logic; the instinct is to either collapse everything to one channel (loses platform strengths) or adopt a heavy notification product (Novu). Also conflating one-way event routing with two-way human communication, which is the real source of the perceived chaos.
**Solution:** Separate one-way event-routing (automated, this fabric) from two-way human-comms (channel strategy — NOT routed). Converge routing to one ingress/brain by REUSING the already-running n8n; specialize egress per platform via Apprise URLs; the declarative routing-table is the productizable unit (client deploy = swap config). Adopt-vs-build flips to ADOPT when the asset already exists (inverse of ADR-005's build decision — same constraint logic, opposite answer because n8n is already deployed and the gap is cross-cutting, not single-source). Heavy notification products (Novu) only earn their place at end-user scale (preference center / in-app inbox) and attach as a delivery SINK behind n8n, never a replacement — so the low-regret choice stays forward-compatible. Caveat: n8n workflows live in n8n's DB, so true IaC needs export/import of workflow JSON; Argo carries the stateless delivery infra but not the workflow content.
**Tags:** `#architecture` `#notifications` `#n8n` `#apprise` `#homelab` `#adopt-vs-build`

### [2026-06-27] Build-once re-tag (ADR-056): read the raw staging pin, protect it from the prune, copy the manifest list

**Context:** Implementing build-once for the `api` image (DELIVERY-002) — prod semver produced by re-tagging the staging-validated `sha-<short>` instead of rebuilding from the release commit (closes the parity gap that CrashLooped the first gated promotion, #666/#679).

**Problem:** Three non-obvious traps. (1) Resolving the sha from the *merged* config surfaces the inherited `dev` from `common.yaml`, masking "staging has no validated artifact" — the resolver would happily re-tag `dev`. (2) The weekly prune janitor (`ci-cleanup.yml`) keeps only the N most-recent `sha-*` and could delete the sha a pending prod promotion still references. (3) A naive `docker pull && docker tag && push` collapses a multi-arch manifest list to a single arch.

**Solution:** (1) Read the **raw** `apps.platform.<app>.version` straight from `values/staging.yaml` and require `^sha-[0-9a-f]{7,}$` — an absent pin is an error, not a silent `dev`. (2) Thread a `protected` set through the pure `select_stale_tags`; the CLI gathers per-app sha pins from staging+prod values so a tag referenced by a committed overlay is never pruned, even outside the retention window. (3) Use `docker buildx imagetools create -t dst src` — a registry-side manifest-list copy (no QEMU, no rebuild), then assert `imagetools inspect --format '{{.Manifest.Digest}}'` equality and fail the release on mismatch.

**Rule:** Re-tag by digest, never rebuild, to ship the validated bytes. Resolve promotion sources from the raw env SSOT (absence must error, not inherit). Any janitor that prunes by recency must exempt state still referenced by committed config. `errors` (edge infra) stays on its rebuild — build-once's value is near-zero for static pages with no staging-validated artifact to lose.

**Tags:** `#delivery` `#ci-cd` `#gitops` `#build-once` `#docker` `#adr-056`

### [2026-06-27] Pick the SSOT lane by where the version lives, not by "it's a custom app" (DELIVERY-003)

**Context:** Automating the `errors` edge image tag (#776). The instinct was to treat it like api/web — add it to `toolkit deployment promote`'s per-env overlay lane.

**Problem:** That's the wrong lane. `errors` pins a *single* `edge.errors.version` in `common.yaml`, shared across all envs — structurally identical to the third-party images (`gitea`, `n8n`…) that `sync_k8s_images.py` already syncs into `base/kustomization.yaml` from common.yaml. api/web are different: their tags live *per-env* in the overlays (`apps.platform.<app>.version` in staging/prod.yaml) and ride `promote` + the K8s generator. Forcing errors onto the promote lane would have invented a per-env split it doesn't have (and the spec's "single SSOT" goal forbids).

**Solution:** Route by SSOT *location*. errors → the **sync** lane: emit it from the structured `edge.errors` keys (`{registry}/{image_name}:{version}`), delete its hardcoded `newTag`, let `sync_k8s_images` own it. `promote --app errors` writes `common.yaml` + re-syncs (env-agnostic, `--env` ignored), never touches an overlay. Note: `sync_k8s_images`'s block-replace regex stops at the `# Custom apps` comment, so web/api stay hand-pinned below while errors joins the synced block above.

**Rule:** Before automating a deploy tag, ask *where does this version live* — one shared key in common.yaml (→ sync lane, like third-party) or per-env in the overlays (→ promote lane, like api/web). The runtime (edge vs platform) is a red herring; the SSOT shape is what decides. Caveat: the drift gate covers the generator (overlays) but NOT the kustomization sync — a manual bump-without-sync isn't caught (tracked: #792).

**Tags:** `#delivery` `#ci-cd` `#ssot` `#kustomize` `#gitops` `#adr-046`

### [2026-07-07] Migrations retire code but not the docs that described the old world (docs audit)

**Context:** Full documentation audit (`docs/audits/docs-audit-2026-07-07.md`, 92 findings D1-D92). The platform went through three migrations (Proxmox→bare-metal, Compose→K3s+GitOps, Gitflow→trunk+release-please) and the code plus the *newest* docs are correct.

**Problem:** Every migration left the previous generation of docs alive and unmarked: README still described Compose prod and swapped node roles; `docs/architecture/diagram.md` drew an architecture two migrations old; `cicd.md`/`deployment.md`/`toolkit.md` taught a pipeline and CLI that no longer exist; troubleshooting kept fictional services (Portainer, Vaultwarden). The docs a newcomer reads FIRST were the most wrong, while niche recent runbooks were accurate — drift concentrates in the outer ring because nobody re-reads it after landing the migration.

**Solution:** Audit report with stable finding IDs + 4 remediation tickets (#824-#827). #824 (entry-surfaces sweep) executed: truth fixes in README/CONTRIBUTING/CLAUDE.md, retirement stubs pointing at the canonical successors, `superseded`/`historical` banners on dead runbooks.

**Rule:** A migration's definition of done must include retiring or banner-marking the docs that described the old world — same PR or a named follow-up ticket, never "later". Docs that restate SSOT data (node roles, IPs, service lists, command tables) drift by construction: reference `common.yaml`/the CLI instead of copying, or generate the table. When retiring a doc, replace it with a stub that redirects to the canonical successor so inbound links keep working.

**Tags:** `#docs` `#drift` `#ssot` `#audit` `#migrations`

### [2026-07-08] Windows CRLF/encoding bugs come in matched read+write pairs, and pytest's own capture can hide the bug you're testing for (TOOL-020)

**Context:** Fixed `toolkit sync all --check` permanently failing on Windows (process-audit P1) — CRLF writer drift plus a homepage `charmap` crash. Two more instances of the same bug class only surfaced by running the full check end-to-end on a real Windows workstation, not from unit tests alone.

**Problem:** Two traps. (1) Every unguarded `open()`/`read_text()` in the sync scripts had a write-side counterpart already suspected, but the read side stayed invisible until non-ASCII content (em-dashes, middots) already committed to the repo got silently mis-decoded under a non-UTF-8 locale (cp1252) and re-encoded as mojibake on the next write — corruption, not a crash, so it never announces itself. (2) A test asserting `sys.stdout.encoding == "utf-8"` after importing the fixed module passed even with the fix commented out, because pytest's own capture stream is already UTF-8 regardless of host OS — the test proved nothing about the real Windows-console crash it was supposed to guard.

**Solution:** For the read side, add `encoding="utf-8"` to every `open(`/`read_text(` call in the same lane the writes were fixed in — the fix search doesn't stop at `write_text()`. For the test, manufacture a real `cp1252` `io.TextIOWrapper` via monkeypatch and prove it genuinely raises `UnicodeEncodeError` before asserting the fix neutralizes it.

**Rule:** When fixing a platform-encoding bug in a script, grep the whole module for `open(`/`read_text(`/`write_text(` — the fix is rarely one-sided. When a test claims to reproduce an environment-dependent crash, verify the harness reproduces it independent of the test runner's own defaults (pytest capture, CI locale) before trusting the green — a test that cannot fail without the fix teaches nothing.

**Tags:** `#windows` `#encoding` `#utf-8` `#cp1252` `#testing` `#tdd` `#tool-020` `#gotcha`

### [2026-07-08] A base-image CVE fixed upstream doesn't need a new base image tag — `apk upgrade` at build time gets it sooner

**Context:** The `errors` image's release build failed the Trivy gate (3 HIGH CVEs in `libexpat` 2.8.1-r0, fixed upstream in 2.8.2-r0) even though `edge/errors/Dockerfile` hadn't changed — the cached `nginx:1.31-alpine` layer simply predates the distro's patch.

**Solution:** `RUN apk update && apk upgrade --no-cache` right after `FROM` pulls the patched package from Alpine's live index at build time, without waiting for the upstream base image tag to be rebuilt and republished. Verified locally: the build log shows the exact package upgrade (`libexpat (2.8.1-r0 -> 2.8.2-r0)`), and a local Trivy scan with the same severity/ignore-unfixed filters as CI reports 0 vulnerabilities.

**Rule:** A sudden Trivy failure on an unchanged Dockerfile usually means "the distro shipped a fix today", not "we introduced a regression" — check whether the flagged package already has a newer version in the base distro's own repo before assuming the code changed.

**Tags:** `#docker` `#trivy` `#cve` `#alpine` `#security` `#ci`

### [2026-07-08] `kubectl create secret | kubectl apply -f -` REPLACES the whole Secret — a partial render silently deletes keys (TOOL-018)

**Context:** Hardening K8s secret delivery (TOOL-018, #829). `_apply_single_secret` in `k8s_secrets.py` assembles a Secret from a mapping of SOPS keys → resolved values and ships it with `kubectl create secret … --dry-run=client -o yaml | kubectl apply -f -`.

**Problem:** `kubectl apply` of a Secret is a **whole-object replace of `.data`**, not a per-key merge. When the SOPS→K8s mapping only *partially* resolves (a key missing, an empty decrypt — see the TOOL-017 lesson below for how that happens), the old code still built a Secret from whatever resolved and applied it — **silently shrinking the live Secret** and dropping keys that running pods depend on. No error surfaced: the deploy "succeeded" with a truncated Secret, and the failure only shows up later as a consumer that can't find its key.

**Solution:** Fail closed — if *any* key in a mapping fails to resolve, raise before the apply, so a partial render can never overwrite a complete live Secret. This is deliberately narrow: true additive merge-semantics (patch instead of replace) is the harder problem, deferred to the SEC-SECRETS-001 capstone (#831). The pre-existing gap of a *dynamic* builder returning empty (apprise/authelia-users → empty Secret) is flagged there too, not patched blind.

**Rule:** Treat `kubectl apply -f - <Secret>` as **replace-all**: the manifest you feed it must be the *complete* desired key set, or you silently delete every key you left out. Any generator that assembles a Secret from N independent sources must fail closed on a partial resolve — never apply the subset it happened to get.

**Tags:** `#secrets` `#kubernetes` `#kubectl` `#fail-closed` `#sops` `#tool-018` `#gotcha`

### [2026-07-08] A `sops` subprocess with a bare `os.environ` passes in your shell and returns empty in CI (TOOL-017)

**Context:** TOOL-017 (#828) — wrapping every `sops` subprocess in the toolkit with `age_key_env()`, a helper that injects `SOPS_AGE_KEY_FILE` into the child process env.

**Problem:** A `sops` call launched with a **bare `os.environ`** (no explicit age key) works fine in an interactive shell that already `export`ed `SOPS_AGE_KEY_FILE` — so the unit suite and every local run go green. But in a **fresh shell or a CI runner** without that ambient export, `sops` can't locate the key and, depending on the code path, either errors or hands back an **empty decrypt** — silently yielding empty secret values. The bug is invisible precisely in the environment a developer would test in, and only bites in automation.

**Solution:** Route *every* sops invocation through `age_key_env()` (five call sites: `secrets_manager` show/set/unset, `configuration` batch-decrypt, `credentials` read-existing) so the key file is injected regardless of the ambient shell. Then add an **AST-based regression guard** that scans `toolkit/` for any `subprocess` call to `sops` using a bare `os.environ` and fails the suite — the invariant is enforced structurally, not by reviewer memory.

**Rule:** A subprocess that depends on an env var you *happen* to have exported is a latent bug — the passing local test proves nothing about a clean shell. Inject the dependency explicitly at every call site and enforce it with an AST scan (not a convention the next call site can quietly skip). "Works in my shell" ≠ "works in CI" — same failure class as the TOOL-020 encoding lesson above.

**Tags:** `#secrets` `#sops` `#age` `#subprocess` `#ci` `#ast-guard` `#tool-017` `#gotcha`

### [2026-07-09] `kubectl create secret` leaks every value into `/proc/<pid>/cmdline` — render the manifest in-process and apply over stdin (SEC-SECRETS-001)

**Context:** SEC-SECRETS-001 (#831), the capstone of the secret-delivery hardening cluster. `_apply_single_secret` in `k8s_secrets.py` shipped Secrets with `kubectl create secret generic … --from-literal=k=v … --dry-run=client -o yaml | kubectl apply -f -`.

**Problem:** Two distinct exposures. (1) `--from-literal=key=value` puts **every plaintext secret in the child process's argv**, world-readable in `/proc/<pid>/cmdline` for the life of the call and visible to any `ps` on the box — a local-user disclosure that no amount of SOPS-at-rest encryption prevents. (2) The dynamic builders (`_build_users_database`, `_build_apprise_config`) assembled their YAML by **f-string interpolation**, so a value containing a `:`, a leading `%`, or a newline (an argon2 hash, a bot token, a display name) could produce malformed or reinterpreted YAML — an injection seam in the config a service then parses as truth.

**Solution:** One delivery primitive, `_render_secret_manifest(name, namespace, data)`: build the Secret as a **dict** with base64-encoded `data`, `yaml.safe_dump` it, and hand it to `kubectl apply -f -` via **stdin** (`input=manifest`). No value ever becomes a subprocess argument. `data` + base64 is byte-equivalent to what `kubectl create secret -o yaml` emitted, so the applied object is unchanged — a pure delivery-path swap, not a semantic one. The two builders became `yaml.safe_dump(dict)` as well, so the serializer owns escaping instead of the caller. TOOL-018's fail-closed-on-partial-resolve behaviour is preserved on top.

**Rule:** Secrets belong on **stdin, never in argv** — the process table is a disclosure channel, and `--from-literal` is the idiom that walks straight into it. Equally: never build YAML that will carry a secret by string interpolation; hand a dict to `safe_dump` and let it own the escaping. Both are the same discipline — stop treating a structured, sensitive payload as text you concatenate.

**Tags:** `#secrets` `#kubernetes` `#kubectl` `#argv` `#proc` `#yaml-injection` `#safe-dump` `#sec-secrets-001` `#gotcha`

### [2026-07-09] A deploy step that warns and exits 0 is a silent failure — the exit code is the only thing the next step reads (TOOL-021)

**Context:** TOOL-021 (#838), from the process audit (P6). `infra k8s deploy` applied the manifests, then ran `kubectl rollout status … --timeout=120s` as a final check.

**Problem:** Every earlier step in the command failed closed (`raise typer.Exit(1)`), but the **rollout wait only logged a warning and returned 0**. So a deploy that left pods CrashLooping reported success. That matters precisely because nothing downstream reads the log: `make deploy-k8s && <next step>` proceeds, CI goes green, and an agent chaining on the exit code marches on over a broken cluster. The failure is loud to a human watching the terminal and completely invisible to every automated consumer.

**Solution:** Fail closed on a non-zero rollout — log the stderr, print a `make logs SVC=<name> ENV=<env>` pointer so the next step is obvious, and `raise typer.Exit(1)`. Made the **default**, not an opt-in `--strict`: a healthy deploy rolls out well inside the 120s timeout, so the only thing an opt-in flag buys is the chance to forget it. Covered by two TDD tests.

**Rule:** In any CLI meant to be chained, the **exit code is the contract** — a warning is a comment, not a signal. If a step's failure invalidates the steps after it, it must be non-zero by default; "strict mode" as an opt-in just relocates the silent failure to whoever didn't pass the flag. Audit the last step of every command specially: it's the one that most often degrades to a warning because "the real work already succeeded".

**Tags:** `#cli` `#exit-code` `#silent-failure` `#kubernetes` `#rollout` `#fail-closed` `#tool-021` `#gotcha`

### [2026-08-07] A config file with two writers can never converge — idempotence is a property of the system, not of the task (ANSIBLE-028)

**Context:** ANSIBLE-028 (#816), the `dev_node` role that provisions ace2 as a self-hosted CDE. The role wired mise activation and tmux-resurrect by injecting marked blocks into `~/.bashrc`, `~/.zshrc` and `~/.tmux.conf`. It also clones the dotfiles repo and runs its `setup-linux.sh` bootstrap.

**Problem:** Two consecutive provision passes reported `changed=2`, forever. Not flaky — *stable*, at exactly two. The dotfiles bootstrap redeploys those three rc files **wholesale on every run**, erasing whatever the role had written; the role then rewrote them on the next pass, and the cycle repeated. There is no ordering of those two tasks that converges: whoever runs last wins and the other one redoes its work next time.

The trap is that an earlier, *different* bug presented identically from outside. Initially the role wrote its block **before** the bootstrap, so the block vanished silently and the task still reported `changed`. Reordering fixed that — the block stopped disappearing — and the `changed=2` remained, which made it look like the same bug was only half-fixed. It was not: the first was a loss-of-write, the second was contention. Ordering cured one and could never cure the other.

**Solution:** Give every file exactly one owner. Ansible owns `/etc/profile.d/mise.sh` and the gitignored `*.local` seams (`~/.bashrc.local`, `~/.zshrc.local`, `~/.tmux.conf.local`); the dotfiles bootstrap owns the tracked rc files it deploys. The bash/zsh seams already existed upstream — gitignored, sourced last, never redeployed. tmux had none, so it was added upstream (`mlorentedev/dotfiles#788`). Second pass then reported `changed=0`, and stayed there even across a subsequent upstream dotfiles change (one changed pass to absorb it, then zero).

**Rule:** An Ansible task (or any provisioning step) that reports `changed` on **every** run is almost always contending for a file with another writer — look for the second writer before you touch the task's logic. The fix is ownership, not ordering. Corollary, and the more expensive half: **one green pass proves nothing about idempotence — the second pass is the test**, and the criterion must read the *task list*, not just the aggregate `changed=` count, because a task whose `changed_when` is derived from something else (a git clone's state, a marker file) can mask a non-converging step inside an otherwise clean total.

**Tags:** `#ansible` `#idempotence` `#dotfiles` `#config-ownership` `#provisioning` `#ansible-028` `#gotcha`

### [2026-08-07] Ansible has no native Windows control node — provision from Linux, and budget for the controller's own toolchain (ANSIBLE-028)

**Context:** ANSIBLE-028 (#816) sat with its runtime acceptance criteria `pending` for ten days. The role was written and statically verified, but no provision run had happened because the dev workstation was Windows.

**Problem:** This is not a missing package or a configuration gap — Ansible's control node requires POSIX primitives (`os.fork()`, ptys, a native `ssh`) that Windows does not provide. `ansible-playbook` is not shipped for native Windows and will not be. Windows is fully supported as a *target*, which is what makes the limitation easy to misread. The practical cost was ten days of a spec sitting at "written but unproven", with five real defects latent in it — every one of which needed a live target and a real remote repo to surface, and none of which lint, unit tests, or code review would have caught.

**Solution:** Run the controller on a Linux box already on the mesh (`msi`, ansible-core 2.20.0) against a powered-on ace2. Note that the bastion transport (TOOL-016 / #818) was **not** needed: from a mesh controller the default transport reaches the target directly, so the "merge the bastion PR first" ordering assumed earlier did not apply.

**Rule:** Provision from a Linux controller — a homelab box on the target's LAN, or WSL. But WSL is not free: it needs its own `ansible`, `sops` and `tailscale` toolchain, plus the SOPS key and mesh membership, before it can run a single playbook. Budget that as real setup work rather than assuming the dev box can stand in. More generally: when a spec's runtime criteria are blocked on an environment you don't have, that blockage is itself the risk — keep the criteria `pending` and say so, rather than marking them verified from static inspection.

**Tags:** `#ansible` `#control-node` `#windows` `#wsl` `#provisioning` `#ansible-028` `#gotcha`

### [2026-08-08] Two merge implementations over the same files meant `common.enc.yaml` had two different meanings (ANSIBLE-033)

**Context:** The ace2 dev-node PAT lives in `common.enc.yaml`. Ansible provisioned it correctly; `toolkit secrets audit` reported it missing.

**Problem:** `ConfigurationManager._deep_update` guarded its recursive branch with `isinstance(value, dict) and value`. An empty mapping is **falsy**, so it fell to the assignment branch and *replaced* the base subtree instead of recursing into it. Moving the token to `common` had left a `dev_node: {}` behind in `staging.enc.yaml`, and that empty mapping erased the common subtree — but only on the toolkit side. The playbooks merge the same two files with `combine(recursive=True)`, which treats an empty mapping as a Mapping and recurses, preserving it. The same two files therefore meant different things depending on which tool read them.

The dangerous half was not the read. `credentials.py` `_promote_shared_secrets` runs the same merge into the decrypted `common.enc.yaml` and **re-encrypts the result to disk**, and `_partition_secrets` copies subtrees verbatim from a `SHARED_NESTED` path — `apps.services.automation`, exactly where the token lives. One `credentials generate` run would have silently and permanently destroyed the credential. A broken read is recoverable by re-running the tool; that write is not.

**Solution:** Recurse whenever the override is a mapping, into the base only when that is a mapping too — matching Ansible's `merge_hash` on all four edge cases (empty mapping, mapping-over-scalar, scalar-over-mapping, explicit null). The same guard also fixed a latent `TypeError` where a mapping override onto a scalar base recursed *into the scalar*. Blast radius was enumerated rather than assumed: a redacted path→hash image of the merged config for all three environments showed exactly two deltas, and the generated staging manifests were byte-identical before and after.

**Rule:** When two tools consume the same configuration files, their merge semantics are a **contract**, and an untested contract drifts. Pin it with tests that assert parity against the reference implementation, not just against your own intent. And when auditing a merge bug, find every call site before judging severity — a merge that only ever fed reads is an inconvenience; the one that feeds an encrypt-and-write is data loss.

**Tags:** `#sops` `#config-merge` `#ansible` `#toolkit` `#data-loss` `#ansible-033` `#gotcha`

### [2026-08-08] When you cannot own the file, verify it — a guarded write is not a fallback (ANSIBLE-033)

**Context:** The `dev_node` role ran `gh auth setup-git` so one PAT would serve both `gh` and git-over-HTTPS. Follows directly from the ANSIBLE-028 one-writer-per-file lesson above.

**Problem:** `gh auth setup-git` writes `~/.gitconfig` — a file the dotfiles bootstrap, run *earlier in the same role*, redeploys wholesale every pass. The task looked harmless because it never fired: the helper was always already present, so the idempotence guard skipped it. Deleting the helper by hand and re-provisioning revealed why — the bootstrap restored it **mid-run**, before the role's own check executed. So the role can never durably write that file at all, and in the one scenario where the task would have fired (dotfiles dropping the helper), it would have churned forever: bootstrap wipes, `setup-git` rewrites, `changed` every pass. The "guarded fallback" was a churn generator wearing a safety guard.

**Solution:** Split ownership by concern. The token is the role's; the credential helper is dotfiles'. The role asserts the wiring and fails loudly with a message naming the owner, instead of writing a file it does not own. The `~/.gitconfig.local` seam alternative was rejected: no such seam exists, and creating one is a change to the dotfiles repo (the `dotfiles#788` precedent), not to this one.

**Rule:** One-writer-per-file has a second half nobody states: when the file's owner is someone else, the answer is **verify, don't write** — assert the contract and fail loudly, naming who owns it. Also: a task that never fires is not automatically safe. Test the branch you think is dead, because "it always skips" and "it would churn if it ran" look identical from a green pipeline.

**Tags:** `#ansible` `#idempotence` `#config-ownership` `#dotfiles` `#ansible-033` `#gotcha`

### [2026-08-08] A tag asymmetry made the play report success while delivering no credential — and the acceptance probe agreed (ANSIBLE-033)

**Context:** `make provision NODE=ace2 ENV=staging TAGS=dev_node` — the exact command the spec's acceptance criterion prescribes.

**Problem:** In every `provision-*.yml`, the config-loading `pre_tasks` carry `tags: [always]` but the three SOPS decryption tasks carry no tags. A `TAGS=` run therefore skipped decryption and left `secrets` undefined — while `config` stayed fully populated, which is precisely what made it look healthy. The role var used `| default('')` (deliberately, so an operator without the secret gets a node with no identity rather than a failed play), so the token silently became the empty string and all four identity tasks skipped. The play reported `ok=29 changed=2 failed=0`.

Worse, the acceptance probe passed. It asserted convergence — a second pass reporting `changed=0` — which cannot distinguish "converged with the credential in place" from "converged because every task that would install it was skipped". A criterion claiming *delivery* was verified by a command that only measured *stability*.

**Solution:** Tag the decryption tasks `always`, matching the config loads directly above them. Then strengthen the probe to also assert the role saw a non-empty token — keyed on the token *read* rather than the login, because the login legitimately skips on an already-converged node while the read is guarded only by the token being non-empty. The same untagged pattern in the other playbooks is tracked separately (#893); those fail loudly instead of silently, because their secret vars carry no `default`.

**Rule:** A `default` on a value sourced from a secret store converts a loud failure into a silent one — pair it with something that proves the value actually arrived. And when writing an acceptance command, ask what *else* could make it exit 0: if the answer includes "the feature was never installed", the command measures the wrong thing. Convergence is not delivery.

**Tags:** `#ansible` `#sops` `#tags` `#verification` `#false-green` `#ansible-033` `#gotcha`

### [2026-08-08] A blocked probe hides every defect downstream of where it stops (ANSIBLE-033)

**Context:** ANSIBLE-033's f2 probe — clone a private repo, commit, push, open a PR, all from a tmux session on ace2 under the dev-node PAT. It had one known blocker: the fixture, `go-dsa-sample`, was archived and therefore read-only.

**Problem:** Two defects, stacked, and the first made the second invisible.

The fixture was chosen for being *dormant*, so an acceptance branch could not collide with real work. That criterion turned out to select for archived repositories — dormant is what archiving produces. The push returned `403 This repository was archived`, which is indistinguishable from a permissions failure and sends you auditing the credential.

Replacing the fixture let the probe reach step 4 for the first time, where `gh pr create` aborted with *"you must first push the current branch to a remote"* — immediately after a `git push -u origin HEAD` that had returned 0. `git clone --depth 1` implies `--single-branch`, which pins the fetch refspec to the default branch. The push therefore writes `branch.<name>.remote` and `branch.<name>.merge`, but nothing can create `refs/remotes/origin/<branch>` because no refspec covers it. `@{upstream}` fails with *"not stored as a remote-tracking branch"*, and `gh` reads that as an unpushed branch. The `-u` had not lied about the config, only about the ref.

Both defects had been in the probe since it was written. The first one is why nobody knew about the second, and each round trip to discover one cost powering on an on-demand node.

**Solution:** A purpose-built private fixture (`kubelab-devnode-fixture`) rather than a borrowed one — of 41 private repos, 36 were archived and the other 5 were in active use, one of them the vault. Being permanent, it also turns post-rotation re-verification into a command instead of a manual step. For the PR, pass `--head` explicitly and skip the inference; widening the clone would trade away a real property of the probe for nothing. The corrected probe was then run end to end **from the workstation under the operator's own token** — enough to prove the flow, explicitly not enough to satisfy AC2, which needs the node and the dev-node PAT.

**Rule:** When a probe is blocked at step N, treat steps N+1 onward as **unverified, not working** — a green record above the blockage says nothing about what is below it. Where the environment is expensive to reach (an on-demand node, a physical device), buy down that cost first: run the probe against a local stand-in to shake out flow defects, then spend the real environment on the one axis the stand-in cannot exercise. And when picking a test fixture, state the property you actually need — *writable* — instead of a proxy like *dormant*, which quietly selected for the opposite.

**Tags:** `#verification` `#probes` `#git` `#github-cli` `#shallow-clone` `#test-fixtures` `#ansible-033` `#gotcha`

### [2026-08-09] `startingDeadlineSeconds` is not about catching up a late run — it is what stops a CronJob from retiring itself (IDP-032)

**Context:** The prod PVC backup CronJob (`infra/k8s/overlays/prod/backup.yaml`, ADR-024) set `schedule`, `concurrencyPolicy: Forbid` and both history limits, but left `startingDeadlineSeconds` unset. A CKA-practices self-audit flagged it as a minor omission about missed-schedule catch-up.

**Problem:** The framing undersold it. Catch-up is the visible half: without the field, a run missed because the controller was down is skipped until tomorrow — annoying, survivable, and on a daily backup you would probably notice.

The invisible half is the one that bites. With the field unset, the CronJob controller counts missed schedules against an unbounded window. At **100** accumulated misses it stops scheduling the CronJob *permanently* and reports that only as an event on the object. Nothing crashes, no pod fails, no alert fires on a workload that simply never runs again. On an infrastructure whose homelab half is deliberately powered off between sessions, accumulating missed schedules is the normal operating mode, not an anomaly — so the counter is a live risk, not a theoretical one. The failure mode of a backup system is silence, and this one is silent by construction.

**Solution:** `startingDeadlineSeconds: 3600` on the CronJob spec. The value bounds the miss-counting window and lets a run missed at 03:00 still start by 04:00, which leaves the existing `activeDeadlineSeconds: 1800` room to finish inside the same maintenance window. The comment in the manifest records the reasoning, because the field reads like a nicety and the next person to touch it needs to know it is not.

Verification was the render, not the file: `kubectl kustomize infra/k8s/overlays/prod` confirms the field survives into the built manifest. Editing an overlay proves nothing on its own — a patch elsewhere in the overlay can strip a field silently, and the diff still looks correct.

**Rule:** For any scheduled workload, ask what happens after N consecutive misses, not just after one. Controllers that give up quietly are worse than controllers that fail loudly, and "the job did not run" produces no signal unless something is watching for absence. Corollary for Kustomize: the unit of verification is the **built output**, never the source file you edited.

**Tags:** `#kubernetes` `#cronjob` `#backup` `#kustomize` `#silent-failure` `#idp-032` `#gotcha`

### [2026-08-09] The same linter behind two gates in different environments is two linters — and only the lenient one was running (CI-GATE-005/006)

**Context:** Rebasing #865 and re-running the local gate showed `make type` failing on `toolkit/features/notify_smoke.py` — missing `types-requests` stubs. The obvious suspicion was the rebase, since master had just moved mypy `^2.1 → ^2.3`. Checking out `master` and running `make type` there reproduced the identical error, so it was not the rebase and not the bump. It had been red for a while: the `requests` import dates from #670.

**Problem:** mypy runs behind two gates in this repo, and they do not agree.

| Gate | Environment | `types-requests` | Extra args |
| --- | --- | --- | --- |
| `make type` | the project venv (`pyproject.toml`) | absent | none |
| pre-commit `mirrors-mypy` | its own isolated env | present via `additional_dependencies` | `--ignore-missing-imports` |

`[tool.mypy]` overrides `ignore_missing_imports` for `sh`, `yaml`, `argon2`, `uptime_kuma_api` — not `requests`. So the venv had neither the stubs nor a suppression, while pre-commit had both. Every commit passed; the documented pre-push gate had been failing on an untouched tree the whole time.

The second, larger question is why nobody tripped over it. Because nothing ever ran it: `.github/workflows/ci.yml` has four jobs — branch-name regex, `yamllint` on the workflow dir, `make -n help`, and the two path-filtered app pipelines. **No CI job runs pytest, ruff, or mypy over `toolkit/`.** The PR that surfaced this changes only toolkit code, and all nine of its checks were green while its test suite never executed in CI. The first failure was invisible because the only gate that would have caught it does not exist.

**Solution:** Add `types-requests` to the dev dependency group (#903) so the venv matches what pre-commit already supplies. Real stubs rather than widening the `ignore_missing_imports` list — the calls then get type-checked instead of skipped, and they pass, so the annotations were correct all along and merely unverified. `make check` now completes all four legs; it had been aborting at `type` and never reaching `test` or `validate-sync`. The missing CI gate is filed separately as CI-GATE-006 because choosing what CI should run is a design call, not a fix.

**Rule:** When the same tool is configured in two places, treat them as two tools until proven identical — an isolated hook environment with its own dependency list and its own flags is not the environment your Makefile uses, and the discrepancy surfaces as "works for me". Corollary: a gate whose failure nothing observes will eventually be red, so before trusting a green check, ask which command it actually ran. Green checks on a PR are evidence about the checks that ran, not about the code.

**Tags:** `#mypy` `#pre-commit` `#ci` `#tooling` `#silent-failure` `#ci-gate-005` `#ci-gate-006` `#gotcha`

### [2026-08-09] A monitor that is green for prod and red for staging is reporting on its own resolver, not on your infrastructure (MON-001)

**Context:** Every `*.staging.kubelab.live` monitor in Uptime Kuma read DOWN. Staging is on `ace1`, an on-demand homelab node, so the first available story — the homelab is powered off — fitted perfectly and was wrong. `toolkit infra headscale probe` passed end to end: `ace1` SSH, `hub->spoke :6443 (staging)`, the RPi4 subnet route, the intra-K3s spoke API. The infrastructure being monitored was entirely up.

**Problem:** The RPi3 host resolved `api.staging.kubelab.live` to `100.64.0.11` correctly, through the Headscale split-DNS route to the RPi4. The `uptime-kuma` container, on the same host, returned `ENOTFOUND`.

Docker had declined to inherit the host's MagicDNS resolver and substituted its own upstreams, which its generated resolv.conf records in a comment that is easy to read past:

```
nameserver 127.0.0.11
# ExtServers: [host(75.75.75.75) host(75.75.76.76) ...]
```

Those are the ISP's resolvers. Staging DNS is VPN-only and has no public record, so every staging FQDN failed — while prod monitors stayed green, because prod resolves publicly through Cloudflare. That asymmetry is the whole trap: a resolver defect that only affects names with no public record is *indistinguishable from a real outage of exactly those services*, and it points the investigation at the infrastructure instead of at the prober.

The repo already carried a gotcha about Docker not inheriting host DNS, written for the systemd-resolved `127.0.0.53` stub, prescribing `dns: [1.1.1.1, 8.8.8.8]`. Applying it here would have been a plausible-looking change that fixed nothing: those resolvers cannot see staging either.

**Solution:** Pin the container to MagicDNS (`100.100.100.100`) via the `docker_dns_servers` idiom the `headscale` role already established, keeping a public resolver as a second entry so prod monitors survive Tailscale being down on the node. The CLAUDE.md gotcha was rewritten to separate the two cases and name the `# ExtServers:` line as the way to tell them apart.

One near-miss is worth recording. The first attempt to verify the fix queried MagicDNS from inside the container with `dns.setServers(['100.100.100.100'])` followed by `dns.lookup()`, and returned `ENOTFOUND` — apparently proving the fix would not work. `dns.setServers()` governs `dns.resolve*()` only; `dns.lookup()` goes through `getaddrinfo` and ignores it entirely, so the test had re-measured the broken path. `dns.resolve4()` returned `100.64.0.11`. A verification that silently exercises the thing you are trying to bypass is worse than no verification, because it carries the authority of evidence.

**Rule:** When a prober reports a partition of its targets down, first ask what distinguishes the failing set from the passing set. If the discriminator is a property of *name resolution* — public record vs split-DNS, internal vs external zone — suspect the prober's resolver before the targets. Check reachability from inside the probing container, not from its host; the host resolving correctly is not evidence, and on a split-DNS mesh it is the single most misleading observation available. And treat a documented gotcha as scoped to the mechanism it was written for: the same symptom from a different cause can make the recorded fix precisely inverted.

**Tags:** `#dns` `#docker` `#tailscale` `#magicdns` `#split-dns` `#uptime-kuma` `#monitoring` `#false-positive` `#mon-001` `#gotcha`

### [2026-08-09] `tls: {}` is not "no TLS config" — an empty map in a strategic-merge patch changes nothing

**Context:** While building the cert-expiry alerting for OBS-007, the first Traefik log line Loki returned for prod was a live ACME error, timestamped minutes earlier:

```
ERR Unable to obtain ACME certificate for domains
error="...for the domains [loki.internal.kubelab.local]: acme: error: 400
   POST https://acme-v02.api.letsencrypt.org/acme/new-order"
```

Traefik in production was asking Let's Encrypt for a certificate covering a `.local` domain — something LE can never issue, since it only certifies public TLDs.

**Problem:** The prod overlay already carried what looked like the fix, complete with a comment stating the intent:

```yaml
tls: {}  # No certResolver — .local TLD can't get ACME certs
```

It does nothing. In a strategic-merge patch an empty map means *"change nothing about this field"*, so the base's `certResolver: letsencrypt` merged straight through. The live resource confirmed it, and so did the source: `kubectl kustomize infra/k8s/overlays/prod` emitted `tls: {certResolver: letsencrypt}`. The patch had been asserting a property it never established, and prod had been retrying an impossible order roughly once a day for months.

Two things kept it invisible. Nothing alerts on Traefik's ACME failures — the very gap OBS-007 exists to close, which is why the bug surfaced while building the detector rather than from the failure itself. And `config-check-drift` passes green here: the committed overlay and the generator agree perfectly. Drift detection compares intent against intent; it cannot notice that the intent does not do what its comment claims. That is the same shape as the Pollex dashboard entry found earlier the same day — a green check over a false statement.

The measurement also corrected the alarm. The instinct on seeing a repeated ACME failure in prod is Let's Encrypt rate limits, which would threaten *legitimate* renewals. Counting the occurrences gave one per 24 h — Traefik's retry cadence for a failed order, nowhere near any published limit. A real defect, but not the urgent one it first appeared to be.

**Solution:** `certResolver: null`. An explicit null is what deletes a key; verified by rendering the overlay and reading the emitted `tls:` block, which became `{}` while the other 94 resources were unchanged. The CLAUDE.md gotcha was rewritten from "Patched to `tls: {}`" — which described an intention — to name the null explicitly and warn against the empty-map form.

**Rule:** An empty map is not a deletion. When a patch is meant to *remove* something, verify by rendering the output and reading the field, never by reading the patch — and treat a comment describing what a patch achieves as a claim awaiting evidence, especially when it sits directly beside the code that fails to achieve it. More generally: a config that silently fails open leaves no trace in the thing it configures, so the only place it shows up is the runtime logs of the component downstream. If nothing watches those logs, the config is unfalsifiable.

**Tags:** `#kustomize` `#strategic-merge` `#traefik` `#acme` `#letsencrypt` `#loki` `#silent-failure` `#drift-detection` `#obs-007` `#gotcha`

---

### [2026-08-09] A LimitRange can *reject* pods — the guardrail has the same failure mode as the thing it guards (IDP-031)

**Context:** Implementing IDP-031 Phase 1 — landing a `LimitRange` on the `kubelab` namespace so that a `ResourceQuota` could safely follow. The spec's whole design rests on ordering: a quota rejects any pod omitting a dimension it constrains, and this namespace ships two initContainers that declare no resources at all (`apprise/seed-config`, `crowdsec/inject-whitelist`). So the LimitRange has to be live and proven before the quota exists.

**Problem:** The plan treated the LimitRange itself as risk-free — a pure floor that can only add. It is not. `default` is injected as a *limit* into every container that omits one, `defaultRequest` as a request, and the `request <= limit` invariant is validated *after* that injection. Two ways that bites:

- a container declaring `requests.memory: 512Mi` with no limit gets `limits.memory: 256Mi` injected — 512 > 256 — and is **rejected at admission**;
- a container declaring `limits.memory: 64Mi` with no request gets a 128Mi request injected, and is rejected the same way.

Neither is exotic: declaring a request without a limit is a common and otherwise valid manifest. The object introduced to stop the namespace exhausting the node could have made healthy pods inadmissible on their next restart — and it would have surfaced not at apply time but hours later, on the next unrelated rollout.

**Solution:** Measure before writing the manifest. One pass over both clusters intersecting *declares a request* with *declares no limit*, filtered to requests above the proposed default, plus the mirror case. Result: 0 in either category across both environments, 35 safe containers, only the 2 known unbounded initContainers — so the chosen 128Mi/256Mi were safe and the phase proceeded unchanged. Had the set been non-empty, the values or those manifests would have needed fixing first, and the spec would have been wrong about its own risk. The acceptance check then captured before/after across a real restart: both initContainers went `UNBOUNDED` → `128Mi`/`256Mi`.

The generic regression test uses `kubectl create --dry-run=server` rather than create-then-delete. A server-side dry run traverses the real admission chain — LimitRanger is a member of it — and returns the mutated object without persisting anything. That tests precisely the thing that can reject a pod, while keeping the infra suite read-only and therefore safe to run against prod.

**Rule:** Before adding an admission-time defaulter, enumerate the inputs it will *change*, not just the ones it will fill. A default that completes a partially-specified object can contradict what the object already declares, and admission validates the merged result, not your intent. State the check as "which existing objects would this reject?" — and if the answer is "none", have run the query that says so. The corollary for the test: assert against the admission chain, not against a sample of today's pods, or the check quietly stops covering anything the moment those pods are given explicit resources.

**Tags:** `#kubernetes` `#limitrange` `#resourcequota` `#admission` `#idp-031` `#preflight` `#dry-run-server` `#gotcha`

---

### [2026-08-09] A check never observed failing is a claim in executable syntax, not a check (AI-007)

**Context:** AI-007 retired Ollama across 38 SSOT surfaces. Two of its eight acceptance criteria carried the weight of the whole change — AC1 ("no live wiring survives in tracked files") and AC8 ("no operational document still describes it as running") — because a subtractive change has no feature to demo. Both asserted completeness the obvious way: search every tracked file, case-insensitively, for the word `ollama`; the criterion passes when the only matches fall inside a declared allowlist of paths.

**Problem:** Neither criterion could ever have passed, on the day it was written, for two independent reasons — and the failure was found by *running* them, not by reviewing them.

1. **`videollamada`.** The Calendly URL in `common.yaml`, and therefore both generated ConfigMaps, contains the substring `ollama`. Nothing about retiring an inference service can remove a Spanish word for "video call". The check was coupled to a coincidence of spelling.
2. **The check fires harder the better the work is.** After a complete sweep, every remaining match is either the ace2 teardown — which *must* name `/opt/ollama` and port `11434` in order to delete them — or a comment explaining why a catalog is now empty. A criterion asserting absence, written against a name, cannot distinguish a live reference from an explanation of its absence. Its false-positive rate is proportional to how thoroughly the retirement was documented.

Neither is a defect in the regex. Both are a category error about what was being asserted, and no amount of reviewing the criterion would have surfaced it: it reads as obviously correct, which is precisely why it was approved.

The second-order problem is the transferable one. There are two ways a verification fails to protect you, and they are not equally bad. A verification that **never runs** is visibly missing — someone eventually notices the gap. A verification that **runs and cannot fail** is strictly worse, because it *reports* protection: it occupies the slot where a real check would go, and it consumes the attention that would have written one. The green tick is the damage.

This exact shape appeared four more times in this repo inside a single week, which is what promoted it from an anecdote to a rule:

| Instance | What it claimed | Why it could not fail |
|---|---|---|
| `tls: {}` in the prod overlay | "no certResolver — `.local` can't get ACME certs" | an empty map in a strategic-merge patch changes nothing; prod retried an impossible LE order ~1/day for months while `config-check-drift` stayed green |
| `credentials hash-password` | prints `[SUCCESS]`, help says it writes SOPS | it prints the hash and tells you to edit by hand (#934) |
| CI-GATE-007 (#933) | pre-commit lints YAML | it only lints *changed* files, so `common.yaml` sat 21 errors red on master, invisibly |
| AC1 / AC8 | the sweep is complete | matched a coincidence and its own documentation |

The common ancestor is that every one of these compares **intent against intent**. Drift detection compares the committed overlay to the generator and finds them in perfect agreement; it has no way to notice that the agreed-upon intent does not do what its comment says.

**Solution:** Rewrite both criteria to assert the **identifiers that make the service reachable** — `ollama.kubelab.live`, `apps.services.ai.ollama`, `api-key-ollama`, `ollama/ollama`, `:11434` — instead of the word that names it. Prose about a retirement never contains an identifier that would make the thing live, so the check needs no allowlist and does not decay as documentation accumulates around it. A second probe (`f9`) was added asserting the **rendered** `kubectl kustomize` output of both overlays rather than the source tree, on the same reasoning that produced the `tls: {}` bug: a clean source still emits through a base or a patch.

**Rule:** **Run every verification command once against a state where it is expected to FAIL, before trusting it.** A negative control costs one command — `git stash`, re-add the line, point it at the pre-fix commit — and it is the only evidence that separates a check from a sentence. Until a check has been observed going red, its green is unfalsifiable and means nothing.

Three corollaries, each of which independently killed one of the cases above:

- **Assert the identifiers that make a thing work, not the string that names it.** Names appear in explanations, comments, changelogs and unrelated words; identifiers appear only in wiring.
- **Assert rendered output, not source.** Verify by reading what the system emits (`kubectl kustomize`, the generated ConfigMap, the live object), never by reading the patch or the config that was supposed to produce it.
- **A check that only inspects what changed cannot report on what is already broken.** Scoping a gate to the diff is a performance decision that silently becomes a correctness one.

**Tags:** `#verification` `#negative-control` `#acceptance-criteria` `#spec-driven-development` `#silent-failure` `#grep` `#false-positive` `#ai-007` `#ci-gate-007` `#gotcha`

### [2026-08-09] A perfect evidence chain measured against a stale baseline (SEC-001)

**Context:** Two agent sessions worked this repo in parallel for an afternoon, merging roughly every twenty minutes. Picking up the remaining third of #910 — an orphaned `users_admin_password_hash` in `prod.enc.yaml` — I did what the previous session's lessons prescribe: took a positive control *before* mutating anything.

```
$ make secrets-show KEY=...users_admin_password_hash SECRETS_ENV=prod
$argon2id$v=19$m=65536,t=3,p=4$GCgsohmhQlm9Mi/...
```

The key was there. I removed it with `toolkit secrets unset`, then verified without trusting the tool's `[SUCCESS]`: the key gone, the operator hash byte-identical, `testuser` intact, audit unchanged at 43/43, and an encrypted diff of exactly one content line plus SOPS metadata. Six independent checks, all green, all genuinely run.

**Problem:** The work was already done. #936 had removed that key and merged at `23:54:56Z` — which is what closed #910 one second later. My PR was a duplicate of a fix that had landed hours before I looked.

I had run `git fetch` once, at session start, when `origin/master` was `d31c506`. #936 merged twelve minutes after that. I created the branch from my **stale local ref**, and every subsequent measurement read a working tree that predated the fix. The hash was real. The file was real. Both belonged to a commit that was no longer master.

What makes this worth recording is that *the evidence chain cannot detect it*. Every check was internally consistent, because they were all consistent with the same wrong baseline. Not one line of that output names the commit it is reading — `secrets-show` prints a hash, `secrets audit` prints a ratio, `git diff` prints a diff against whatever `origin/master` happens to point at locally. A positive control proves a key exists *somewhere*; it says nothing about whether that somewhere is current. The discipline that was supposed to protect me produced six pieces of corroborating evidence for a false conclusion, and the corroboration is what made it convincing.

The parallel session hit the sibling failure the same afternoon: a loop testing whether three branches still merged cleanly, where one branch's `git rev-parse` failed, so `git merge-tree` never ran, so the grep found no conflict markers in the error text — and the branch was reported **clean**. A check that passed because it could not run. The two hazards compound: a stale ref gives you the wrong answer, and a silently-skipping check stops you noticing.

**Solution:** `git fetch` immediately before branching, and take the baseline *after* the fetch. #939 closed as a duplicate; the incorrect comment on #910 corrected in place.

**Rule:** **A session-start fetch expires the moment anyone else merges.** In any multi-agent or multi-session day, treat your local `origin/*` refs as a cache with a lifetime of minutes, and re-validate immediately before every branch, baseline reading, or "is this still needed?" judgement.

Two corollaries that generalise past git:

- **A positive control establishes that a state exists, not that it is current.** Where the answer depends on a baseline, the baseline is part of what must be verified — say which commit, revision or generation the reading came from, or the reading is unfalsifiable.
- **Distinguish a check that ran and passed from a check that never ran.** Any composite command where an early step can fail must report `CANNOT CHECK` distinctly from `OK`; a grep over an error message finds no matches and looks exactly like success.

**Tags:** `#git` `#stale-ref` `#parallel-sessions` `#verification` `#positive-control` `#silent-failure` `#false-positive` `#sops` `#sec-001` `#gotcha`

---

### [2026-08-10] Containers keep running with no published ports, and every restart reports success

**Context:** The homepage cockpit showed every Glances widget dark. The obvious reading was that the on-demand nodes were powered off.

**Problem:** All seven nodes were up. Glances answered on two. Probing further, `iptables -t nat -S DOCKER` returned only `-N DOCKER` — the chain present with zero rules — on ace1, ace2, beelink, rpi4 and vps. Every Docker-published port on those five nodes was unreachable: Glances everywhere, MinIO on beelink. Nothing reported an error. `docker ps` listed the containers, `docker inspect` reported correct `PortBindings`, the processes inside were listening, and the healthchecks passed. The only node whose rules were intact, rpi3, was the only node without ufw.

`systemctl restart docker` did not repair it. Neither did `docker restart <name>` — rc=0, chain still empty. A throwaway container with a published port, however, got its DNAT rule created normally on *both* a broken node and the healthy one.

**Solution:** The damage is per container, not per daemon. Containers that survived a daemon restart via `live-restore: true` lost their rules, and restarting them preserves the network sandbox where the damage lives. Only recreation reprograms them — `docker compose up -d --force-recreate`. Tracked as #959.

The cause of the original flush is **not** settled, and the reason is worth recording: rpi3 lacks `base_system` (so it has no ufw) **and** lacks the `docker` role (so it has no `daemon.json`, so no `live-restore`). Those two differences travel together across the whole fleet, so comparing rpi3 against a ufw node varies two things at once. Matching Docker versions between rpi3 and rpi4 felt like a controlled comparison and was not one.

**Rule:**
- **A container reporting healthy says nothing about whether its port is reachable.** Health probes run inside the container; port publishing is kernel state outside it. Assert the DNAT rule or an external request, never the container's own status.
- **A ufw rule cannot restrict a Docker-published port.** Docker's DNAT is evaluated before ufw's filter chains and `DOCKER-USER` is empty on every node here, so the access control for a container is its bind address and nothing else. Interface-scoped ufw rules on published ports look like protection and are decoration.
- **Before calling a comparison a control, list what else differs between the two sides.** A node that never ran a role differs by everything that role installs, not by the one variable under test.
- Fourth same-day instance of a check that passed *because it could not run*: `ignore_errors: true` on a ufw task whose ufw was never installed; a role invocation missing `tags:` so `TAGS=glances` matched nothing and reported success; a `| head` that truncated the evidence a conclusion rested on; and a corrective Ansible task that reported `changed` while fixing nothing. Extends the 2026-08-09 `CANNOT CHECK` rule from composite commands to **any** gate: require that it has been observed failing at least once.

**Tags:** `#docker` `#ufw` `#iptables` `#live-restore` `#silent-failure` `#false-positive` `#confounded-control` `#glances` `#ops-016` `#gotcha`

### [2026-08-11] Five candidate triggers eliminated, and the reboot turned out to be the repair

**Context:** The 2026-08-10 entry above left the cause of the DNAT flush unsettled and named the confound. The attack plan on #959 opened with a ten-minute causal test that had never been run.

**Problem:** Every candidate failed to reproduce it. On beelink and again on ace1 — deliberately chosen for opposite Docker generations, 29.7.2 and 29.3.1 — `ufw reload`, `ufw disable && ufw --force enable`, `systemctl restart ufw` and `systemctl restart docker` each left the DNAT count unchanged and every probe at 200. That is five candidates across two Docker versions with zero reproductions.

The fifth candidate is the one worth naming: the plan tested the two ufw **CLI** paths, but `base_system` uses neither — `tasks/main.yml:96` is `notify: restart ufw`, whose handler is `service: state=restarted`. That goes through `ufw.service` → `/lib/ufw/ufw-init`, which flushes tables on stop and restores only ufw's own rules on start. Mechanically a far better suspect than `ufw reload`, and it was in our own repo the whole time.

**Solution:** Candidate 3 (a host reboot) was answered without running it, in the opposite direction to the guess. `docker inspect` separates what was recreated from what was merely started: on rpi4, `glances` was `created` at 01:14Z by the remedy, while `pihole` and `coredns` were created in March and only **started** at 01:03Z by the boot. All six of rpi4's DNAT rules are present and both services answer. Nothing recreated pihole or coredns — **a reboot repairs this, it does not cause it.**

The VPS sharpens it further: it has not rebooted since 2026-06-21, its headscale container was never recreated, and headscale's rules are back. The likely mechanism is that creating *any* container makes dockerd rebuild the whole chain, which would make the earlier "recreating a container restores its rules" correct but understated.

**Rule:**
- **A correlation with a perfect sample can still be wrong about mechanism.** The between-node correlation here had no exceptions and died in eight seconds to one intervention. When a confound cannot be separated by observation, trigger the event and watch — do not collect more observations.
- **`ufw reload`, `ufw disable/enable` and `systemctl restart ufw` are three different operations.** The CLI paths rebuild only ufw's chains; the unit path goes through `ufw-init`, which is a hammer. Testing "ufw" means naming which one.
- **Check the whole line before concluding from a log.** `dpkg.log` upgrade lines are `date time upgrade pkg OLD NEW`; an `awk '{print $1..$5}'` prints the version being *replaced*, so every upgrade reads as its predecessor. That truncation hid a `docker-ce` 29.5.3→29.7.2 upgrade three minutes before the measurement that discovered the incident — the only event-shaped evidence in the window. Same family as the `| head` that truncated evidence the day before.
- **`journalctl --list-boots` is not a reboot log.** On the VPS its earliest entry is 2026-08-10 while `uptime -s` says 2026-06-21: that gap is journal vacuuming. Reading `--list-boots` alone concludes a reboot that never happened.
- **A node that "was never in the comparison" is not covered by its conclusion.** Docker version was ruled out by pairing rpi3 against rpi4; beelink, which runs a different version entirely, was never in that pair.

**Tags:** `#docker` `#ufw` `#iptables` `#causal-test` `#confounded-control` `#evidence-truncation` `#ops-016` `#gotcha`

### [2026-08-11] The same bug three times: compare exactly the fields you write

**Context:** `make monitoring-apply` deleted all 31 Uptime Kuma monitors and recreated them on every run, discarding every monitor's uptime history (#962). The fix was an upsert that compares the seed against the live instance.

**Problem:** The comparison was wrong three times, each more subtly than the last.

1. It projected the two sides onto **different field sets** — `key` stripped from the seed, `active`/`tags`/`notificationIDList` stripped only from the live monitor. Every real monitor therefore read dirty. 16 unit tests passed, because their fixtures carried none of those fields.
2. Fixed by hand-enumerating the exclusions. That held for the three fields I knew about and silently failed for two I did not: `expiryNotification` (in 20 seed entries, in neither the export list nor the API payload) and `httpBodyEncoding: null` (in 11, and the apply path skips `None`). 20 + 11 = the 31 phantom edits.
3. Only the third fix was structural: one `WRITABLE_FIELDS` set that **both** the payload builder and the comparison derive from.

**Solution:** Compare exactly the fields the write path sends, enforced by construction. A field the apply path never writes cannot be reconciled, so flagging it as a difference requests an edit that can never clear the flag — the monitor is not merely noisy, it is *permanently* dirty.

What caught it was not a test. It was running the plan **read-only against the live instance** before ever writing: connect, fetch the real monitors, compute the diff locally, print it. The defect lived in the gap between the real seed and what the write path accepts, and no fixture written by the author of the code was going to contain that gap.

**Rule:**
- **In any declarative sync, the comparison set and the write set must be the same object.** Two lists describing one contract will drift, and the drift is invisible because both halves look correct in isolation.
- **A unit fixture cleaner than production data cannot test the case that matters.** These fixtures carried `{key, name, interval}`; real monitors carry twenty fields. Build at least one fixture from the real artifact.
- **Dry-run against production state before writing to it.** Read-only, no risk, and here it was the single highest-value step of the session — it found a defect that had already passed review and merged.
- **Verifying the absence of damage means checking what the damage would have taken.** The proof that the sync was safe was not that it exited 0; it was that monitor 462 still had 720 beats of history afterwards.
- **A negative control can be invalid in a way that flatters you.** Adding `expiryNotification` to the writable set did *not* reproduce the bug — because the fix makes that field written *and* compared. Reproducing it required breaking the symmetry itself. A control that passes may be testing nothing.

**Tags:** `#declarative-sync` `#uptime-kuma` `#ssot` `#false-negative` `#test-fixtures` `#dry-run` `#negative-control` `#ops-016` `#gotcha`
---

### [2026-08-11] Nine stateful services were duplicated across environments by a packaging choice, not a decision

**Context:** A question about whether Gitea should run in both staging and prod — a git host duplicated across environments has no obvious meaning — generalised into an audit of every stateful service.

**Problem:** Nine PVCs run in both overlays: `gitea`, `n8n`, `minio`, `postgres`, `loki`, `grafana`, `authelia`, `crowdsec-db`, `crowdsec-config`. No ADR decided that. They are all in `infra/k8s/base/`, and both overlays inherit base, so the topology was set as a side effect of where a file was filed.

Three of them turned out to be inert. Staging `gitea`, `n8n` and `minio` are empty and unused — the operator tests directly in prod — and staging `minio` has no consumer whatsoever, because the only writer is the PVC backup CronJob in `overlays/prod/backup.yaml`, which exists solely in the prod overlay.

Two premises that felt solid were wrong. The vault's `context.md` hardware inventory said Gitea runs on Beelink; the manifests say it is in `base/` and serving on both `gitea.staging.kubelab.live` and `gitea.kubelab.live`, and it appears nowhere in `beelink_services`. A prod e2e run confirmed it live (`TestAPIJsonKeys::test_api_json_contains_keys[gitea]` green against `/api/v1/version`). So #507 — "Deploy Gitea on VPS prod K3s", open and untouched since 2026-06-11 — describes work whose headline was already done.

**Solution:** Two independent axes, not one, recorded as ADR028-004 (#988):

- **Axis 1, environment:** does the state have a promotion path in git? Grafana dashboards and Authelia config do (they are ConfigMaps in git), so staging validates and prod receives the same thing. Gitea repos, n8n workflows and MinIO objects do not.
- **Axis 2, location:** ADR-028's 3 AM test. Independent of axis 1 — "prod" is an environment, not a machine.

A reference audit found no counter-example: `khuedoan/homelab` declares multi-environment support for workloads but defines `platform/gitea` once; `onedr0p/home-ops` runs one cluster; GitLab's own docs prescribe testing upgrades on a *clone* of production and name "automating production-to-staging restores"; a Gitea mirror is read-only by design to preserve one canonical instance; and the Argo CD management/workload split exists specifically to avoid duplicating platform services per environment.

**Rule:**
- **If the state has no promotion path, a second instance is not a test bed — it is a fork.** That single question sorts the platform tier from the workload tier, and it is mechanisable, unlike "which services feel like they should be duplicated".
- **`base/` in Kustomize is a silent multiplier.** Putting a stateful service there is a topology decision wearing a packaging decision's clothes. It duplicates the PVC per overlay with nothing recording that anyone chose it.
- **The cheapest moment to place a stateful service is before it has state.** Empty means "delete and redeploy"; six months of repos later the same move is a migration with a downtime window and metadata (issues, PRs, webhooks) that git clones do not replicate.
- **Do not host your control plane's source of truth behind the infrastructure that control plane rebuilds.** Argo CD keeps reconciling from GitHub rather than from the self-hosted Gitea, for the same reason ADR-015 keeps Headscale outside K3s and the Ansible inventory addresses the VPS by public IP — third instance of one doctrine, in three layers.
- **Trust order held, and it is worth re-stating because the stale source was the vault:** code > repo ADRs > `context.md` > auto-memory. Verify placement against manifests, then against a live probe; never against a hardware inventory in prose.

**Tags:** `#kustomize` `#topology` `#stateful` `#gitea` `#minio` `#n8n` `#adr-028` `#adr-037` `#circular-dependency` `#ssot-drift` `#adr028-004`

### [2026-08-11] `.yamllint`'s own header claimed CI coverage it doesn't have

**Context:** OPS-020 (#966) needed a two-line edit to `infra/config/values/common.yaml` — dropping the redundant `domain:` keys for crowdsec/loki, since every environment already overrides them.

**Problem:** The pre-commit hook failed on `yamllint`, reporting 19 indentation errors scattered across the file, none on the lines touched. Confirmed via `git stash` that the same 19 errors exist unmodified on `master` — pre-existing, unrelated to the edit. The `.yamllint` file's own header comment reads "the single SSOT consumed by pre-commit **AND CI**", but `.github/workflows/ci.yml`'s yamllint step is `yamllint .github/workflows/` — it never touches `infra/config/values/`, `infra/k8s/`, or anything else. The claim was true about which config file governs the rules, and false about where those rules actually get enforced. Nobody had committed to this specific file since the yamllint SSOT was unified (2026-06-27, #795) without hitting the local hook, so the violations accumulated invisibly — CI stayed green because it was never looking.

**Solution:** The 19 errors were all `indentation: wrong indentation, expected N but found N-2` — yamllint's inherited default (`indent-sequences: true`) rejecting this file's actual, uniform, pre-existing style of flush-left sequences. Reformatting the file to satisfy the strict rule would have turned a 2-line fix into a 60-100 line whitespace diff across the single most load-bearing config file in the repo. Set `indentation.indent-sequences: whatever` in `.yamllint` instead — accepts both styles, so it can only remove errors, never introduce new ones elsewhere in the repo (verified: `yamllint infra/config/values/` clean afterward, no new violations surfaced).

**Rule:**
- **A comment claiming "X enforces this" is a claim, not a guarantee — check what X actually runs, not what its header says it runs.** `ci.yml`'s yamllint step covers one directory; nothing else in the repo is CI-linted for YAML at all, so any of the other values/K8s/ansible YAML files could carry the same kind of dormant violation today.
- **When a lint failure's errors don't touch your diff, check master first.** `git stash && yamllint <file>` before assuming the failure is yours to fix as part of the change — it decides whether the fix belongs in this PR or is separable policy work.
- **Reformatting to satisfy a linter and relaxing the linter to match reality are different fixes with different blast radii.** The existing style was uniform across the whole file, not sloppy — that made it the file's convention, not a defect, and the config was wrong for not accepting it.

**Tags:** `#yamllint` `#ci-gap` `#pre-commit` `#false-assumption` `#config-drift` `#ops-020` `#gotcha`

### [2026-08-12] A stage-agnostic pre-commit hook silently redundant since hooks went machine-wide

**Context:** Noticed directly in this session's own commit output: the pre-commit hook block (trim-whitespace, gitleaks, the local env-file check, etc.) printed twice per `git commit`, sometimes three times. Traced instead of dismissed as cosmetic.

**Problem:** A pre-commit hook that declares no `stages:` of its own defaults to running at **every** stage. That was harmless while `.git/hooks/` only held what `pre-commit install` wrote per-repo — a stage-agnostic hook still only fired at commit time, because nothing else invoked it. Once hooks are dispatched machine-wide via `core.hooksPath` (shared across every repo/worktree on the machine), every git hook type — `pre-commit`, `prepare-commit-msg`, `commit-msg`, `pre-push` — reaches `pre-commit hook-impl`, and each stage-agnostic hook in `.pre-commit-config.yaml` runs once per hook type that fires: 2-3x per commit, plus once per checkout, plus once per push. Confirmed directly: invoking each dispatcher against a repo whose only hook was `gitleaks` ran `gitleaks` on `pre-commit`, `prepare-commit-msg`, and `commit-msg` alike.

**Solution:** One line, `default_stages: [pre-commit]`, at the top level of `.pre-commit-config.yaml` (DX-001, #895). A hook that genuinely needs another stage still declares its own `stages:`, which overrides the default — nothing else changes. Verified before/after in this repo's own commits: the hook block went from running 2-3 times to once. The one deliberate tradeoff (gitleaks' pre-push re-check, the safety net for a `--no-verify` commit) was confirmed with the maintainer before applying — accepted, since the real gate for that case is CI, not a local hook `--no-verify` already bypasses for everything else.

**Rule:**
- **A shared hook dispatcher (`core.hooksPath` set once, machine-wide) changes what "no `stages:`" means.** It stops being "runs once, whenever commit happens" and starts being "runs at every hook type this machine's git ever fires" — the migration from per-repo to machine-wide hooks silently multiplied every stage-agnostic hook's invocation count.
- **Redundant-but-correct output is easy to stop noticing.** The duplicated block had been printing in commit output for long enough to go unremarked in at least one other repo (`dotfiles`) before this session traced it here — results were never wrong, just repeated, which is exactly the kind of noise that trains a reader to stop reading.
- **Tightening a security-relevant default (dropping the pre-push net) is a decision to surface, not infer.** The technical fix and the security tradeoff were separable; only the tradeoff needed a human call.

**Tags:** `#pre-commit` `#hooks-path` `#dx-001` `#redundant-checks` `#security-tradeoff` `#gotcha`

### [2026-08-12] `bootstrap-sha` in `release-please-config.json` is a manifest-level option, not a per-package one

**Context:** Evaluating VER-009 (#989) — adding `infra`/`toolkit` as new release-please packages in a repo with years of pre-existing history under both paths. Set a per-package `bootstrap-sha` on each, expecting it to scope the first release-please pass to commits after that SHA.

**Problem:** It had no effect. A local dry-run (`release-please release-pr --dry-run --local`, against an isolated scratch clone — never the real repo) proposed `toolkit: 1.0.0` with a changelog spanning the entire commit history under `toolkit/`, back through the original K3s migration. `debug-config` showed why: the per-package `ReleaserConfig` object that `extractReleaserConfig` builds from `packages.<path>` has no `bootstrapSha` field at all — it silently accepted and dropped the unrecognized key. Confirmed against the published JSON schema (`raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json`): `bootstrap-sha` is a sibling of `packages` at the top level of the whole config document, described as "For the initial release of a library, only consider as far back as this commit SHA" — global to the run, not scoped per path.

**Solution:** Moved `bootstrap-sha` to the top level. Confirmed dormant for already-released packages (`api`/`errors` — they have real tags, so `latestRelease` lookup succeeds and the SHA is never consulted) and effective for the new ones (re-ran the same dry-run: `infra`/`toolkit` correctly showed 0 commits at the bootstrap point, then correctly picked up exactly one synthetic commit each in a follow-up test, with no cross-contamination between paths). VER-009 itself was later declined on unrelated grounds (SemVer without a consumer is decorative) — the config mechanics stayed correct regardless.

**Rule:**
- **An unrecognized key in a nested config object is not validated — it is dropped.** `release-please`'s config parser (`extractReleaserConfig`) pulls only the fields `ReleaserConfig` defines; anything else nested under `packages.<path>` vanishes with no warning, so a wrong-scope option looks identical to a correctly-scoped one until you read the actual dry-run output.
- **A schema field's own description states its scope — read it before placing the key.** The published schema literally says "for the initial release of *a* library" (singular, global), which was the tell; the assumption that "if it's about one package, it must go inside that package's block" was never verified against the schema before the first (wrong) placement.
- **`debug-config` (or the equivalent introspection command) beats re-reading docs when a config option "has no effect."** Docs describe intent; a dump of the parsed config shows what the tool actually saw.

**Tags:** `#release-please` `#config-schema` `#ver-009` `#silent-failure` `#dry-run` `#gotcha`

### [2026-08-12] "The app was extracted" and "the app is dead here" are different claims

**Context:** Researching a docs rewrite (`versioning-strategy.md`/`cicd.md`), found `promote-prod.yml`'s `workflow_dispatch` dropdown offered `web`/`api`, and the toolkit's `promote`/`image-tag` CLI help text still said "(api|web)". Read this as leftover debt from `web`'s extraction to its own repo (ADR-053) — about to file a ticket for it.

**Problem:** The premise was half right and half wrong. `web`'s *source* did move to `mlorentedev/web`. Its *deployment* — `apps.platform.web.version` in `common.yaml`/`staging.yaml`/`prod.yaml`, the `PLATFORM_APPS` constant, the `promote` command's `web` branch — never left, because `web-image-receiver.yml` (a `repository_dispatch` cross-repo receiver, ADR-053 §2) is how the other repo's CI hands a built image back to this one for staging/prod promotion. Reading that one workflow file — which the docs rewrite needed anyway — resolved it before any ticket got filed: `web` in those five places is correct, current, load-bearing config, not residue.

**Solution:** No fix needed for `web`. The search that surfaced it also found genuine (much smaller) dead-app residue elsewhere in the same file family — `orchestrator.py` iterating `["api", "web", "blog", "wiki"]` for local dev build/deploy, and hardcoded prod-status URLs for `blog.mlorente.dev`/`wiki.mlorente.dev` (blog killed, wiki retired into a toolkit command, neither resolves to anything this platform serves) — fixed in #1010, after the same one-more-file-read standard applied to confirm those two really were dead (checked `apps/` had no `blog`/`wiki` directories, and DNS had no records for either).

**Rule:**
- **"Extracted to its own repo" describes where the code lives, not whether the artifact is still deployed from here.** A platform/product repo split (ADR-053's own shape) routinely keeps deployment tracking in the platform repo after the source leaves it — the split is about code ownership, not runtime responsibility.
- **Before filing a debt ticket for "dead" references, find the mechanism that would make them live, not just the absence of a local Dockerfile.** A cross-repo `repository_dispatch` receiver is exactly the kind of live wiring that a same-repo grep for `apps/web/` will never surface.
- **The false alarm and the real finding came from the same search.** Casting the net wide enough to catch one meant catching the other too — the discipline was verifying each hit individually rather than accepting the first plausible story for all of them.

**Tags:** `#adr-053` `#platform-product-split` `#false-positive` `#verify-before-ticketing` `#debt-triage` `#gotcha`

### [2026-08-12] Rebasing a PR onto another PR's pre-merge branch tip conflicts against the real post-squash master

**Context:** #1019 depended on #1015 (both touched the tail of `docs/lessons.md`). Once #1015 merged, a peer session rebased #1019's branch onto #1015's original branch tip (`54c1254`) to resolve the shared conflict, resolved it cleanly, force-pushed — and reported #1019 mergeable.

**Problem:** GitHub reported #1019 as `CONFLICTING`/`DIRTY` anyway. This repo squash-merges every PR (ADR trunk-based rule), so `master`'s actual tip after #1015 was a *new* commit (`e0fb86f`) with `master`'s pre-#1015 tip as its parent — `54c1254` was never one of its ancestors, despite carrying identical file content. `git merge-base origin/master origin/<branch>` therefore resolved to the commit *before* #1015's change on both sides, not to `54c1254`/`e0fb86f`. From that base, git saw both `master` and the rebased branch independently inserting the same `docs/lessons.md` entry — a real conflict, confirmed by reproducing the merge in a scratch clone (`git merge-base --is-ancestor 54c1254 origin/master` → `NO`).

**Solution:** Merged current `origin/master` into the PR branch (not another rebase) — a squash-merged base only needs to be picked up once, and a merge commit is squashed away at final merge anyway so it costs nothing. Resolved the now-trivial conflict (branch content already had everything `master`'s side lacked), verified with `markdownlint`, pushed as a normal fast-forward (`350a541`, no force needed). `mergeable` flipped `CONFLICTING` → `MERGEABLE`.

**Rule:**
- **After a dependency PR squash-merges, rebase the dependent branch onto the new `master` tip — never onto the source branch's pre-merge commits.** They carry the same file content but are not the same commit; git's 3-way merge cares about ancestry, not content equality.
- **`mergeable: CONFLICTING` from the GitHub API is ground truth — a peer's local conflict-resolution success is not,** if that resolution happened against a branch tip that never reached `master`. Verify against `origin/master`, not against the branch that was rebased onto.
- **Once truly caught up, prefer a merge commit over a second rebase to reconcile a dependent branch.** It avoids a second force-push (and the coordination risk of two sessions racing on the same ref) and gets squashed away regardless at merge time.

**Tags:** `#git` `#squash-merge` `#rebase` `#merge-conflict` `#cross-session-coordination` `#gotcha`

### [2026-08-12] `kubectl exec` with a CLI that boots a full runtime shares the pod's own cgroup

**Context:** Gathering per-instance emptiness evidence for ADR028-004 (#988) meant counting n8n's staging workflows. The obvious tool existed already — n8n ships `n8n list:workflow` — so the natural move was `kubectl exec <pod> -- n8n list:workflow`.

**Problem:** The command hung past its own timeout, was killed with exit 137, and the pod failed its liveness probe and restarted seconds later — an active incident triggered by a read-only diagnostic. The n8n CLI doesn't just query the running server; it boots a second, full copy of the n8n runtime inside the container to do it. That process runs in the *same* cgroup as the server process already serving traffic, competing for the same CPU and memory ceiling. Against a pod with no headroom to spare — this one turned out to already be CPU-throttled under its 1-core limit, filed separately as #1009 — the exec was enough to tip it over. The evidence pod was gone (replaced by an unrelated rollout restart from a parallel session) before its `Last State: Terminated` reason could even be read, so the exact kill mechanism is unconfirmable after the fact.

**Solution:** Never got the workflow count from inside the pod. Used `kubectl cp` to copy the SQLite files (`database.sqlite` + `-wal` + `-shm` — the WAL held 2.7MB of uncheckpointed writes, so all three were needed for a correct count) to local disk and queried them with Python's `sqlite3` module. Bytes-out costs the container nothing; it never touches the running process's cgroup.

**Rule:**
- **`kubectl exec` runs inside the target container's own resource limits, not a scratch space of its own.** A CLI that starts a second app-runtime process (this one; `gitea admin <cmd>` would hit the identical shape) is not a lightweight query — it's launching a second workload inside a box already sized for one.
- **Prefer copying data out over executing anything inside a live, resource-constrained pod.** `kubectl cp` + local tooling is strictly safer for read-only inspection: zero contention with what's already running. This repo already has the correct pattern committed — the backup CronJob (`overlays/prod/backup.yaml`) runs its own `sqlite3` against the same class of PVC in a **separate pod**, with its own limits, never via exec into the live service.
- **A container's official CLI is not automatically a safe diagnostic tool.** It was built to be run once, by an operator, with the resources to spare — not assumed to be free against a pod already near its ceiling.

**Tags:** `#kubectl` `#kubectl-exec` `#cgroup` `#n8n` `#resource-limits` `#diagnostics` `#adr028-004` `#gotcha`

### [2026-08-12] `kubectl describe pod`'s "Reason" field distinguishes OOM from a probe-triggered kill — a bare exit 137 does not

**Context:** Verifying OPS-022 (#969) in staging, `import-n8n`'s `kubectl exec` failed mid-`deploy-k8s` with exit 137. First instinct: OOM — 137 is `128+SIGKILL`, and that's the textbook cgroup-OOM signature.

**Problem:** It wasn't OOM. `kubectl describe pod` showed `Last State: Terminated, Reason: Error` (not `OOMKilled`, which the kubelet reports verbatim when the cgroup OOM-killer fires) alongside a very specific event: `Liveness probe failed: ... context deadline exceeded` immediately followed by `Killing: Container n8n failed liveness probe, will be restarted`. The actual cause was CPU starvation, not memory: `kubectl top` showed 378m against a 200m request, which is not evidence of anything (requests don't throttle; only the limit does, and one sample can't show whether the limit was ever hit). The discriminating check was the container's own cgroup counters (`kubectl exec ... -- cat /sys/fs/cgroup/cpu.stat`): `nr_throttled=211/554` accounting periods (38%), with `throttled_usec` (30.9s) *exceeding* `usage_usec` (27.5s) — the container spent more wall-clock time waiting on its 1-core limit than it spent running. That, not memory pressure, is what made `/healthz` miss its 5s liveness timeout often enough to get killed.

**Solution:** Raised the CPU limit 1.0→2.0 cores (`infra/k8s/base/services/n8n.yaml`, PR #1022) and re-measured the same counter after a staging soak: throttled periods dropped 38%→3.3%, throttled/usage ratio dropped 112%→24%. The fix was verified by the same instrument that diagnosed the defect, not by "restarts stopped happening" (too slow a signal, and this session's soak window was too short to prove restarts alone).

**Rule:**
- **Exit 137 is SIGKILL — it says *who* ended the process, not *why*.** OOM-kill, a liveness-probe-triggered `Killing`, and a manual `kubectl delete --force` all produce it. `kubectl describe pod`'s `Last State.Reason` and the Events block distinguish them; the exit code alone does not.
- **CPU throttling needs its own evidence, not an inference from `kubectl top`.** A single usage sample can't show whether a *limit* was ever hit — only `cpu.stat`'s `nr_throttled`/`throttled_usec` can, and it was one `kubectl exec` away the whole time.
- **A tight liveness-probe timeout turns "slow" into "dead."** The mechanism connecting CPU throttling to a restart loop was the probe's 5s `timeoutSeconds` — under 38%-throttled periods, that budget just isn't enough, independent of whether the process was actually unhealthy.

**Tags:** `#kubernetes` `#cgroup` `#cpu-throttling` `#liveness-probe` `#n8n` `#ops-020` `#gotcha`

### [2026-08-12] A manifest changed in git is a claim, not a deployed fact — nothing was reading back the live Argo CD Application

**Context:** Verifying OPS-022 (#969) in staging, `make deploy-k8s ENV=staging` applied the Pi-hole overlay move correctly — then the live IngressRoute reverted to its old `Host()` 19 seconds later, with no action taken in between.

**Problem:** The live `kubelab-staging` Argo CD Application had `selfHeal: true`, even though git (`infra/k8s/argocd/applications/staging.yaml`) has said `selfHeal: false` since PR #211 (ARGO-015/ADR-037, merged 2026-05-24) — the whole point of that PR being that staging needed to tolerate a direct `make deploy-k8s` without Argo CD reverting it within seconds. `kubectl diff -f infra/k8s/argocd/applications/ --kubeconfig ~/.kube/kubelab-hub-config` confirmed this was the *only* delta — prod's live object matched its git file exactly, so this wasn't a deliberate override drifting elsewhere too. `managedFields` on the live object showed why: its last full `kubectl apply` was 2026-03-29, *before* PR #211 existed, and a `kubectl-patch` on 2026-05-19 never touched `syncPolicy`. Nobody ran `make deploy-apps` after PR #211 merged, and nothing checked that the live object had actually changed — the same defect shape as the yamllint header overstating CI coverage and the `overlays/prod/patches.yaml` `tls: {}` comment claiming a resolver was gone (both earlier entries in this file): a comment, a merged PR, or a config file all *describe an intent*, and none of them are the same fact as "the live object matches."

**Solution:** Structural fix in PR #1020 — `toolkit infra argo check-drift` runs `kubectl diff` against the Applications directory and treats its exit code as three-way, not two: clean, drift-found, or *hub unreachable* (the last one found live, for free, because aws1 happened to be down for an unrelated Spot-reclaim reason during this exact investigation — measured kubectl's own default timeout there at ~60s, bounded to ~30s with `--request-timeout=15s`). Wired into `check-apps` for visibility and as a post-apply read-back inside `deploy-apps` itself, so the fix step verifies its own result instead of trusting `kubectl apply`'s exit code. The actual live fix (`make deploy-apps`) is a one-line no-op-on-git-side operation, but it was still blocked on the hub being reachable — the drift persisted for the rest of this session for exactly that reason.

**Rule:**
- **A `make <target>` that exists is not evidence it was ever run.** PR #211 shipped both the git change and the target that applies it, and still went undeployed for ~3 months — the review gate that would have caught it (`make deploy-apps` in the PR's own "how to verify" section) was never itself made mandatory or automated.
- **"Hub unreachable" must be a third state, never silently folded into "clean."** Collapsing "couldn't check" into "no drift found" is the exact mechanism that let this go unnoticed — any read-back check with only two possible answers (clean/dirty) will eventually make that mistake the first time its target goes offline.
- **The fastest way to prove staleness in a live object is a fresh, targeted `kubectl diff` against its exact git manifest — not a memory of when it was supposed to have changed.** `managedFields` timestamps were the tie-breaker between "deliberately overridden" and "simply never redeployed"; without them this would have needed a guess.

**Tags:** `#argocd` `#gitops` `#drift-detection` `#adr-037` `#silent-failure` `#ops-020` `#gotcha`

### [2026-08-12] A domain rename is invisible to `grep` when the reference lives in a template string inside a Python generator

**Context:** An independent adversarial review of OPS-022 (#969) — requested from a separate session/subagent specifically because this session implemented the change and self-review is forbidden by the skill's own guardrail — found that the rename shipped without regenerating `infra/k8s/base/services/homepage-config/custom.js`, the committed output of `toolkit/scripts/sync_homepage_config.py`.

**Problem:** The PR's own verification swept `infra/k8s/`, `infra/terraform/`, `tests/`, and `docs/runbooks/` for the old name and found nothing — because the live reference didn't live in any of those. `sync_homepage_config.py`'s Pi-hole entry in its `shared` service list hardcoded `f"https://pihole.staging.{base}"`, inconsistent with every sibling entry in the same list (Argo CD, Headscale, Uptime Kuma all use `{base}` alone, no env prefix) — a manual insertion that predated this session and nobody had reason to touch until now. The generated `custom.js` is a committed artifact, not rebuilt by CI or by `make deploy-k8s`; it only changes when someone remembers to run `make sync-homepage`. Worse than stale text: `custom.js`'s `checkHealth()` does a live client-side `fetch(url, {mode: "no-cors"})` on every dashboard load, and `no-cors` resolves `.then()` (green) for *any* reachable response, including the staging catch-all's 404 that this exact rename intentionally introduced (AC5) — so the dashboard would have shown a false "up" status and a dead link for precisely the service being renamed, recurring the exact "SSOT keeps lying, nothing ever fails to tell us" failure this spec's own "Why" section named as its reason for existing.

**Solution:** Fixed the hardcoded string (now matches its own list's established pattern), the DNS-map table, and the mermaid diagram edge in the same generator function; regenerated `custom.js` via `make sync-homepage`; added 4 named regression tests to `tests/test_sync_homepage_config.py`, each verified to fail against the pre-fix code before being confirmed green.

**Rule:**
- **A rename's blast radius includes every place a name is *generated*, not only every place it's *declared*.** `infra/k8s/`, Terraform, and the test suite were all correctly swept; a Python script whose output is a committed artifact was not, because it doesn't live in any of the directories a routing change "obviously" touches.
- **Grepping the diff finds edited files, not files that should have been edited.** The bug wasn't a wrong string in the changed files — it was a right string that stayed wrong in an unchanged one. A rename's completeness check needs to search the *repository* for the old name, not just review the PR's own diff.
- **A generated file that's committed instead of built-on-demand can silently outlive the source of truth it was generated from.** `custom.js` had no CI regeneration step and no drift check — the same defect shape as this session's other two findings (yamllint's coverage claim, the Argo CD selfHeal drift): a description of intent, once written down, is trusted long after the reality it described has changed.
- **Requesting review from a session that never implemented the change is what caught this.** The implementing session's own verification pass (5/5 stated acceptance criteria, genuinely passing) had no reason to look at a file none of its own acceptance criteria named.

**Tags:** `#homepage` `#generated-config` `#adversarial-review` `#silent-failure` `#dns-rename` `#ops-022` `#gotcha`

### [2026-08-13] `uptime-kuma-api`'s wrapper times out on the first call over a fresh v2 socket, and integration-test containers need per-process names

**Context:** #962 (`toolkit monitoring bootstrap` swallows a Kuma-v2 setup timeout and misreports it as "admin already exists") turned out to be three separate defects layered on top of each other, each hidden until the fix for the one above it was live-tested.

**Problem 1 — the wrapper genuinely can't talk to v2 for two different calls.** `api.setup()` (`_call("setup", ...)`) times out against a real v2 instance, as the ticket's own investigation already found. Live-testing the fix surfaced a second instance of the identical failure: `api.need_setup()` — a plain read, called *before* `setup()` even runs — timed out the same way, every time, when it was the first call issued on a just-opened socket. `api.login()` elsewhere in this file has never shown the symptom. The distinguishing factor is not the event name, it's socket freshness: a short settle delay (`time.sleep(1)`) before the first call on a newly-connected `UptimeKumaApi` made both `need_setup()` and the raw `setup` emit succeed reliably; `login()` apparently never needed it because nothing calls it as the very first thing on a cold connection. A third call inherited from the pre-existing code, `upload_backup` with the v1 `{"version": "1.23.0", ...}` backup envelope, was flagged in the ticket as "not yet tested" and turned out to also time out against v2 once actually exercised live — `bootstrap`'s import step now delegates to `apply_monitors`, which already has a working, tested per-monitor create path, instead of carrying a second broken import mechanism.

**Problem 2 — a fixed integration-test container name collides across parallel sessions.** This repo runs several worktree lanes in parallel, each running `make test` independently. The integration suite's Docker container used a literal fixed name (`kubelab-test-kuma`); one lane's `docker rm -f` on setup silently killed another lane's live container mid-run. The failure read as a plain socket connection refusal and initially looked like host memory pressure (this machine's swap was genuinely near-exhausted from ~9 concurrent Claude sessions) — a plausible-but-wrong diagnosis that cost real time before the actual mechanism (a `docker ps` timeline showing a container that existed but wasn't the one this test process started) was checked.

**Solution:** `_settle()` — one named constant, one helper, called before both `need_setup()` in `bootstrap()` and inside `_run_setup()` itself (so the latter is self-contained regardless of caller). Container names suffixed with `os.getpid()`. A defensive `_wait_until_socket_reachable()` retry was also added as belt-and-braces, though the real fix was the unique name, not a longer wait.

**Rule:**
- **"Mechanically identical to a proven-working call" is not evidence a new call will succeed against the same server.** `sio.call()` and a manual `emit()` + polled callback are the same code path underneath, yet `need_setup()` failed where `login()` never had — the variable that mattered was connection freshness, not which wrapper function was used. Test every distinct *call*, not just the mechanism, against the real server before trusting it.
- **A bare "connection refused" from a fresh test container should raise "did something else claim my container's name" before "is the host out of resources."** Memory pressure produces slow, not refused; a refusal from a URL that was healthy seconds earlier is what a different process's `docker rm -f` on a shared name looks like. Check `docker ps` for a container you didn't expect before reaching for `free -h`.
- **Any shared literal identifier (container name, lock file, tmp path) is a collision risk the moment more than one agent session can run the same code concurrently** — the same bug class as the `gh` default-repo ambiguity already known to bite parallel sessions in this project. PID-suffix or otherwise namespace anything a concurrent run of the same test suite could also create.
- **Delegating one function's write path to another's does not preserve safety guarantees for free — audit every caller before assuming it does.** `apply_monitors` is a safe declarative sync when invoked deliberately (`make monitoring-apply`), but `bootstrap` runs unattended on every rpi3 Ansible provision, not just the first one; calling `apply_monitors` unconditionally from `bootstrap` would have handed an automated, unattended path the power to delete monitors the seed had merely drifted from — exactly the hazard #962/#925 had just removed from `apply_monitors` itself. The fix stayed correct by keeping the delegation strictly inside the fresh-install branch, where an empty live set makes the diff provably create-only.

**Tags:** `#uptime-kuma` `#socketio` `#integration-tests` `#docker` `#parallel-sessions` `#obs-012` `#gotcha`

### [2026-08-12] A cleanup step that reverts more than the step wrote is a destructive op wearing a check's clothing

**Context:** `make config-check-drift ENV=<env>` regenerates config into the working tree, diffs it against the committed files, then cleans up after itself. Run mid-PR to prove that new `common.yaml` fields did not change any generated ConfigMap.

**Problem:** It reported `✓ No drift` and, in the same breath, deleted the hand-written edits it had just been run to validate.

`Makefile:259`:

```make
git checkout -- infra edge 2>/dev/null || true; \
```

The comparison immediately above it is scoped to exactly three files. The cleanup is scoped to two entire top-level trees. So the target already knows precisely which paths it dirties — the revert simply does not use that knowledge, and `infra/config/values/*.yaml`, the repo's declared source of truth and hand-edited by definition, sits inside the blast radius.

Two details turn a rough edge into a trap. `2>/dev/null || true` means the step cannot fail and cannot warn, so there is no output distinguishing "reverted the two files I generated" from "reverted your unstaged SSOT edit". And `git checkout --` on unstaged changes leaves no reflog entry and no stash: it is the one git operation with no undo.

The workflow it punishes is the correct one. Running the drift check *before* committing is the entire point of the check; the target is safe only if you have already committed, which inverts its purpose.

**Solution:** Filed as #1034 rather than fixed inline, to keep the PR to one concern. The fix is the same shape as OPS-016's: derive the revert set and the diff set from **one** declaration instead of maintaining two.

Recovery was cheap only by accident — the edits had been applied by a script rather than typed, so re-running it restored them exactly. That is not a safety property, it is luck that happened to hold.

**Rule:**
- **Scope a cleanup to what the step actually wrote, never to the tree it wrote into.** "Revert the directory" is not a conservative choice; it is the widest possible one, and it silently includes files the step never touched.
- **This is the sixth instance of one shape: a declared set and an applied set maintained separately.** `WRITABLE_FIELDS` (#986) was the fifth. When two lists must agree, make them one object — the drift is invisible precisely because both halves look correct in isolation.
- **Commit before running any target whose recipe contains `git checkout`, `git clean`, or `git restore`.** Grep the Makefile for those verbs before trusting a target with uncommitted work; here exactly one target had one, and one was enough.
- **A step that cannot fail cannot be audited.** `2>/dev/null || true` on a destructive operation removes the only signal that would have distinguished intended cleanup from collateral damage.

**Tags:** `#makefile` `#destructive` `#git` `#ssot` `#drift-check` `#tool-031` `#gotcha`

---

### [2026-08-13] A default value has to be judged by what it converges toward, not just whether it avoids a crash

**Context:** #912 — mute the Apprise/Slack notification on Uptime Kuma's 9 staging-tagged monitors, since the always-on rpi3 prober watches on-demand homelab targets that are correctly DOWN whenever the homelab is off, and alerting on that trains the operator to ignore the dashboard. The fix compares "does the live monitor have a notification attached" against "does the seed, given its tags, want one" and edits when they disagree.

**The trap:** the natural signature for that comparison takes a `has_default_notification: bool` — true when the instance actually has a notification marked `isDefault`. The first draft defaulted the "false" branch to *"the seed wants zero notifications"*, on the reasoning that an instance with no default notification has nothing to attach, so nothing should be requested. That reasoning is correct for the create path — a brand-new monitor genuinely gets no notification — but wrong for the *comparison*: on an instance whose one real notification happens not to carry `isDefault: true` (a plausible SOPS/config drift, not a hypothetical), `has_default_notification` reads `False` even though every one of the 22 non-staging monitors already carries a real, working notification link. Comparing against "wants zero" would flag all 22 as dirty, and the next apply would edit every one of them to an empty `notificationIDList` — silently wiping live alerting across prod, on an unattended sync path, in the name of a monitor-muting feature.

**Fix:** when there is nothing to converge toward, *skip the comparison entirely* rather than picking a value for it. `has_default_notification=False` now short-circuits `_needs_edit`'s notification check before it runs at all, so an edit triggered by an unrelated field never touches whatever `notificationIDList` the instance already has. The same principle was applied to the write side: `edit_monitor()`'s wrapper does `data = get_monitor(id); data.update(kwargs)` before sending — reading its source confirmed that *omitting* a kwarg preserves the live value, which is what "skip" actually relies on to be safe.

**Rule:**
- **A boolean gate on a comparison has three real states, not two: "true", "false", and "not applicable" — collapsing the third into "false" picks an answer for a question that shouldn't be asked.** The tell is asking what the false branch converges *toward*: if the answer is "a state that could wipe something real", the gate needs to skip, not decide.
- **Before trusting a partial-update API to "leave the rest alone", read the source for how it builds the write payload** — not just its docstring. `edit_monitor(id, **kwargs)`'s merge-then-send behavior was the deciding fact for whether "send fewer fields" is actually safe, and it isn't documented, only implemented.
- **Fail-safe (skip, do nothing) beats fail-destructive (converge to empty) on any unattended sync path**, same principle #962/#925 already established for `bootstrap`'s delegation to `apply_monitors` — this is the third time a "the safe default is obviously X" instinct turned out backwards on this exact codepath.

**Tags:** `#uptime-kuma` `#defaults` `#ssot` `#mon-002` `#gotcha`

---

### [2026-08-14] Ansible's `apt` module can report `changed: true` for two unrelated reasons that both look like "nothing really happened"

**Context:** OPS-017 (#960) added `base_system` to rpi3's provisioning playbook — the first time that role had ever run on a Debian-family node (every other fleet node is Ubuntu). Getting it to a clean, idempotent, `--check`-safe state surfaced two distinct bugs in the same two tasks, on the same node, in the same session.

**Bug 1 — `--check` fails on a completely standard package.** A `CHECK=1` dry-run failed with `No package matching 'vim' is available`, even though `vim` is a stock Debian package. Root-caused by reading the vendored module source (`ansible/modules/apt.py`, around line 1415) rather than guessing: `update_cache`'s real work — `cache.update()` — is wrapped in `if not module.check_mode:`, so a `--check` run never actually refreshes the on-disk apt cache, yet the task still unconditionally reports `changed: true` for it. Confirmed independently that this node's cache really was empty (`find /var/lib/apt/lists -name '*Packages*'` → 0 files, since `base_system` — the only place `apt update_cache` is declared — had never run here before). A `--check` run therefore evaluates every subsequent `apt: name: ...` task against a cache that was never populated. Proof the diagnosis was right, not just plausible: the identical `CHECK=1` command, re-run after a real (non-check) pass had genuinely refreshed the cache, passed clean.

**Bug 2 — a real run keeps reporting `changed: true` for a package that's already installed.** After fixing Bug 1, an idempotence re-run still showed `changed: true` on "Install base packages", even though `apt-get`'s own output said `0 upgraded, 0 newly installed`. `dnsutils` is a pure virtual package on Debian trixie — `dpkg -l dnsutils` reports `un` (unknown, no entry at all), only `Provides` from the real package `bind9-dnsutils`. Ansible's `apt` module pre-checks the *literal requested name* against dpkg before invoking `apt-get`, and does not resolve `Provides` the way `apt-get` itself does — so it never finds `dnsutils` "installed" and re-invokes `apt-get install dnsutils` every run, which itself is a real no-op (apt resolves the virtual name correctly) but the module still reports it as `changed`. On Ubuntu 24.04, `dnsutils` happens to be a genuine transitional package with its own dpkg entry (`ii`), which is why this had never surfaced anywhere else in the fleet — rpi3 was the first Debian-family tester. Fixed by naming the real package (`bind9-dnsutils`) instead of the virtual alias — a no-op rename on Ubuntu, a real fix on Debian.

**Rule:**
- **A module reporting `changed: true` is a claim about what the module *decided to attempt*, not proof that a real state change occurred — verify against the underlying tool's own output (`apt-get`'s "0 upgraded, 0 newly installed") before trusting the module's own changed/unchanged signal**, especially the first time a role runs against a new OS family.
- **`--check` mode is not "the same logic, minus writes" for every module** — some modules (this `apt` one included) skip specific side-effecting calls under check-mode while still reporting the task as changed, which can make a `--check` run fail on things a real run would have fixed for itself moments earlier. When a `--check` failure looks absurd (a stock package "unavailable"), suspect the dry-run's own state assumptions before the repo's config.
- **A package's identity in Ansible's `apt` module is the literal string in `dpkg`'s database, not what `apt-get` would resolve it to.** Virtual/transitional packages are exactly where these two views diverge; when adding a fleet role to a new OS family for the first time, check every package name against that OS's `dpkg -l`, not just whether `apt-get install` would succeed.

**Tags:** `#ansible` `#apt` `#debian` `#check-mode` `#idempotence` `#ops-017` `#gotcha`

---

### [2026-08-14] `--tags` silently skips prerequisite `pre_tasks` that were never tagged, and a shared secret key collides across an Ansible env-override merge

**Context:** ANSIBLE-035 (#928) rolled a systemd maintenance timer out to 7 nodes as a property of provisioning, then wired its failure to POST a notification through n8n's webhook. Both bugs below were caught before shipping — one by a live failure, one by simulating the merge before writing any Ansible task — but both were the kind of thing that would otherwise have shipped silently.

**Bug 1 — `--tags` skips config/secrets loading that nothing marks as prerequisite.** Adding a task that referenced `secrets.*` under `--tags maintenance` failed with `'secrets' is undefined` on 4 of the 7 playbooks (vps, aws1, rpi3, rpi4). Their `pre_tasks` that decrypt SOPS and build the `secrets` fact carried no `tags:` at all, so Ansible's normal tag-filtering behavior — a task with no matching tag and no `always` tag is skipped when a `--tags` filter is active — silently dropped them, while the new role task (which *did* inherit a matching tag from its role invocation) still ran and referenced an undefined fact. The other 3 playbooks (beelink, ace1, ace2) already had `tags: [always]` on the equivalent tasks, each with a comment naming this exact scenario — the fix was bringing the 4 stragglers in line with an already-correct, already-documented pattern already living in the same repo, not inventing one.

**Bug 2 — reusing a secret's key path across a merge context it wasn't scoped for.** The plan was for all 7 nodes to authenticate to n8n's webhook using the existing `apps.services.automation.notify.webhook_secret`. Before writing the Ansible task, the exact `combine()` merge every playbook performs (`common.enc.yaml` deep-merged with that node's own `{env}.enc.yaml`) was simulated in a throwaway script for all three node contexts in play (common-only, common+staging, common+prod) — and it showed that 3 of 7 nodes (the ones with `deploy_env: staging`) would resolve *staging's own, different* value for that key, because staging's env-file override wins the merge. Those nodes would have sent prod n8n a token it doesn't recognize, and gotten a silent 403 nobody was watching for. Fixed with a new key, `fleet_webhook_secret`, stored *only* in `common.enc.yaml` — no per-env override exists for it, so there's nothing for any env file to win against.

**Rule:**
- **A `pre_tasks` block with no tags is invisible to `--tags` filtering, even if a task three roles later assumes its output exists.** Any fact another task might reference under a narrower `--tags` run needs `tags: [always]` on the tasks that build it — grep for the pattern already established elsewhere in the same repo before assuming a new playbook needs to invent one.
- **Reusing an existing secret's key path for a new consumer is only safe if that consumer resolves config exactly the same way every existing consumer does.** Before wiring a secret into a new set of callers, simulate (or trace by hand) the actual merge/override chain each caller goes through — "it's the same key, so it'll be the same value" is an assumption, not a fact, the moment more than one file can define that key.
- **Both of these were caught by measuring the actual resolved state (a live error; a simulated merge output) rather than reading the Ansible source and reasoning about what "should" happen.** Neither is discoverable by code review alone — `--tags` skip behavior and merge-precedence collisions both only manifest at the exact invocation that exercises them.

**Tags:** `#ansible` `#tags` `#secrets` `#sops` `#merge-order` `#ansible-035` `#gotcha`

---

### [2026-08-14] `max_over_time` remembers a spike long after the value that caused it is gone — it silently defeats `for:`

**Context:** OBS-010 — two Grafana alert rules (`obs010-quota-requests`/`-limits`) on `kubelab` namespace memory utilization, `for: 5m` so the rules should only fire on a *sustained* breach, not a momentary one during a routine deploy restart.

**Problem:** the surge-drill acceptance criterion — a normal `make deploy-k8s` + rollout restart must NOT fire the alert — failed for real on its first live run. The query was `max_over_time({container="quota-watcher"} | json | unwrap pct [10m]) > 80`. That function returns the *peak* value observed anywhere inside the 10-minute lookback window, not the current value — so a single transient spike (the surge itself, ~88% for well under a minute) stayed visible to every evaluation for up to 10 minutes after the real value had already dropped back under 71%. `for: 5m` requires the query result to stay above threshold across multiple evaluations, but with `max_over_time` the *query result itself* is an artifact of window memory, not of present reality — the sustain check was satisfied by the window, not by anything actually sustained. Caught by watching the rule transition `inactive` → `pending` → **`firing`** live during the drill (a 15-minute background poll of the rules API), then cross-checking the raw Loki log lines directly and finding the real value had already recovered to 70.54% within 5 minutes — the rule was alerting on a ghost.

A second surprise on the same incident: restarting the Grafana pod (to deploy the `last_over_time` fix) did **not** clear the stale `firing` state — Grafana's alert state lives in its own database, not in-memory, so the pod restart was a no-op for the already-firing alert. It needed one more real evaluation cycle after the fix deployed to naturally resolve.

**Solution:** `sed -i 's/max_over_time(/last_over_time(/g'` on both rules — `last_over_time` reflects only the most recent sample in the window, so `for:` genuinely requires the underlying value to stay elevated across real evaluations, not just within one remembered peak. Locked in with a permanent regression test, `test_query_uses_last_not_max_over_time`, asserting the provisioned query string contains `last_over_time` and not `max_over_time`. Re-ran an identical drill afterward: same 88% peak, rule reached `pending` at worst, never `firing`.

**Rule:**
- **`max_over_time`/`min_over_time` over a window and a `for:` sustain check are two different memories of the same interval, and stacking them double-counts.** `for:` already provides "did this stay true across N evaluations" — feeding it a query that itself remembers the window's peak makes the alert fire on "was this ever true in the window", which is a much weaker, and often wrong, condition. Use `last_over_time` (or no windowing function at all, if the metric is already a point value) whenever `for:` is doing the sustain-detection work.
- **A passing static review of the LogQL expression would not have caught this** — `max_over_time` reads as the obviously-correct choice for "did utilization get too high," and only diverges from `last_over_time` under exactly the condition a surge drill creates. This is the same "exercised, not assumed" lesson OBS-009/IDP-031 already established for prod ordering claims, now shown to apply to alert *logic*, not just deployment state.
- **A restart does not clear alert state if that state lives outside the pod.** Don't treat "the fix is deployed" as "the symptom is gone" for anything with its own persisted state machine — wait for a real evaluation cycle and check the actual state transition, not just rollout status.

**Tags:** `#grafana` `#logql` `#alerting` `#obs-010` `#gotcha`

---

### [2026-08-14] K3s's built-in ServiceLB masks every client's real IP — `externalTrafficPolicy: Local` cannot fix it

**Context:** SEC-004 — before adding any rate-limit middleware to K3s Traefik, checking whether a per-client-IP `sourceCriterion` would actually see distinct client IPs.

**Problem:** it does not. A request from a known source IP (verified via `tailscale ip -4`) reached Traefik's access log tagged with an internal pod-CIDR address instead — and a different one on a second, near-simultaneous request. The standard first fix for source-IP mangling behind a Kubernetes `LoadBalancer` Service, `externalTrafficPolicy: Local` (skips kube-proxy's SNAT for cross-node delivery), was tried and changed nothing.

The actual cause sits one layer below kube-proxy entirely: K3s's built-in ServiceLB (`klipper-lb`) is not a real load balancer, it is a per-node `iptables` script. Reading its container logs directly (`kubectl logs <svclb-pod> -c lb-tcp-443`) showed the exact rules it installs for every `LoadBalancer` Service:

```shell
iptables -t nat -I PREROUTING -p TCP --dport 443 -j DNAT --to <service-clusterIP>:443
iptables -t nat -I POSTROUTING -d <service-clusterIP>/32 -p TCP -j MASQUERADE
```

The `POSTROUTING ... MASQUERADE` rule is unconditional — every packet reaching that Service's ClusterIP gets its source rewritten, regardless of `externalTrafficPolicy`, because the rewrite happens at the klipper-lb hostPort DNAT hop, before the packet is anywhere near the Service or kube-proxy's own forwarding logic. This is klipper-lb's documented design (it avoids asymmetric routing without needing anything smarter than raw NAT), not a misconfiguration — so there is no flag to flip; the fix is a different ServiceLB implementation (e.g. MetalLB) entirely.

**Solution:** not fixed — filed as its own prerequisite issue (kubelab#1067) rather than attempted inline, since the real remediation is an infrastructure-level replacement affecting every `LoadBalancer` Service in the cluster, not a K3s Traefik config change. The ticket this was discovered under (SEC-004, rate-limit middleware) was rescoped to a global, non-per-client limit as a direct, documented consequence rather than shipping a per-IP limiter that silently buckets everyone together.

**Rule:**
- **Before designing anything keyed on "the client's IP" behind K3s's default `LoadBalancer` implementation, verify empirically what Traefik actually sees — do not assume `externalTrafficPolicy: Local` is sufficient.** It is the correct fix for kube-proxy-level SNAT, and irrelevant to klipper-lb's own masquerade, which happens upstream of that layer. Test with a temporary `--accesslog=true` and a real request from a known source, not by reading Kubernetes docs about `externalTrafficPolicy` in isolation.
- **"We already have CrowdSec" does not mean client-IP visibility is a solved problem for every future feature.** CrowdSec's bouncer plugin consumes application-level decisions from its own LAPI and doesn't need Traefik's view of source IP the same way a `sourceCriterion`-based rate limiter would — the two security layers have different dependencies on this fact, and assuming one implies the other is how this would have shipped broken.
- **A finding that changes a ticket's feasible scope belongs in that ticket and a dedicated follow-up issue, not folded silently into "ship what we can."** Global vs. per-client rate limiting are different guarantees; conflating them in the PR description would have overstated what the feature actually protects against.

**Tags:** `#k3s` `#networking` `#servicelb` `#klipper-lb` `#sec-004` `#gotcha`

---

### [2026-08-14] `kubectl apply` cannot convert a Service with a selector into a selector-less one — omitting a field is not deleting it

**Context:** ADR028-004 / #1062 moved Gitea out of K3s onto the Beelink and kept its domain, replacing the in-cluster workload with the repo's external-service pattern — `Service` (no selector) + hand-written `EndpointSlice` → the node's Tailscale IP. The manifest was correct, both overlays rendered clean, `make test-fast`, `make validate-sync` and staging e2e were green, and the first post-apply probe of `gitea.kubelab.live` returned the Beelink's instance. Everything said the cutover had worked.

**The trap:** it hadn't. The live Service still carried `selector: {app.kubernetes.io/name: gitea}` from its previous life. `kubectl apply` did not remove it, because the new manifest does not *set* `selector: null` — it simply has no `selector` key, and the field remained owned by whichever manager wrote it originally. So the endpoints controller went on managing its own slice next to the manual one:

```
NAME             ADDRESSES      PORTS
gitea-external   [100.64.0.3]   3000     # the Beelink, from git
gitea-qwcfk      [10.42.0.11]   3000     # the old in-cluster pod, still selected
```

Two EndpointSlices behind one Service means Traefik round-robins — so the domain served **two different Gitea instances, alternately**, each with its own database. Not a 502 anyone would notice: a push landing in one and a read served from the other. The single verification request that "confirmed" the cutover had a 50% chance of being right, and was.

The manifest is not wrong, and on a fresh cluster it produces exactly the intended object. The defect only exists in the *conversion*: an object that already had a selector cannot lose it by omission.

**Fix:** `kubectl patch svc gitea --type=merge -p '{"spec":{"selector":null}}'` — an explicit null is the only way to express removal — plus scaling the retired Deployment to 0 so the controller-managed slice emptied. Re-verified with **12 consecutive requests, 12/12 hitting the Beelink**, discriminated by the admin account's creation timestamp rather than by "it responded".

**Rule:**
- **When a live object is being converted rather than created, ask which fields the old shape had that the new one merely omits.** Strategic-merge apply treats absent and null as different things, and only one of them deletes. This is the same shape as the ADR-037 `certResolver: null` gotcha already in CLAUDE.md — an empty map means "change nothing", not "remove".
- **Verify a cutover with repeated requests and a discriminator that identifies *which backend answered*, never with one request and a 200.** Round-robin between an old and a new backend is indistinguishable from success in any single sample. Pick a field the two instances cannot both have — here, the admin account's creation date, 146 days apart.
- **Count EndpointSlices per Service after any switch to the external-service pattern.** `kubectl get endpointslice -l kubernetes.io/service-name=<svc>` must return exactly the hand-written one; a second, controller-managed slice is the tell that the Service still has a selector.

**Tags:** `#kubernetes` `#service` `#endpointslice` `#kubectl-apply` `#cutover` `#adr-061` `#gotcha`

---

### [2026-08-14] An unpinned `:latest` image took down the dashboard the same day upstream shipped a major version

**Context:** SEC-004's rate-limit values need a real request-rate measurement, so before writing any Middleware, the plan was to reload the Homepage cockpit in staging and read the burst off Traefik's access log — the same diagnostic pattern already used earlier in this session. The page came back `503` instead.

**Problem:** both Homepage pods were crash-looping. `kubectl describe` showed `Readiness probe failed: HTTP probe failed with statuscode: 400`; the pod's own logs explained why: `Host validation failed for: 10.42.0.99:3000. Hint: Set the HOMEPAGE_ALLOWED_HOSTS environment variable to allow requests from this host / port.` kubelet's `httpGet` probes hit the pod's own IP directly — `10.42.0.99:3000` — but Homepage (a Next.js app) validates the incoming `Host` header against `HOMEPAGE_ALLOWED_HOSTS`, which only ever listed the two public domains. A probe request's `Host` header is whatever the destination IP:port is, so it was never going to match, and every probe got HTTP 400 → CrashLoopBackOff → the whole dashboard down.

The manifest pins nothing: `image: ghcr.io/gethomepage/homepage:latest`. Checking prod's *running* pod against upstream's release list explained the timing precisely — prod's pod was 18h old (started well before today), and `gethomepage/homepage` shipped `v2.0.0` (a new Next.js major, plus a new built-in auth gate) hours before staging's pod restarted and pulled it fresh. Every other third-party image in this repo (n8n, authelia, loki, minio, crowdsec, redis...) is pinned through the `apps.services.*.image` SSOT in `common.yaml` and synced into `kustomization.yaml`'s `images:` transformer by `sync_k8s_images.py` — Homepage was the one service that had never been brought into that pattern, left on a floating tag directly in the base manifest.

**Solution:** two independent fixes, both required:
1. Both probes now send an explicit `Host` header that's already in `HOMEPAGE_ALLOWED_HOSTS` (`httpHeaders: [{name: Host, value: home.staging.kubelab.live}]`) — makes the probe's request match the allowlist regardless of which pod IP it landed on.
2. Brought Homepage's image into the existing pinning SSOT: `apps.services.observability.homepage.image: ghcr.io/gethomepage/homepage:v1.13.2` in `common.yaml` (the last release before the `v2.0.0` jump — matches prod's empirically-known-good state, and avoids adopting the new unconfigured auth gate mid-incident), added to `sync_k8s_images.py`'s `IMAGE_SOURCES`, regenerated `kustomization.yaml` via `make sync-k8s-images`.

Fix 1 alone would have restored the dashboard on `v2.0.0` — but that version's behavior (new auth gate, whatever else the major bump changed) was never evaluated, so shipping it by accident on the next pod restart was still live risk. Fix 2 makes the whole incident non-recurring until a version bump is deliberate.

**Rule:**
- **`:latest` is not a version, it's a promise that the next pod restart might run different code than the last one** — a node drain, an OOM kill, or a routine rollout can all trigger a fresh pull. If every other image in the repo is pinned through one SSOT and one is not, that's the one that will break first and hardest, because nothing will have exercised the new version before it lands.
- **A Kubernetes `httpGet` probe sends whatever Host the destination IP:port implies — never the app's real hostname.** Any app that validates the `Host` header (Next.js's `allowedHosts`, and increasingly common elsewhere as a DNS-rebinding defense) will reject kubelet's own health checks unless the probe explicitly overrides it with `httpHeaders: [{name: Host, value: ...}]`. Look for this class of failure whenever a probe starts failing right after an app's base image moves, with no change to the app's own manifest.
- **When a live pod is healthy and a sibling pod of the same Deployment is crash-looping, diff what's actually different, not just what changed in git** — here, nothing in the repo changed; the two pods differed only in which real-world instant they last pulled `:latest`.

**Tags:** `#kubernetes` `#homepage` `#image-pinning` `#liveness-probe` `#next.js` `#sec-004` `#gotcha`

---

### [2026-08-15] Staging's `selfHeal: false` doesn't stop Argo CD from reverting a manual deploy mid-session — it only suppresses drift correction, not new-revision sync

**Context:** SEC-004's burst drill needed the new `rate-limit` Middleware attached to a live staging IngressRoute (`make deploy-k8s ENV=staging`, applied from an unmerged feature branch) long enough to fire a couple hundred requests at it and read the response codes.

**Problem:** two early drill attempts (2000+ requests combined, via `ab`) produced zero HTTP 429s — looked exactly like the rate limiter wasn't working. It was working; the Middleware had already been silently stripped from the router minutes before those requests were sent. `kubectl get ingressroute homepage -n kubelab --show-managed-fields` told the real story: `kubelab-toolkit Apply` (the manual deploy) was followed ~25-30 seconds later by `argocd-controller Update`, and the live object had reverted to match `master` — which didn't have the change, since it only existed on the local branch.

ADR-037 sets staging's Argo CD Application to `syncPolicy.automated.selfHeal: false` specifically so a manual worktree deploy persists long enough to validate against. That flag did exactly what it says — it did not correct *drift* against an unchanged desired state. What it does not do is stop `automated` sync from firing when the desired state itself changes: **any new commit landing on `master` triggers a sync to that revision regardless of `selfHeal`**, and that sync reapplies the tracked manifests wholesale, including the field my manual apply had just changed. Confirmed by reading the staging Application's own sync history (`kubectl get application kubelab-staging -o json` against the hub): a sync had run in the exact window, to the exact revision, of a docs-only PR merged moments earlier by a completely unrelated, parallel worktree lane. On a day with several lanes merging to `master` in parallel — this repo's normal working mode — that window opens often enough to matter, not as a hypothetical edge case.

**Solution:** not fixed here (filed as kubelab#1083 — the fix is its own scoped decision: pause/resume automation around a validation window, or make the risk visible, neither of which belongs inside an unrelated feature spec). Worked around for this session by chaining deploy -> read live state -> act immediately in a single command sequence, keeping the window as short as possible, and re-verifying live state was correct at the moment of every measurement rather than trusting the deploy command's own success message.

**Rule:**
- **A rate-limit / feature-flag / config test that returns "no effect at all" is at least as likely to mean "my change isn't actually live" as "my change is broken."** Before concluding a mechanism doesn't work, re-verify the live object state at the moment of the test, not just at deploy time — the two can silently diverge on a shared, multi-writer cluster.
- **`selfHeal: false` answers "does Argo CD correct drift," not "does Argo CD leave my manual changes alone."** Those are different guarantees. If a repo runs multiple parallel worktrees that all deploy manually to the same staging Argo CD-managed cluster, any of them can lose a change to any other's merge, silently, with no error from either side.
- **`kubectl get <resource> --show-managed-fields` is the fastest way to ask "did something else touch this after me, and when."** Faster than diffing YAML by hand, and it names the actor — here, the difference between "my apply didn't work" and "something reverted it 25 seconds later" was one flag away.

**Tags:** `#kubernetes` `#argocd` `#adr-037` `#staging` `#sync-policy` `#sec-004` `#gotcha`

---

### [2026-08-15] A local `kubectl diff` against an Argo CD-managed cluster describes a merge that will never happen

**Context:** prod was reporting OutOfSync and the question was narrow — does this need `make deploy-k8s ENV=prod`, or is Argo CD going to reconcile it on its own? The instinct was to look at the diff: `kubectl kustomize infra/k8s/overlays/prod | kubectl diff -f -`.

**Problem:** the diff came back enormous — every one of ~90 resources showed its `argocd.argoproj.io/tracking-id` annotation being removed. Read literally, prod had drifted wholesale and needed an urgent apply. That conclusion was wrong, and it was acted on before it was checked.

`kubectl diff` without `--server-side` simulates a **client-side** apply, whose three-way merge is computed against the live object's `kubectl.kubernetes.io/last-applied-configuration` annotation — not against `managedFields`. The rule it follows: a field present in that annotation but absent from the local manifest is proposed for deletion, while a field absent from *both* is left alone. Argo CD's applies write a last-applied configuration that includes `argocd.argoproj.io/tracking-id`; the manifest rendered locally from the overlay does not carry that annotation. So on every resource it lands in exactly the "present there, absent here" case. Nothing had drifted; the diff was reporting the difference between two apply strategies.

The repo's real deploy path never takes that strategy: `toolkit/cli/infra.py:784` sets `--server-side --force-conflicts --field-manager=kubelab-toolkit`. Server-side apply reasons over `managedFields` instead, and leaves fields the manifest does not submit untouched. `--force-conflicts` is not a free pass — it takes ownership of any field the manifest *does* submit and another manager owns, resolving the conflict by winning it. That is safe here only because the tracking annotation is never submitted in the first place. The diff was answering a question about a code path that is never executed.

Real drift, once measured properly, was **one** resource out of 91.

**Solution:** ask the component that owns the comparison. `kubectl get application kubelab-prod -n argocd -o json` — **pinned to the hub** with an explicit `--kubeconfig` or `--context`, since the Application object lives there and a current context aimed at a spoke returns the wrong answer or nothing at all — and read `status.resources[]`. That is Argo CD's own per-resource desired-vs-live verdict, computed by the controller doing the syncing. It named the single offending object immediately, without touching the spoke.

**Rule:**
- **On a cluster reconciled by Argo CD, the authority on "is this in sync" is the Application's `status.resources[]` on the hub — not a local diff.** Pin the query to the hub explicitly; the object does not exist on the spoke you are asking about.
- **If you do run `kubectl diff` against server-side-applied resources, pass the flags the real apply uses** (`--server-side --force-conflicts --field-manager=...`). Otherwise the output is a faithful description of an apply nobody will ever perform.
- **An annotation or label showing up as a deletion on *every* resource is a cue that the comparison is misconfigured — not proof of it.** A shared manifest or a cluster-wide policy change can legitimately touch everything, so uniformity is ambiguous on its own; genuine drift is merely *usually* lumpy. Treat it as the signal to go confirm against `status.resources[]`, never as the conclusion.

**Tags:** `#kubernetes` `#argocd` `#server-side-apply` `#field-manager` `#kubectl-diff` `#gotcha`

---

### [2026-08-15] A retired PVC stays pinned by *completed* Job pods — and the CronJob's retention setting is what pins it

**Context:** ADR-061 moved Gitea off K3s and onto the Beelink, and the `gitea-data` PVC was duly removed from the manifests. Prod then sat permanently OutOfSync on exactly that one resource, for days, with Argo CD retrying the prune and never completing it.

**Problem:** the manifest was already correct — nothing in git referenced the PVC, and the desired state was unambiguous. The object was in `Terminating` with a `deletionTimestamp` set and simply would not go.

The blocker was the `kubernetes.io/pvc-protection` finalizer, which Kubernetes holds on a PVC while **any pod** still references it in its spec. "Any pod" includes pods in a terminal phase: three `pvc-backup-*` pods in `Succeeded`, from Jobs that predated the cutover, still carried the claim. They were not leftovers from a crash — `infra/k8s/overlays/prod/backup.yaml:27` sets `successfulJobsHistoryLimit: 3`, so the CronJob retains *up to* three successful Jobs, and their pods with them, for inspection. The retention knob that exists for debuggability and the thing holding the volume hostage are the same fact viewed from two sides. Nor does anything age them out: a per-Job TTL would have to be declared at `spec.jobTemplate.spec.ttlSecondsAfterFinished`, and that manifest does not configure one.

The second-order cost is the one that earned a ticket. An environment pinned at "1 of 91 OutOfSync, permanently" retrains you to read OutOfSync as background noise — so the next *genuine* drift arrives invisible. The drift detector was effectively down while looking green enough to ignore (kubelab#1072).

**Solution:** delete the three completed Jobs, which removes their pods. That drops the last references, the finalizer clears itself, and Argo CD completed the prune it had been retrying — prod went to 90/90 Synced.

Be precise about which step is the dangerous one. Deleting the Jobs is **not** destructive: it touches neither the PVC nor its contents. What it does is unblock the PVC deletion that was already pending, and whether the backing storage goes with it depends on the PV's reclaim policy. *That* is the step that warrants verifying a backup first and getting explicit authorization — here it destroyed the pre-cutover Gitea state, on the operator's explicit call.

**Rule:**
- **A PVC stuck in `Terminating` is almost never about the PVC.** Find what still references it, and search pods in *every* phase — `Succeeded` and `Failed` pods hold the finalizer exactly as firmly as `Running` ones.
- **Retiring a stateful service is not finished when its manifest is deleted.** Whatever referenced its volume outlives the service — backup Jobs above all, since their entire purpose is to touch the storage.
- **A retained Job is a live reference, not a record.** If Jobs mount PVCs, `successfulJobsHistoryLimit` is a storage-lifecycle setting, not just a debugging convenience; pair it with `spec.jobTemplate.spec.ttlSecondsAfterFinished` so retention is bounded by time as well as by count.
- **Treat a permanently OutOfSync environment as an outage of the drift detector**, not as a cosmetic annoyance to be filtered out mentally. One stuck resource is enough to hide every one that follows.

**Tags:** `#kubernetes` `#pvc` `#finalizer` `#argocd` `#cronjob` `#adr-061` `#gitea` `#gotcha`

### [2026-08-15] One placeholder document exiled a whole manifest from GitOps, and `Synced` said nothing

**Context.** SEC-004 (#970) applied a `rate-limit` middleware to every K3s IngressRoute. PR #1084 merged, `kubelab-prod` reported `Synced`/`Healthy` at exactly that revision, the static coverage test (`tests/test_rate_limit_coverage.py`) passed, and CI was green. Part 5 of the spec — "confirm every prod route carries it" — looked like a formality.

**Problem.** Prod's `argo.kubelab.live` route was running with `middlewares=['crowdsec-bouncer', 'secure-headers']`. No rate limit. It had been that way since the merge.

`infra/k8s/overlays/prod/argocd.yaml` held three documents — a Service, an EndpointSlice, and the IngressRoute. Only the **EndpointSlice** was unpublishable: it carries `RESOLVE_AWS1_TAILSCALE_IP`, because aws1 is a Spot instance whose Tailscale IP rotates on replacement. But the *whole file* had been excluded from the prod overlay (#152) as a blunt instrument for that one field. So Argo CD never managed any of it, its only apply path was `make deploy-argocd` (a hub-lifecycle operation nobody had reason to run for a middleware change), and the edit sat in git, applied to nothing.

**Why nothing reported it.** Three separate signals were all technically correct and all silent:

- **`Synced` speaks only for managed resources.** An Argo CD Application compares live against desired for what is in its source. A resource outside the overlay is not "drifted" — it is not in the comparison at all. `Synced` is not a statement about the cluster; it is a statement about a subset of it.
- **A static test that reads manifests tests git, not the cluster.** The file was correct. Every assertion about it passed, and would have kept passing forever.
- **The live object's own `last-applied-configuration`** still showed the pre-SEC-004 middleware list, and it had no `argocd.argoproj.io/tracking-id` — the two facts that identify this state — but nothing was looking at them.

**A wrong turn worth recording.** The first diagnosis was "implementation drift from ADR-047 D3", whose text says all three inline render sites migrate onto the `cluster_bootstrap` layer. The proposed fix was to add per-environment scoping (`envs:`) to that schema. Then `specs/TOOL-009-cluster-operator-bootstrap/tasks.md` T4 turned up: *"coredns is applied via the `cluster_bootstrap` loop; rpi3/aws1 EndpointSlices via a small toolkit command each"* — the split was a recorded decision, not drift, and the proposed fix would have contradicted it. **An ADR's prose can be narrower than it reads; the spec that implemented it is where the disambiguation lives.**

**Fix (#1089).** Split the file so only the EndpointSlice stays out-of-band. The Service and IngressRoute joined the prod overlay — which is what `overlays/prod/headscale.yaml` (same Service + EndpointSlice + IngressRoute shape) already did, because the VPS IP is stable enough to commit. The route then reached prod through GitOps on the next sync, with no manual deploy and no new Makefile target.

**Rules.**

- **A file is not the unit of GitOps exclusion — a document is.** Before exiling a multi-document manifest, check which documents actually cannot be committed. Usually it is one.
- **`Synced` is not "the cluster matches git."** It is "the resources this Application manages match git." Whenever the answer to "did the change arrive?" matters, ask what is *not* in the source before trusting the status.
- **A guard that reads manifests cannot fail on this class of defect** — the manifest is the thing that is right. Pair it with one that reads the cluster (`tests/infra/test_rate_limit.py`) and one that fails when a manifest is applied by nothing at all (`tests/test_orphan_manifests.py`).
- **Out-of-band manifests are legitimate; silent ones are not.** Where a resource genuinely cannot be committed, make it name the command that applies it, and assert that command still exists — otherwise the note outlives the target it describes.

**Tags:** `#kubernetes` `#argocd` `#gitops` `#kustomize` `#traefik` `#sec-004` `#adr-047` `#gotcha`
### [2026-08-15] A security finding's proposed fix can be worse than the bug it invents — reproduce before remediating

**Context:** ANSIBLE-035's adversarial review returned three Minor findings against the maintenance notify script. One was filed under **Security**: `TOKEN="$(cat /opt/...-secret)"` followed by `curl -H "Authorization: Bearer ${TOKEN}"`, flagged as a shell-injection surface — "if the secret file were tampered with to contain `$(...)`, backticks, or shell metacharacters, injection is possible". Recommended fix: read the token via `curl --config <file>` instead.

**The trap:** the finding is wrong, and applying its fix would have made the system less safe. Bash does not re-parse the *value* of a variable expanded inside double quotes — no command substitution, no word splitting, no globbing. Measured directly:

```
$ cat /tmp/tok-test
$(touch /tmp/PWNED-should-not-exist)`touch /tmp/PWNED2-should-not-exist`
$ TOKEN="$(cat /tmp/tok-test)"; set -- -H "Authorization: Bearer ${TOKEN}"
  [Authorization: Bearer $(touch /tmp/PWNED-should-not-exist)`touch ...`]
PWNED files created? -> 0
```

Passed through as a literal; nothing ran. The finding reasons by analogy with `eval`, which this path does not use. Meanwhile its remedy — `curl --config <file>` — would have written a live fleet-wide bearer token to a file on disk, to defend against an attack that does not exist.

The **Security** label is what makes this dangerous. A Minor labelled *reliability* invites a cost/benefit argument; a Minor labelled *security* invites compliance, and "it's cheap, just apply it" is the path of least resistance for both a human and an agent.

**Fix:** reproduce the exploit before writing the patch. Two of the three findings reproduced (a real `UnicodeDecodeError` from a byte-truncated UTF-8 sequence, and curl's missing timeouts) and were fixed; this one did not, and was refuted in writing on the ticket with the transcript above. A regression test now pins the property from the other direction — `test_token_value_is_not_shell_interpreted` fails if anyone later "hardens" the line into an `eval` or an unquoted expansion, which is where the risk actually lies.

**Rule:**
- **Reproduce a vulnerability before remediating it.** A finding is a hypothesis. If you cannot make the exploit fire in a scratch shell, you do not yet know what you are fixing — and you cannot judge whether the proposed remedy is proportionate.
- **Read the proposed fix as adversarially as the finding.** Ask what the remedy itself costs. Moving a secret from a process argument to a file on disk is not obviously an improvement; here it was a regression.
- **When you decline a finding, leave the evidence where the finding lives** — on the ticket, and as a test. "We looked at it and it's fine" is indistinguishable from "we never looked", three months later.

**Tags:** `#security` `#code-review` `#adversarial-review` `#bash` `#false-positive` `#ansible-035`

### [2026-08-15] Refuting a finding does not vaccinate the line it was about

**Context:** immediately after the refutation above, round 2 of the same review examined the same two lines and found something else: the bearer token *is* exposed, just not the way round 1 claimed. `-H "Authorization: Bearer ${TOKEN}"` becomes an argv element of `curl`, so it is readable in `/proc/<pid>/cmdline` and `ps` output for roughly a second per invocation.

**The trap:** having just proved — correctly, with a transcript — that the token is not shell-injectable, the natural reading of any further concern about that line is "we already settled this". The two findings share a file, a line, and a credential. They do not share a mechanism: one is about whether the shell *re-parses the value*, the other about *where the value ends up* once it is an argument. The first question being answered says nothing about the second.

The refutation was not wrong. Its scope was narrower than it felt.

**Fix:** treat a refutation as closing exactly one attack path, never the line. Recorded on #1088 with the distinction spelled out, and fixable without reintroducing the on-disk problem the round-1 remedy would have caused — fed from a pipe, the token appears in neither argv nor any file, which is what round 1 was reaching for and got wrong by choosing a file.

**Correction, when the fix was actually implemented (same day).** This entry originally published the one-liner below as the fix. **Do not use it as written** — it silently corrupts the credential:

```sh
# WRONG — loses everything from the first `"` in the token
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" | curl --config - ...
```

curl's config parser processes `\` and `"` *inside* a quoted value. Measured against a local listener, a token containing `"` arrived as `Authorization: Bearer tok`; dropping the quotes instead made curl send no `Authorization` header at all. Both outcomes are a 403 from the far end, i.e. the notification is lost — strictly worse than the ~1s of `ps` exposure being fixed. The shipped form escapes first:

```sh
TOKEN_ESC=${TOKEN//\\/\\\\}
TOKEN_ESC=${TOKEN_ESC//\"/\\\"}
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN_ESC" | curl --config - ...
```

**Rule:**
- **State what a refutation covers, in mechanism terms, not in location terms.** "Not shell-injectable" is a claim about parsing. "This line is fine" is a claim about everything, and you did not test everything.
- **Expect the second finding on code you just defended.** Successfully arguing against a reviewer is precisely the state in which the next concern about that code gets waved through.
- **A correct fix for a wrong finding can still be the right fix later.** Round 1's `curl --config` was disproportionate to a nonexistent bug, and its piped form is proportionate to a real one. Reject the reasoning without discarding the technique.
- **Moving a secret between transports moves its escaping problem too, and the new parser is rarely the one you were thinking about.** argv needed shell quoting; a curl config needs curl's own quoting. This lesson published an unescaped form as settled *because the security question it was reasoning about had been settled* — the transport question underneath it had not been asked.
- **A remediation deserves the same reproduction as the finding.** Both findings here were reproduced before being accepted or refuted; the *fix* was not, until it was implemented. That asymmetry is where this entry went wrong.

**Tags:** `#security` `#code-review` `#adversarial-review` `#reasoning` `#ansible-035` `#ansible-038`

### [2026-08-15] The adversarial-review gate writes a ~90MB artifact into the spec folder, untracked and unignored

**Context:** `dotf spec review` (CLI-034's archive gate) writes two files beside the spec: `review.md`, the verdict, and `review-transcript.jsonl`, the reviewer's full tool-call log. The pool's own documentation argues the transcript is essential — "the verdict records what a reviewer concluded and the transcript is the only record of how".

**The trap:** for one spec, that transcript was **91 MB**, because it embeds the content of every file the reviewer read. It lands inside `specs/<id>/`, is not gitignored, and no archived spec in `specs/archive/` contains one — so the house convention of not committing them existed only as an accident of nobody having tried. A routine `git add -A` before the archive commit stages it silently; GitHub warns above 50 MB and rejects above 100 MB, so the failure surfaces at `git push`, after the commit, in whatever session is trying to close the spec.

Caught here only because the commit's file list was read before pushing.

**Fix:** ignore it explicitly, with the reasoning attached so the next reader does not "fix" the ignore by removing it:

```gitignore
# Adversarial-review transcripts (`dotf spec review`). The verdict in review.md
# IS committed; the transcript is the reviewer's full tool-call log and runs to
# ~90MB for one spec [...] Kept local as the record of HOW a verdict was
# reached; re-derivable by re-running the review.
specs/**/review-transcript.jsonl
```

**Rule:**
- **Any repo adopting the review gate needs this ignore before its first review, not after.** The artifact is produced by a tool the repo does not own, into a directory the repo does commit.
- **Read the file list of a commit that includes tool-generated artifacts.** `git add -A` after running an unfamiliar tool is where oversized and secret-bearing files enter history; the staged list is the last cheap checkpoint.
- **"No prior example has it" is not evidence of a convention** — it can equally mean the situation never arose. Here both readings looked identical until the file size was checked.

**Tags:** `#git` `#spec-driven-development` `#adversarial-review` `#gitignore` `#cli-034` `#gotcha`

### [2026-08-15] Adding a role to a playbook does not install it on any path that never runs the playbook

**Context:** ANSIBLE-035 was created because a rebuild of aws1 "wiped the fleet's only maintenance timer with nothing noticing". The fix was to add the `node_maintenance` role to `provision-aws1.yml`, and the spec's verification then concluded that *"a future Spot replacement now reinstalls the timer (with notify wiring) automatically via provisioning, not by hand."*

**The trap:** that conclusion was never traced end to end, and it is false. The replacement path is:

```
make aws1-replace  →  terraform -replace  →  cloud-init  →  "then run: make deploy-argocd"
                                                 │                      │
                                      tailscale + k3s + ns        helm + kubectl only
                                                 └── provision-aws1.yml: never invoked
```

`node_maintenance` lives in `provision-aws1.yml`. Nothing in the chain calls it, so a replaced aws1 comes up with no timer and no notify units — the exact original incident, through a different door. Adding the role was **necessary and not sufficient**, and the gap is invisible in the direction it fails: no timer means no maintenance failures to report, so the missing alert path never announces its own absence either.

Found only because a claim written into a PR body was checked before merging, rather than after.

**Fix:** filed as #1102. The durable shape is Standing Order #1 — the replace target should *run* the provisioning step, not print it as a manual instruction which is also incomplete.

**Rule:**
- **"The role is in the playbook" answers a different question than "the node gets the role".** The second requires naming every path that brings that node up, and cattle nodes usually have a bring-up path — a `-replace` target, cloud-init, an autoscaler — that deliberately bypasses configuration management.
- **A fix that closes an incident deserves a trace of the incident's own path, not of the path you were editing.** ANSIBLE-035 traced the playbook; the incident came through Terraform.
- **Suspect any capability whose failure removes its own alarm.** A missing maintenance timer produces no maintenance failures, so the missing notifier is never exercised. These read as healthy and are indistinguishable from working, which is why they need an external check (#1021) rather than a self-report.

**Tags:** `#ansible` `#terraform` `#cattle` `#observability` `#ansible-035` `#ansible-041` `#gotcha`

### [2026-08-15] `gh pr edit` aborts on this repo with an error about a board, and leaves the body unchanged

**Context:** editing a PR description here with `gh pr edit <n> --body-file f` exits non-zero with:

```
GraphQL: Projects (classic) is being deprecated in favor of the new Projects
experience [...] (repository.pullRequest.projectCards)
```

**The trap:** the error names *Projects*, so it reads as a board-metadata problem, incidental to the edit. It is not — the body silently does not update. Confirmed by grepping the fetched body for the new text: 0 matches before the workaround, 1 after. An agent that reads the error, concludes "that's just the deprecated board", and moves on has left the PR description stale while believing it published.

**Fix:** the REST endpoint has no such coupling.

```bash
gh api -X PATCH repos/<owner>/<repo>/pulls/<n> -F body=@body.md
```

The same `-F body=@file` form repairs an issue or comment body (`.../issues/<n>`), which is also the remedy when zsh has eaten backticks out of a `--body` string.

**Rule:**
- **Verify a write landed by reading it back, not by reading the exit path.** This one failed loudly *and* partially: an error was printed, and it pointed at the wrong subsystem.
- **Prefer `gh api` over the porcelain for body writes.** `gh pr edit` bundles unrelated GraphQL calls; the REST endpoint does exactly one thing.

**Tags:** `#github` `#gh-cli` `#tooling` `#gotcha`

## A declared control can be absent, and nothing will say so

**Context:** 2026-08-15. Three unrelated defects surfaced in one session, on three different mechanisms, and only after the third did the shape become obvious.

1. **A memory limit the kernel discarded.** `common.yaml` declared `memory_limit: 256M` for Glances on the RPi3, the role rendered it, the deployed compose file carried it, and `docker inspect` reported `HostConfig.Memory=0`. The memory cgroup controller was absent from that kernel, so Docker dropped the limit — while applying the **CPU limit from the same compose block** (`NanoCpus=250000000`). (#1101)
2. **A healthcheck that could never execute.** CoreDNS on the RPi4 reported `unhealthy` with a FailingStreak of **996**. The probe was `["CMD", "dig", ...]` and `coredns/coredns` is distroless — no shell, no `dig`. It had never passed once. (#1108)
3. **A published port that was never published.** Glances containers ran with `HostConfig.PortBindings` requesting `100.64.0.3:61208` and `NetworkSettings.Ports` empty. Docker started them before tailscaled had put the address on the interface, so `docker-proxy` could not bind and the port was dropped silently. Five of seven monitoring endpoints were unreachable from the dashboard scraping them. (#1115)

**The trap:** in every case the *declaration* was correct and reviewable. The compose file said 256M. The healthcheck was in the template. The port was in `ports:`. Reading the configuration — which is what review, linting and `git diff` all do — confirms the intent every time and can never observe the effect.

Worse, each had camouflage:

- The CPU limit from the same stanza **did** apply, so any spot check that happened to look at CPU confirmed "limits work".
- The neighbouring Pi-hole healthcheck used the same `dig` and was genuinely green, so one red beside one green reads as a known-bad service rather than a broken probe.
- `docker ps` reported the portless containers `Up`, and a crashed container would have been *more* visible than a healthy-looking one serving nothing.

None of them self-heal, for the same underlying reason: **container attributes are fixed at create time**, and `docker compose up -d` compares the compose spec hash, which had not changed. `restart: unless-stopped` re-runs the same wrong container. So each defect survived every restart and reboot until someone compared the two sides by hand.

**Fix:** compare the declared value against the enforced one, in the role that declares it, and recreate on divergence.

```yaml
- name: Read the limit currently applied to the container
  command: docker inspect glances --format '{{.HostConfig.Memory}}'
  register: _applied
  changed_when: false
  failed_when: false

- name: Detect drift between the declared and the applied value
  set_fact:
    _drift: "{{ (_applied.stdout | trim | int) != (glances_memory_limit | human_to_bytes) }}"

# ...then fold `_drift` into the --force-recreate condition.
```

For ports the same idea reads `{{len .HostConfig.PortBindings}}:{{len .NetworkSettings.Ports}}` — requested versus in effect. Both shipped in the `glances` role; generalising them across every compose role is #1104.

**Rule:**
- **A configuration file is a request, not a state.** Verify the state, and prefer a check that reads it back from the thing that enforces it — the kernel, the daemon, the cluster.
- **Two-sided controls only.** When a test can only fail one way, it cannot distinguish "working" from "not running at all". The cgroup fix was only believable once 300MB under a 64M cap died with exit 137 **and** 32MB under the same cap survived.
- **Suspect an implausibly good result.** A memory sweep reporting that restic survived a 16M cap was the tell; a Go runtime alone exceeds that. The cap was a silent no-op, and the sweep had been measuring nothing.
- **A probe that has never passed is worse than no probe.** It is indistinguishable from a service that has never worked, so the one real outage it exists to catch arrives at an indicator that was already red.

**Tags:** `#docker` `#ansible` `#cgroups` `#healthcheck` `#verification` `#gotcha`

### [2026-08-16] `tailscale status` says `active` about a machine that is powered off

**Context:** aws1 was interrupted by a Spot reclaim. Checking whether it had come back, `tailscale status` showed:

```
100.64.0.7   aws1   kubelab   linux   active; relay "fra"; offline, tx 103116 rx 0
```

Read left to right, `active` is the first word and it reads as "the node is up". It is not about the node at all — it describes *this workstation's* connection attempt: a session is open via the Frankfurt DERP relay. The two tokens that carry the answer come after it: `offline`, and `tx 103116 rx 0` — 103 KB sent, **zero bytes back**.

EC2 said `stopped` the whole time, with the persistent Spot request still `open / capacity-not-available`.

**The trap:** the existing entry above (2026-03-28) already records the inverse pair — *"tailscale showing offline while EC2 still reports running / impaired"* — as diagnostic of a wedged Spot. That framing makes Tailscale look like one of two equal witnesses. It is not: **a VPN peer's state is never authoritative about whether the machine exists**, in either direction. Tailscale reports transport, EC2 reports the host.

**Fix:** answer the two questions from their own sources.

```bash
# "Is it powered on?" -> EC2, always
aws ec2 describe-instances --profile kubelab --region eu-central-1 \
  --filters "Name=tag:Project,Values=kubelab" \
  --query 'Reservations[].Instances[].State.Name' --output text

# "Is it reachable?" -> rx, not the status word
tailscale status | grep aws1
```

**Rule:**
- **`rx 0` beats every adjective on the line.** Bytes received is the only field on a `tailscale status` row that cannot be true of a dead peer.
- **Never let a transport report stand in for a liveness report**, especially when the cheap check is one CLI call away and the expensive mistake is a destructive recovery command. This was one step away from `make aws1-replace` against a stopped-but-recoverable instance — see `runbooks/aws1-destroy-replace.md`.

**Tags:** `#tailscale` `#aws` `#spot` `#diagnostics` `#gotcha`

### [2026-08-16] Rebasing onto a squash-merged branch conflicts against your own merged work

**Context:** an implementation branch was cut from a spec branch. The spec PR merged, and `git rebase origin/master` on the implementation branch immediately conflicted — on the spec files, against content that was already upstream.

**The trap:** this repo squash-merges, so master received the spec as **one** commit whose content matches the *end state* of the branch's three. Rebase replays those three originals on top of that end state, and each one conflicts with the result it helped produce. The conflict markers look like a genuine disagreement between two authors; they are the branch arguing with its own merged output, and "resolving" them by hand reintroduces intermediate states that were deliberately squashed away.

**Fix:** drop the already-merged commits instead of replaying them. Cut a fresh branch from master and cherry-pick only what is *not* upstream.

```bash
git rebase --abort
git checkout -B <branch> origin/master
git cherry-pick <impl-commit>     # only the commits master does not have
```

**Rule:**
- **After a squash-merge, the parent branch's commits no longer exist upstream in any form git can match.** `git rebase` has nothing to deduplicate against — unlike a merge-commit workflow, where it would drop them silently.
- **Stacked branches and squash-merge do not compose.** Either rebase the child *before* the parent merges, or plan to cherry-pick after. Deciding this at conflict time is how intermediate states leak back into history.
- **A conflict in files your branch did not modify in this commit is the signal.** It means the commit is already applied, not that someone else edited it.

**Tags:** `#git` `#squash-merge` `#rebase` `#worktrees` `#gotcha`
