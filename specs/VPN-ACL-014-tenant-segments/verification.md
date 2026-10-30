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
- [x] AC4: `test_the_wildcard_pattern_tells_old_policies_from_new_ones` (wildcard ports
  included), `test_only_a_policy_this_template_rendered_carries_the_marker`,
  `test_a_previous_policy_is_restored_only_when_safe` (the rescue's own expression,
  evaluated by Jinja), `test_the_fallback_is_the_segment_free_policy_not_an_allow_all`.
- [x] AC5: `test_segments_reach_the_role_only_from_sops`. CI on `fef5715d`: `Drift / prod`
  and `Drift / staging` passed, and they run `toolkit infra headscale policy-check`
  (segment-free and synthetic segment) on the pinned image.
- [x] AC6: `test_every_node_the_live_server_held_is_accounted_for` (the 2026-10-30 node
  list), `test_a_node_rule_one_would_cut_off_stops_the_deploy`,
  `test_a_tenant_node_is_accounted_for_by_its_segment`.
- [x] AC7: `test_a_missing_owner_is_created_once_and_an_existing_one_never` (the loop
  expression evaluated by Jinja),
  `test_owner_creation_runs_before_the_render_quotes_its_argument_and_prints_no_name`.

## Rollout evidence

- **Step 1, 2026-10-30** (deploy with no segment, from the operator's controller). The
  policy was read back through the audit identity: policy get and 
odes list both
  exited 0. The effective policy equals 
ender_policy() (segment-free), ignoring
  comments and whitespace. It carries the template marker and no wildcard grant, and
  rule 1 lists kubelab@, manu@, work@, gents@, 	ag:hermes and lan-rpi4,
  each on every port. The server holds 14 nodes, 9 online, as before.
- **Step 2, 2026-10-30.** The segment is written to prod.enc.yaml under a neutral
  key. Decrypted: one entry, with fields owner, hosts_tag, clients_tag and
  ports; the ports are the integers [22, 45000].
## Test status

- `pytest tests/test_headscale_segments.py tests/test_headscale_role.py
  tests/test_headscale_probe_hub_source.py`: 71 passed (Windows, 2026-10-30).
- The other Headscale test files fail on this Windows workstation for portability
  reasons fixed in #2826, not for this change (17, unchanged by this branch).
- `make mutate`: ten mutants, all RED (five for the first commit, four for the
  live-node guard, the marker and the wildcard-port pattern, one for owner creation).

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
