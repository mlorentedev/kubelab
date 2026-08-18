---
id: lesson-330-staging-s-selfheal-false-doesn-t-stop-argo-cd
type: lesson
status: active
created: "2026-08-15"
owner: manu
tags: [kubelab, lesson, kubernetes, argocd, adr-037, staging, sync-policy, sec-004, gotcha]
---

# Staging's `selfHeal: false` doesn't stop Argo CD from reverting a manual deploy mid-session — it only suppresses drift correction, not new-revision sync

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
