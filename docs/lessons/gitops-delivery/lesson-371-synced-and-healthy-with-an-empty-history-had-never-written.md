---
id: lesson-371-synced-and-healthy-with-an-empty-history-had-never-written
type: lesson
status: active
created: "2026-08-23"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, argocd, gcp, verification, false-green]
---

# `Synced`/`Healthy` with an empty history had never written

**Context**: Handing prod's Argo CD reconciliation from the `aws1` hub to `gcp1`
(GCP-001, #1299). The retiring hub was paused — `argocd-application-controller`
scaled to 0, nothing deleted — and the new hub was recreated by its MIG, with
cloud-init installing Argo CD and registering both spokes from Secret Manager
unattended.

**Problem**: Immediately after the recreate, before any sync was forced, the new
hub reported:

```
kubelab-prod   Synced   Healthy
```

and `.status.history` was **empty**.

The green status was true and meant something other than it appears. The hub had
**compared** the spoke against git, found them equal — because `aws1` had already
reconciled it before being paused — and concluded there was nothing to do. It had
never exercised its own write path. Nothing distinguishes that from a fully
working hub unless you ask for the history specifically.

This was the tenth such signal in one migration. The others: `check-spokes`
measuring the operator's kubeconfig instead of the hub's, a double-encoded secret
that looks exactly like a secret, `docker ps` healthy over a dead resolver.

**A second trap sits inside the fix.** History is per-hub, not per-Application-
name: `aws1`'s `kubelab-prod` history ended at id 51, while `gcp1`'s own starts
at id 0, because cloud-init created a fresh Application object. An acceptance
check written as the obvious `history > 51` reports **failure on a hub that works
perfectly**.

**Solution**: Accept a hub's reconciliation only from a forced sync that reaches
`operationState.phase: Succeeded` **with a non-empty history** — never from a
status read.

```bash
make sync-app APP=kubelab-prod
kubectl -n argocd get application kubelab-prod \
  -o jsonpath='{.status.operationState.phase}{" "}{.status.history[*].id}'
# Succeeded 0
```

Judge `history >= 1` **on the hub being tested**, never against another hub's
last id.

Stronger evidence arrived on its own afterwards: merging #1299 made `gcp1` pick
up `eb41ee2` and then `ea1a7c2` unattended, reaching `history: [0 1]`. A real
change arriving from git and being applied with no operator action is the actual
job; a forced sync against the revision the spoke already held only proves the
path exists.

**Rule**: **A green signal answers a specific question, and the question it
answers is usually narrower than the one being asked.** `Synced` answers "does
the spoke match git", not "did THIS hub put it there". Ask for the artefact that
only the action being verified could have produced — here a history entry, which
only a write creates.

Two corollaries measured the same day, both the same shape:

- **HTTP 200 does not identify a backend.** After repointing `argo.kubelab.live`
  (#1308) both hubs answered 200 on the same NodePort. What distinguished them
  was the SHA-256 of the served body.
- **An absent log line is not a negative result.** Two probes — a marked
  `User-Agent` and a marked URL path — returned zero hits on *both* hubs, because
  `argocd-server` logs events rather than HTTP requests. Zero on the hub you
  expect reads as evidence; zero on both is the tell that the question was never
  asked.

**See also**: [[lesson-369-applying-terraform-from-a-feature-branch-destroyed-the-hub]],
[[lesson-370]] (the nine false greens this extends).
