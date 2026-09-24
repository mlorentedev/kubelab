---
id: "TOOL-062-gitea-actions-secrets"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-09-23"
issue: "mlorentedev/kubelab#1626"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, gitea, forge, secrets, actions, migration]
template_version: "1.0"
---

# TOOL-062: deliver Actions secrets to forge repositories from SOPS

## Why

<!-- from issue #1626: TOOL-062: nothing populates Actions secrets in the Gitea forge -->

Nothing writes Actions secrets on the Gitea forge. On the forge, an unset secret reads as an empty
string, not an error, so the first migrated workflow that needs a credential fails somewhere that
does not name the cause. That workflow now exists. `personal/resume`'s Google Drive publish has
delivered nothing since 2026-08-11 (resume#272, part of the parity epic resume#271). It needs four
`GDRIVE_*` values, and #1626's comments measured that neither forge returns a secret's value. So the
values have to be re-minted by the operator, stored in SOPS, and pushed from there by something
reproducible.

## What

1. **The catalog is the declaration.** `SecretSpec` gains `forge_actions: tuple[str, ...]`, the
   forge repositories (`org/name`) that receive the value as a repository Actions secret. This has
   the same shape and the same reasoning as `sync_to_secret_manager`: a separate list of "secrets to
   push" would state a second time what the catalog already records, and the two could disagree
   without anyone noticing.
2. **The secret's name is derived by rule, not written by hand.** It is the key path's last segment
   in upper case: `…personal.resume.gdrive_oauth_client_id` becomes `GDRIVE_OAUTH_CLIENT_ID`. A test
   fails if two catalog entries would deliver the same name to the same repository.
3. **`toolkit services gitea actions-secrets [--env prod] [--apply] [--force]`.** Without `--apply`
   it only prints the plan, like `gitea reconcile`. For each repository the plan compares three
   things: the declared names, the live names (`GET /repos/{o}/{r}/actions/secrets`, which returns
   names only), and whether SOPS holds a value.
   - A secret that is declared, absent on the forge, and valued in SOPS is created with
     `PUT /repos/{o}/{r}/actions/secrets/{name}`.
   - A declared secret with no SOPS value is **reported, never pushed empty**. `--apply` exits
     non-zero and names it.
   - A live secret the catalog does not declare is reported and never deleted.
   - `--force` re-PUTs every declared secret that has a value. The API returns neither the value nor
     an `updated_at`, so this is the only way a rotation reaches the forge (#1626, design comment).
4. **The first entries:** `personal/resume`'s four `GDRIVE_*` values, under
   `apps.services.core.gitea.actions_secrets.personal.resume.*` in `prod`, all of kind `EXTERNAL`.

## Out of scope

- Organization-level secrets. Only one repository needs any, and a repository-level secret has the
  smaller blast radius.
- Deleting secrets. Undeclared ones are reported only, following the reconciler's no-deletion rule
  (TOOL-035).
- The machine identity from AUTH-007 (#1781). Until it exists, secrets are written with the
  superadmin's basic auth: the same credential and the same class (`GiteaBasicAuthClient`) that
  already write webhooks and repository settings. Swapping the credential later does not change this
  command's shape.
- `BITACORA_PAT`. Its two workflows are superseded by the forge webhook into n8n (ADR-066 D4), not
  migrated (#1626).
- `teledyne/fae-brain`'s `NAN_API_KEY`. It gets added when that workflow ports (#1799).
- The workflow-side guard. Only the consuming job can check that a secret actually arrived, so the
  preflight that refuses empty inputs lives in resume's `publish-drive` workflow (resume#272). This
  spec is the first of the two guards #1626 calls for.

## Risks / open questions

- **Existence is not correctness.** `changed=0` here only means the names exist. A rotation left in
  SOPS without a `--force` push cannot be detected. The command's output says so plainly rather than
  printing a bare "matches".
- **The superadmin password becomes load-bearing for one more operation.** It already is for
  webhooks, repository settings and migration, so this adds no new failure class. AUTH-007 is where
  that dependency gets removed.
- **Values must never reach output.** Values travel only in request bodies. Any record holding one
  is `repr=False`, and tests assert that neither the plan nor its formatting carries a value, the
  same pattern `SyncItem` uses.
- **Resolved: which env holds the values.** `prod`. `_gitea_merged_config("prod")` is what reaches
  the forge, and the forge's `admin_password` lives in `prod.enc.yaml`.

## Acceptance criteria

- [ ] With the four values in SOPS and none on the forge, a plan-only run lists four creations for
      `personal/resume` and changes nothing.
- [ ] `--apply` creates them, and the next plan reports nothing to do (`changed=0`).
- [ ] `--force --apply` re-PUTs all four and reports each one.
- [ ] A declared secret missing from SOPS is never written. `--apply` exits non-zero and names it.
- [ ] A live secret the catalog does not declare is reported and left in place.
- [ ] No secret value appears in the plan, in its formatted output, or in any record's `repr`.
- [ ] **Checked by effect:** resume's `publish-drive` run passes its empty-input preflight and
      uploads a file that then appears in the Drive folder (resume#272).

## References

- Issue: #1626, with its two design comments (the two-guard rule, and "the blocker is the source").
- #1781 (AUTH-007), the future owner of this write.
- resume#271 (parity epic) and resume#272 (the first consumer).
- The pattern mirrored: `toolkit/features/gcp_secret_sync.py` and `sync_to_secret_manager`.
- The reconciler's conventions: TOOL-035 (`specs/TOOL-035-gitea-repository-reconciliation/`).
