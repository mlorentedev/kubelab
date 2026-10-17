---
id: lesson-546-mcpo-takes-its-api-key-only-on-the-command-line
type: lesson
status: active
created: "2026-10-10"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, mcpo, mcp, open-webui, secrets, hermes]
---

# mcpo takes its API key only on the command line, where every user on the host can read it

**Context**: AI-009 AC9 (#1933) serves Open WebUI the vault through mcpo, which
turns the stdio filesystem MCP server into an OpenAPI tool server. The bridge
runs on ace2's system Docker daemon, beside an agent whose Unix user must not
be able to use it.

**Problem**: mcpo v0.0.20 reads its key from `--api-key` and from nothing else:
no environment variable, no file. Put in the container's `command:`, the key is
in `/proc/<pid>/cmdline` of a process in the host's PID namespace, which every
user on the node can read, the agent's included. Two more defaults surprised:
without `--strict-auth` the OpenAPI spec and `/docs` answer without the key, and
a tool removed with `disabledTools` in the config is not refused but absent
(its endpoint answers 404 and it is missing from the spec), so the spec itself
is the proof of what is served.

**Solution**: a five-line launcher is the image's entrypoint. It pops the key
from the environment (an `env_file` of mode 0600) and calls `mcpo.app(args=...)`
in-process, so the key is never on a command line. Measured on ace2,
2026-10-10: the key in 0 of the container's cmdlines; 401 on `openapi.json`
without it; 10 read tools in the spec and none of `write_file`, `edit_file`,
`create_directory`, `move_file`. The only host processes as uid 65534 are the
bridge's own two, so its `/proc/<pid>/environ` is readable by root and itself.
The provision probes all of this from inside Open WebUI's container with the key
Open WebUI holds (`roles/agent_stack/files/mcp-bridge-probe.py`).

**Rule**: before passing a secret to a tool, find out how the tool reads it. A
flag-only secret goes through a launcher that hands it over in-process, never
through `command:`. And when a server can drop a capability by configuration,
verify against its own published spec, not by calling the dropped capability.

**Tags**: `#mcp` `#secrets` `#ai-009`
