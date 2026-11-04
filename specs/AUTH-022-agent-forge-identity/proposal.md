---
id: "AUTH-022-agent-forge-identity"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-11-03"
issue: "mlorentedev/kubelab#2577"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
owner: manu
wip_override: "owner lifted the park on 2026-11-03 (#2577) (14 active, limit 10, 2026-11-03)"
---

# AUTH-022-agent-forge-identity

## Why

Agents author on the Gitea forge as its superadmin. The `toolkit services gitea` wrappers resolve the break-glass password, and `dotf forge` uses a PAT on `manu`. So every agent write is attributed to a person, and the superadmin credential is in agent hands for routine work (#2577, #2296). The owner decided on 2026-10-20 that agents get a non-admin machine account of their own. It is minted the way `mentor` was and held where `dotf` reads secrets.

## What

- A third machine identity, `apps.auth.identities.agent: dedalo`. `gitea-bootstrap.sh` creates it, it owns nothing, and it is in no team.
- Its token, `kubelab-agent`, has exactly `write:issue,write:repository`. Ansible mints it into prod SOPS, gated on the key being absent. It is rotatable (`TOKEN=agent`) and catalogued.
- Per-repository write: a repository lists identity keys under `writers:`, and `make gitea-reconcile` makes each one a collaborator at `write`, then reads the grant back. Only `personal/imagesensortool` declares it.
- `make secrets-copy-gitea-agent-token` copies the token from SOPS into Bitwarden (`GITEA_KUBELAB_AGENT_TOKEN`, mlorentedev/dotfiles#3152). The value never reaches argv or stdout.
- An ADR-062 amendment records the third machine exception.

## Out of scope

- Moving `toolkit services gitea git/pr/issue create` off the admin password (wrapper retirement), and the push path (#2578).
- Which token `dotf forge`/`dotf pr` uses on Gitea (mlorentedev/dotfiles#1622). `GITEA_KUBELAB_TOKEN` is untouched.
- Removing collaborators that are not declared. The reconciler creates and reports; it never deletes.

## Risks / open questions

- The permission endpoint reports the coarse mode, so it reads `read` for an unrelated account on a public repository (lesson-707). Resolved: the plan reads the collaborator row as well as the mode.
- Provisioning from the branch writes a real token into prod SOPS before merge. This is the same as TOOL-080, and the SOPS change is committed on this branch.

## Acceptance criteria

- [ ] AC1: the declared identity, its scopes (by equality), the mint and record tasks, the orphan guards, the catalog and the rotation entry agree. A test fails on any drift.
- [ ] AC2: `make provision NODE=bee ENV=prod TAGS=gitea` creates `dedalo` and records `agent_token`. A second run reports `changed=0`.
- [ ] AC3: `make gitea-reconcile ENV=prod APPLY=1` makes `dedalo` a write collaborator on `personal/imagesensortool` and nowhere else. A second plan is a no-op.
- [ ] AC4: the token is in Bitwarden under `GITEA_KUBELAB_AGENT_TOKEN`, checked by consequence (`dotf secrets verify`), never printed.
- [ ] AC5: `dedalo` has opened one PR on `personal/imagesensortool`. `GET pulls/{n}` reports `.user.login == dedalo`.

## References

- Issue: mlorentedev/kubelab#2577; decision on #2296; consumer imagesensortool#114.
- ADR: `docs/adr/adr-062-platform-identity-model.md` (amendment 2026-11-03).
- Precedent: TOOL-080 (#1832), the reviewer's identity.
