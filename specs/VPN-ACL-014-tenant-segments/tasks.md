---
tags: [spec, tasks]
created: "2026-10-30"
---

# Tasks - VPN-ACL-014-tenant-segments

`[ACn]` maps a step to `proposal.md`; `[P]` means no dependency on another
unchecked step.

## Setup

- [x] Open issue #2830, self-assigned, In Progress. ✓ 2026-10-30
- [x] Worktree `feat/vpn-acl-014-tenant-segments` from `origin/master`. ✓ 2026-10-30
- [x] Read-only audit of the live policy (14 nodes, 4 users, live equals the
  rendered template). ✓ 2026-10-30, recorded in the tenant's own repository.

## Implementation

- [x] [P] [AC1] [AC2] [AC3] [AC4] [AC5] Write `tests/test_headscale_segments.py`;
  run it: RED at collection (`EXAMPLE_SEGMENT` missing). ✓ 2026-10-30
- [x] [AC1] Rule 1 destinations from `headscale_policy_private_users` +
  `headscale_policy_private_destinations` (role defaults). ✓ 2026-10-30
- [x] [AC2] Segment `tagOwners` and client rule in `policy.hujson.j2`, from
  `headscale_policy_segments`. ✓ 2026-10-30
- [x] [AC3] Two `assert` tasks before the render; loop label prints an index only.
  ✓ 2026-10-30
- [x] [AC4] Rescue: `hs_prev_safe` decides the `.prev` restore; the fallback renders
  the template with no segment. ✓ 2026-10-30
- [x] [AC5] `deploy-vps.yml` reads segments from `secrets`; `render_policy(segments=)`
  and `policy-check` validate a synthetic segment too. ✓ 2026-10-30
- [x] [AC1] [AC4] Update the two guards in `tests/test_headscale_role.py` that pinned
  the old wildcard and the allow-all fallback. ✓ 2026-10-30
- [x] Mutation: rule 1 back to a wildcard, segment hosts as a source, owner check
  removed, `.prev` restored unconditionally, LAN route dropped. All five RED.
  ✓ 2026-10-30

## Rollout (production, operator-approved window; not authorized by this spec)

- [ ] Deploy once with no segment in SOPS (`make deploy TARGET=vps ENV=prod`), so
  `.prev` becomes a policy this template rendered. Check the probe, then read the
  effective policy through the audit identity and compare it with the render.
- [ ] Write the segment to SOPS at `apps.services.core.headscale.segments`.
- [ ] Deploy again. The role creates the owner user if missing, then renders and
  reloads the segment. Repeat both checks.
- [ ] A third deploy reports `changed=0`.

## Closing

- [x] Every acceptance criterion has a test and a `features.json` entry whose
  selector is non-empty.
- [ ] `toolkit infra headscale policy-check` green in CI (Docker is not available
  on the authoring workstation).
- [ ] Rollout evidence in `verification.md`; independent review before archive.
