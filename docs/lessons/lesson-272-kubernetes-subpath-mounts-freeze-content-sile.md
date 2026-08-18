---
id: lesson-272-kubernetes-subpath-mounts-freeze-content-sile
type: lesson
status: active
created: "2026-05-25"
owner: manu
tags: [kubelab, lesson, k8s, secrets, mounts, authelia, gotcha, secret-reload-001]
---

# Kubernetes `subPath` mounts freeze content — silently breaks app-level watch and live Secret updates

**Context:** Phase B prod smoke (`make deploy-k8s ENV=prod`) updated the `authelia-users` K8s Secret to contain the renamed admin (`operator` instead of `manu`). Authelia config had `authentication_backend.file.watch: true` — designed precisely so users_database changes propagate without restart. But after deploy, Authelia kept serving the cached `manu` user. Pod AGE was 47h (no rotation), and the only options on the table were ad-hoc `kubectl rollout restart` (violating `feedback_no_manual_kubectl.md`) or a `secretGenerator` hash-suffix refactor (overkill for this case).
**Problem:** The mount used `subPath: users_database.yml`. **Kubernetes does not propagate Secret/ConfigMap updates to volumes mounted with `subPath`** — the file is frozen at mount time. This is a documented K8s limitation (https://kubernetes.io/docs/concepts/storage/volumes/#subpath) but easy to miss because: (1) the Secret IS updated in etcd / `kubectl get secret` shows new content; (2) `watch: true` works perfectly when the file changes — but the file never changes from the pod's filesystem perspective; (3) the symptom (cached value) looks like an app-level cache problem, not a mount problem. False root-cause hypotheses (Authelia cache, in-memory store, missing reload signal) waste time. The real diagnosis requires recognizing that the mount strategy itself is the bug.
**Solution:** **Mount the Secret as a directory** (no `subPath`). For a Secret with a single key `users_database.yml` mounted at `/config/users`, K8s materializes `/config/users/users_database.yml` and DOES refresh on update (~60s mount sync). Authelia config `path:` adjusted to the new location. The deploy that introduces this change causes ONE final rolling restart (deployment spec changes — mountPath + path); after that, every future `users_database` change propagates zero-downtime. Generalizes to any (Secret|ConfigMap) × app-with-file-watch combo: **if the data is meant to evolve at runtime, mount the volume as a directory, never with subPath**. Reserve `subPath` for truly static config that's tied to the deploy lifecycle (e.g., immutable scripts shipped with the image). Shipped in PR #224. Tracked follow-up: `SECRET-RELOAD-001a` (audit other subPath mounts) + `SECRET-RELOAD-001c` (ADR-039 reload-policy hierarchy: app-watch > directory mount > hash-suffix > Reloader > manual restart).
**Tags:** `#k8s` `#secrets` `#mounts` `#authelia` `#gotcha` `#secret-reload-001`
