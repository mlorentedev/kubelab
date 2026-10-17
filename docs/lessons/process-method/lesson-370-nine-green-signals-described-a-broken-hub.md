---
id: lesson-370-nine-green-signals-described-a-broken-hub
type: lesson
status: active
created: "2026-08-22"
owner: manu
category: process-method
tags: [kubelab, process-method, gcp, argocd, terraform, observability, verification]
---

# Nine green signals described a broken hub, and running it found all nine

**Context**: GCP-001 — moving the Argo CD hub from AWS EC2 Spot to GCP Compute
Engine Spot. Entering the session the hub existed, CI was green, the runbook had
been followed, and Argo CD reported `Synced / Healthy`. The session's actual work
was to exercise it end to end: provision it, cut staging over from `aws1`, and
prove the result.

**Problem**: Nine separate signals reported success while the thing they
described was broken. Not one was visible statically — every one needed the
system to be *run*.

| The signal | Claimed | Actually measured | Fix |
|---|---|---|---|
| `kubelab-staging Synced / Healthy` on gcp1 | the hub reconciles staging | that git and the cluster agreed — **because `aws1` had already applied everything**. `history: 0`, `phase: None`: it had never written | forced a sync → `Succeeded, 89 resources` |
| `make check-spokes` → `OK (registered + reachable)` | the hub reaches its spoke | that **the operator** could, with the operator's kubeconfig. Green for a hub that could not authenticate at all | #1280 |
| the spoke token in Secret Manager | a ServiceAccount JWT | the JWT **base64-encoded twice**. `make register-spoke` had always decoded it; porting the read dropped the decode | #1277 |
| `on-sync-failed` never firing | nothing is failing | that the expression **could not evaluate** — expr-lang raises on nil, and a raised `when:` is a *skipped* trigger. Blind precisely while a sync starts | #1276 |
| `docker ps running` + healthcheck `healthy` + ping monitor up | DNS is serving | three proxies for liveness. The healthcheck resolved a name Pi-hole answers *itself*; the monitor measured ICMP. Staging DNS was dead 90 minutes under all three | #1278 |
| `terraform apply` succeeding | infra matches config | nothing durable: the **next** plan still read `1 to add, 1 to destroy` — twice, for two fields GCP computes and writes back. Checking for drift was itself an outage | #1282, #1284 |
| `gcloud recreate-instances` → `SUCCESS` | the machine was replaced | that the **request was accepted**. The next step connected to the dying VM and cached its host key | #1283 |
| `unregister-spoke` → "staging detached" | the detach completed | that the loop finished. Exit codes were never read, so a failed finalizer patch still let the delete run — and that delete **cascades** | #1285 |
| a green mutation battery | the guard does not fire | that the replacement string **never matched** — `ruff format` had collapsed the targeted line | assert the match |

Two of these were defects written *the same day*, in code added to fix an earlier
one. The `unregister-spoke` case is the sharpest: its docstring says
*"patch-then-delete detaches, delete-then-patch destroys"*, and a test pins the
order — but an order is not a guarantee when the first step may fail silently.

**Solution**: Three questions found all nine, and they are cheaper than the
audits they replace.

1. **"Has it ever done the thing, or only reported it?"** Ask for history, not
   status.
   ```
   kubectl -n argocd get application X -o jsonpath='{.status.history}'   # 0 entries = never wrote
   ```
2. **"Is the SECOND apply empty?"** The first proves nothing; convergence is the
   property. `terraform plan` immediately after a successful apply must say
   `No changes`.
3. **"Whose credential is this using?"** Separates *I* can reach it from *the
   thing that needs to* can. Probe with the credential the consumer stores, and
   let the HTTP status be the verdict.

**Rule**: **A signal is only evidence if it can distinguish itself from the
failure it exists to catch.** Before trusting a green, name what would have to be
true for it to be green *and* wrong — if that state is reachable, the signal is
decoration.

Two corollaries earned the hard way here:

- **A mutation that does not apply reads exactly like a guard that does not
  fire.** Assert the replacement text matched before running the test.
- **A text scan matching the COMMENT that explains a thing passes a file that
  only documents it.** Strip comments before scanning — this recurred **five
  times in one day** (lesson-363's shape).

Cross-project form: [[pattern-verification-fails-toward-unproven]] in the vault,
where this session's nine join six from dotfiles and three from an earlier
kubelab session.

**Tags**: `#verification` `#false-green` `#gcp` `#argocd` `#terraform`
`#pr-1276` `#pr-1277` `#pr-1278` `#pr-1280` `#pr-1282` `#pr-1283` `#pr-1284`
`#pr-1285`
