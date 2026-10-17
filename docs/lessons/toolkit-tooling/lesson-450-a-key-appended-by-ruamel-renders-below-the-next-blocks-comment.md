---
id: lesson-450-a-key-appended-by-ruamel-renders-below-the-next-blocks-comment
type: lesson
status: active
created: "2026-09-04"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, ruamel, yaml, promotion, version-pin, pr-1603]
---

# A key appended by ruamel renders below the next block's comment

**Context**: Promoting `web` to `1.12.0` (#1600) took prod off an 81-day-old
image and exposed how `promote()` writes an app's `version:` pin into
`values/{staging,prod}.yaml`. #1603, closes #1602.

**Problem**: The one key that decides which image an environment runs was
rendered under `# Third-party services`, reading as if it belonged to
`services:`:

```yaml
      enable_contact: false

  # Third-party services
      version: 1.12.0
  services:
```

It parses correctly: the six-space indent keeps it inside
`apps.platform.web`, and a comment does not break a mapping. That is what
makes it a trap rather than a bug. The file is wrong to a human and right to
the parser, and the human's natural repair, dedenting `version` to match the
comment it appears to belong to, moves a production image tag out of the app
block; the overlay regenerates without a pin and the drift gate compares
against a source of truth that silently lost a key. Three keys were
affected across both env files.

It never self-corrected because `promote()` round-trips with ruamel, which
rewrites an existing key in place. The misplacement is created once, on an
app's first promotion, when `app_cfg["version"] = version` appends to the end
of the mapping, and ruamel holds a comment that follows a block as a trailing
comment of that block's last key, not a leading comment of the next one.
Every later promotion preserved the wrong position faithfully. Confirmed by
probe: the append form reproduces the committed layout exactly.

**Solution**: A first-time pin is inserted at the top of the app block
(`CommentedMap.insert(0, ...)`), the one position that cannot collide with a
trailing comment; existing pins keep their place. The three misplaced keys
were repaired by hand, since a generator re-run preserves them. Two guards:
`tests/test_values_version_key_placement.py` asserts every
`apps.platform.<app>.version` is adjacent to its block and fails on the
pre-fix tree naming all three, and a promotion test that goes red when the
insert reverts to assignment. `make config-check-drift` for both envs stayed
`No drift`, proving the change is placement-only.

**Rule**: A round-tripping YAML writer preserves what it finds, including a
key it once appended in the wrong place, so a layout defect created on the
first write is permanent and invisible to every later write. When adding a
key to a mapping that may carry a trailing comment, insert at a position that
cannot inherit it, and guard placement with a test that reads adjacency, not
parse results, because the parser is the one reader the defect does not
fool.

**Tags**: `#ruamel` `#yaml` `#comments` `#promotion` `#pr-1603`
