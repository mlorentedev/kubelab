---
id: lesson-081-stale-tags-and-releases-accumulate-from-ci-re
type: lesson
status: active
created: "2026-02-28"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation]
---

# Stale Tags and Releases Accumulate from CI Renames and Deleted Branches

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
