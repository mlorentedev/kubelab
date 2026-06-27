---
tags: [spec, verification, templates]
created: "2026-06-26"
---

# Verification - DELIVERY-002-build-once-apps

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [~] C1 — no `docker build` for the semver tag -> `release.yml` `publish-api` is now a re-tag job (`docker buildx imagetools create`), no `build-push-action`, no call to `ci-publish.yml`. **Runtime digest-equality proof pending the first `api` release in CI.**
- [~] C2 — `api:X.Y.Z` == `api:sha-<short>` manifest-list digest -> asserted in-job (`imagetools inspect --format '{{.Manifest.Digest}}'`, fail on mismatch). **Verified at first release.**
- [x] C3 — sha resolved from staging SSOT, never hardcoded -> `tests/test_image_tag.py::TestResolveImageSha` (reads `values/staging.yaml`; `test_errors_on_dev_pin` / `test_errors_on_semver_pin` enforce the sha shape).
- [x] C4 — `promote-prod.yml` unchanged -> not touched; `tests/test_promotion.py` still green (5/5).
- [x] C5 — toolkit command resolves the pinned sha without network -> `tests/test_image_tag.py::TestResolveImageSha::test_returns_pinned_sha` (no registry mock; a network call would raise).

## Test status

- Test suite: `poetry run pytest tests/` -> **322 passed, 108 deselected** (live-env markers), 17s. New: `tests/test_image_tag.py` (6), prune guard `tests/test_registry_prune.py::TestSelectStaleTags::test_never_prunes_protected_sha`.
- Type: `mypy` clean on all 4 changed modules (pre-existing `notify_smoke.py` stub gap unrelated).
- Manual smoke: `toolkit deployment image-tag --env staging --app web` -> `sha-c8fa9a6` (rc=0, clean stdout); `--app api` -> rc=1 (no sha pin yet — guard fires correctly).
- No regressions: yes (322 green, including the 5 prior promotion tests after the shared-loader refactor).

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- Resolver reads the **raw** `staging.yaml` pin, not the merged config — merged would surface the inherited `dev` from `common.yaml` and mask "no validated staging artifact". The absent pin must be an error, not a silent `dev`.
- Prune guard implemented as a `protected` set threaded through the pure `select_stale_tags` (not an ad-hoc filter in the I/O loop) so it stays unit-testable and protects a pinned sha even outside the retention window.
- `:latest` alias preserved on the re-tag (the old stable build pushed it too) so nothing downstream that resolves `:latest` regresses.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons.md`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/DELIVERY-002-build-once-apps/` -> `specs/archive/DELIVERY-002-build-once-apps/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
