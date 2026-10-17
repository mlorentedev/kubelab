---
id: lesson-377-rotating-is-not-landing-under-selfheal
type: lesson
status: active
created: "2026-08-23"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, argocd, selfheal, secrets, incident]
---

# Under selfHeal, a rotation that is not committed is not a rotation — it is a scheduled outage

**Context**: `make credentials-generate ENV=prod` rotated 25 prod secrets and 2
hub secrets, then `make deploy-argocd` applied them. The command writes SOPS
**and** `infra/k8s/overlays/prod/authelia-config/configuration.yml`, and then
stops. The working tree was left dirty and nothing said so.

**Problem**: `applications/prod.yaml` runs with `syncPolicy.automated.selfHeal:
true`. Argo CD saw the cluster diverge from git and did exactly its job:

```
running ConfigMap  sha256 c33b230f8a1f
origin/master      sha256 c33b230f8a1f   <- identical: reverted
working tree       sha256 90a13632501d   <- the new hashes, uncommitted
```

Authelia was reverted to a configuration that **rejects the client secrets the
cluster had just been given**. The rotation had been applied and undone, and the
only durable copy of 27 randomly generated credentials was an uncommitted file
in one worktree.

Two details made it worse than it looked, and both are counter-intuitive:

- **The deploy died halfway.** `deploy-argocd` is two phases with no
  transaction. Phase 1 (Authelia) succeeded; phase 2 (Argo CD) failed on an
  unrelated stale kubeconfig. The system was left in a state neither phase
  describes.
- **The reversion protected two services and broke one.** Grafana and MinIO were
  never restarted, so they still presented the *old* secrets — which the
  *reverted* Authelia still accepted. Argo CD had been given the new one and was
  the only thing broken. That inverts the safe recovery order: restarting a
  consumer before the merge makes it pick up a credential the reverted config
  rejects.

**Solution**: Commit and merge first, then restart consumers. The credentials
were committed (#1337), merged, and only then were Grafana and MinIO restarted —
after which all three agreed. The new `toolkit secrets rotate` refuses to apply
to the cluster at all and returns an ordered plan: commit → merge → restart, with
the consumer list derived from the catalog's `services` field.

**Rule**: With `selfHeal` enabled, git is the state and the cluster is a cache.
Applying a value git does not carry is not a shortcut — it is an outage with a
delay fuse, timed to the next reconcile. Any command that mutates both SOPS and a
tracked manifest must say that its work is not landed, or land it itself.

**Tags**: `#argocd` `#selfheal` `#secrets` `#incident` `#pr-1337` `#pr-1349`
