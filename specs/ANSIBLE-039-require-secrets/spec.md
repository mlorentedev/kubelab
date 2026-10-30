---
id: ANSIBLE-039-require-secrets
type: spec
status: active
created: "2026-10-30"
owner: manu
issue: "kubelab#1100"
---
# ANSIBLE-039: Require secrets

## Intent

A play that reads `secrets` and built none templates every `| default('')` to an empty credential and reports failed=0 (#893). #2836 keeps the SOPS load under every `--tags` that reads it, so a play that loads can no longer skip it. A play that reads `secrets` and never loads them still passes in silence. The operator decided AC4 on #1100: fail loudly, with an explicit opt-out.

## Scope

In:

- `_includes/require-secrets.yml`: one assert, `secrets is defined or allow_missing_secrets`, whose output says which branch held.
- Each play with a reader of `secrets` imports it with `tags: [always]` after its SOPS merge. `maintain.yml`'s load gains `always`, so a tagged run does not fail the assert.
- `tests/test_require_secrets.py`: every play with a reader of `secrets` (found with `test_pre_task_facts`'s readers) imports it, tagged `always`, after a load tagged `always`; and a local `ansible-playbook` run of the real file under `--tags role`.

Out:

- A tree that loaded but lacks one key. Its `| default('')` still templates to empty; removing those defaults is a separate decision.
- `deploy-k3s.yml`, which loads `secrets` and reads none of them.
- Provisioning without the operator's SOPS key. `sops -d` runs first in every play that loads and fails on its own.

## Checklist

- [x] Failing tests first: the static rule, its resolution on a hand-built play, and the run of the real assert (four cases, one of them `include_tasks` to show why the import is static).
- [x] The include, twelve plays across eleven playbooks, `maintain.yml`'s tags.
- [x] Mutants red: `include_tasks` in a play, `that: true`, the opt-out removed, the import's `always` replaced, the import removed.
- [x] Lesson: lesson-677.

## Evidence

See the PR body.
