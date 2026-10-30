# Run segment-20261030T0545Z: report

**Verdict:** run segment-20261030T0545Z ended `budget-items` at 2026-10-30T09:30Z. All 4
queue items are done, after about 12 iterations and 3.7 h (05:45Z to 09:30Z). 5 PRs
were landed by this session (#2820, #2821, #2823, #2832, #2826). One corporate PR is
open and waiting for you: teledyne-e2v/pixelnam-lab#8. Nothing is parked.

**Nothing irreversible happened in production:** no deploy, no policy reload, no enrolment.
The landed code takes effect only when you deploy the VPS by hand.

## Waiting on you (irreversible first)

1. **Production rollout of the tenant segment, VPN-ACL-014 (#2830).** The mechanism is
   in `master` (`72a4c689`). The order is in `specs/VPN-ACL-014-tenant-segments/tasks.md`:
   1. `make deploy TARGET=vps ENV=prod` with no segment in SOPS. The only change is
      rule 1's explicit destinations, which equal today's wildcard for all 14 nodes.
      Before rendering, the role checks every live node is still reached. Then compare
      `ssh -F $HOME\.ssh\pixelnam-automation\config lab-control 'docker exec headscale headscale policy get'`
      with the render.
   2. `toolkit secrets set` the segment at `apps.services.core.headscale.segments`:
      `[{owner: <new user>, hosts_tag: tag:pixelnam-lab, clients_tag: tag:pixelnam-client, ports: [22, 45000]}]`.
      Pick the user name; the role creates the user.
   3. Deploy again, check the effective policy again, then deploy a third time and expect
      `changed=0`.
2. **Merge teledyne-e2v/pixelnam-lab#8** (the NODE-001 audit and the bridge candidate).
   That repository has no merge grant.
3. **Bridge pin (NODE-001 AC5).** ts-bridge v1.20.0 windows-amd64 has SHA-256
   `034c6bff288ad0b32c669bc876cab7250ad262c0ae53cbde4376746784868d0c`. It matches
   `checksums.txt`, but the release has no provenance. Either accept it, or land
   mlorentedev/ts-bridge#518 (SEC-003, a CI workflow change, so a human merge) and use
   the next release.
4. **DNS residual.** On v0.28, every node receives the split-zone resolver address. It is
   unreachable under the policy, but visible. Accept it, or retire what can be retired
   (OPS-019, #964) first.

## Parked

None.

## Done

| PR | What | Merge |
|---|---|---|
| #2820 | Hosts-owner test: UTF-8 reads and POSIX paths (VPN-ACL-006 G7) | `cd38905` |
| #2821 | VPN-ACL-006 spec frozen, digests re-resolved | `1a1a56d` |
| #2823 | AC1 upgrade eligibility preflight, fail-closed expiry | `49411256` |
| #2832 | VPN-ACL-014 tenant segments (inert) | `72a4c689` |
| #2826 | Native-Windows portability, CVE-2024-4030 scratch refusal, lesson-666 | `e396d062` |

Also filed: #2830 (VPN-ACL-014, In Progress) and mlorentedev/ts-bridge#518 (SEC-003, Backlog).

## Evidence index

| Item | Command | Result |
|---|---|---|
| #2820 | `pytest tests\test_headscale_role.py tests\test_headscale_hosts_entry_owner.py tests\test_headscale_probe_hub_source.py` | 37 passed (2 failed before) |
| #2823 | `pytest tests\test_headscale_upgrade.py -k eligibility` | 41 passed; 7 mutants RED |
| #2832 | `pytest tests\test_headscale_segments.py tests\test_headscale_role.py` | 66 passed; 10 mutants RED; CI `policy-check` printed "Policy is valid" twice |
| #2826 (after merging master) | `pytest tests\test_lesson_index_integrity.py tests\test_core_io.py tests\test_restore_drill.py tests\test_app_drill.py tests\test_headscale_*.py` | 458 passed on Windows |
| Audit | `ssh lab-control`: version, `policy get`, users, nodes | all four exited 0; the live policy equals the render; 14 nodes, 4 users |

## Budget

About 12 iterations, 3.7 h, 4 of 4 items. No cost figure is available.

## Host

Sleep is disabled (AC and DC standby are both 0), so the window was covered.

## Coordination

- #2826 was held about 1 h so it would not conflict with #2833 (another session) in the
  lesson index, and landed after #2833 did.
- #2840 (another session) already conflicts with `master` in that index, independently
  of #2826.

## Next action

Run VPN-ACL-014 rollout step 1, a deploy with no segment, in an approved window.
