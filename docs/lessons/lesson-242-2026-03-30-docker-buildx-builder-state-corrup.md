---
id: lesson-242-2026-03-30-docker-buildx-builder-state-corrup
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-03-30: Docker buildx builder state corruption on ephemeral runners

**Symptom:** `docker buildx inspect multiarch` → "no builder found". `docker buildx create --name multiarch` → "existing instance, no append mode". `docker buildx rm multiarch` → "no builder found". All three commands fail.

**Root cause:** Builder was created with `become: false` (ansible_user) while Docker runs as root. The builder metadata split across user/root `.docker/buildx/instances/` directories — inspect sees root's empty state, create sees user's existing registration.

**Fix:** Clean both CLI state AND filesystem state before recreate:
```yaml
- shell: |
    docker buildx rm multiarch 2>/dev/null || true
    rm -rf /root/.docker/buildx/instances/multiarch 2>/dev/null || true
```

**Rule:** All Docker operations in Ansible must run with consistent privilege. Don't mix `become: true` and `become: false` for docker buildx commands in the same role.
