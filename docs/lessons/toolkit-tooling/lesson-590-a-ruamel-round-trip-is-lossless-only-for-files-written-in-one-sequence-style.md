---
id: "lesson-590-a-ruamel-round-trip-is-lossless-only-for-files-written-in-one-sequence-style"
type: lesson
status: active
title: "A ruamel round-trip is lossless only for files written in one sequence style"
created: "2026-10-17"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, ruamel, promotion, generated-files]
---

# A ruamel round-trip is lossless only for files written in one sequence style

**Context**: `toolkit deployment promote --app errors` sets `edge.errors.version` in `common.yaml`. The `promote-errors` job in `release.yml` runs it on every errors release and opens the PR. The errors 1.2.1 PR (#2388) carried +137/−112 lines in `common.yaml` for a one-line bump, conflicted with master and failed the platform manifest check.

**Problem**: Two defects, and neither showed in the tool's own output, which reported success.

1. The tool loaded `common.yaml` with ruamel and dumped all of it back. ruamel preserves comments and key order, but it writes every block sequence with one indent and wraps long strings at its width. `common.yaml` has both indented (`  - x`) and flush (`- x`) sequences. A round-trip with no edit, measured on master `424f577`: 250 changed lines with the default config, 268 with `indent(2,4,2)`, 186 with `indent(2,2,0)`. No setting is lossless. `staging.yaml`, `prod.yaml` and `dev.yaml` round-trip with 0 changes, which is why api/web promotion never showed it.
2. `infra/config/platform.json` records `source_commit`, the git blob hash of `common.yaml`. Any edit to `common.yaml` is drift until the manifest is regenerated, and the tool never did. It also ignored the exit status of the kustomization sync, so a failed sync would still have been reported as a promotion.

**Solution**: #2430. ruamel still parses the file, which validates it and gives the scalar's position (`mapping.lc.value("version")`), and the write replaces that scalar on its own line only. If the key is absent, the tool refuses; it never falls back to a full dump. The promotion then regenerates `platform.json` and fails when either sync returns non-zero. Run on master, the fixed tool produced a three-file, four-line diff identical to the hand-checked #2432 (same `source_commit`).

**Rule**: Before letting a tool rewrite a hand-written YAML file through ruamel, round-trip the real file once with no edit and count the changed lines. Zero means a dump is safe. Anything else means edit the one value in place. And when a file feeds a generated artifact keyed on its content hash, the change that edits it has to regenerate the artifact too.

**Tags**: `#ruamel` `#promotion` `#platform-json` `#pr-2388` `#issue-2430`
