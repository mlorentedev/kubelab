---
spec: "AI-013-hermes-liveness"
verdict: "FAIL"
reviewed_sha: "65af8dca182ec5fc2405feae675f004eeb671bb3"
reviewer: "nan/deepseek-v4-flash"
date: "2026-11-14"
---

## Adversarial review

**Scope**: AI-013-hermes-liveness (`git diff 338fc72f46254ee92d05964bbad6187a4db70b64...HEAD`, 138 files; the
spec's own slice is 4 of 23 commits: `7cf5841f`, `4fe25d95`, `4aca4ee7`, `65af8dca`, plus the two late socket
fixes `66ef148d` / `8fbc646d` that touch the same template and test). Other work in the range (EDGE-001 registry
DNS, ANSIBLE-037, OPS-065, console image, load-test docs) judged only where it interacts: the spec's test file
imports `tests.shells.BASH`, which already existed at the base commit, so the spec's commit is self-contained.

**Sources**: `specs/AI-013-hermes-liveness/{proposal,tasks,verification}.md`, `features.json`,
`infra/ansible/roles/agent_stack/{files/hermes-liveness.sh,tasks/hermes.yml,templates/agent-stack-hermes-watchdog.service.j2,templates/agent-stack-hermes-watchdog.timer.j2,templates/compose-hermes.yml.j2}`,
`tests/test_hermes_liveness.py`, `docs/runbooks/hermes-kubelab.md`,
`docs/lessons/observability/lesson-756-*`, `infra/ansible/roles/node_notify/templates/*`.

**Evidence-gathering commands run in this session** (all at `65af8dca`):
`poetry run pytest -q tests/test_hermes_liveness.py` → **19 passed**; four mutations of the shipped wiring
reverted after each run (below); `bash -n` + `shellcheck -s bash` on the probe → clean;
`dotf spec digest AI-013-hermes-liveness` → **matches `review-request.json` `contract_digests` byte for byte**, so
the contract was untouched by this review; a live Docker 29.5.2 experiment on the stopped-container question.
`make lint` scopes ruff to `toolkit/` only (`Makefile:2259`), so the test file's I001 import order is outside
every gate in this repo — existing test files carry the same — and is not a finding.

### Spec and task alignment

- **AC1 (detection + delivery)**: satisfied by construction and evidenced live (stop at `21:22:43Z`, notifier
  success, one `ops-log` incident at `21:22:47.606959Z`). The `OnFailure=`/`OnSuccess=` pair and the dedup are
  the fleet idiom, not a new mechanism. **No deduction.**
- **AC2 (recovery + semantics)**: the strongest part of the change. The probe is a 22-line script whose only
  accepted value is `healthy`; `starting`/`unhealthy`/`missing`/daemon-failure all exit non-zero and invalid
  container names exit 64 *before* `docker` runs. Recovered pages are suppressed when no incident is open
  (`kubelab-notify.sh.j2`: `[ "$COUNT" -gt 0 ] || exit 0`), so the every-two-minute `OnSuccess=` costs a quiet
  process rather than a recovery storm. **No deduction.**
- **AC3 (on-demand silence)**: no `Persistent`/`OnCalendar`, no Kuma monitor, no `agent-stack-egress`
  dependency — each pinned by a named test. Power-off itself was declared unexercised rather than claimed.
  **No deduction**, but see F3 for a wording defect in the same area.
- **AC4 (configuration lifecycle)**: the code is right — the enable task is the last task of the deploy block,
  after the health wait, and the unconfigured branch stops the timer before tearing Compose down. The
  *evidence* for it is not: see **F1**.
- **AC5 (reproducible evidence)**: `changed=0`/`failed=0`, the 10,630-test suite, lint and type are prose in
  `verification.md` with `/tmp` log paths a reviewer cannot reopen from the repo. The wiring claims that *can*
  be re-run from the repo, I re-ran: they hold, and the late `ProtectHome` fix is genuinely pinned (mutation
  below). **No deduction**, untestable live gate declared.
- **Tasks**: every implementation and closing box is ticked except the four that cannot be true yet (PR, CI
  disposition, this review, handoff). Consistent with the review window; not a finding.
- **Knowledge**: the lesson (`lesson-756`, index row present, numbering collision fixed twice, no duplicate
  756 elsewhere) and the runbook section both landed inside the change. Handoff-readiness is genuinely good.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|--------------|
