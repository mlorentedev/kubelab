---
spec: "AI-013-hermes-liveness"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "cb4948c554a68e8ad303395d8f8680fd9d4a144a"
reviewer: "anthropic-review/claude-haiku-5-5"
date: "2026-11-14"
---

## Adversarial review

**Scope**: AI-013-hermes-liveness, whole change `git diff 338fc72f46254ee92d05964bbad6187a4db70b64...HEAD` (28 commits; the 8 spec-owned commits were read in full, the rest only where they touch the watcher, the gateway healthcheck, or the notify path).
**Sources**: `specs/AI-013-hermes-liveness/{proposal,tasks,verification,features}.md`; `infra/ansible/roles/agent_stack/{files/hermes-liveness.sh,templates/agent-stack-hermes-watchdog.{service,timer}.j2,templates/compose-hermes.yml.j2,tasks/hermes.yml}`; `tests/test_hermes_liveness.py`; `docs/runbooks/hermes-kubelab.md`; `docs/lessons/observability/lesson-756-*.md`.

### Verification performed in this run

- `poetry install` (full project) then `poetry run pytest tests/test_hermes_liveness.py` → **20 passed** (16:40 MST).
- Adjacent suites `test_hermes_{persona,sidecar,webui_backend,config}.py`, `test_agent_stack_role.py`, `test_node_notify_role.py` → **314 passed, 16 skipped**, exit 0.
- `shellcheck -s bash files/hermes-liveness.sh` → clean.
- `ansible-lint roles/agent_stack` on HEAD vs base (`git archive 338fc72f`): one **new** warning, `partial-become` on "Wait for the Hermes healthcheck to report healthy" (hermes.yml:822). The base already carries 17 of the same rule in this file, so it is the existing pattern, not a new class.
- `dotf spec digest AI-013-hermes-liveness` → `features.json`, `proposal.md`, `tasks.md` digests **match** `review-request.json` exactly; `spec.md` is absent (full spec), recorded as `""`.
- **Live Docker probe, Docker 29.5.2 on this host** (scratch container under `mktemp -d`, removed afterwards):
  - `docker kill` of a healthy container → `State.Running=false`, `Health=unhealthy` immediately; probe exits 1. The stop-path claim holds.
  - Crash with `--restart unless-stopped`: after each automatic restart the container reports `Health=starting` until the first health check completes, and `hermes-liveness.sh` **exits 1 during that window** (samples t=4..6 and t=11..16 s, `restarts` 1→4). The probe fails closed as AC2 literally requires.
- Not run: ansible `--check` against ace2 (no inventory or host in this worktree); a real systemd timer or unit (no systemd here, macOS host); the power-off scenario; the archive gate itself (`dotf spec archive` would move files, so it was not invoked).

### Spec and task alignment

