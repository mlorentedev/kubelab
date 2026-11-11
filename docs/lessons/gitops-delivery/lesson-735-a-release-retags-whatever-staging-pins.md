---
id: lesson-735-a-release-retags-whatever-staging-pins
type: lesson
status: active
created: "2026-11-11"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, release, adr-056, api]
---

# An api release re-tags whatever staging pins, so a release merged before its staging deploy ships the previous build

**Context**: Under ADR-056 an api release does not build an image. The
"Publish API (re-tag staging digest)" job in `release.yml` copies the image
staging pins (`sha-<short>`) to the new semver tag, and checks that both tags
resolve to one digest.

**Problem**: `api-v1.7.1` was released from `0324786`, and its changelog lists
#3246, the Gitea pagination fix. Staging still pinned `sha-1bad811`, the 1.7.0
build, because the staging deploy of `sha-0324786` (#3259) merged 40 minutes
after the release. The job re-tagged `sha-1bad811` as `1.7.1`, and the digest
check passed because the two tags really were one artifact. After promotion,
prod logged the exact error #3246 fixes
(`next page points off gitea:3000`, 2026-11-11 04:49 UTC). So a merged fix, a
published release and a green promotion together shipped no change at all.

**Solution**: The tag was not moved, since a published semver keeps its digest
(ADR-056). The fix ships in the next release, cut only after staging pins a
build that contains it. #3266 adds the missing check: the release commit must
be an ancestor of the commit behind staging's pin, or the publish fails and
names the deploy that has to land first.

**Rule**: Before merging a release PR, check that staging's pin for that app
was built from the release commit or from a later commit
(`git merge-base --is-ancestor <release> <pin>`). Then verify a promotion by
what prod does, not by the version it reports: a green digest check proves the
tags are one artifact, not that it is the artifact the changelog describes.

**Tags**: `#release` `#adr-056` `#console-004` `#issue-3266`
