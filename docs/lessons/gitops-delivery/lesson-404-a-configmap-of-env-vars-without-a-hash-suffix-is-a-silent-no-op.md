---
id: lesson-404-a-configmap-of-env-vars-without-a-hash-suffix-is-a-silent-no-op
type: lesson
status: active
created: "2026-08-26"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, kustomize, configmap, argocd, grafana]
---

# A ConfigMap of env vars without a hash suffix is a silent no-op, and Argo CD reports Synced

**Context**: #1446 added `GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH` to Grafana's config so that Authelia's `admins` group would finally grant a Grafana role (AUTH-002, #951). The value was correct and the render was correct.

**Problem**: It would never have reached the running process. `grafana-config` was a plain ConfigMap declared in `base/services/grafana.yaml` and consumed through `envFrom: configMapRef`. Environment variables are injected once at container start and Grafana re-reads none of them, so the sequence in prod would have been:

1. the ConfigMap changes,
2. Argo CD applies it and reports **Synced / Healthy**,
3. the pod keeps running with the old environment, indefinitely.

Nothing is red. No probe fails, no event fires, and the PR's own claim — "Grafana derives a role from Authelia groups" — is false in production while every dashboard says the deploy worked. Found by pr-agent on review, not by any check.

The repository already knew the general rule and had applied it three times: `homepage-config`, `authelia-config` and `grafana-alerting` are all `configMapGenerator` entries that keep their name-suffix hash, and `grafana-alerting`'s comment states the reasoning exactly ("read ONCE at Grafana startup, so without the hash suffix a rule change would land on disk and never take effect"). `grafana-config` was the one that had never had a value added to it since the rule was learned.

**Solution**: Move the data to `services/grafana-config/grafana.env` behind a `configMapGenerator` with `envs:`, so an edit appends a new content hash and rolls the Deployment. Verified **by render, never by reading the patch** — the discipline the Loki `certResolver` gotcha exists to enforce:

- every `data:` key byte-identical in both overlays, before and after;
- the Deployment's `envFrom` following the hashed name automatically;
- staging (`grafana-config-7ddgfg7tbm`) and prod (`grafana-config-kg88t7dh5h`) getting **different** hashes — which is what proves the prod overlay's patch is applied *before* hashing rather than after.

The SEC-014 guard that read the value from the manifest followed it to the new file and gained a case asserting the arrangement itself: the manifest must not declare the object, and the generator must keep its hash.

**Rule**: If a ConfigMap's contents are consumed at container start — env vars, or any config read once at boot — it must be generated with a name-suffix hash, never declared as a plain resource. The test is not "does this file change" but "**does anything re-read it**"; where nothing does, the object name has to change or the change does not exist.

And note which failure mode this is. It is not an error, it is a **silent success**: Argo CD reporting Synced is accurate about what it did and misleading about what it achieved. Any pipeline whose green signal means "the desired state was applied" cannot, by construction, tell you the desired state was *adopted*.

**Tags**: `#kustomize` `#configmap` `#argocd` `#grafana` `#pr-1446` `#issue-951`
