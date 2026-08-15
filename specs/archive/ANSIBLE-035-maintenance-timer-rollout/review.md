---
spec: "ANSIBLE-035-maintenance-timer-rollout"
verdict: "PASS"
reviewed_sha: "4619a5701429cf3ff1c0d1399fb9f8816f1658e1"
reviewer: "nan/deepseek-v4-flash"
date: "2026-08-18"
---

## Adversarial review

**Scope**: ANSIBLE-035-maintenance-timer-rollout (current branch: `chore/ansible-035-aws1-verification` @ 4619a57)
**Sources**: specs/ANSIBLE-035-maintenance-timer-rollout/{proposal,tasks,verification,features}.md, git diff b91c1f2..HEAD, live commands run against the merged code

### Spec and task alignment

This is a **round-2 review**. Round 1 (reviewed_sha b91c1f2, same reviewer) issued FAIL with two Major findings and three Minors:

| Round-1 finding | Status as of this review | Verdict |
|---|---|---|
| F1 (Major, REAL): staging secret count 39/39 unreproducible (actual 35/35) | FIXED. verification.md corrected to 35/35 with a note that the base was 34/34 before the +1 from `fleet_webhook_secret`. Reproduced by running `poetry run toolkit secrets audit --env staging` → 35/35. | ✅ |
| F2 (Major, REAL): no automated regression tests for notify script / OnFailure= wiring | FIXED. `tests/test_node_maintenance_notify.py` added (15 tests). All 15 pass (`532 passed, 129 deselected` confirmed by running `make test`). Tests cover: OnFailure= linkage, target-verifies unit exists, ExecStart matches tasks, domain literal not derived, curl timeouts, UTF-8 truncation, shell-injection refutation, JSON encoding. | ✅ |
| Minor #1: no curl timeout | FIXED. `--connect-timeout 10 --max-time 15` added to the notify script. | ✅ |
| Minor #2: UTF-8 truncation crashes encoder | FIXED. `sys.stdin.buffer.read().decode('utf-8', 'replace')` replaces the raw `sys.stdin.read()`. Reproduced before fix: `printf 'caf\xc3'` → `UnicodeDecodeError`. After fix: passes. `split-utf8-sequence` is a regression case in the test suite. | ✅ |
| Minor #3: token interpolated in shell string | REFUTED, withdrawn. A test `test_token_value_is_not_shell_interpreted` now pins that double-quoted expansion does not re-parse the value. | ✅ |

Round 1's F2 mitigation also created a **new artifact**: `infra/ansible/playbooks/maintenance-notify-test.yml` and the `make maintain-notify-test NODE=x` target, codifying what was previously an operator's one-off `systemctl start` over SSH.

All 8 playbooks (7 provision + 1 notify test) pass `ansible-playbook --syntax-check`. Lint (`make lint`) and type (`make type`) pass.

### Findings

