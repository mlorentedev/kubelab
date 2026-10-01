---
id: lesson-496-changed-when-false-does-not-make-a-task-a-read
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, check-mode, idempotence, ansible-059]
---

# `changed_when: false` does not make a task a read

**Context**: ANSIBLE-059 (#1978) set out to make every read in every role run under `--check`. Lessons 392 and 397 record why: check mode skips `command` and `shell`, a skipped task registers no `rc` or `stdout`, and whatever consumes the register breaks the dry run. The plan was a fleet-wide guard defining a read as "a registered `command`/`shell` with `changed_when: false`", and a mechanical `check_mode: false` on every match.

**Problem**: the shape is not the property. Of the 23 matches, two write. `node_maintenance`'s `apt-mark hold` marks packages and reports no change because the same run releases every hold it creates, which keeps a provision at `changed=0`. `docker`'s `Test Docker functionality` pulls `hello-world` and runs a container. A blanket `check_mode: false` would have made a dry run hold packages and pull images, and in check mode the matching `apt-mark unhold` stays skipped, so the holds would have outlived the dry run. `changed_when: false` answers "should this be reported", which is an idempotence question. Whether a task has side effects is a different question, and nothing in the task's syntax answers it.

**Solution**: `tests/test_ansible_reads_run_in_check_mode.py` keeps the shape as the default rule and names the exceptions: `WRITES_THAT_REPORT_NO_CHANGE`, keyed by (role, task name), each with the reason it reports no change. A third test fails when a declared write is renamed or removed, or gains `check_mode: false`, so the list cannot go stale or be used to hide a read.

**Rule**: before adding `check_mode: false`, read the command, not the `changed_when`. A task that reports no change may still write, when its effect is undone later in the run, or when it is a smoke test. A guard that infers "read" from syntax needs a declared, reviewed list of the writes that share that syntax.

**Corollary (waits)**: a read that polls a service the run itself starts (`until:` on `docker info`, a container's health) is side-effect-free and still not safe to run unguarded under `--check`, because check mode starts nothing: on a node that was never provisioned it exhausts its retries and fails the dry run. Waits take `until: (<cond>) or ansible_check_mode` and `ignore_errors: "{{ ansible_check_mode }}"`, so a dry run makes one attempt and moves on; the guard's fourth test enforces it. Found by review on #1986, not measured on a fresh node.

**Tags**: `#check-mode` `#idempotence` `#ansible-059` `#issue-1978`
