---
id: lesson-312-yamllint-s-own-header-claimed-ci-coverage-it-
type: lesson
status: active
created: "2026-08-11"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling]
---

# `.yamllint`'s own header claimed CI coverage it doesn't have

**Context:** OPS-020 (#966) needed a two-line edit to `infra/config/values/common.yaml` — dropping the redundant `domain:` keys for crowdsec/loki, since every environment already overrides them.

**Problem:** The pre-commit hook failed on `yamllint`, reporting 19 indentation errors scattered across the file, none on the lines touched. Confirmed via `git stash` that the same 19 errors exist unmodified on `master` — pre-existing, unrelated to the edit. The `.yamllint` file's own header comment reads "the single SSOT consumed by pre-commit **AND CI**", but `.github/workflows/ci.yml`'s yamllint step is `yamllint .github/workflows/` — it never touches `infra/config/values/`, `infra/k8s/`, or anything else. The claim was true about which config file governs the rules, and false about where those rules actually get enforced. Nobody had committed to this specific file since the yamllint SSOT was unified (2026-06-27, #795) without hitting the local hook, so the violations accumulated invisibly — CI stayed green because it was never looking.

**Solution:** The 19 errors were all `indentation: wrong indentation, expected N but found N-2` — yamllint's inherited default (`indent-sequences: true`) rejecting this file's actual, uniform, pre-existing style of flush-left sequences. Reformatting the file to satisfy the strict rule would have turned a 2-line fix into a 60-100 line whitespace diff across the single most load-bearing config file in the repo. Set `indentation.indent-sequences: whatever` in `.yamllint` instead — accepts both styles, so it can only remove errors, never introduce new ones elsewhere in the repo (verified: `yamllint infra/config/values/` clean afterward, no new violations surfaced).

**Rule:**
- **A comment claiming "X enforces this" is a claim, not a guarantee — check what X actually runs, not what its header says it runs.** `ci.yml`'s yamllint step covers one directory; nothing else in the repo is CI-linted for YAML at all, so any of the other values/K8s/ansible YAML files could carry the same kind of dormant violation today.
- **When a lint failure's errors don't touch your diff, check master first.** `git stash && yamllint <file>` before assuming the failure is yours to fix as part of the change — it decides whether the fix belongs in this PR or is separable policy work.
- **Reformatting to satisfy a linter and relaxing the linter to match reality are different fixes with different blast radii.** The existing style was uniform across the whole file, not sloppy — that made it the file's convention, not a defect, and the config was wrong for not accepting it.

**Tags:** `#yamllint` `#ci-gap` `#pre-commit` `#false-assumption` `#config-drift` `#ops-020` `#gotcha`
