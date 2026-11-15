---
tags: [spec, verification]
created: "2026-11-14"
id: "AI-013-hermes-liveness"
type: spec-verification
status: active
owner: manu
---

# Verification - AI-013-hermes-liveness

## Evidence

- [x] **AC1 — detection and delivery:** local contract is green. In the clean live drill the gateway stopped at `2026-11-14T21:22:43Z`; the probe failed because it was `unhealthy`, `kubelab-notify@` returned success and `ops-log` recorded the incident at `21:22:47.606959Z`. No duplicate page appeared.
- [x] **AC2 — recovery and semantics:** 26 focused tests pass. Healthy and one recent start younger than 90 seconds with `RestartCount <= 1` succeed; sustained `starting`, repeated restart, stopped/unhealthy/missing containers, invalid metadata and Docker failure return non-zero. Invalid container names exit 64 before Docker runs. The simple `/health` check contains no credential, Slack or provider readiness. `OnSuccess=kubelab-notify-recovered@%n.service` is rendered.
- [x] **AC3 — on-demand silence:** tests prove no `Persistent`/`OnCalendar` directive, no Kuma monitor and no always-on dependency. The timer runs locally after ten minutes of boot grace or two minutes after a mid-session activation. **Power-off was not physically exercised**; no external path exists that could emit a page while ace2 is off. A powered-on but hung host is explicitly accepted as uncovered; no independent node-liveness alert is claimed. The watcher deliberately remains independent of the egress kill switch, so daemon failure cannot disable its own detector.
- [x] **AC4 — configuration lifecycle:** role-ordering tests prove the timer starts only after unit installation plus API, Slack and Docker health checks, and the unconfigured path disables/removes the watcher before Compose teardown. Provisioning waits for Docker health before enabling the timer; the read also runs safely in check mode. A deployment failure after a pause runs `rescue`, restores the timer and then propagates the failure.
- [x] **AC5 — reproducible evidence:** local suite and lint are green. Initial provisions measured `changed=5` then `changed=0`; the systemd socket correction measured `changed=1`, and the final post-drill provision measured **`changed=0`, `failed=0`**. In the clean drill, restart reached Docker health at `21:23:43Z`; the probe and recovery notifier returned success and `ops-log` recorded `recovered … after 1 failed runs` at `21:23:44.059549Z`. Failure-to-recovery delivery spanned 56.453 seconds. The review-fix recreation measured `changed=4` and its next provision `changed=0`, with zero new watchdog messages. Direct-fix provisions also reached `changed=0`, `failed=0`; a baseline-controlled real restart observed `starting`, returned `grace_rc=0`, then healthy/probe success with zero new watchdog messages. No ace2 power-off was performed.

## Test status

Initial watched RED showed the absent implementation, and the final focused/direct-fix suites are green. The relevant excerpts are inline rather than references to session-local log files:

```text
Initial contract: 16 failed, 2 passed.
First review hardening: 3 failed, 17 passed -> 20 passed.
Direct AC2/AC4 hardening: 5 failed, 21 passed -> 26 passed.
Neighboring Compose/role/notification suites: 320 passed, 16 skipped.
```

The first full run introduced four hygiene failures (UTF-8, bare bash and two check-mode contracts), all corrected. Full-suite evidence after review fixes is:

```text
10631 passed, 96 skipped, 30 warnings in 332.46s
TOTAL coverage: 78%
make lint: All checks passed; 169 files already formatted
make type: Success, 168 source files
make lint-ansible: All 26 playbooks parse
shellcheck bash/sh, bash -n, zsh -n, git diff --check: passed
```

A final full-suite run remains required after the direct AC2/AC4 changes. Live manual smoke was operator approved: clean stop/start produced exactly one failed run, one `ops-log` incident and one recovery; final gateway was `running/healthy`, timer active, both notifiers `Result=success`, spool 0. No credentials were printed.

## Decisions made during implementation

- Chose local Compose health + systemd fabric delivery over Kuma push or an external tailnet probe. Kuma's `on-demand` mute would suppress the very agent failure being detected; an external probe would add the #2189 dependency.
- Kept the watchdog independent of `agent-stack-egress.service`. The runbook now requires stopping the timer before an intentional silent kill-switch stop; an unexpected daemon/egress failure still pages.
- Liveness uses the simple unauthenticated `/health` route. Authenticated Slack/provider readiness remains a provisioning concern and does not create third-party-outage pages.
- Docker restart events are not audited. A transient kill repaired by Compose between polls is not a sustained outage; the live drill uses a stopped container.
- Corrected four newly introduced cross-suite hygiene violations rather than exempting them; no unrelated failure was observed in the final suite.
- Live verification found that `ProtectHome=yes` hides `/run/user`, so the sandboxed probe could not reach the rootless socket even though the same uid could outside systemd. Regression tests now pin `ProtectHome=read-only` plus `ReadWritePaths=/run/user/<uid>/docker.sock`; the clean post-fix drill passed.

## Independent review dispositions

