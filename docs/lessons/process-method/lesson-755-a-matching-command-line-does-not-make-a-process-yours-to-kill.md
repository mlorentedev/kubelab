---
id: lesson-755-a-matching-command-line-does-not-make-a-process-yours-to-kill
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: process-method
tags: [kubelab, process-method, agents, parallel-sessions]
---

# A matching command line does not make a process yours to kill

**Context**: Two agent sessions ran on the same controller, from different worktrees and harnesses, and both needed `make provision NODE=ace2 ENV=staging`. One session had stopped a background task of its own and believed a child had survived the stop, which can happen: stopping a task does not always take its children with it.

**Problem**: That session found a running `ansible-playbook ... provision-ace2.yml` and killed it as its own leftover. It belonged to the other lane: its parent chain led to a herdr pane running a different agent. That lane's provision died mid-play. Separately, the first session's own earlier run had already reverted the other lane's uncommitted `agent_stack` changes on ace2, because a provision renders whatever the checkout it runs from holds. Two lanes converging one node undo each other even when nobody kills anything.

**Solution**: Reported to the operator at once, with the PID and what it was running, and handed over a message for the other lane. The session then stopped provisioning ace2 until the other lane had merged its change (#3518), merged master, and only then ran again.

**Rule**: Before killing a process, walk `ps -o pid,ppid,command -p <pid>` up to its root (shell, tmux or herdr pane, agent binary). Kill it only if that chain ends in your own session's tree; otherwise leave it and coordinate. A node, like the staging slot, is one shared target: when two lanes need to converge it, one runs and the other waits for the first to merge. If a process that was not yours is already dead, say so straight away rather than retrying around it.

**Tags**: `#parallel-sessions` `#pr-3518` `#issue-1075`
