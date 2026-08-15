---
spec: "ANSIBLE-035-maintenance-timer-rollout"
verdict: "FAIL"
reviewed_sha: "b91c1f20d50077ab53532d52943317b18646a260"
reviewer: "nan/deepseek-v4-flash"
date: "2026-08-16"
---

## Adversarial review

**Scope**: ANSIBLE-035-maintenance-timer-rollout (PR #1070 - merge e63f1e0)
**Sources**: specs/ANSIBLE-035-maintenance-timer-rollout/{proposal,tasks,verification,features}.md, git diff e63f1e0^..b91c1f2, live commands run against the merged code

### Spec and task alignment

The proposal, tasks, and code are well-aligned. All 7 provisioning playbooks receive the role with `maintenance_run_cleanup: false`. The `maintain.yml` playbook is confirmed unaffected (it never sets `maintenance_run_cleanup`, inheriting the `true` default — confirmed by reading the playbook before/after, noting no diff). The `OnFailure=` wiring is in the unit template, the notify script delivers the envelope, and the secret path is a dedicated key in `common.enc.yaml` immune to env-override collisions.

One verified spec-to-code divergence: the verification artifact claims a staging secret count of 39/39, but the actual audit yields 35/35. See Finding F1 below.

Four side changes are documented (untagged pre_tasks fix on provision-vps/aws1/rpi3/rpi4.yml) with an explicit "in-scope" claim. The claim is defensible: these are the same file set and the same bug class surfaced by the ticket's own new task.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|-------------|
| Major | REAL | Verification evidence | Staging secret count claimed as 39/39 but actual audit yields 35/35 at both the merge commit (e63f1e0) and HEAD (b91c1f2) | `poetry run toolkit secrets audit --env staging` at d23dd24 (parent): 34/34; at e63f1e0 (merge): 35/35 (+1 from fleet_webhook_secret); the verification.md claim of 39/39 is unreproducible | UNTESTED (the count itself is an assertion, not a testable path) | spec artifacts (verification.md: correct the claimed staging count) |
| Major | REAL | Test coverage | No automated regression tests exist for the notify script, the OnFailure= wiring, or the JSON encoding of journal output | Manual inspection of `tests/` directory confirms zero test files target the `node_maintenance` role's templates or the notify delivery. The verification relied entirely on one-off live commands (standalone delivery on 2 nodes, deliberate failure injection on 1). Per skill rule: lack of negative tests is a Major finding by default. | UNTESTED | tests (add pytest or bats test for notify script behavior, curl delivery, and failure handling) |
| Minor | THEORETICAL | Security (shell injection) | Notify script reads token via `TOKEN="$(cat ...)"` and embeds `${TOKEN}` in curl header. If the secret file were tampered with to contain `$(...)`, backticks, or shell metacharacters, injection is possible | Code read of `kubelab-maintenance-notify.sh.j2`: line 20 `TOKEN="$(cat ...)"`, line 40 `-H "Authorization: Bearer ${TOKEN}"`. The file is 0600 root-owned and SOPS-resolved (not user-writable), but the script has no sanitization layer | UNTESTED | code (token read via a safer mechanism — e.g. `sed` substitution into a Python arg, or curl's `--config` with a one-line config file that already contains the token) |
| Minor | THEORETICAL | Reliability (UTF-8 truncation) | `tail -c 2000` in the notify script can split a multi-byte UTF-8 character mid-sequence, causing `python3 -c 'import json; print(json.dumps({"body": sys.stdin.read()}))'` to raise UnicodeDecodeError on stdin read | Code read: the piped chain `printf ... | tail -c 2000 | python3 -c ...` may pass invalid UTF-8 to Python's stdin decoder if the 2000-byte boundary falls inside a multi-byte character. Journal output is mostly ASCII, making this unlikely but the path exists | UNTESTED | code (read via `python3 -c "sys.stdout.buffer.read(2000).decode('utf-8', 'replace')"` or add `errors='replace'` to the stdin handling) |
| Minor | THEORETICAL | Reliability (no curl timeout) | `curl -sS -f` has no `--connect-timeout` or `--max-time`. If n8n is unreachable, the default curl timeout (~120s connect, no total max) can hold the notify unit past a user's expectations | Code read: no timeout on `curl ... --connect-timeout 10` in the script. Systemd's `TimeoutStartSec=30` in `kubelab-maintenance-notify.service.j2` will eventually kill it, but a 30s hang is still a delay | UNTESTED | code (add `--connect-timeout 10 --max-time 15` to the curl invocation in the notify script) |
| Minor | REAL | Documentation accuracy | `maintain.yml`'s doc comment says `maintenance_install_timer` default is `false` ("TIMER=1" toggles it), but the role default is now `true`. This is correct behavior (maintain.yml explicitly overrides with its own var), so not a code bug — but a future reader could be confused | Code read: maintain.yml passes `maintenance_install_timer: "{{ install_timer \| default(false) \| bool }}"` so it explicitly sets the value; the role default change to `true` doesn't affect it. But maintain.yml's doc header says "install weekly timer" for `TIMER=1` and doesn't mention that the role default flipped | N/A | spec artifacts (optional: note in maintain.yml header that the explicit override protects this from the role-default change) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness | B | All acceptance criteria met functionally; cleanup gating, timer install, and notify wiring all work. Minor edge cases untested but no observed defects. |
| Verification | C | Per-node deployment evidence is detailed and credible, but the staging secret count (claimed 39/39, actual 35/35) is an unreproducible claim that undermines trust in the verification artifact. |
| Scope | A | Diff matches proposal exactly; the untagged pre_tasks fix is the same files, same bug class, explicitly documented. |
| Reliability | B | Error paths handled via `maintenance_run_cleanup` gate, `OnFailure=` cascade, `set -euo pipefail`, `curl -sf`. Missing: curl timeout, UTF-8 truncation guard, retry on notify failure. |
| Maintainability | A | Abundant in-line WHY comments, clear gate-variable design, gotchas captured in lessons.md. Excellent documentation. |
| Handoff-readiness | A | Spec complete, lessons captured (two ANSIBLE-035 entries in docs/lessons.md), runbook written, known artifact documented. |

### Verdict

FAIL

Two Major findings block PASS:

1. **F1 (Verification evidence not reproducible)**: The staging secret count in `verification.md` (39/39) cannot be reproduced. The actual count before ANSIBLE-035 was 34/34; the change adds exactly 1, yielding 35/35. The audit passes at 100% — the code is correct — but the verification artifact is inaccurate.

2. **F2 (No automated regression tests)**: The notify script and `OnFailure=` wiring have zero automated tests. The skill mandates: "Lack of negative tests is a Major finding by default." Manual live verification on rpi3/beelink is thorough but not repeatable in CI.

The rubric independently yields PASS WITH GAPS (one C in Verification), but the Major findings escalate the verdict to FAIL.

### Recommended next steps (before archive)

1. **Fix F1 — correct verification.md**: Change the staging count from "39/39" to "35/35" and add a note that the base was 34/34 before the +1 from the new `fleet_webhook_secret` spec. This restores the verification artifact's reproducibility.

2. **Fix F2 — add automated tests**: At minimum:
   - A bats test that confirms notify script template renders without Jinja errors (`ansible-playbook --check` or `ansible all -m template -a ...` with a mock inventory)
   - A pytest test asserting that `OnFailure=kubelab-maintenance-notify.service` appears in the rendered service unit (use the ansible template module to render and grep the output)
   - Optionally: a bats test that validates the journal-to-JSON encoding handles truncated multi-byte input (`printf '\xe2\x86' | ./script` should not crash)
   - Optionally: a bats test asserting that `curl -f` without a timeout gets `--connect-timeout` (parses the rendered notify script)

**After F1 and F2 are resolved, the verdict flips to PASS WITH GAPS** (rubric: C in Verification → B after F1 fix; Correctness stays B due to unresolved minor findings; the remaining Minor findings in security/reliability are documented but not blockers for archive).

`dotf spec archive` is **not advisable** in the current state — it will refuse because of the FAIL verdict. Apply the two fixes above first, then re-evaluate.

### Additional notes

- The `features.json` state is correct: all features are `pending` with empty `evidence` (the harness writes `passing`). No violations.
- No `[AGENT-DRAFT]` or `[AGENT-SUGGESTION]` tags found in any spec file.
- The three Minor findings (shell injection surface, UTF-8 truncation, missing curl timeout) are documented as THEORETICAL or low-risk concerns. They do not block the archive by themselves but should be triaged before or after archiving.
