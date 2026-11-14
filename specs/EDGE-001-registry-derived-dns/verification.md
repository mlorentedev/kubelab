---
tags: [spec, verification, templates]
created: "2026-11-13"
id: "EDGE-001-registry-derived-dns"
type: spec-verification
status: active
owner: manu
---

# Verification - EDGE-001-registry-derived-dns

## Evidence

- [x] AC1 -> `toolkit/features/edge_dns.py`, `toolkit sync edge-dns`; tests `test_the_committed_manifest_is_what_the_derivation_produces`, `test_the_platform_no_longer_hand_lists_a_product_zone`; `make validate-sync ENV=staging` and `ENV=prod` exit 0 on the final HEAD (2026-11-14); a hand edit of `edge.json` made it exit 2, naming `edge-dns`.
- [ ] AC2 -> `tests/test_edge_dns_zero_diff.py` (goldens captured on master, frozen manifest). Live half pending: the owner's `make deploy TARGET=vps ENV=prod CHECK=1` and `TARGET=dns ENV=staging CHECK=1`, expected `changed=0`.
- [x] AC3 -> `tests/test_edge_dns.py` (add/remove, ungranted apex, not `staging.<domain>`), `tests/test_product_staging_hostname.py` (render refusal naming `zones.json`).
- [ ] AC4 -> `tests/test_acme_token_scope.py::test_the_cli_probes_the_registered_product_apexes_too`, `test_every_committed_registered_hostname_has_its_apex_probed`. Live half pending: the owner's `make acme-token-scope`.
- [x] AC5 -> `tests/test_product_image_receiver_workflow.py::test_the_edge_manifest_follows_the_snapshot_into_the_same_pr`.
- [x] AC6 -> `make mutate` red on the zone append, the grant check, the probe loop and the shape check; `make test` on the final HEAD: 10417 passed, 95 skipped, 1 setup error in `test_monitoring_integration.py` (Docker exit 125, passes alone; #3514).

## Test status

- Test suite: `make test` -> 10417 passed, 95 skipped, 1 unrelated intermittent setup error (#3514; `2 passed` when re-run alone).
- Manual smoke test: none yet; the two `CHECK=1` deploys and `make acme-token-scope` are the owner's.
- No regressions in existing test suite: yes.

## Decisions made during implementation

- Goldens render from a frozen manifest, so onboarding a product never needs a fixture edit (lesson-749).
- The rendered Corefile header still names `networking.staging_zones`, kept for the zero diff; #3511 tracks it.
- The derivation repeats D8's `staging.<domain>` shape check: it reads snapshots directly, and a bare apex would capture prod for VPN clients.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/networking-dns/lesson-749-a-golden-render-of-live-data-turns-every-onboarding-into-a-hand-edit.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: the grant rule is an amendment to ADR-067 (line 91), recorded there; slice B needs ADR-073, out of scope
- [x] New pattern candidate for `00_meta/patterns/`? no: one project so far

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/EDGE-001-registry-derived-dns/` -> `specs/archive/EDGE-001-registry-derived-dns/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
