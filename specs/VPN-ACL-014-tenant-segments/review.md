---
spec: "VPN-ACL-014-tenant-segments"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "51a4a80dbcf39e0eaf8aafa977a308ab6ef67b32"
reviewer: "nan/glm5.3-flash"
date: "2026-10-30"
---

## Adversarial review

**Scope**: VPN-ACL-014-tenant-segments — PRs #2832 (implementation), #2850/#2852/#2853/#2856 (SOPS mapping + rollout + review follow-ups), all merged; reviewed at HEAD `51a4a80d` (base `15f6fe5c` per review-request.json).

**Sources**: `specs/VPN-ACL-014-tenant-segments/{proposal,tasks,verification,features}` + `gh pr diff 2832/2852/2853/2856` + current files at HEAD (`infra/ansible/roles/headscale/{tasks,templates,defaults}`, `infra/ansible/playbooks/deploy-vps.yml`, `tests/test_headscale_segments.py`, `toolkit/scripts/render_headscale_policy.py`).

### Spec and task alignment

- All seven ACs map to named tests in `tests/test_headscale_segments.py` (and two updated guards in `test_headscale_role.py`); the tests evaluate the role's own Jinja assert expressions, not re-implementations — the strongest shape this repo's Ansible-only test environment allows.
- AC1/AC2/AC4 verified by fresh run (below); AC3 verified for its 12 enumerated cases; AC5 verified against CI, not only claimed; AC6/AC7 guard tasks run before the render (order asserted by `test_the_validation_runs_before_the_policy_is_rendered`, `test_the_live_node_check_runs_before_the_policy_is_rendered`, `test_owner_creation_runs_before_the_render_quotes_its_argument_and_prints_no_name`).
- Rollout evidence in `verification.md` states its comparison method (render from `render_policy(segments=)` vs `policy get` through the audit identity, both comment-stripped, JSON-equal) and correctly demotes the convergence deploy to idempotency-only. The acceptance rests on step 3's read-back — honest framing.
- Test deletions: two guards in `test_headscale_role.py` were *rewritten*, not deleted (`test_permissive_first_rule_preserves_existing_identities` → `test_rule_one_preserves_existing_identities_without_a_wildcard`; `test_first_activation_reverts_to_allow_all` → the segment-free fallback test). Each pinned a contract the spec explicitly reversed (wildcard rule 1, allow-all fallback); the new guards pin the replacement contracts, and `test_no_rule_grants_a_wildcard` covers the wildcard side. Retention bar met; the allow-all deletion is additionally protected by `test_the_fallback_is_the_segment_free_policy_not_an_allow_all`.
- `tasks.md` has two unchecked Closing boxes: "policy-check green in CI" is checkbox lag (CI is green — evidence below) and "independent review before archive" is this review; no `[x]` without diff evidence found.
- No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags in the spec artifacts.

### Fresh evidence (this session, at `51a4a80d`)

