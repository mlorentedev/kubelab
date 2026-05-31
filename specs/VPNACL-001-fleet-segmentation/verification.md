---
tags: [spec, verification]
created: "2026-05-31"
---

# Verification - VPNACL-001-fleet-segmentation

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, observed behavior). Filled during implementation.

- [ ] AC1 (role policy-path param + reload-on-change) -> commit `<hash>` / molecule or render test `<name>`
- [ ] AC2 (`headscale policy check` CI gate) -> CI run `<link>`
- [ ] AC3 (permissive baseline preserves flows + auto-revert) -> probe output `<evidence>`
- [ ] AC4 (hermes SSH-reachable, tagged, own-credential auth) -> `headscale nodes list` + service-auth observation

## Test status

- Test suite: `<command> -> <output>`
- Manual smoke test: probe of preserved flows post-reload; deliberately-broken-policy auto-revert exercised
- No regressions in existing test suite: yes / no

## Decisions made during implementation

- (log non-obvious trade-offs here during the work)

## Promotion candidates

- [ ] Lesson for `90-lessons.md`? <likely yes — permissive-first + external-probe rollout on a single Headscale control plane without the v0.29 tests block>
- [ ] ADR-worthy decision? <no — ADR-041 already covers the model>
- [ ] New pattern candidate for `00_meta/patterns/`? <maybe — "deny-by-default rollout on a single control plane via permissive-first + external probe + auto-revert" if it recurs>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/VPNACL-001-fleet-segmentation/` -> `specs/archive/VPNACL-001-fleet-segmentation/`
- [ ] Backlog entries `VPN-ACL-001/002/003` ticked in vault `11-tasks.md` with PR link
- [ ] Promotions above executed (if any)
