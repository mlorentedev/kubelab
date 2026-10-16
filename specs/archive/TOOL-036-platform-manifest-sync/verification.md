---
tags: [spec, verification, templates]
created: "2026-09-05"
---

# Verification - TOOL-036-platform-manifest-sync

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof:

> Test names below are copied from the file, not written from memory. Three of the
> names this section used to carry — `test_nodes_projection`,
> `test_services_projection`, `test_zero_addressing_guard_catches_leak` — never
> existed. Evidence that names a test nobody can run is indistinguishable from no
> evidence, and it reads stronger than a blank.

- [x] AC1 (Schema projection from SSOT) -> `test_manifest_schema_and_counts`, `test_dynamic_projection_from_mock_config` (mutates the mock SSOT and asserts the output follows), `test_dynamic_public_service_from_ssot`, `test_compute_total_services_calculation`
- [x] AC2 (Zero-Addressing isolation) -> `test_zero_addressing_sanitization`, `test_zero_addressing_guard_catches_leaked_ip`, `test_zero_addressing_guard_catches_leaked_ipv6`, `test_zero_addressing_guard_catches_internal_hostname`, `test_zero_addressing_guard_does_not_falsely_catch_mac_address`
- [x] AC3 (Deterministic drift gating) -> `test_drift_gate_across_simulated_commit_boundary`, `test_drift_gate_detects_mutation`, `test_drift_gate_missing_file_returns_error`, `test_provenance_determinism`, `test_provenance_content_hash`
- [x] AC4 (Makefile integration) -> `make sync-platform-json-check` returns exit 0; `make validate-sync` passes cleanly.
- [x] AC5 (Testing & safety boundary) -> 22 unit tests passing, **100%** branch/line coverage on `toolkit/features/platform_manifest.py`, which is what AC5 asks for. It was 97% while this line claimed 97% and the criterion said 100%; the gap was closed by covering the five real defensive paths that had none (corrupt existing manifest, `warning` node status, the `edge.traefik` fallback, non-mapping entries in the services tree, and an already-prefixed K3s version) rather than by rewording the criterion.

## Test status

- Test suite: `poetry run pytest tests/test_sync_platform_json.py` -> 22 passed, 100% coverage
- Manual smoke test: `make validate-sync` verifies `[SUCCESS] platform-json: in sync` and `[SUCCESS] All generated files in sync`
- No regressions in existing test suite: yes (all tests green)

## Decisions made during implementation

- **Content Hash Provenance over Git Commit SHA:** Derived `source_commit` from the pure-python git blob hash of `common.yaml` (equivalent to `git hash-object`) and preserved `generated_at` when content is unchanged. This prevents the chicken-and-egg commit boundary problem where `git log -1` would drift on every post-sync commit.
- **Zero-Addressing Sinkhole:** Replaced `0.0.0.0 / Blocked` in DNS Mermaid diagram with `Sinkhole / Blocked` to maintain zero IP leak false positives.
- **Low Cyclomatic Complexity:** Decomposed node and service extraction functions into dedicated single-responsibility helpers ensuring all functions maintain CC <= 14 (under the 15 threshold).
- **UTF-8 serialization:** Enforced `ensure_ascii=False` so accented characters (`ó`, `·`) render cleanly in web frontend.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons/`? Not needed now (captured in spec verification & commit message).
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? No (aligns with ADR-071 SSOT and ADR-056 Zero-Addressing).
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. No.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/TOOL-036-platform-manifest-sync/` -> `specs/archive/TOOL-036-platform-manifest-sync/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)

## Second review dispositions (added 2026-09-06, post-archive)

A second adversarial review ran after this spec archived — `agy/gemini-3.1-pro-high`
against `924eb47c`, the merged state, where the archiving review
(`nan/deepseek-v4-flash`, `521f5cc3`) predated five commits. Verdict again
PASS-WITH-GAPS. It was found uncommitted in a stale worktree, which is why it is
landed separately rather than by re-archiving; dispositions live here because
`verification.md` is outside the contract set the archive gate measures
staleness against.

| Finding | Reality claimed | Disposition |
|---|---|---|
| `source_commit` is a blob hash and `web` renders it as a link to a commit in `web` | Major, THEORETICAL | **Already carried** — same finding as the first review, recorded under "Gaps carried past the archive" in `tasks.md`. Fix belongs in the `web` repository. Unchanged. |
| `compute_total_services` returns `len(stg) + len(prd) + 2` with an undocumented offset | Minor, REAL | **Partly applied.** The offset is now documented — but NOT with the rationale the reviewer proposed. See below. |
| Four `monkeypatch` parameters are untyped, so `mypy tests/…` fails with 4 `no-untyped-def` | Minor, **claimed REAL** | **Does not reproduce.** See below. |
| `project_services` iterates the static `SERVICE_CATALOG_DEFAULTS` | Minor, THEORETICAL | **Already carried** in `tasks.md`. Unchanged. |
| A zero-addressing violation raises `ValueError` uncaught through `sync()` | Minor, THEORETICAL | **Already carried** in `tasks.md`. Fails closed, so UX rather than safety. Unchanged. |

### The mypy finding does not reproduce

Its stated evidence is `poetry run mypy tests/test_sync_platform_json.py` failing
with four `no-untyped-def` errors. Run against the sha the review names:

```
$ poetry run mypy tests/test_sync_platform_json.py
Success: no issues found in 1 source file
```

All four functions it names already carry `monkeypatch: pytest.MonkeyPatch` and
`-> None` (lines 169, 190, 212, 402), and `disallow_untyped_defs = true` is
global in `pyproject.toml`, not scoped to `toolkit` — so the "CI only checks
`mypy toolkit`, masking the untyped fixtures" explanation does not hold either.

Recorded rather than quietly dropped, because a review is trusted evidence: the
archive gate reads its verdict, and a finding labelled REAL and supported by a
pasted command result is exactly the kind of claim a reader would not re-run.
This one was worth re-running. Verify a finding by consequence, the same way the
code under review is verified.

### On the `+2`, and the docstring that was NOT used

An uncommitted docstring in the stale worktree explained the offset as
accounting for "core infrastructure workloads (edge ingress gateway and
kube-system) to preserve the published platform total of 35 services".

Nothing supports the first half. `ba1a2dd6`, the commit that introduced the
offset, says nothing about ingress or kube-system, and this file's own "Gaps
carried past the archive" records what is actually known: the `+2` exists to
keep the derived figure at 35 — the literal the change set removed — and whether
33, 35 or 39 is correct is an open product decision.

So the docstring that landed states that, and names the decision as open. A
comment that supplies a plausible reason for a number nobody chose converts an
unexamined default into an apparent decision, which is the shape lesson 427 is
about and the reason the gap was written down instead of closed.
