---
id: lesson-392-check-mode-skips-command-so-a-guard-reading-its-rc-does-not-gate
type: lesson
status: active
created: "2026-08-24"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, check-mode, dry-run, idempotence, issue-1400]
---

# `--check` skips `command:`, so a guard that reads its `rc` stops gating — the dry run fails where the real run does not

**Context**: Deploying a one-line Gitea change to the Beelink (#1389). Ran `make provision NODE=bee ENV=staging CHECK=1` first, as a dry run should be.

**Problem**: The dry run reported `failed=1`, on a task unrelated to the change:

```
fatal: [beelink]: FAILED! => {"msg": "Could not find the requested service ollama: host"}
```

The role's guard is correct and carefully written. A probe runs `systemctl cat ollama` with `failed_when: false`, and the teardown is gated on `when: _ollama_check.rc == 0`, with a comment explaining why `failed_when` rather than `ignore_errors`. Ollama was retired in 2026-08, so on every node the probe fails, the `rc` is non-zero, and the stop task is skipped.

**In check mode Ansible skips `command:` tasks by default.** The register is populated with a skip result, the `when` no longer evaluates the way the author intended, and the `systemd` task runs against a service that does not exist. **The real run was clean:** `failed=0`, the guard working exactly as designed.

So `CHECK=1` on that node reports a failure that does not exist, which is worse than reporting nothing: the operator either stops and investigates a phantom, or learns to run past a red dry run.

**Solution**: The real run was the answer here, and the finding was recorded on #1400 rather than fixed inline. The fix, when taken, is `check_mode: false` on the probe — a read-only `systemctl cat` is safe to execute during a dry run, and executing it is what makes the guard behave the same in both modes.

**Rule**: Any `when:` reading a field of a registered `command:`/`shell:` result is unguarded in check mode. Put `check_mode: false` on the probe whenever it is read-only, which is the case for every probe worth having. Generalizes past Ansible: a dry-run mode that skips the step producing a decision's input does not simulate the run, it simulates a different run — and a dry run that fails where the real one succeeds trains people to ignore it, the same habit `roles/glances/defaults/main.yml` warns about with "a check that fails on a working deploy is worse than no check".

**Tags**: `#ansible` `#check-mode` `#dry-run` `#issue-1400`