| Major | REAL | verification / AC4 | AC4's "starts the watcher only after gateway health verification succeeds" is **not protected by any test**, and two spec artifacts state that it is. The Docker-health wait can be moved *below* the timer-enable task and the suite stays green — the failure the criterion exists to prevent (timer enabled, then the provision aborts on an unhealthy gateway) is reachable by any future reordering. | I swapped `- name: Wait for the Hermes healthcheck to report healthy` and `- name: Enable the Hermes liveness timer` in `tasks/hermes.yml`; `pytest -q tests/test_hermes_liveness.py` → **19 passed** (reverted). `features.json` f4 claims "timer activation follows API/Slack health **plus Docker healthy**"; `verification.md` AC4 repeats it. | `test_activation_order_waits_for_gateway_health_before_starting_the_watcher` — exists, but only asserts ordering against the API and Slack checks; the Docker-health wait and the unit-install tasks are uncovered. | tests (+ evidence wording) |
| Minor | THEORETICAL | reliability | A provision that changes config/env/persona recreates the container (`--force-recreate`), leaving it `starting` or absent for roughly 30–150 s while the already-enabled timer keeps probing. `starting` fails closed *by design* (AC2), so a routine config-changing provision can emit one failure page and one recovery page. The proposal's mitigation covers boot only; nothing suppresses the timer around a recreate. | Code read of `tasks/hermes.yml` `Start hermes-kubelab` / `Enable the Hermes liveness timer`; the last provisions measured `changed=0`, so no recreate was observed with the timer armed. | UNTESTED | code (stop/start the timer around a recreate) or spec risk acceptance |
| Minor | REAL | documentation | `.timer` provides a **boot** grace only, yet the proposal says "boot/activation grace period" and the runbook says the timer "waits ten minutes after boot **or activation**". A mid-session `systemctl enable --now` fires at once, because `OnBootSec=10min` is already in the past. Harmless today (activation follows the healthy wait) but the operate doc is wrong about the mechanism an operator would rely on. | `agent-stack-hermes-watchdog.timer.j2` has `OnBootSec`/`OnUnitActiveSec` and no activation offset; runbook §Gateway liveness. | UNTESTED | docs (runbook) |
| Minor | REAL | lifecycle | Disabling Hermes removes both units but leaves `/usr/local/libexec/agent-stack/hermes-liveness.sh` on the node. AC4 asks only for the units, so this is tracked, not blocking — but "removes its units" now reads as "removes its artefacts" and the leftover is a root-owned executable nobody manages. | `tasks/hermes.yml` unconfigured branch: `file: absent` loop covers only `agent-stack-hermes-watchdog.{timer,service}`. | `test_unconfigured_hermes_stops_watching_before_taking_the_gateway_down` (does not cover the script) | code or an explicit note |
| Question / assumption | SPECULATIVE | reliability | The new Compose healthcheck invokes `python -c`, while every other in-container Python invocation in this role uses `python3 -c`. Live evidence says the gateway reached `healthy`, so the image has `python` today; if it ever loses that alias, every container becomes permanently unhealthy and the watchdog pages forever — a false-positive storm the probe cannot distinguish from a real outage. | `compose-hermes.yml.j2` healthcheck `CMD python -c ...` vs `tasks/hermes.yml` `docker exec ... python3 -c`; image not present locally, so UNVERIFIED here. | UNTESTED | code (one-word change) / confirm with the image owner |

#### Hypotheses I attacked and failed to break (recorded so they are not re-derived)

- **"A stopped container still reads `healthy`, so stopping the gateway would not page."** Refuted by
  measurement: on Docker 29.5.2 a container whose healthcheck had just reported `healthy` shows
  `running=false status=unhealthy` immediately after `docker stop`, and the shipped probe script then exits 1
  against the real daemon (`PROBE_STOPPED_RC=1`). AC1's stopped-gateway path is genuinely detected; the live
  drill's "failed because it was `unhealthy`" is consistent with running `docker stop` as the runbook
  prescribes. Cleanup: the probe container was removed, no repo files touched.
- **"`kubelab-notify@%n.service` doubles the suffix and mis-names the unit."** Not a defect: the fleet idiom is
  `%n.service` in 10+ existing units, and `kubelab-notify@.service.j2` documents the live-verified resolution
  (`%i` = `foo.service`, which is what `journalctl -u` needs). Consistent across the failure and recovery hooks,
  so the dedup key is stable.
