---
tags: [spec, verification, templates]
created: "2026-11-03"
id: "AUTH-022-agent-forge-identity"
type: spec-verification
status: active
owner: manu
---

# Verification - AUTH-022-agent-forge-identity

## Evidence

- [x] AC1 -> commit `b2f24b48` / `tests/test_gitea_agent_identity.py`, `tests/test_gitea_token_scope_drift.py`, `tests/test_gitea_token_rotation_registry.py` (green locally and in CI).
- [ ] AC2 -> first prod run 2026-11-05: `ok=59 changed=4 failed=0`, the changes being the bootstrap (creates `dedalo`), the mint, the record and the Gitea restart. `agent_token` committed in `055983b0`; read back by length only (40). The idempotence run (`changed=0`) is still pending.
- [x] AC3 -> `make gitea-reconcile ENV=prod APPLY=1`: `collaborator granted: personal/imagesensortool -> dedalo (write, read back)`; the next plan: `nothing to do — forge matches the declaration`. With the agent's token, `GET /repos/personal/imagesensortool` reports `permissions {admin: false, push: true}`. `AUTH-022 AC3 ok — dedalo owns: (none)`, printed by the reconcile since `feat(gitea): report what the agent account owns`.
- [x] AC4 -> `make secrets-copy-gitea-agent-token` created Bitwarden item `gitea-kubelab-agent` (2026-11-05; the first run needs `--yes`, since `dotf secrets set` refuses to create an absent item without it). `dotf secrets verify` exits 0 with `OK GITEA_KUBELAB_AGENT_TOKEN bw`; the token injected by `dotf secrets run --only GITEA_KUBELAB_AGENT_TOKEN` reads `personal/imagesensortool` as `{admin: false, push: true}`. Never printed.
- [x] AC5 -> personal/imagesensortool#152, `.user.login == dedalo`, opened through the API with the agent token. Closed, not merged, once #114 had its measurement (comment 6443): `created=true` returns 1 PR (#152) for `dedalo` and 607 PRs, all `manu`'s and not #152, for `manu`'s token.

## Test status

- Test suite: `make test` locally, 8894 passed; the 32 failures and 2 errors are the five macOS-only files tracked in #3072 and fail identically on the base commit `d0f46e1d`. CI `Tests` on Linux: 1 failure, the renumbered lesson's quoted `id` (fixed in `c0709bd5`; tool defect tracked in dotfiles#3124).
- Manual smoke test: the live AC3 and AC5 runs above.
- No regressions in existing test suite: yes.

## Decisions made during implementation

- Write is granted per repository as a collaborator, not through a team: a team grant cannot be scoped to one repository by construction.
- The plan reads both the collaborator row and the access mode, because `GET .../collaborators/{u}/permission` answers `read` for an account a team grants write to (lesson-707).
- The token is minted without `read:user`, so `GET /user` answers nothing for it; ownership is checked with the admin token on the reconcile path.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/identity-secrets/lesson-707-gitea-permission-endpoint-misses-team-units.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? yes: docs/adr/adr-062-platform-identity-model.md
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: the machine-account recipe is specific to this forge's bootstrap

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/AUTH-022-agent-forge-identity/` -> `specs/archive/AUTH-022-agent-forge-identity/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