The first pooled review (`nan/deepseek-v4-flash`, reviewed `65af8dca`) returned FAIL for one REAL Major and four minor/question items. Its artifacts are preserved in commit `4adb30ac`.

- **F1 REAL Major, applied:** `test_activation_order_waits_for_gateway_health_before_starting_the_watcher` now requires unit installation and Docker health before timer enable. Mutation: `Reproduction: reproduced (exit 1) on ce5065215b2f with probe ai013-move-health-wait.diff` moving the wait below the enable.
- **F2 minor, applied and live-verified:** rendered-input prediction pauses an existing timer only before a gateway recreate; it is not disabled and unchanged provisions do not stop it. Live order was Pause → Start → Docker healthy → Enable, `changed=4`; next run `changed=0`; zero new Slack watchdog messages.
- **F3 minor, applied with corrected mechanism:** the runbook now says ten minutes after boot but two minutes after mid-session activation, which `OnUnitActiveSec=2min` actually implements. The review's alternative “at once” would contradict that directive and the observed timer schedule.
- **F4 minor, applied and corrected after round-two inspection:** unconfigured teardown removes the probe script as well as both units. The loop uses complete paths with `path: "{{ item }}"`; a test rejects the earlier incorrect `/etc/systemd/system/{{ item }}` prefixing of an absolute script path.
- **F5 question, applied:** the healthcheck uses `python3`, matching every other in-container invocation; the resulting recreate reached healthy.

The second reviewer (`nan/qwen3.8-flash`) timed out with `verdict: PENDING`, which is not accepted as review coverage. Its transcript exposed the absolute-path cleanup defect corrected above. A fallback review with `--fallback-reason timeout` was required. No archive is attempted from the implementing session.

## Fallback review dispositions

The fallback (`anthropic-review/claude-haiku-5-5`, reviewed `cb4948c5`) returned PASS-WITH-GAPS. The owner then chose direct fixes rather than AI-034/AI-035 follow-up tickets; no such tickets were created.

- **Restart `starting` (minor): applied in code.** One recent start receives 90 seconds of grace only for `RestartCount <= 1`; sustained startup, repeated automatic restart, stopped/missing/invalid state fail. Named tests cover each branch; proposal and runbook now describe the exact behavior.
- **Paused timer on failed deployment (THEORETICAL Major): applied in code.** `Deploy hermes-kubelab` now has a `rescue` that restores only a timer this run paused and then executes `ansible.builtin.fail`, so the original failure is not swallowed. A named ordering/structure test protects it and all 26 playbooks parse. A deliberately broken provision was not authorized or executed, so this remains structural rather than live-failure evidence.
- **Host hang (question): accepted and explicit.** A powered-on hung host is outside this local detector's coverage; no independent node-liveness alert is claimed.
- **First timer run (minor): verified on the host.** The observed schedule was `LAST 21:49:48`, `NEXT 21:51:48`, confirming the two-minute mid-session activation interval. The runbook is correct; the alternative immediate-fire concern did not occur.
- **`partial-become` (minor): applied.** The Docker-health wait declares `become: true` alongside `become_user`.
- **Evidence hygiene (minor): applied.** Relevant RED/GREEN, suite and live excerpts are inline above; no external log path is needed to reopen the claims.
- **Test quality (minor): applied.** The health URL assertion is exact, and detector-independence tests reject `Requires`, `Requisite`, `BindsTo`, `PartOf` and `ConditionActive`, not only one string.
- **Comment drift (minor): applied.** The task comment distinguishes the root-owned executable from the agent-run oneshot.
- **Round-two placeholders (housekeeping): preserved as audit history.** `review-round2.md` records the timed-out PENDING attempt; only a terminal `review.md` is used for archive.

A fresh independent review is required after the direct contract changes.

## Direct-fix live validation

- Corrected-head provisioning reached `changed=0`, `failed=0`; the Ansible recap reports `rescued=0` on normal runs.
- A real restart with `RestartCount=0` was observed in `starting` and the installed probe returned `grace_rc=0`. It then reached `running/healthy` and the systemd probe returned `Result=success`.
- Slack read-back from immediately before that restart returned zero new watchdog messages, with timer active and watchdog spool 0. Earlier validation incidents from the inspect-field/startup defects had recovered before this clean baseline.
- Live inspection caught and corrected Docker's top-level `.RestartCount` field; a regression test now rejects the invalid `.State.RestartCount` path.

No deliberately broken provision or host power-off was performed. Failure restoration is covered structurally, not by a live injected failure.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: `docs/lessons/observability/lesson-756-an-on-demand-liveness-watchdog-must-be-local-but-independent-of-the-agent-kill-switch.md`.
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: implements the existing ADR-028 on-demand and ADR-044 fabric decisions; no new architecture decision.
- [x] New pattern candidate for `00_meta/patterns/`? no: one-repo implementation evidence so far; do not promote prematurely.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`.
- [ ] Folder moved to `specs/archive/AI-013-hermes-liveness/`.
- [ ] Bitácora #2175 closed by the merged implementation PR.
- [ ] Promotions above executed; independent adversarial review completed before archive.