- `poetry run python -m pytest -o addopts= -p no:cacheprovider tests/test_headscale_segments.py tests/test_headscale_role.py tests/test_secrets_input_hardening.py -q` → **94 passed** (after `poetry install --with dev` in this review worktree).
- `gh run list --workflow=check-config-drift.yml` → run at `51a4a80d` (2026-10-30T20:22:56Z) **success**; the workflow runs `poetry run toolkit infra headscale policy-check` (segment-free + synthetic segment on the pinned image) — AC5's CI half verified, not assumed.
- Not independently re-run: `make mutate` (ten mutants, all RED — claimed in `verification.md`), and the production read-backs (operator's controller; raw outputs intentionally out of the repository).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | AC3 / injection | Segment tag validation checks only the `tag:` prefix and non-membership in private tags. A tag containing `"` (or a space, `,`, `{`) passes validation and is interpolated raw into `policy.hujson.j2` (`"{{ segment.hosts_tag }}"`), corrupting the policy. On v0.28 the reload can then be rejected while the deploy reports green (the #2190 failure mode this spec cites), or in the worst case the corrupted HuJSON parses with unintended grants. Input is SOPS, operator-controlled — not attacker-facing — and never observed; hence not a Blocker. But AC3's own words ("with a malformed tag … refused") cover this shape and the code does not. | Code read of `tasks/main.yml` assert block vs `policy.hujson.j2` interpolation; `test_a_malformed_segment_is_refused`'s 12 cases include no quote/space/brace payload | UNTESTED | code + tests (character whitelist in the assert; refusal cases with `"`, space, `{`) |
| Minor | THEORETICAL | AC4 / rollback | With segments declared, a `.prev` rendered by *this* template under a *previous* segment set (marker present, no wildcard) passes `hs_prev_safe` and is restored on probe failure — reinstating grants for a segment possibly renamed or removed from SOPS since. The restored grants are themselves isolated, so isolation holds; the residual is a stale-but-benign grant pair until the next successful deploy re-renders. | Code read of the `hs_prev_safe` expression; no repro | `test_a_previous_policy_is_restored_only_when_safe` covers marker/wildcard but not the stale-segment case (UNTESTED for this residual) | code (compare restored tags against current SOPS) or accept with a note |
| Minor | THEORETICAL | AC7 / first install | When the container does not exist (`No such container` tolerated in `failed_when`), `users list` fails → the `hs_users_list.rc | default(1) == 0` guard silently skips owner creation, while the policy still renders naming `owner@` — the unknown-user reload risk on a fresh install. Current production node is unaffected (container exists; step 3 created the owner). | Code read of the two guard `when:` clauses | UNTESTED | code (fail loudly when segments are declared and the users list could not be read) or accept |
| Minor | THEORETICAL | AC6 / drift | `test_every_node_the_live_server_held_is_accounted_for` pins a dated fixture (2026-10-30). New nodes after that date make the test green-but-stale. The deploy-time guard is the live enforcement, so this is a regression-only check; noted so nobody reads the fixture test as ongoing coverage. | Fixture `_source` field | `test_every_node_the_live_server_held_is_accounted_for` (named, and itself the thing going stale) | tests (refresh fixture on next live read) or spec note |
| Minor | THEORETICAL | AC4 / rollback | A hand edit to a `.prev` *after* this template rendered it still carries the marker; the guard checks marker + no wildcard, so a hand-added CIDR grant could be restored. Operator self-inflicted; the defaults comment already concedes CIDRs for pre-014 policies. | `headscale_policy_marker` comment in `defaults/main.yml` | UNTESTED | accept (documented residual) |
| Question | — | features.json | All seven entries are `state: pending` with empty `evidence`, while `verification.md` carries per-AC evidence. The digest normalisation ignores harness-owned state, so this does not invalidate the review — but confirm whether `dotf spec archive` demands a different state, before the archive attempt. | `features.json` content | — | spec artifacts (fill states) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All seven ACs verified with negative paths; one negative-path gap (malformed tag characters) and two low-impact edge cases open |
| Verification       | A | Reproducible commands per AC, stated comparison method, rollout read-backs; CI green verified fresh this session |
| Scope              | A | Diff matches the proposal; SOPS-mapping detour (#2852) and review follow-ups (#2856) are documented inside the spec artifacts |
| Reliability        | B | Rollback redesigned to preserve isolation and probed; first-install and stale-`.prev` edges unhandled but out of the current deployment path |
| Maintainability    | A | Tests evaluate the role's own expressions (fail when the role changes, survive renames); comments explain WHY; functions small |
| Handoff-readiness  | B | Spec carried through rollout into `verification.md`; promotion candidates and archive checklist pending by design; two task checkboxes lag reality |

### Verdict

PASS WITH GAPS — no Blocker; the single Major is THEORETICAL (operator-controlled input, never observed); rubric all B or above. Tracked findings carry dispositions below.

### Recommended next steps

Routed by set: on PASS WITH GAPS the contract set (`proposal.md`, `tasks.md`, `features.json`) is closed — the following are for the implementer to disposition in `verification.md` (applied / ticketed / declined with reason), or to carry into a follow-up ticket.

- F1 (Major, tag characters): add a character whitelist to the segment assert and refusal cases with `"`, space, `{` payloads — code + tests; ticket if deferred. This is the only finding I would not let silently lapse: it is the one place where a typo in SOPS converts this spec's guarantee into the silent green-deploy failure the spec itself cites as motivation.
- F2/F5 (stale or hand-edited `.prev`): accept with a one-line note in `verification.md`, or ticket the compare-against-current-SOPS guard.
- F3 (first install): ticket a loud failure when segments are declared but the users list is unreadable; low urgency (fresh-install path only).
- F4: refresh the node fixture at the next live read, or note its regression-only role beside the test.
- Q1: fill `features.json` state/evidence (or confirm the archive tooling ignores it) before `dotf spec archive`.
- Tick the "policy-check green in CI" Closing box (CI evidence above) and this review's box in `tasks.md`.
- Promotion candidates in `verification.md` remain unanswered — the archive gate refuses unanswered lines; resolve the lesson candidate ("a wildcard destination makes every tenant visible…") at archive time.
