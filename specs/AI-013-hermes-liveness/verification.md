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
- [x] **AC2 — recovery and semantics:** 20 focused tests pass. The probe accepts only `healthy`; `starting`, `unhealthy`, `missing` and Docker failure return non-zero; invalid container names exit 64 before Docker runs. The simple `/health` check contains no credential, Slack or provider readiness. `OnSuccess=kubelab-notify-recovered@%n.service` is rendered.
- [x] **AC3 — on-demand silence:** tests prove no `Persistent`/`OnCalendar` directive, no Kuma monitor and no always-on dependency. The timer runs locally after ten minutes of boot grace or two minutes after a mid-session activation. **Power-off was not physically exercised**; no external path exists that could emit a page while ace2 is off. The watcher deliberately remains independent of the egress kill switch, so daemon failure cannot disable its own detector.
- [x] **AC4 — configuration lifecycle:** role-ordering tests prove the timer starts only after unit installation plus API, Slack and Docker health checks, and the unconfigured path disables/removes the watcher before Compose teardown. Provisioning waits for Docker health before enabling the timer; the read also runs safely in check mode.
- [x] **AC5 — reproducible evidence:** local suite and lint are green. Initial provisions measured `changed=5` then `changed=0`; the systemd socket correction measured `changed=1`, and the final post-drill provision measured **`changed=0`, `failed=0`**. In the clean drill, restart reached Docker health at `21:23:43Z`; the probe and recovery notifier returned success and `ops-log` recorded `recovered … after 1 failed runs` at `21:23:44.059549Z`. Failure-to-recovery delivery spanned 56.453 seconds. The review-fix recreation measured `changed=4` and its next provision `changed=0`, with zero new watchdog messages. No ace2 power-off was performed.

## Test status

- Initial watched RED: `poetry run pytest -q tests/test_hermes_liveness.py` → **16 failed, 2 passed** (`/tmp/ai013-red.log`): healthcheck, units, script and role wiring absent.
- Focused GREEN before review: same command → **19 passed** (`/tmp/ai013-green.log`); after review hardening → **20 passed** (`/tmp/ai013-review-fixes-green.log`).
- Neighboring Compose/role/notification suites → **302 passed, 77 skipped** (`/tmp/ai013-focused.log`).
- Cross-repository hygiene failures from the first full run were corrected: explicit UTF-8, `tests.shells.BASH`, and check-mode-safe Ansible read/wait → **34 passed** (`/tmp/ai013-hygiene.log`).
- Final full suite after live fixes and master merges: `make test` → **10,631 passed, 96 skipped**, 30 warnings, 78% total coverage (`/tmp/ai013-make-test-live-final.log`).
- `make lint` → all checks passed; 169 files already formatted. `make type` → no issues in 168 source files. `make lint-ansible` → all 26 playbooks parse.
- `shellcheck -s bash` and `-s sh`, `bash -n`, `zsh -n`, and `git diff --check` passed.
- Live manual smoke test: operator approved. Clean stop/start produced exactly one failed run, one `ops-log` incident and one recovery; final gateway is `running/healthy`, timer active, both notifiers `Result=success`. No credentials were printed.

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

The second reviewer (`nan/qwen3.8-flash`) timed out with `verdict: PENDING`, which is not accepted as review coverage. Its transcript exposed the absolute-path cleanup defect corrected above. A fallback review with `--fallback-reason timeout` is required. No archive is attempted from the implementing session.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: `docs/lessons/observability/lesson-756-an-on-demand-liveness-watchdog-must-be-local-but-independent-of-the-agent-kill-switch.md`.
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: implements the existing ADR-028 on-demand and ADR-044 fabric decisions; no new architecture decision.
- [x] New pattern candidate for `00_meta/patterns/`? no: one-repo implementation evidence so far; do not promote prematurely.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`.
- [ ] Folder moved to `specs/archive/AI-013-hermes-liveness/`.
- [ ] Bitácora #2175 closed by the merged implementation PR.
- [ ] Promotions above executed; independent adversarial review completed before archive.
