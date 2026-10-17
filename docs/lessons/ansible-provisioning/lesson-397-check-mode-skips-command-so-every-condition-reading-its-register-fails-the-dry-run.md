---
id: lesson-397-check-mode-skips-command-so-every-condition-reading-its-register-fails-the-dry-run
type: lesson
status: active
created: "2026-08-26"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, check-mode, idempotence]
---

# Check mode skips `command:`, so every condition reading its register fails the dry run — and there is never just one

**Context**: #1400 noted, as a smaller aside, that `make provision NODE=bee
CHECK=1` failed on `Stop Ollama systemd service` against a node whose real run
is clean. The guard read `_ollama_check.rc`; Ansible skips `command:` tasks in
check mode, so the register carried no `rc` and the `when` raised instead of
gating.

**Problem**: Fixing that one moved the failure down the file rather than
clearing it. The dry run then died on `Wait for MinIO container to be running`
with `"Command would have run if not in check mode"` after twelve retries.

Auditing the whole role turned up **five** instances of one shape — a read-only
`command:` registered and consumed by a `when` or an `until`:

| register | consumed by |
|---|---|
| `_ollama_check` | `when` |
| `_buildx_check` | `when` |
| `_minio_state` | `until` |
| `_runner_state` | `until` |
| `_gitea_health` | `until` |

The `until` variants are the nastier half: the condition never matches, so the
task retries to exhaustion — sixty seconds of waiting — before failing a dry run
on a converged node.

**Solution**: `check_mode: false` on the probes. All five only read
(`systemctl cat`, `docker buildx inspect`, `docker inspect`), so running them
during a dry run changes nothing and is what lets the dry run answer at all.

Deliberately **not** applied to `_pull`, `_compose_up` and `_gitea_bootstrap`:
those mutate, check mode is right to skip them, and none of their registers
gates another task — `_gitea_bootstrap`'s feeds `changed_when`, which a skipped
task never evaluates.

A second path reaches the same undefined value and `check_mode: false` does not
close it: the Ollama probe carries no `cleanup` tag while its three consumers
do, so `--tags cleanup` runs them without it. That needs
`(_ollama_check.rc | default(1)) == 0` — defaulting to "absent unless measured",
which skips a cleanup rather than acting on an unmeasured node.

**Rule**: A `command:` register consumed by a condition is a check-mode failure
by construction. When you find one, **grep the whole role for the shape** rather
than fixing the instance in front of you — the sibling probes were written by
the same hand on the same day and fail the same way. Read-only probe →
`check_mode: false`; mutating task → leave it skipped and make sure nothing
gates on it. And where the probe and its consumers can be separated by tags, the
default in the `when` is a second, independent guard, not belt-and-braces.

**Tags**: `#ansible` `#check-mode` `#idempotence` `#pr-1421`
