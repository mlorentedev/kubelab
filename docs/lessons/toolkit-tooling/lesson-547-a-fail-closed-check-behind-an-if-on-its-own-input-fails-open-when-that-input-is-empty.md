---
id: lesson-547-a-fail-closed-check-behind-an-if-on-its-own-input-fails-open-when-that-input-is-empty
type: lesson
status: active
created: "2026-10-10"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, kubernetes, fail-closed, testing]
---

# A fail-closed check behind an `if` on its own input fails open when that input is empty

**Context**: The `cluster_bootstrap` layer applies manifests outside Kustomize, and `render_text` substitutes their `RESOLVE_*` placeholders from each entry's `render:` map. Its docstring promised it fails closed: a placeholder with no mapping raises, so a half-substituted manifest never reaches the cluster. TOOL-009's adversarial review read the caller.

**Problem**: `render_and_apply` called `render_text` only `if entry.render:`. The check for unmapped placeholders lived inside the function the `if` skipped, so the one input it most needed to catch, an entry with a placeholder and no map at all, bypassed it. The review reproduced it: `render={}` with `RESOLVE_RPI4_TAILSCALE_IP` in the manifest returned `True` and handed `kubectl` the literal string. No live entry was in that state, and every existing test passed, because the only empty-map test used a manifest with no placeholder.

**Solution**: `render_and_apply` renders unconditionally. With an empty map every placeholder is unmapped, so a forgotten map now fails the entry (or skips it when `optional`). `test_a_placeholder_with_no_render_map_is_never_applied` covers both branches, and `make mutate` restoring the `if` turned both red.

**Rule**: When a check fails closed on bad input, the decision to run it must not depend on that same input. An `if config:` in front of a validator turns "the config is missing" into "the config is valid". Test the empty case with input that would fail, not with input that has nothing to check.

**Tags**: `#fail-closed` `#testing` `#tool-009`
