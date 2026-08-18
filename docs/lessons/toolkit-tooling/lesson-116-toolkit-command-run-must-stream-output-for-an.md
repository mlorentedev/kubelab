---
id: lesson-116-toolkit-command-run-must-stream-output-for-an
type: lesson
status: active
created: "2026-03-15"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling]
---

# Toolkit command.run must stream output for Ansible

**Context:** Running Ansible playbooks via toolkit infra ansible run command
**Problem:** command.run() with capture_output=True buffers all stdout until the command finishes. For Ansible playbooks that take 30-60s with per-task output, the CLI appears hung with no feedback.
**Solution:** Pass capture_output=False to command.run() in the ansible_run CLI command. This streams Ansible output directly to the terminal in real-time. Trade-off: can't inspect result.stdout/stderr after, but for interactive commands like Ansible this is the correct behavior.
**Tags:** `#toolkit` `#ansible` `#cli` `#ux`
