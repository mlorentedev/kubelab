---
id: lesson-542-ufw-does-govern-a-port-published-by-a-rootless-daemon
type: lesson
status: active
created: "2026-10-08"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, rootless, ufw, firewall, hermes, open-webui]
---

# ufw does govern a port published by a rootless daemon

**Context**: AI-009 AC4 (#1933) connects Open WebUI, on ace2's system Docker
daemon, to hermes-kubelab's API, on the agent's rootless daemon. Two daemons
share no network, so Open WebUI has to reach Hermes at an address of the host.
The fleet rule (CLAUDE.md, #959) says a ufw rule cannot restrict a
Docker-published port, which would leave the bind address as the only control.

**Problem**: That rule is true of the system daemon and false of a rootless one.
The system daemon publishes with a DNAT in PREROUTING, before ufw's filter
chains see the packet. A rootless daemon has no rights over the host's tables:
rootlesskit's builtin port driver publishes with a listener process in the
host's network namespace, so the connection is an ordinary one to a local
socket and crosses INPUT, where ufw denies by default.

Measured on ace2, 2026-10-08, with Hermes published on Open WebUI's bridge
gateway:

```text
$ sudo ss -ltnp | grep 8642
LISTEN 0 1024 172.30.250.1:8642 0.0.0.0:* users:(("rootlesskit",pid=1129,fd=13))

# from a container on docker0, the system daemon's default network:
[UFW BLOCK] IN=docker0 ... SRC=172.17.0.2 DST=172.30.250.1 ... DPT=8642 ... SYN
```

A container on Open WebUI's network connects through the one allow rule
(`172.30.250.1 8642/tcp on br-open-webui ALLOW 172.30.250.0/24`).

**Solution**: Hermes publishes on the bridge gateway, and ufw admits that
bridge's subnet alone (`roles/agent_stack/tasks/hermes.yml`). Every provision
proves both directions: a probe on Open WebUI's network must connect, and a
probe on the default network must be refused, after the API read-back has
proven the listener up, so the refusal cannot come from a dead API.

**Rule**: Before relying on ufw for a published port, ask which daemon
publishes it. A rootful daemon's port is governed by its bind address alone; a
rootless daemon's is governed by the host firewall too. Prove it from a
container on another network and read the `[UFW BLOCK]` line, not the
connection failure, which a dead listener produces just as well.

**Tags**: `#rootless` `#ufw` `#ai-009`
