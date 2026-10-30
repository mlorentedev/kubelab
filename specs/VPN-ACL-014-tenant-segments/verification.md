---
tags: [spec, verification]
created: "2026-10-30"
---

# Verification - VPN-ACL-014-tenant-segments

## Evidence

- [x] AC1: `test_no_rule_grants_a_wildcard`,
  `test_rule_one_reaches_every_identity_the_policy_knows_except_tenants`.
- [x] AC2: `test_no_private_rule_names_a_segment_tag`,
  `test_segment_hosts_originate_nothing_and_clients_reach_only_the_declared_ports`,
  `test_segment_tags_are_owned_only_by_the_segment_owner`.
- [x] AC3: `test_a_malformed_segment_is_refused` (12 cases),
  `test_two_segments_sharing_a_tag_are_refused`, `test_the_segment_label_never_prints_tenant_data`.
  The assert expressions are evaluated by Jinja exactly as written in the role.
- [x] AC4: `test_the_wildcard_pattern_tells_old_policies_from_new_ones`,
  `test_a_previous_policy_with_a_wildcard_is_not_restored_while_segments_exist`,
  `test_the_fallback_is_the_segment_free_policy_not_an_allow_all`.
- [ ] AC5: `test_segments_reach_the_role_only_from_sops` passes; the pinned-image
  `policy-check` runs in CI.

## Test status

- `pytest tests/test_headscale_segments.py tests/test_headscale_role.py
  tests/test_headscale_probe_hub_source.py`: 63 passed (Windows, 2026-10-30).
- The other Headscale test files fail on this Windows workstation for portability
  reasons fixed in #2826, not for this change.
- `make mutate`: five mutants, all RED.

## Decisions made during implementation

- Rule 1's destinations live in role defaults, not in the template, so the role's
  segment validation and the template read one list.
- A segment owner may not be a private identity. A private user's untagged nodes
  fall into rule 1, so a segment owned by one would not be isolated.
- Rollback restores `.prev` only when it holds no quoted wildcard, or when no segment
  is declared; otherwise it renders the segment-free policy.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? Pending rollout: candidate "a wildcard destination makes every tenant visible, because a grant in either direction shows both peers".
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? Pending: possibly an ADR-041 amendment for tenant segments on the shared instance.
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. Pending.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/VPN-ACL-014-tenant-segments/` -> `specs/archive/VPN-ACL-014-tenant-segments/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
