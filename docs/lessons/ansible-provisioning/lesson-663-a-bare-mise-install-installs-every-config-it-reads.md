---
id: lesson-663-a-bare-mise-install-installs-every-config-it-reads
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, mise, dev-node, idempotence]
---

# A bare `mise install` installs every config it reads, and reports installing when nothing is missing

**Context**: Provisioning ace2, the developer node, behind the lab edge (NET-005). The `dev_node` role renders `~/.config/mise/config.toml` with node, go and python, then runs `mise install`.

**Problem**: With no tool named, mise installs every tool from every config it reads, including `~/.config/mise/conf.d/`, where the operator's dotfiles put 39 more tools, two at `@latest`. Three of them were missing (about 450 MB). They downloaded at about 19 kB/s each and hit mise's own 1800 s per-download limit. That failed the provision before `agent_stack`. A partial download is discarded, so a rerun starts from zero. Separately, the task's `changed_when` looked for "installing" in the output, and mise prints `installing N tools` even when all N are already installed, so the task never converged.

**Solution**: Name the tools: `mise install {{ dev_node_toolchains | list | join(' ') }}`. Gate the install on `mise ls --missing <tools>`, a read with `changed_when: false`, rather than parsing mise's output. On ace2 the second and third runs then reported `changed=0`. `mise config ls` shows which files a node's mise reads.

**Rule**: A role that installs tools through a manager that merges several configs names its own tools, because the other configs belong to someone else's deploy. Decide whether anything changed from a state read, never from the installer's progress text.

**Tags**: `#ansible` `#mise` `#idempotence` `#pr-2816`
