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
| AC2 | f2 | Private clone → commit → push → PR from tmux, no agent forwarding | `pending` | **AWAITING NODE** 2026-08-08 — fixture replaced, two probe defects fixed, flow proven workstation-side; ace2 run outstanding |
| AC3 | f3 | Fine-grained token; `workflows: write` actually refused | `pending` | Not run — fixture no longer blocks it; awaiting a powered ace2. Expiry/scope halves are manual |
| AC4 | f4 | Role delivers the credential from SOPS; second pass `changed=0` | `pending` | **PASS** 2026-08-08 — verbatim, exit 0 |
| AC5 | f5 | No prod credential reachable from ace2 | `pending` | **PASS** 2026-08-08 — re-run last, after every node mutation |
| AC6 | f6 | Token never in argv/logs/world-readable files; `gh` owns the sink | `pending` | **PASS** 2026-08-08 — verbatim, both halves, exit 0 |
| AC7 | f7 | Rotation runbook exists and is operational | `pending` | **PASS** 2026-08-08 — verbatim, exit 0 |

**5 of 7 verified.** AC2/AC3 are no longer blocked on the fixture — that is resolved. They now wait only on ace2 being powered on (on-demand node, ADR-028). Neither has ever indicated a credential problem; see below.

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

### Fixture resolution and probe repair 2026-08-08 (controller-side)

The fixture is now `mlorentedev/kubelab-devnode-fixture` — private, README-only,
created for this purpose. Borrowing was not an option: of 41 private repos, 36
are archived and the remaining 5 are in active use, one being the vault.

Reaching step 4 for the first time exposed a **second** defect the 403 had been
masking. `gh pr create` aborted with *"you must first push the current branch to
a remote"* right after a push that returned 0: `clone --depth 1` implies
`--single-branch`, so the pinned fetch refspec cannot create
`refs/remotes/origin/<branch>`, `@{upstream}` does not resolve, and `gh` reads
that as unpushed. The probe now passes `--head` explicitly.

With both fixed, the full f2 body runs green end to end — `F2_OK`, exit 0, trap
leaving no branch and no PR behind. **That run does not count toward AC2.** It
executed from the workstation under the operator's own token, so it evidences the
*flow*; AC2 requires the same script on ace2, inside tmux, under the dev-node PAT.
The value of separating them: if f2 fails at step 4 on the node despite passing
here, the flow is not the suspect — the token is, being the only axis the
workstation run could not exercise.

Side effect worth noting: the local run also proved **draft PRs work on a private
repo for this account**, a documented GitHub Free limitation that would otherwise
have failed f2 at its last line and looked like yet another credential fault.

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
  Awaiting the operator — these are readable only from the token's settings page
  by its owner, so they cannot be captured from this session.
  - Expiry observed: `<YYYY-MM-DD, expect 2026-11-05>`
  - Repository access observed: `<All repositories / narrowed>`
  - Permissions observed: `<contents:w, pull-requests:w, checks:r, statuses:r, metadata:r>`
- **AC4** — the aggregate `changed=0 failed=0` is necessary but not sufficient.
  Read the **per-task list** of the second pass; a task that flips to `changed`
  while the total stays 0 is the failure mode ANSIBLE-028 hit.
  - Pass 1: `ok=35 changed=1 failed=0` (2026-08-08, ace2)
  - Pass 2: `ok=35 changed=0 failed=0` — tasks reporting changed: **none**. The
    recap's `changed` counter *is* the count of tasks that reported changed, so
    `changed=0` settles the per-task question rather than merely being consistent
    with it. The two `changed` events seen in an intermediate run were the
    dotfiles clone + bootstrap (known ANSIBLE-028 behaviour), not identity churn.

## Test status

All captured 2026-08-08 on the controller.

- Test suite: `make test` -> `389 passed, 108 deselected in 17.52s`. Includes the
  8 cases in `tests/test_secrets_dev_node_catalog.py` added by this change.
- Probe scripts: `bash -n` + `shellcheck` on `probes/*.sh` -> both clean, exit 0,
  re-run after the `--head` and fixture edits.
- Manual smoke test: the corrected `f2-private-repo-flow.sh` executed in full
  against the new fixture -> `F2_OK`, exit 0. Fixture inspected afterwards: only
  `main` remains, zero open PRs, so the cleanup trap does what it claims. Run from
  the **workstation under the operator's token** — a flow check, not AC2 evidence.
- `f7` re-run verbatim after this session's runbook edit -> exit 0, still green.
- No regressions in existing test suite: yes — no failures, and the only
  production code touched by this session's commits is a spec probe.

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

- [x] Lesson for the repo's `docs/lessons.md`? **Yes — four, all written.** Two
  merge implementations disagreeing over `common.enc.yaml`; verify-don't-write
  when another tool owns the file; a tag asymmetry producing a false green; and
  a blocked probe hiding every defect downstream of where it stops.
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? **No.** This is
  PR-1c *of* ADR-058 and changes none of its decisions. The interim PAT's
  replacement (GitHub App) is already deferred to its own ADR.
- [ ] New pattern candidate for `00_meta/patterns/`? **Operator's call.** The
  blocked-probe lesson is project-independent — it is about acceptance probes and
  expensive environments, not about Ansible or GitHub — so it may belong in the
  cross-project store. Not promoted unilaterally; flagged here.>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/ANSIBLE-033-dev-node-credentials/` -> `specs/archive/ANSIBLE-033-dev-node-credentials/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
- [ ] Token rotation (2026-11-05) tracked outside this spec — the spec archives, the expiry does not
