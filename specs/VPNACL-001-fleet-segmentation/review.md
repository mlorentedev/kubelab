---
spec: "VPNACL-001-fleet-segmentation"
verdict: "FAIL"
reviewed_sha: "04d538e0cb1c0d421fe3067948aaaea65aeabf04"
reviewer: "nan/mimo-v2.6-flash"
date: "2026-10-10"
---

## Adversarial review

**Scope**: VPNACL-001-fleet-segmentation (round 1; no prior `review.md` existed — `review-transcript.jsonl` on disk is this run's own)
**Sources**: `specs/VPNACL-001-fleet-segmentation/{proposal,tasks,verification,features}.md|json`; diff `3733dce8b992bb23d10ffef01d92d664fc2dc453...HEAD` (launcher-resolved base = ADR-041 merge, where this spec's work starts), reviewed in full for the spec's footprint: `infra/ansible/roles/headscale/` (defaults, handlers, tasks, `config.yaml.j2`, `policy.hujson.j2`), `toolkit/scripts/headscale_probe.py`, `toolkit/scripts/render_headscale_policy.py`, `infra/ansible/playbooks/deploy-vps.yml` (policy host build), `.github/workflows/check-config-drift.yml`, `Makefile`, `tests/test_headscale_role.py`, `tests/test_headscale_probe_hub_source.py`, plus every later commit touching those files (`10966ba5` → `9b44456a` → `d31c506e` → `3f46c450` → `294ea621` → `be150e20`) so late fixes were judged against the early ones they modify.

### Spec and task alignment

- **AC1 (policy-path param, mount, reload-not-restart)** — met and re-verified: `headscale_policy_path` default `""` (allow-all no-op), `policy.path` templated, handler is `docker kill --signal=HUP headscale`, `config.yaml` change keeps the separate restart path. `poetry run pytest tests/test_headscale_role.py` → **28 passed** (fresh, this session); the three `features.json` f1 `-k` selections → 7 passed.
- **AC2 (`headscale policy check` CI gate)** — met: `make check-headscale-policy` → **"Policy is valid", exit 0** (real v0.28 image via Docker, run this session); gate step `Validate Headscale ACL policy` in `check-config-drift.yml` runs on `pull_request`/`push` to master/nightly, prod only.
- **AC3 (preserved flows + auto-revert)** — flows half **re-verified live today**: `toolkit infra headscale probe` → **7/7 PROBE OK, rc=0** against the production mesh from this workstation. Auto-revert restore has never executed (`TestAutoRevert` asserts YAML structure only) — disclosed in `verification.md`'s 2026-10-10 correction and ticketed #2184. Partial.
- **AC4 (SSH + tag + own credential)** — partial/superseded: subject `hermes-nan` retired 2026-09-30; `tag:hermes` now on `hermes-kubelab`; the C6 own-credential half never done (#590). `features.json` records `state: partial` for f3/f4 honestly.
- **No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags remain** in any spec file (only referenced as resolved history in `tasks.md`).
- **Task `[x]` claims** spot-checked against the diff: named tests exist and pass; SIGHUP handler exists; probe/backup/rescue tasks exist; CI step exists. No scope creep into VPN-ACL-004/005/006 observed (policy still permissive-first, no `tests` block, no rotation code).
- **Regression claim** re-verified fresh: full suite `pytest -m "not e2e and not infra"` → **4491 passed, 16 skipped, 2 xfailed, exit 0** (8m03s, this session).
- **Diff-scope note (not held against the implementer):** the launcher-resolved base is 902 commits back, so `git diff base...HEAD` is ~194k inserted lines / 2009 files, dominated by unrelated master history (backup, gitea, open-webui, deps…). I scoped the adversarial pass to the spec's footprint and its consumers rather than pretending to read 194k lines; `tasks.md`'s "no unrelated changes" claim is true of #235's own diff, not of this three-dot range.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | REAL | spec-vs-code / ACL | The proposal's **resolved operator decision** says `hermes` "is reachable **only by admin on `:22`** (`dst: tag:hermes:22`, via `acls`)" and ADR-041 §3 + `docs/runbooks/onboard-vpn-fleet-agent.md:52` repeat it. The shipped `policy.hujson.j2` has **no such rule**: rule 1 `{src:[kubelab@,manu@,work@], dst:["*:*"]}` admits **every port of `tag:hermes`** to all three identities. **Reproduced live, 2026-10-10:** from this workstation (`msi`, user `kubelab`), `timeout 5 bash -c '</dev/tcp/100.64.0.16/1055'` → **rc=0** (full TCP handshake to `hermes-kubelab`'s SOCKS proxy — a non-`:22` port on the tagged node), while `hermes-kubelab:22`/`:12345` time out only because the userspace-mode node drops un-listening ports (inconclusive alone; `ace1:22`/`ace2:22` rc=0 as method control). The same rule is what made the documented `ssh hermes-nan` (admin→:22) work under this policy, so user→tagged matching by rule 1 is doubly confirmed. The proposal's clause is also **not expressible alongside** a `dst: *:*` baseline (no dst negation), so either the clause or the baseline must give. | rendered policy (`poetry run python -c '…print(render_policy())'`) + live connect rc=0; `proposal.md` L37; `adr-041` §3 | UNTESTED — `test_hermes_egress_is_node_like_controlled`/`test_crown_jewels_excluded_from_hermes` cover egress only; nothing asserts the inbound matrix | **code** (add inbound restriction, e.g. deny `manu@`/`work@` → `tag:hermes:*` plus an explicit admin `:22` path — check v0.28 deny semantics first) **+ tests**; if the operator instead decides permissive-first defers this to VPN-ACL-004, the clause is wrong in **spec** (contract set → edit invalidates this verdict → re-review) |
| Major | REAL | AC3 / safety net | The auto-revert **restore** path has never executed anywhere: `TestAutoRevert` only asserts that the rescue YAML contains `.prev`, `kill --signal=HUP` and a `fail` — it never runs a revert. The one live probe failure took the first-activation branch (no `.prev`) and left the baseline in place (`verification.md` correction 2026-10-10). AC3 as written ("a deliberately-broken policy triggers auto-revert") is unmet. | `verification.md` correction; `tests/test_headscale_role.py::TestAutoRevert` read; #2184 open | UNTESTED (executable) — static structure assertions only | **tests** — the #2184 drill (or an integration harness) that restores a policy and proves the mesh returns; evidence to `verification.md` (non-contract) |
| Major | REAL | AC4 / C6 | Half of AC4 was never delivered: hermes "authenticates to at least one target service with its **own scoped credential**" — never provisioned, handed to #590; and the SSH half's subject (`hermes-nan`) no longer exists, so today no live subject proves AC4 at all. Honest and ticketed (`features.json` f4 `state: partial`), but an unmet acceptance criterion is what the archive gate exists to catch. | `tasks.md` VPN-ACL-003 `[~]` rows; `features.json` f4 evidence; #590 open | UNTESTED | **spec** (amend AC4 to match the superseded subject, contract → re-review) or **implementation** via #590, with evidence |
| Major | THEORETICAL | resilience / fail-open | Nothing verifies that headscale **accepted** the reloaded policy. If `policy.hujson` is rejected on SIGHUP (or the playbook's render diverges from the CI render), headscale keeps the previous/allow-all policy, the probe — under permissive-first — passes anyway, and the deploy reports success with **segmentation silently inactive**. Compounding: CI validates `render_headscale_policy.build_hosts()` while deploy renders `deploy-vps.yml` `_headscale_policy_hosts`; no test enforces parity (comment at `deploy-vps.yml:61` says "the two must agree" — nothing checks it). | code read of role + both render paths; no reproduction attempted | UNTESTED — no parity test, no post-reload `policy get`/digest check | **code** (post-reload confirmation the loaded policy matches the rendered one) + **tests** (build_hosts ↔ playbook parity) |
| Minor | REAL | traceability | `features.json` f4's `verification` command runs only `test_hermes_egress_is_node_like_controlled`, which exercises **egress** and says nothing about "SSH-reachable over VPN, carries tag:hermes, own scoped credential" — the behavior the row states. | `features.json` f4 vs test content | n/a | **spec** (features.json is contract set — fix alongside the FAIL round) |
| Minor | THEORETICAL | probe gating | AC3 says the probe confirms **all** preserved flows, but `rpi4 route 172.16.1.0/24` and `intra-K3s` are `required=False`: an ACL regression severing only those would be logged and the deploy would pass with **no auto-revert**. Deliberate (homelab power-state rationale, `test_optional_broken_flow_is_logged_not_fatal`), yet the `rpi4 route` flow is controller-sourced and always runnable during a deploy. | `headscale_probe.py` `preserved_flows`; named test cited | `test_optional_broken_flow_is_logged_not_fatal` (covers the behavior, not the AC tension) | spec disposition in `verification.md` / follow-up ticket |
| Minor | SPECULATIVE | process | All four AC checkboxes in `proposal.md` remain `- [ ]` while `tasks.md` closing claims coverage — archive will record a spec whose own AC boxes were never ticked. | `proposal.md` AC block | n/a | **spec** (contract — resolve in this FAIL round) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | C | AC1/AC2 verified end-to-end, but AC3's restore and AC4's C6 are unmet, and the declared inbound ACL matrix is contradicted by the shipped policy (reproduced live). |
| Verification       | C | Reproducible evidence for the gate, the tests and the live flows (all re-run this session), but the auto-revert restore and C6 halves have no evidence at all and f4's named verification doesn't test its own row. |
| Scope              | B | Spec footprint matches the proposal with no creep into VPN-ACL-004/005/006; the launcher's three-dot range is dominated by unrelated master history, noted rather than charged. |
| Reliability        | B | Rescue/first-activation fallback, probe retries, check-mode tolerance and idempotence (`.prev` backup `changed_when: false`) are handled; residual fail-open (no load confirmation) is THEORETICAL. |
| Maintainability    | B | Named, focused tests; clean template/probe structure; comments explain why — static-YAML tests are shallow by design and documented as such. |
| Handoff-readiness  | B | `verification.md` corrected in-session, lesson-275 + runbook + tickets #2184/#590 exist; but two ACs remain open at archive time and contract text overstates the inbound matrix. |

Rubric aggregation: C present, no D → PASS-WITH-GAPS *minimum* by rubric. Severity axis: **REAL Major(s)** → the more severe path governs.

### Verdict

**FAIL**

Driven by F1 (REAL, reproduced: proposal's "reachable only by admin on `:22`" vs a policy that admits all three user identities to every port of `tag:hermes`), reinforced by two REAL unmet-AC findings (F2 auto-revert never executed, F3 C6 credential never provisioned). F1 alone is a REAL Major and is decisive; F4 (THEORETICAL fail-open) and the Minors are tracked, not gating.

### Recommended next steps (minimum set that would flip this to PASS)

1. **Resolve F1 either way, then re-review** — it is the only finding that is both REAL and freshly reproduced:
   - *code path*: restrict inbound to `tag:hermes` in `policy.hujson.j2` (deny non-admin → `tag:hermes:*`, explicit admin `:22`; verify v0.28 deny/allow precedence semantics first) and add a named test asserting the inbound matrix the way `test_hermes_egress_is_node_like_controlled` asserts egress; confirm on prod with a connect test from a non-admin identity (the exact command above must go rc=124);
   - *spec path*: if the operator rules that permissive-first deliberately defers inbound narrowing to VPN-ACL-004, `proposal.md` L37 (and the runbook's step) must be corrected — a contract edit, which invalidates this verdict by design, so the next round is the mechanism.
2. **F2**: execute the #2184 drill (break a policy on prod, observe restore + reload + mesh recovery) or add an executable regression; put the output in `verification.md` (non-contract, editable freely).
3. **F3**: either deliver the C6 credential via #590 with evidence, or amend AC4 in `proposal.md` to match the superseded subject — contract edit, same re-review.
4. **F4** (tracked, not gating): add a post-reload check that the loaded policy equals the rendered one, and a parity test between `build_hosts()` and the playbook's `_headscale_policy_hosts`.
5. **F5/F7**: fix `features.json` f4's verification mapping and the proposal's unticked AC boxes in the same contract pass.

These recommendations ask for contract-set changes, which is what a FAIL verdict is for — do not attempt to land them alongside this verdict; re-run `dotf spec review VPNACL-001-fleet-segmentation` after the contract pass.

**`dotf spec archive` is NOT advisable in the current state** — this `review.md` is a FAIL and the archive gate will (correctly) refuse it.
