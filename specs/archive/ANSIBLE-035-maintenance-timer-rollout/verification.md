---
tags: [spec, verification, templates]
created: "2026-08-14"
---

# Verification - ANSIBLE-035-maintenance-timer-rollout

## Evidence

- [x] AC1 (gate vars: `maintenance_install_timer` defaults true, new `maintenance_run_cleanup` gates cleanup) -> `25b4e67`
- [x] AC2 (7 playbooks include the role, `maintenance_run_cleanup: false`) -> `25b4e67`
- [x] AC3 (`maintain.yml` unaffected) -> verified via `--list-tasks` (task set unchanged) + by inspection: `maintain.yml` doesn't set `maintenance_run_cleanup`, inherits the `true` default unaffected by this change; `maintenance_install_timer` is set explicitly regardless of the role default, both before and after
- [x] AC4 (live per-node rollout + idempotence) -> real `make provision NODE=<x> TAGS=maintenance` run + second real run per node, both confirmed `changed: 0` on the second pass, `systemctl is-enabled kubelab-maintenance.timer` = `enabled` on all 6 reachable nodes:
  - rpi3: first run `changed=4`, second `changed=0`, timer enabled, `Set hostname`/ufw work from OPS-017 unaffected
  - beelink: first run `changed=4`, second `changed=0`, timer enabled
  - rpi4: first run `changed=4`, second `changed=0`, timer enabled
  - ace1: first run `changed=4`, second `changed=0`, timer enabled
  - ace2: first run `changed=4`, second `changed=0`, timer enabled
  - vps: first run `changed=4`, second `changed=0`, timer enabled; K3s health re-verified after (`kubectl get nodes` -> Ready, `kubelab.live` -> HTTP 301) since this is the prod ingress node
  - **aws1: verified 2026-08-14, follow-up session.** The Spot instance recovered (`i-0be7ecf199975bf1a`'s replacement request cleared `capacity-not-available`, confirmed reachable via `tailscale ping`). Baseline checked first: the pre-existing hand-installed timer was already `enabled`/`active` (this is the ticket's original premise -- the fleet's only timer, installed by hand, on cattle), but none of this PR's additions existed yet (`/opt/kubelab-maintenance-notify.sh` missing, no `OnFailure=` on the unit, no secret file). `make provision NODE=aws1 ENV=hub TAGS=maintenance` run twice: first `changed=4` (matches all 6 other nodes exactly), second `changed=0`. Post-run: `systemctl is-enabled/is-active` both confirm, `OnFailure=kubelab-maintenance-notify.service` present, notify script + secret file present. Standalone delivery test (`systemctl start kubelab-maintenance-notify.service`) -> `Result=success, ExecMainStatus=0`, proving the fleet-wide secret resolves correctly from aws1's own `hub` env context, not just staging/prod. This closes the ticket's actual motivating case: a future Spot replacement now reinstalls the timer (with notify wiring) automatically via provisioning, not by hand.
- [x] AC5 (runbook) -> `docs/runbooks/maintenance-timer.md`
- [x] AC6 (OnFailure wiring: `OnFailure=kubelab-maintenance-notify.service` on the main unit, posts to prod n8n via a dedicated `fleet_webhook_secret`) -> `b46919b`
- [x] AC7 (notify path proven live, twice, per node where run) ->
  - Standalone delivery: `systemctl start kubelab-maintenance-notify.service` on rpi3 AND beelink (a staging-env node, to specifically prove the dedicated-secret fix works from a node whose own `deploy_env` isn't prod) -> both `Result=success, ExecMainStatus=0` (curl `-f`, so this means n8n returned 2xx)
  - `OnFailure=` linkage itself: on rpi3, installed a temporary `ExecStart=/bin/false` drop-in, ran `systemctl start kubelab-maintenance.service` -> failed as expected (`Result=exit-code`), journal shows `kubelab-maintenance.service: Triggering OnFailure= dependencies.` immediately followed by the notify unit starting and completing successfully. Drop-in removed, `systemctl reset-failed` run, timer confirmed still `enabled` afterward. Not repeated on every node -- one thorough proof of the linkage mechanism, per tasks.md's own design, then rolled out.
- [x] AC8 (rotate_note updated on both the existing `webhook_secret` SecretSpec and the new `fleet_webhook_secret` SecretSpec) -> `b46919b`

## Test status

- `make lint` / `make type` / `make test` (517 passed, 116 deselected): green after every commit in this branch.
- Manual smoke test: see AC4/AC7 above -- every node re-provisioned twice (idempotence), notify path exercised end-to-end on 2 of 7 nodes, `OnFailure=` linkage exercised via real failure injection on 1 node.
- No regressions: `make secrets-audit` reports prod 44/44 and staging **35/35**, both 100% after the secret-catalog change. Staging's base was 34/34 before this ticket; the new `fleet_webhook_secret` SecretSpec adds exactly 1. (An earlier revision of this line claimed 39/39 for staging -- unreproducible at any commit, corrected 2026-08-15 after the adversarial review reproduced the real counts at both `e63f1e0` and `b91c1f2`.)

## Decisions made during implementation

- Notify design initially assumed a direct Apprise integration; corrected after finding `apprise.yaml` is cluster-internal-only (`Cluster-internal only: no IngressRoute`). Real integration point is n8n's public `/webhook/notify` ingress.
- All 7 nodes notify to prod n8n regardless of their own `deploy_env`, to avoid the alert path depending on ace1 (staging n8n's host) being powered on -- user-confirmed design choice, measured live (prod n8n publicly reachable, real cert, 403-gated; staging needs VPN + self-signed cert).
- **Secret collision caught before shipping**: reusing the existing `apps.services.automation.notify.webhook_secret` key path for the fleet-wide notify secret would have collided with staging's own distinct value in the Ansible `combine()` merge for the 3 staging-env nodes (env override wins) -- verified by simulating the exact merge for all three node contexts (common-only, common+staging, common+prod) before writing any Ansible task. Fixed with a dedicated `fleet_webhook_secret` key, common.enc.yaml only, immune to any env override. Confirmed functionally correct afterward by running the standalone delivery test specifically from beelink (a staging-env node).
- **Second bug caught live**: 4 of the 7 playbooks (vps, aws1, rpi3, rpi4) didn't tag their config/secrets pre_tasks as `always`, so `--tags maintenance` silently skipped secret loading -- surfaced as `'secrets' is undefined` on the first attempt to deploy the notify unit. beelink/ace1/ace2 already had this tagged correctly, each with a comment naming this exact failure mode; brought the other 4 in line with that existing pattern rather than inventing a new one.
- aws1 down for the entire original session (Spot interruption); rollout there deferred, tracked as a follow-up above rather than silently claimed as done, then completed once the node recovered (see AC4/AC7 above).

## Adversarial review disposition (round 1: FAIL, `nan/deepseek-v4-flash`, reviewed_sha `b91c1f2`)

- **F1 (Major, REAL) — staging secret count unreproducible. FIXED.** The reviewer was right: the claim of 39/39 is reproducible at no commit. `make secrets-audit` in this session gives dev 28/32, **staging 35/35**, prod 44/44. The "Test status" line above is corrected and now records the base (34/34) and the +1 the new SecretSpec adds, so the number can be re-derived rather than trusted.
- **F2 (Major, REAL) — no automated regression tests. FIXED.** `tests/test_node_maintenance_notify.py` added: **15 tests**, rendering the role's templates with `StrictUndefined` and executing the JSON encoder extracted from the rendered script (so the test exercises the shipped code path rather than a copy that can drift from it). It pins the `OnFailure=` linkage — the single line the whole alert path hangs from, whose removal breaks nothing observable: maintenance keeps running, it just stops reporting its own failures — that the `OnFailure=` target names a unit the role actually installs, that the notify unit's `ExecStart` matches what `tasks/main.yml` deploys, that `maintenance_notify_domain` stays a literal rather than a per-env derivation, and that the journal body survives JSON encoding across six inputs including a deliberately truncated multi-byte sequence. **This change adds exactly 15 tests and breaks none** — the reproducible claim. Absolute totals depend on the base: 517 → 532 measured on `b91c1f2`, then 546 (134 deselected, 0 failures) after rebasing onto `bc7e31b`, which brought 14 more tests from parallel lanes. Verify the delta, not the total: `poetry run pytest tests/test_node_maintenance_notify.py` → 15 passed, and `poetry run pytest tests/ -m "not e2e and not infra"` → 0 failures. *(An earlier revision of this line asserted the bare total, which stops being reproducible the moment master moves — the same defect F1 failed this spec for, caught here before it shipped.)*
- **Minor #1 (curl has no timeout) — CONFIRMED, FIXED.** `--connect-timeout 10 --max-time 15` added. Without them an unreachable n8n stalls the unit until systemd's `TimeoutStartSec=30` kills it: bounded, but a 30s delay on the one path whose job is to report promptly.
- **Minor #2 (UTF-8 truncation crashes the encoder) — CONFIRMED, FIXED.** Reproduced before fixing rather than accepted from the report: `printf 'caf\xc3' | python3 -c "...sys.stdin.read()..."` → `UnicodeDecodeError: can't decode byte 0xc3 in position 3: unexpected end of data`. `tail -c 2000` cuts on a byte boundary, so a multi-byte character straddling it loses the notification at the exact moment it matters. Fixed with `sys.stdin.buffer.read().decode('utf-8', 'replace')`; `split-utf8-sequence` is kept as a parametrized regression case.
- **Minor #3 (token interpolated into a shell string) — REFUTED, withdrawn.** Not a shell-injection sink. Expanding a variable inside double quotes does not re-parse its value; a secret file containing `$(touch ...)` and backticks was passed to curl as a literal argv element and neither ran (verified by injecting both forms and confirming zero side effects). The finding reasons by analogy with `eval`, which this path does not use. Notably its proposed remediation — `curl --config <file>` — would have written the bearer token to disk to defend against an attack that does not exist, so applying it unexamined would have been a net regression. `test_token_value_is_not_shell_interpreted` now pins the property, failing if anyone later "hardens" it into an `eval` or an unquoted expansion. Recorded on #1088.
- **Consequence accepted:** fixing #1 and #2 changes the deployed script, so AC7's original live evidence was re-established rather than inherited. See "Re-verification after ANSIBLE-038 fixes" below.
- **New in this pass:** `make maintain-notify-test NODE=x` (playbook `infra/ansible/playbooks/maintenance-notify-test.yml`) codifies the live delivery check that was previously an operator's one-off `systemctl start` over SSH. Written because F1 failed this spec for an unreproducible claim, and re-establishing AC7 with another uncodified one-off would have repeated that defect in a different shape.

## Adversarial review disposition (round 2: PASS, `nan/deepseek-v4-flash`, reviewed_sha `4619a57`)

Both round-1 Majors confirmed closed by the reviewer, which reproduced the claims rather than reading them: `make test` (532/129), `secrets audit` (staging 35/35, prod 44/44), and syntax checks across the 8 playbooks. Verification graded A, up from C. Four new Minor findings, none blocking:

- **Stale acceptance checkboxes in `proposal.md` (Minor, REAL) — FIXED.** AC4 still read "6/7 done … aws1 was offline" and AC8 was unticked, both contradicted by evidence already in this file. Ticked and reconciled. Worth naming the pattern rather than just the instance: this is the same defect as F1 — a spec artifact asserting something the evidence disproves — and it survived a round precisely because a checkbox looks like bookkeeping rather than a claim.
- **Bearer token visible in `ps` (Minor, THEORETICAL) — TICKETED, #1088.** A different mechanism from round 1's refuted shell-injection finding, and this one holds: the header becomes an argv element of `curl`, so it is readable in `/proc/<pid>/cmdline` for about a second. The round-1 refutation showed the value is not re-parsed by the shell; it said nothing about where the value ends up once it is a curl argument. Fixable without putting the token on disk (`curl --config -` fed from a pipe).
- **Notify unit has no `Restart=` (Minor, THEORETICAL) — TICKETED, #1088.** One attempt, no retry, on the path whose job is to report. The script comment documents the absence of an `OnFailure=` *cascade*, which is not the same thing as documenting the absence of a *retry*.
- **`no_log: true` hides idempotency on the secret-write task (Minor) — ACCEPTED AS-IS,** per the reviewer's own recommendation: `copy:` is checksum-idempotent, and suppressing the output is deliberate so the secret never reaches Ansible's log.

Both ticketed findings require a fleet re-provision, so they are bundled on #1088 with the beelink remainder — one re-provision closes all three.

## Re-verification after ANSIBLE-038 fixes

The two confirmed Minor fixes change `kubelab-maintenance-notify.sh.j2`, so AC7's original evidence describes a script that is no longer deployed. It was re-established, not inherited.

**Re-provision** (`make provision NODE=<x> [ENV=…] TAGS=maintenance`) — every reachable node reported `changed=1, failed=0`, the single change being `Install maintenance notify script`:

| Node | ENV | Result |
|---|---|---|
| rpi3 | staging | `ok=16 changed=1 failed=0` |
| rpi4 | staging | `ok=14 changed=1 failed=0` |
| ace1 | staging | `ok=22 changed=1 failed=0` |
| ace2 | staging | `ok=21 changed=1 failed=0` |
| vps | prod | `ok=19 changed=1 failed=0` |
| aws1 | hub | `ok=17 changed=1 failed=0` |
| beelink | staging | **DEFERRED — unreachable** (`tailscale ping` fails; on-demand node, powered off) |

**Live delivery** (`make maintain-notify-test NODE=<x> [ENV=…]`) — all six reachable nodes returned `Result=success, ExecMainStatus=0`. Since the unit's curl uses `-f`, that is a real 2xx from prod n8n, not merely a script that ran:

`rpi3`, `rpi4`, `ace1`, `ace2`, `kubelab-vps`, `aws1` — six for six.

This is **stronger** than round 1's evidence, not merely equal to it: the original AC7 exercised delivery on 2 of 7 nodes and reasoned the rest by symmetry. This pass exercised 6 of 7, including the prod ingress node and the hub, each from its own env context.

**beelink remainder.** Deferred exactly as aws1 was in round 1 — recorded rather than silently claimed. It still runs the previous, verified script; the fix is an improvement to an already-working path, not a repair of a broken one, so the node is not degraded while it waits. Tracked on #1088, which stays open for this remainder. Re-provision and re-test it with the two commands above when the homelab is next powered on.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons.md`? **Yes, written** -- two entries: the apt check-mode/virtual-package gotchas (OPS-017) and the untagged-pre_tasks + secret-key-collision gotchas (this ticket). Commit `0439a18`.
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? No -- these are role/playbook-level design choices (gate variables, secret key naming), not architecture-level.
- [ ] New pattern candidate for `00_meta/patterns/`? No -- single-project evidence so far (matches the same "single-project, flag for next /crystallize" disposition this lane used on the equivalent OPS-022 question).

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/ANSIBLE-035-maintenance-timer-rollout/` -> `specs/archive/ANSIBLE-035-maintenance-timer-rollout/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
- [ ] **aws1 rollout follow-up (see AC4) resolved** -- not a blocker for merging this PR, but should not be forgotten; either close it out before archiving this spec or open a small follow-up issue at archive time.
