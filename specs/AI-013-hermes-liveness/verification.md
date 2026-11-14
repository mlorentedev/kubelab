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

- [ ] **AC1 — detection and delivery:** local contract is green: `test_healthcheck_uses_bounded_simple_health_without_credentials`, `test_notification_hooks_and_recovery_use_the_fleet_fabric`, `test_timer_interval_and_boot_grace_match_the_contract`, and behavioral non-healthy probes pass. **Live gate pending:** provision ace2, stop the gateway, observe one fabric incident and measure the interval.
- [x] **AC2 — recovery and semantics:** 19 focused tests pass. The probe accepts only `healthy`; `starting`, `unhealthy`, `missing` and Docker failure return non-zero; invalid container names exit 64 before Docker runs. The simple `/health` check contains no credential, Slack or provider readiness. `OnSuccess=kubelab-notify-recovered@%n.service` is rendered.
- [x] **AC3 — on-demand silence:** tests prove no `Persistent`/`OnCalendar` directive, no Kuma monitor and no always-on dependency. The timer runs locally after ten minutes of boot/activation grace. **Power-off was not physically exercised**; no external path exists that could emit a page while ace2 is off. The watcher deliberately remains independent of the egress kill switch, so daemon failure cannot disable its own detector.
- [x] **AC4 — configuration lifecycle:** role-ordering tests prove the timer starts only after API and Slack health checks, and the unconfigured path disables/removes the watcher before Compose teardown. Provisioning waits for Docker health before enabling the timer; the read also runs safely in check mode.
- [ ] **AC5 — reproducible evidence:** local suite and lint are green. **Live gate pending:** two provisions and an operator-approved stop/start notification exercise. No ace2 power-off will be performed for this spec.

## Test status

- Initial watched RED: `poetry run pytest -q tests/test_hermes_liveness.py` → **16 failed, 2 passed** (`/tmp/ai013-red.log`): healthcheck, units, script and role wiring absent.
- Focused GREEN: same command → **19 passed** (`/tmp/ai013-green.log`).
- Neighboring Compose/role/notification suites → **302 passed, 77 skipped** (`/tmp/ai013-focused.log`).
- Cross-repository hygiene failures from the first full run were corrected: explicit UTF-8, `tests.shells.BASH`, and check-mode-safe Ansible read/wait → **34 passed** (`/tmp/ai013-hygiene.log`).
- Full suite: `make test` → **10,571 passed, 96 skipped**, 30 warnings, 78% total coverage (`/tmp/ai013-make-test-final.log`).
- `make lint` → all checks passed; 168 files already formatted. `make type` → no issues in 167 source files. `make lint-ansible` → all 26 playbooks parse.
- `shellcheck -s bash` and `-s sh`, `bash -n`, `zsh -n`, and `git diff --check` passed.
- Live manual smoke test: **pending explicit operator approval**. No credential output is required or permitted.

## Decisions made during implementation

- Chose local Compose health + systemd fabric delivery over Kuma push or an external tailnet probe. Kuma's `on-demand` mute would suppress the very agent failure being detected; an external probe would add the #2189 dependency.
- Kept the watchdog independent of `agent-stack-egress.service`. The runbook now requires stopping the timer before an intentional silent kill-switch stop; an unexpected daemon/egress failure still pages.
- Liveness uses the simple unauthenticated `/health` route. Authenticated Slack/provider readiness remains a provisioning concern and does not create third-party-outage pages.
- Docker restart events are not audited. A transient kill repaired by Compose between polls is not a sustained outage; the live drill uses a stopped container.
- Corrected four newly introduced cross-suite hygiene violations rather than exempting them; no unrelated failure was observed in the final suite.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: `docs/lessons/observability/lesson-754-an-on-demand-liveness-watchdog-must-be-local-but-independent-of-the-agent-kill-switch.md`.
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: implements the existing ADR-028 on-demand and ADR-044 fabric decisions; no new architecture decision.
- [x] New pattern candidate for `00_meta/patterns/`? no: one-repo implementation evidence so far; do not promote prematurely.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`.
- [ ] Folder moved to `specs/archive/AI-013-hermes-liveness/`.
- [ ] Bitácora #2175 closed by the merged implementation PR.
- [ ] Promotions above executed; independent adversarial review completed before archive.
