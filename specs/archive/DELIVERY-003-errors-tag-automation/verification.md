---
tags: [spec, verification, templates]
created: "2026-06-26"
---

# Verification - DELIVERY-003-errors-tag-automation

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] AC1 — `edge.errors.version` is the single SSOT; no hardcoded `kubelab-errors` `newTag` -> `sync_k8s_images.resolve_errors_image`/`collect_images` emit errors from `edge.errors`; the custom-apps group in `base/kustomization.yaml` no longer lists errors. Tests `tests/test_sync_k8s_images.py`.
- [x] AC2 — release-please `errors:X.Y.Z` updates the K3s tag with no manual edit -> `release.yml` `promote-errors` job runs `toolkit deployment promote --app errors` then opens a PR; `promotion._promote_errors` writes the version + re-syncs. Test `tests/test_promotion.py::TestPromoteErrors::test_writes_edge_version_and_syncs`.
- [x] AC3 — VPS Ansible and K3s resolve the same SSOT -> both read `edge.errors.{image_name,version}` (`deploy-vps.yml` `errors_image` unchanged; K3s `newTag` now derived from the same key). No divergence possible.
- [~] AC4 — config-drift gate stays green after a promotion -> the gate (`make config-check-drift`) regenerates overlays only; the base kustomization is `make sync-k8s-images` territory, which the promote command always runs, so committed == sync output. Gate stays green. _Gap: nothing in CI asserts kustomization==common.yaml independently (follow-up below)._
- [x] AC5 — toolkit refuses an errors tag absent from the registry -> `_promote_errors` calls `tag_exists` and raises. Test `test_rejects_missing_tag`; smoke: `promote --app errors --version 0.0.0-nonexistent` -> "not found" (real Docker Hub 404).

## Test status

- Test suite: `poetry run pytest tests/` -> **330 passed, 108 deselected** (live-env markers), 18s. New: `tests/test_sync_k8s_images.py` (5), `tests/test_promotion.py::TestPromoteErrors` (3).
- Type: `mypy` clean on changed modules (pre-existing `notify_smoke.py` stub gap unrelated). Lint: `make lint` All passed. `yamllint` green at both local (100) and CI (120) thresholds.
- Manual smoke: `make sync-k8s-images` -> errors emitted in the synced block as `kubelab-errors:1.1.1` from `edge.errors.version`; `toolkit deployment promote --app errors --version 0.0.0-nonexistent` (no `--env`) -> registry 404 refusal.
- No regressions: yes (updated one pre-existing test that used `errors` as the rejected example — now a valid target; switched it to `traefik`).

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- `errors` joins the **sync** lane, not the promote-overlay lane — it is semver-in-`common.yaml` (shared), structurally a third-party image, unlike api/web's per-env tags. The sync regex naturally stops at the `# Custom apps` comment, so web/api stay hand-pinned below while errors moves into the synced block above.
- `promote --app errors` is **env-agnostic** (single SSOT): `--env` made optional, ignored for errors, still required for api/web. `_promote_errors` writes `common.yaml` + re-syncs instead of regenerating an overlay.
- `sync_k8s_images.main()` refactored to `sync(common, kustomization)` with injectable paths so the promote command can sync a working tree under `settings.project_root` (and so the policy is unit-testable).
- Follow-up (not in scope): add a `sync-k8s-images --check` to the drift gate so a manual `edge.errors.version` bump without a sync is caught in CI (the automated release path already syncs).

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons.md`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/DELIVERY-003-errors-tag-automation/` -> `specs/archive/DELIVERY-003-errors-tag-automation/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
