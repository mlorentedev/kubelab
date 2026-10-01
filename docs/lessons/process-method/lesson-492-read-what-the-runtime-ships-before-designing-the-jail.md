---
id: lesson-492-read-what-the-runtime-ships-before-designing-the-jail
type: lesson
status: active
created: "2026-09-30"
owner: manu
category: process-method
tags: [kubelab, process-method, agents, architecture, security, topology]
---

# Read what the agent runtime ships before designing its jail, and apply "always-on" to callees, not callers

**Context**: Placing the Hermes agent and Open WebUI on ace2 (AI-009, #1933, ADR-068). ADR-058 D3 gates autonomous agents behind a host-level policy jail and a human-approval channel, both deferred as unbuilt. C8 says anything an agent may call at any hour runs on an always-on host, and ADR-058 D5 sends unattended 24/7 agents to the always-on tier.

**Problem**: Read literally, the two rules put Hermes on the VPS or gcp1 and make a bespoke jail a prerequisite. The VPS is the prod K3s server (C2 forbids that), gcp1 had 0.49 GB available, and the jail was a project of its own. The ticket had already gone the other way: it put Hermes on ace2, with approvals off and a shared writable vault.

**Solution**: Two readings changed the answer.
- Hermes upstream ships the controls D3 asks for: `terminal.backend: docker` runs commands in a sandbox container, and `approvals.mode: manual` with `timeout: 300` fails closed, with prompts sent over the messaging channel. Its cron catches up each missed recurring slot once (`cron.catch_up_missed`).
- C8 constrains what is *called*. Nothing in kubelab calls Hermes; Hermes pulls, reconciles and pushes. An on-demand host is correct for it, and the only cost is that its chat does not answer while the host is off.

**Rule**: Before designing an isolation or approval layer for an agent, read the runtime's own security and scheduling docs; the gate may already be a config block. When a placement rule says "always-on", ask whether the workload is a callee anything depends on, or a caller that tolerates downtime. Only the first needs the always-on tier.

**Tags**: `#agents` `#adr-068` `#issue-1933`