- **"`OnSuccess=` on every healthy two-minute run pages a recovery each time."** Refuted in the notifier:
  `[ "$COUNT" -gt 0 ] || exit 0`.
- **"The late systemd-sandbox fix is cosmetic."** Mutation-tested: `ProtectHome=read-only` → `yes` fails the
  named test; deleting `ReadWritePaths=` fails it; deleting `OnFailure=` fails it. The AC5 claim "focused tests
  fail if the wiring is removed" holds for these properties.
- **"The probe accepts a hostile container name / shell metacharacters."** The `case` validation rejects
  `-*` and any non `[A-Za-z0-9_.-]`, exits 64 before touching `docker`; the parametrized test proves Docker is
  never invoked (`fake_args == ""`). No injection path.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Every criterion holds on the happy path and on the negative paths I could execute; the startup-window page (F2) is the unconverted rough edge. |
| Verification       | C | Four wiring properties are genuinely mutation-proof, but AC4's ordering claim is demonstrated false and `changed=0`/full-suite evidence is prose only. |
| Scope              | A | Diff matches the proposal; the two lesson renumberings are knowledge hygiene, no creep, no out-of-scope monitor or channel. |
| Reliability        | B | Fails closed on daemon error, missing container, non-healthy status; bounded by `TimeoutStartSec=30s`; the recreate window is untolerated. |
| Maintainability    | A | 22-line probe, one template per unit, comments state the WHY (including the measured `ProtectHome` boundary); no dead code. |
| Handoff-readiness  | A | Lesson indexed and unique, runbook section with the drill and the kill-switch ordering, verification records decisions and the declared live gate. |

Aggregation: one **C** (Verification) puts the floor at PASS WITH GAPS; the severity axis escalates above it —
see Verdict.

### Verdict

**FAIL** — one **REAL Major** (F1): an acceptance criterion's own protection is absent while `features.json` and
`verification.md` both assert it is proven. A Major in the contract *evidence* is not a wording nit here: the
archive freezes that sentence as the record of how AC4 was established. Per the severity × reality rule, a REAL
Major blocks the archive regardless of the otherwise strong grades (Scope and Handoff-readiness exemplary).

### Recommended next steps

**Contract-set implications (do not edit while this verdict stands).** `proposal.md`, `tasks.md` and
`features.json` are the staleness set. The one change F1 needs in `features.json` is its `evidence` field, which
`dotf spec digest` normalises out — so correcting f4's wording ("timer activation follows API/Slack health plus
Docker healthy" → name the ordering actually pinned, and what the new test now pins) does **not** orphan this
review. Nothing in `proposal.md` or `tasks.md` needs to change.

- **F1 (Major, must land before a PASS round):** add to
  `tests/test_hermes_liveness.py::test_activation_order_waits_for_gateway_health_before_starting_the_watcher`
  an assertion that `names.index("Enable the Hermes liveness timer")` is greater than
  `names.index("Wait for the Hermes healthcheck to report healthy")` and greater than both unit-install tasks.
  Red-green it the way I did: swap the two tasks, watch the new assertion fail, restore. Fix location: tests +
  the digest-neutral `features.json` evidence line. Then re-review (the next round is the mechanism).
- **F2 (Minor, track):** either stop the timer before `Start hermes-kubelab` recreates and start it after the
  health wait, or record in the runbook that a config-changing provision may emit one incident + one recovery.
  Disposition in `verification.md` (it is outside the staleness set) or a follow-up ticket.
- **F3 (Minor, fix now — docs):** correct `docs/runbooks/hermes-kubelab.md` "after boot or activation" to
  "ten minutes after boot; a mid-session activation runs at once because the enable follows the health wait",
  and align the proposal wording at archive time if the curator touches it.
- **F4 (Minor, disposition):** add the probe script to the unconfigured removal loop, or state in the runbook
  that the script persists harmlessly.
- **F5 (Question):** confirm with the image owner that `python` is a supported entry point (or switch the
  healthcheck to `python3` for parity with every other invocation). One word, removes a single point of
  false-positive failure.
- **Not blocking, for the record:** the full-suite/`changed=0` evidence is live-only and cannot be re-derived
  from the repo — acceptable as a declared gate, but keep `/tmp/ai013-*.log` paths out of the archive or move
  the logs somewhere durable.

`/spec archive` is **not advisable in this state**: `dotf spec archive` will accept the review file's shape, but
the verdict is FAIL and F1 is a REAL Major in what the archive records as proof.
