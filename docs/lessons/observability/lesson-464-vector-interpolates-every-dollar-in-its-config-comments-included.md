---
id: lesson-464-vector-interpolates-every-dollar-in-its-config-comments-included
type: lesson
status: active
created: "2026-09-26"
owner: manu
category: observability
tags: [kubelab, observability, vector, vrl, sec-021]
---

# Vector interpolates every `${...}` in its config file, comments included, and refuses to start on an unset one

**Context**: Adding a VRL `replace()` with a braced capture reference (`"${1}_REDACTED"`) to the Vector remap for SEC-021 (#1840).

**Problem**: Vector expands environment variables over the raw text of the config before parsing YAML or VRL. `${1}` in the VRL string and `$1_REDACTED` in a comment above it were each read as a variable, and `vector test` failed with `Missing environment variable in config. name = "1"`. In the DaemonSet that is a DaemonSet that never starts, so no logs reach Loki at all.

**Solution**: Write a literal dollar as `$$` (`"$${1}_REDACTED"`), and keep dollars out of comments. The shipped config is run through `vector test` with the pinned image in `tests/test_oauth_tokens_not_logged.py`, which is how this was caught before any cluster saw it.

**Rule**: In a Vector config, every `$` is Vector's before it is YAML's or VRL's. Test the shipped file with `vector test`, not a copy of the VRL.

**Tags**: `#vector` `#vrl`