- AC1 (detection + delivery through `kubelab-notify@`): wiring verified by the named tests below and by the live drill recorded in `verification.md`. The drill's ops-log evidence is not reproducible from this worktree (see Finding 6).
- AC2 (healthy exits 0; failed/missing/starting fail closed; recovery via `kubelab-notify-recovered@`): the probe's behaviour is verified live (above). The **restart-transient** consequence of the fail-closed `starting` state contradicts the proposal's own Risks text and the runbook (Finding 1).
- AC3 (powered-off ace2 cannot page): satisfied by construction. There is no `Persistent`/`OnCalendar` directive, no external Kuma monitor, and no dependency on the gateway. The test suite asserts the directives and the absence of the monitor. **Physical power-off was not exercised**, and the verification artifact says so. A hung-but-powered host is not covered (Finding 4).
- AC4 (lifecycle): the unconfigured path removes the watcher before Compose teardown (`cb4948c5` fixed the removal paths: the `{{ item }}` form had been resolving wrongly). The enable path is ordered after the Docker healthy wait. But the pause that precedes the enable is **not restored on failure** (Finding 2).
- AC5 (idempotent, tests fail if wiring removed, live evidence without credentials): the 20 tests are green. `changed=0` on re-run is UNVERIFIED (no host). The `/tmp/...` references in `verification.md` (5 occurrences) point to logs outside the repo (Finding 6).
- Non-goals: honoured. No Kuma monitor, no catch-up timer, no move to another host.
- `tasks.md`: the implementation boxes are ticked. The closing boxes (CI, reviewer dispositions) are still open, which is correct at this point.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | Semantics / docs | A gateway that auto-restarts pages an incident. The proposal (Risks, bullet 2) and runbook (`docs/runbooks/hermes-kubelab.md` ~L74-76) say a restart transient is "intentionally not paged". The probe rejects `starting`, as AC2 requires, and Docker holds `starting` until the first check (~`interval`, 30 s in production), so a poll landing in that window pages. Reproduced on Docker 29.5.2 with the actual probe script. Not a missed detection; it is a noisy page plus a recovery page, and the documented expectation is wrong. | Live probe run (this review); proposal.md Risks L2; runbook L74-76; compose `interval: 30s`, `start_period: 60s` | UNTESTED (no test asserts restart behaviour; `test_probe_fails_closed_for_non_healthy_health` covers only the static `starting` string) | Decide: (a) accept that a restart pages and correct the runbook/Risks text (docs, and the Risks line is contract set, so at archive or in a follow-up); or (b) suppress a `starting` result for a running container within a bounded grace, in code plus a named test. Choose at a follow-up ticket; do not edit the contract set under this PASS. |
| Major | THEORETICAL | Reliability / lifecycle | The timer is paused before the gateway is restarted and re-enabled only after the final health wait. If any task between them fails (API verify 150 s, Slack verify, sidecar verify, the Docker healthy wait with 24 retries), `ansible-playbook` stops with the timer still **stopped**. The watcher then stays silent until the next successful provision or a reboot, while the gateway may still be down. The operator sees the Ansible failure, which limits the damage, but the detector is silently off. No block/rescue, no restore-on-failure, and no test covers this path. Argued from task order in `hermes.yml` (pause ~L539, enable ~L840, failing tasks between). Not reproduced. | `tasks/hermes.yml` ordering; `test_hermes_liveness.py` has no failure-path test | UNTESTED | Code + tests: wrap the restart window in `block/rescue` that re-enables the timer on failure, or re-enable before the healthy wait and let the watcher fire on a real outage. Add a named ordering/failure-path test. Ticket with root cause if not fixed in this PR. |
| Question / assumption | — | Scope | A powered-on but hung ace2 (kernel hang, no progress) is indistinguishable from powered off, so the watcher, which runs on ace2, is silent in that case. The lesson's own rule says a watchdog must not share a failure domain with what it watches unless another independent alert covers that domain. The spec does not state this as accepted risk, and the Out of scope section does not list it. | proposal.md Out of scope; lesson-756 Rule | UNTESTED (not testable in the suite) | Spec artifact (`verification.md` or a risk line): state "host hang is out of scope and not paged" as an accepted decision, or name the covering alert. Confirm with the owner. |
| Minor | THEORETICAL | Docs accuracy | Runbook L58 says that when the timer is enabled mid-session, "OnUnitActiveSec makes the first run two minutes after activation". With `OnBootSec=10min` already elapsed at activation, systemd's `OnBootSec` base is likely to fire at once. The first run may therefore be immediate, not in two minutes. Not checked on systemd (no systemd here). Operator-facing only; it has no effect on AC behaviour. | runbook L58; timer template | UNTESTED | Docs: correct the runbook after checking on the host (`systemctl list-timers` after enable). |
| Minor | REAL | Maintainability / lint | `ansible-lint` reports a **new** `partial-become` warning for the new "Wait for the Hermes healthcheck to report healthy" task (hermes.yml:822). The same rule fires 17 times in this file at base, so it is the existing pattern, not a regression. Lint is not in the focused suite. | `ansible-lint roles/agent_stack/tasks/hermes.yml` on HEAD vs base | UNTESTED | Code: add `become: true` (or match the sibling tasks' style) when the role's lint debt is ticketed. Track with the existing lint debt. |
| Minor | REAL | Evidence hygiene | `verification.md` cites `/tmp/...` logs (5 references) for RED/GREEN runs and the live drill (e.g. `ops-log` at 21:22:47.606959Z). Those are not reproducible from the repo or this worktree. The live-drill evidence is therefore anecdotal, which is what rubric Verification grades down. | `grep -c /tmp verification.md` = 5 | n/a | Spec artifact (`verification.md`, outside the contract set): paste the relevant log excerpt inline, or name the commit that reproduces it. |
| Minor | REAL | Test quality | `test_simple_health_does_not_turn_provider_readiness_into_liveness` (L63) asserts `endswith("/health'") or "/health'" in command`. The first clause is redundant, so the check is weaker than its name. `test_unexpected_agent_manager_death_cannot_disable_its_own_detector` only asserts the absence of the string `agent-stack-egress`, which misses a `BindsTo=`/`Requires=` on `user@<uid>`, though the name claims more. | `tests/test_hermes_liveness.py` L63 and the named test | self | Tests: tighten both to assert the exact directive set (`Requires=`, `BindsTo=`, `PartOf=`) so the name and the check agree. |
| Minor | REAL | Docs drift | `hermes.yml` L802 comments that the probe "is root's", but the service runs as `User=agent` with `ProtectHome=read-only`. The root-owned script and the agent-run unit are both true, but the comment should say which is which. | hermes.yml L802; service template `User=` | UNTESTED | Code comment only. |
| Minor | REAL | Housekeeping | The spec folder contains `review-request-round2.json` and `review-round2.md` (untracked) and `review-request.json` (modified) from the launcher, with placeholder reviewers. They are not part of the contract set but will confuse a later archive reader. | `git status` | n/a | Operator: remove the round-2 placeholders before archive; leave `review.md` as the single verdict. |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness | B | Detection, probe semantics and wiring verified; the restart-transient and pause-window gaps are open but do not miss an outage that the watcher is designed to see. |
| Verification | C | Tests and the live probe are reproduced here, but power-off, the drill's ops-log and `changed=0` rest on `/tmp` artifacts outside the repo or are UNVERIFIED. |
| Scope | B | The change stays on the watcher, its probe, its tests, the runbook and one lesson; the `cb4948c5` fix is narrow. |
| Reliability | C | A failed provision leaves the detector silently stopped (Finding 2); restart transients page (Finding 1). |
| Maintainability | B | Small role, clear names and ordering tests; a new lint warning and two weak assertions. |
| Handoff-readiness | B | Lesson and runbook are written, but the runbook's first-run and restart claims are not accurate yet, and round-2 placeholders sit in the folder. |

### Verdict
PASS WITH GAPS

Gaps are all Minor, or Major and THEORETICAL, and the grades include a C, with no D. No Blocker. No REAL Major. The archive is advisable once the dispositions below are recorded in `verification.md` (the contract set is closed under PASS WITH GAPS), and the two follow-up tickets are filed.

### Recommended next steps
- Record a disposition in `verification.md` for each finding above (applied / ticketed / declined with a reason). Contract-set text (Risks bullet 2 in `proposal.md`) is a follow-up, not an edit under this verdict.
- File a ticket for Finding 2 (pause-window failure path) with root cause and the `block/rescue` fix option; give it a named regression test.
- Decide Finding 1 (accept restart pages and correct the text, or suppress a bounded `starting` grace) and file it.
- State the host-hang silence (Question) as an accepted decision in `verification.md`, or name the covering alert.
- Before archive: remove the untracked round-2 placeholder files and confirm `changed=0` on a second provision run on ace2 (UNVERIFIED here, no host).
- Fix the runbook first-run sentence after checking the timer on the host.
- `dotf spec archive` was not run in this review; its gate remains UNVERIFIED by this reviewer.