New findings in this round — none are Blockers or Majors:

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|-------------|
| Minor | REAL | Spec artifacts (proposal.md) | AC4 checkbox says "6/7 done" but verification.md confirms 7/7 (aws1 was completed 2026-08-14). AC8 checkbox is still `[ ]` but the rotate_note for `apps.services.automation.notify.webhook_secret` was updated (confirmed by reading secrets_manager.py: `"Regenerate, paste into the n8n 'notify-webhook' Header Auth credential, update every source."`). The checkboxes in proposal.md don't reflect the current state. | `grep '\[ \]\|6/7' specs/ANSIBLE-035-maintenance-timer-rollout/proposal.md` shows the stale checkboxes; code reading of `secrets_manager.py` confirms AC8 is done; `make secrets-audit --env staging` confirms 35/35 | UNTESTED (doc-only) | spec artifacts (proposal.md — tick the boxes) |
| Minor | THEORETICAL | Reliability (notify unit) | `kubelab-maintenance-notify.service` has no `Restart=` directive. If the curl POST to prod n8n fails (network blip, n8n temporarily unavailable), the notification is lost with exactly one attempt — the unit exits non-zero and has no retry or its own `OnFailure=` chain. Proposal says nothing about retry, but a failure notification that fails silently is a blind spot on the path whose job is to report promptly. | Code read of `kubelab-maintenance-notify.service.j2`: no `Restart=`, no `RestartSec=`, no `OnFailure=` on the notify unit itself. `TimeOutStartSec=30` bounds the stall but the result is the same — the notification is dropped. | `test_onfailure_target_names_a_unit_the_role_actually_installs` indirectly verifies the main unit's OnFailure target exists, but no test asserts retry on the notify unit itself | code (add `Restart=on-failure` with `RestartSec=10` to the notify service unit, or document the one-shot-only design as a deliberate choice in the comments) |
| Minor | THEORETICAL | Security (information disclosure) | `TOKEN="$(cat ...)"` in the notify script exposes the fleet-wide bearer token via process listing (`/proc/PID/cmdline`, `ps`) for the ~1s duration of the curl call. For a `log`-severity (non-paging) notification path on a root-owned service, the practical risk is low — an attacker with `ps` access likely has elevated privileges. However, the token is a long-lived fleet credential stored in `common.enc.yaml` and rotated only by re-provisioning, so disclosure has a wider blast radius than an env-scoped secret. | Code read: `kubelab-maintenance-notify.sh.j2` line 17 `TOKEN="$(cat ...)"` then line 48 `-H "Authorization: Bearer ${TOKEN}"`. The test `test_token_value_is_not_shell_interpreted` pins the injection property but does not test for process-listening exposure. | `test_notify_script_reads_the_token_from_the_declared_secret_file` (tests the file path, not the read mechanism) | code (read via curl `--config` with a one-line config file, or via a heredoc that doesn't place the token in any `ps`-visible argument) |
| Minor | THEORETICAL | Observability (secret write task) | The `Write fleet notify secret` Ansible task uses `no_log: true`, which prevents the operator from confirming idempotency at a glance — `changed` vs `ok` is suppressed in the playbook output. Ansible's `copy:` module IS idempotent by checksum comparison, so the behavior is correct; the gap is purely in runtime observability. | Code read of `tasks/main.yml` at the `Write fleet notify secret` task: `no_log: true`, `copy:` with `content: "{{ secrets... }}"`. | UNTESTED (operational, not testable) | code (accept as-is — `no_log` is intentional to avoid leaking the secret in Ansible output; surface in runbook as an operational note) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness | B | All acceptance criteria met functionally; cleanup gating, timer install on 7/7 nodes, OnFailure wiring proven via live failure injection and standalone delivery. Minor documentation stale-checkbox gap. |
| Verification | A | Per-node evidence with `changed=` counts and env context. Re-verification after ANSIBLE-038 fixes documented. Claims reproduced: `make test` (532/129), `secrets audit` (staging 35/35, prod 44/44), syntax checks (8 playbooks pass). Verdict from round 1's FAIL to this round's PASS backed by concrete code changes. |
| Scope | A | Diff matches proposal exactly. The untagged-pre_tasks fix on 4 playbooks is the same files and same bug class, explicitly documented. The maintenance-notify-test playbook is a new artifact demanded by the round-1 review. |
| Reliability | B | Error paths handled via gate variables, `OnFailure=` cascade, `set -euo pipefail`, `curl -sf`, bounded timeouts, UTF-8 truncation safe. No retry on notify failure (accepted design gap), secret token exposed in `ps` (low-risk). |
| Maintainability | A | Abundant WHY comments, clear gate-variable names, design decisions documented in comments rather than remaining implicit. Test suite uses `StrictUndefined` Jinja rendering (load-bearing), tests extract the real encoder body from the template to test the shipped code path. Runbook written, lessons captured. |
| Handoff-readiness | A | Spec updated with re-verification evidence, lessons captured (two ANSIBLE-035 entries in docs/lessons.md), runbook written, beelink remainder tracked on #1088. |

### Verdict

**PASS**

### Recommended next steps (before archive)

1. **Tick the stale checkboxes in proposal.md** — AC4 (aws1 done → 7/7) and AC8 (rotate_note updated → ticked). These are documentation artifacts only, not functional gaps, but `proposal.md` is the spec's front door and its unchecked boxes mislead future readers.

2. **Consider adding `Restart=on-failure` to the notify service unit** — or document the one-shot design explicitly in `kubelab-maintenance-notify.service.j2` as a deliberate choice (e.g. "# No retry — a single delivery attempt; the timer will fire again on the next run."). Either route closes the observability gap. Not a blocker for archive.

3. **Consider the `ps`-visible token concern** — triage on #1088 alongside the beelink remainder. The practical risk is low, but worth noting on the ticket that tracks this spec's post-archive loose ends.

4. **Archive is advisable.** `dotf spec archive` should pass: the frontmatter spec name matches the folder, `reviewed_sha` points to the current HEAD, `proposal.md`/`tasks.md`/`features.json` are unchanged since round 1's review (verified: `git diff b91c1f2 -- specs/ANSIBLE-035-maintenance-timer-rollout/{proposal,tasks,features}.json` is empty — the spec contract files are stable). The one unchecked item — beelink deferral on AC7 (tracked on #1088) — does not block the archive; it is recorded rather than silently claimed.
