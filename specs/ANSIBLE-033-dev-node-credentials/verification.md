---
tags: [spec, verification, templates]
created: "2026-08-07"
---

# Verification - ANSIBLE-033-dev-node-credentials

## Evidence

One row per acceptance criterion, each bound to the `features.json` feature that
carries its executable command. Fill `Evidence` with observed output and a date,
never with intent. `State` mirrors `features.json` and is **harness-owned**: an
agent may not promote a feature out of `pending`.

| AC | Feature | What it proves | State | Evidence |
| --- | --- | --- | --- | --- |
| AC1 | f1 | `gh` authenticated on ace2, working non-interactively | `pending` | **PASS** 2026-08-08 — verbatim, exit 0 |
| AC2 | f2 | Private clone → commit → push → PR from tmux, no agent forwarding | `pending` | **BLOCKED** — fixture archived; clone half proven, push half unproven |
| AC3 | f3 | Fine-grained token; `workflows: write` actually refused | `pending` | Not run — blocked on the same fixture; expiry/scope halves are manual |
| AC4 | f4 | Role delivers the credential from SOPS; second pass `changed=0` | `pending` | **PASS** 2026-08-08 — verbatim, exit 0 |
| AC5 | f5 | No prod credential reachable from ace2 | `pending` | **PASS** 2026-08-08 — re-run last, after every node mutation |
| AC6 | f6 | Token never in argv/logs/world-readable files; `gh` owns the sink | `pending` | **PASS** 2026-08-08 — verbatim, both halves, exit 0 |
| AC7 | f7 | Rotation runbook exists and is operational | `pending` | **PASS** 2026-08-08 — verbatim, exit 0 |

