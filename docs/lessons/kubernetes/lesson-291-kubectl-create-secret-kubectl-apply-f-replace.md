---
id: lesson-291-kubectl-create-secret-kubectl-apply-f-replace
type: lesson
status: active
created: "2026-07-08"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# `kubectl create secret | kubectl apply -f -` REPLACES the whole Secret — a partial render silently deletes keys (TOOL-018)

**Context:** Hardening K8s secret delivery (TOOL-018, #829). `_apply_single_secret` in `k8s_secrets.py` assembles a Secret from a mapping of SOPS keys → resolved values and ships it with `kubectl create secret … --dry-run=client -o yaml | kubectl apply -f -`.

**Problem:** `kubectl apply` of a Secret is a **whole-object replace of `.data`**, not a per-key merge. When the SOPS→K8s mapping only *partially* resolves (a key missing, an empty decrypt — see the TOOL-017 lesson below for how that happens), the old code still built a Secret from whatever resolved and applied it — **silently shrinking the live Secret** and dropping keys that running pods depend on. No error surfaced: the deploy "succeeded" with a truncated Secret, and the failure only shows up later as a consumer that can't find its key.

**Solution:** Fail closed — if *any* key in a mapping fails to resolve, raise before the apply, so a partial render can never overwrite a complete live Secret. This is deliberately narrow: true additive merge-semantics (patch instead of replace) is the harder problem, deferred to the SEC-SECRETS-001 capstone (#831). The pre-existing gap of a *dynamic* builder returning empty (apprise/authelia-users → empty Secret) is flagged there too, not patched blind.

**Rule:** Treat `kubectl apply -f - <Secret>` as **replace-all**: the manifest you feed it must be the *complete* desired key set, or you silently delete every key you left out. Any generator that assembles a Secret from N independent sources must fail closed on a partial resolve — never apply the subset it happened to get.

**Tags:** `#secrets` `#kubernetes` `#kubectl` `#fail-closed` `#sops` `#tool-018` `#gotcha`