**5 of 7 verified.** AC2/AC3 are blocked on one thing only: a private, **non-archived** fixture repository (see f2's evidence). Not a credential problem — see below.

### Node-side evidence 2026-08-08

- **f1 PASS.** `gh auth status` on ace2: logged in to github.com as `mlorentedev`,
  *Git operations protocol: https*, token `github_pat_…` (fine-grained), stored at
  `/home/manu/.config/gh/hosts.yml`. `gh api /user --jq .login` → `mlorentedev`.
- **f4 PASS.** Pass 1 `ok=35 changed=1 failed=0`; pass 2 `ok=35 changed=0 failed=0`.
  The two `changed` events in an intermediate run were the dotfiles clone + bootstrap
  (the known ANSIBLE-028 behaviour), not identity churn.
- **f6 PASS**, both halves — including `stat -c %a ~/.config/gh/hosts.yml` = `600`.
- **f5 PASS**, deliberately re-run **after** all provisioning: no age key, no `sops`
  binary, no prod context in `~/.kube/`. The assumption the spec rests on still holds
  once the node has an identity.
- **f2 BLOCKED, and the distinction matters.** The push failed 403 *"This repository
  was archived so it is read-only"*. Everything before it succeeded on the node:
  the fixture was confirmed private via the API **under the dev-node token**, and
  `git clone` over HTTPS completed. So private read access via the PAT is proven;
  only the write half is unproven. The probe now checks `.archived` up front and
  reports `F2_FIXTURE_ARCHIVED`, so this cannot be misread as a credential fault.
  Cleanup behaved correctly throughout — trap fired, no stray branch, no stray
  tmux session, `F2_FAIL` written immediately rather than after the poll window.

### Controller-side evidence captured 2026-08-08

Everything below runs without ace2 powered on. States stay `pending` — a feature
is promoted only by the harness, and each of these criteria still has a node-side
half outstanding.

- **AC4 (partial) — the audit now tracks the token.** `apps.services.automation.dev_node.github_token`
  registered in `SECRET_CATALOG` with `envs=("staging",)`. `make secrets-audit`
  → `STAGING — 38/38 (100%)`, and the key resolves as `present`, `missing=0`.
  Before registration it was in SOPS but invisible to the audit.
  New `tests/test_secrets_dev_node_catalog.py` (8 cases) pins registration, the
  `EXTERNAL` kind, the staging audit dimension, and — as a regression guard for
  #891 — that an empty mapping in the env vault cannot hide a secret declared in
  common.
- **AC6 (static half) — PASS.** Run as written from `features.json`:
  `no_log: true` is present within 8 lines of the `gh auth login` task, and the
  token does not appear in argv alongside `--with-token` (it is delivered via the
  command module's `stdin:`). Exit 0.
- **AC7 — PASS.** The f7 command run verbatim against
  `docs/runbooks/dev-node-token-rotation.md` exits 0: symptom (`401`), `revoke`,
  `repository access`, `mint`, and the exact `make provision NODE=ace2` line all
  present.
- **Playbook wiring** — `provision-ace2.yml` passes
  `dev_node_github_token` from `secrets.…` with `| default('')`, so a run without
  the secret degrades to "not configured". `ansible-playbook --syntax-check`
  against `infra/ansible/generated/staging/hosts.yml`: clean.

Two criteria are **not fully machine-checkable**, and are recorded here so the
gap is visible rather than assumed closed:

- **AC3** — a fine-grained PAT's **90-day expiry** and **All-repositories**
  scope are not exposed by the GitHub API. They are read off the token's
  settings page. `f3` verifies only the executable half (fine-grained prefix +
  workflow-write refusal); do not mark AC3 satisfied on that half alone.
  - Expiry observed: `<YYYY-MM-DD, expect 2026-11-05>`
  - Repository access observed: `<All repositories / narrowed>`
  - Permissions observed: `<contents:w, pull-requests:w, checks:r, statuses:r, metadata:r>`
- **AC4** — the aggregate `changed=0 failed=0` is necessary but not sufficient.
  Read the **per-task list** of the second pass; a task that flips to `changed`
  while the total stays 0 is the failure mode ANSIBLE-028 hit.
  - Pass 1: `<ok=N changed=N failed=N>`
  - Pass 2: `<ok=N changed=N failed=N>` — tasks reporting changed: `<none / list>`

## Test status

- Test suite: `make test` -> `<output>`
- Probe scripts: `bash -n` + `shellcheck` on `probes/*.sh` -> `<output>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- **The role does not run `gh auth setup-git`; it asserts the helper instead.**
  That command writes `~/.gitconfig`, which the dotfiles bootstrap — run earlier
  in this same role — redeploys wholesale every pass. Deleting the helper and
  re-provisioning showed the bootstrap restoring it *before* the role's own check
  ran, so a write here is erased next pass and the task would report `changed`
  forever. A guarded write is not a fallback in that situation, it is a churn
  generator. Split: the token is this role's, the helper is dotfiles'. Rejected
  alternative — writing to a `~/.gitconfig.local` seam: no such seam exists, and
  creating one is a dotfiles change (the `dotfiles#788` precedent for
  `.tmux.conf.local`), not a kubelab one. Cost: a cross-repo coupling, named in
  the assert's failure message.
- **`SECRET_CATALOG` registered `envs=("staging",)`, not a `common` env.** No
  `common` pseudo-env exists — `envs` is the audit dimension, and `audit()`
  merges common into each environment. Staging is the env ace2 provisions with,
  so it is where the token's absence must be reported. Same construction as the
  Argo CD hub keys under `prod`.
- **The playbook's SOPS decryption needed `tags: [always]`.** Without it a
  `TAGS=dev_node` run — the command AC4 prescribes — skipped decryption and every
  SOPS-sourced var silently fell back to its default. The play reported success
  and delivered no credential. The same pattern in the other `provision-*.yml`
  playbooks is tracked as ANSIBLE-034 (#893); they fail loudly rather than
  silently because their secret vars carry no `default`.
- **f4 was strengthened after it passed while proving nothing.** Convergence
  alone cannot distinguish "converged with the credential in place" from
  "converged because every identity task skipped". It now also asserts the role
  saw a non-empty token, keyed on the token *read* rather than the login — the
  login legitimately skips on an already-converged node.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons.md`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/ANSIBLE-033-dev-node-credentials/` -> `specs/archive/ANSIBLE-033-dev-node-credentials/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
- [ ] Token rotation (2026-11-05) tracked outside this spec — the spec archives, the expiry does not
