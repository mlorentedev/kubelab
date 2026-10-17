---
id: lesson-413-a-credential-can-exist-authenticate-and-not-work
type: lesson
status: active
created: "2026-09-01"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, gitea, scopes, verification, tool-035]
---

# A credential can exist, authenticate, and still not work — and every presence check will call that success

**Context**: Unblocking TOOL-035's Gitea reconciler, which needed the prod
superadmin token that `beelink_services` mints. The token was absent, so
`make provision NODE=bee ENV=prod TAGS=gitea` minted it.

**Problem**: Every signal said done.

- the Ansible mint task reported `changed`
- the value landed in `prod.enc.yaml`
- a key-name diff showed one key added, none removed (80 → 81)
- `make secrets-audit` counted it present

And the capability was dead:

```
$ make gitea-reconcile ENV=prod
GET /admin/orgs -> 403: token does not have at least one of required scope(s),
                        token scope=write:organization,read:repository
```

The token authenticated. It just could not reach `/admin/orgs`, which needs
`read:admin`. The cause was structural rather than a typo: the **grant** was a
literal string in `provision-bee.yml` and the **requirement** lived in the Python
that makes the calls, with nothing tying them together. The tell was already in
the file — the comment beside the wrong string described the reads the token
could not perform. Rationale and value had drifted apart because they were
written in different files, in different languages, neither able to import the
other.

Then the same shape appeared three more times in one session:

1. The **bot** token had the identical defect: declaration correct,
   live token minted before `write:organization` was added to it.
2. `create_team` sent no `units`, which Gitea 1.25 refuses with HTTP 500. Sending
   `units_map` fixed the 500 and the bot was *still* refused — because creating a
   repository in an organization is governed by `can_create_org_repo`, a separate
   boolean, not by the `repo.code` unit.
3. `ensure_team` asserted `team["permission"] == "write"` and raised on `none` —
   but `none` is what a **correct** team reads back as, since Gitea sets the
   coarse access mode to none precisely when the grant moves per-unit. The check
   refused correct teams and would have gone on refusing them however the payload
   was rewritten.

Three of those four were 403s, and the status code could not tell them apart. A
probe script walked straight into it: it read a token-scope 403 as a
team-permission 403 and reported the payload wrong when the payload had never
been reached. That is the same confusion AUTH-004 AC5 already recorded.

The unit tests could not have caught any of it. Their `FakeClient` echoed
`permission: "write"` back from `create_team`, modelling a forge that does not
exist. Every test passed while the real reconcile 500'd.

**Solution**: Move the grant to `common.yaml`
(`apps.services.core.gitea.token_scopes`) so one declaration feeds Ansible, and
tie it to the requirement with a test that **imports** `REQUIRED_BOT_SCOPE` /
`REQUIRED_ADMIN_SCOPES` from the client rather than copying them — copying would
reproduce the defect. Assert **superset, not equality**: equality fails on a
legitimate widening, and a test that fails on correct changes gets loosened.

For the team, settle it by consequence, because no field could: build the team
the reconciler builds, add the bot, and have the bot try to create a repository.
201 or 403 is the answer (`team_consequence_probe.sh`). Then assert the fields
that turned out to govern — `can_create_org_repo` and `units_map["repo.code"]` —
and make the control test assert `permission == "none"` explicitly, so nobody
restores the coarse field to the check.

Rotation is the other half, and widening a scope does not perform it: Gitea
cannot edit a minted token's scopes and the mint task is gated on the SOPS key
being **absent**, so the old narrow token survives the declaration change
forever. `make gitea-rotate-token TOKEN=<x> ENV=prod APPLY=1` then
`make provision NODE=bee ENV=prod TAGS=gitea`. Second provision: `changed=0`.

Evidence: PR #1546. `make gitea-reconcile ENV=prod` now plans, applies three
organizations and three repositories, and converges to "forge matches the
declaration".

**Rule**: **Verify a credential by consequence, never by presence.** "The key
exists", "the audit counts it", "the diff shows it added" all answer *did this
value get set*. The question that matters is *does it do the thing it was set
for*, and only running the operation answers it. This generalises past
credentials: the same gap produced lesson-404's silent ConfigMap and the Vikunja
`VIKUNJA_FILES_S3_ENABLED` key viper ignored without complaint.

Three corollaries earned the hard way:

- **A grant and its requirement declared in different languages agree only by
  coincidence.** Put the declaration where both can read it and add the test that
  imports the other side. Two copies that happen to match are not an SSOT.
- **A 403 is not one answer.** Token scope, team permission, and account state
  all produce it. Read the body; the status code is not a diagnosis, and treating
  it as one sends you to the wrong layer.
- **A fake that encodes a wrong belief about a system does not fail — it
  certifies the belief.** When tests pass and the real thing does not, suspect
  the fake before the code.

**Tags**: `#gitea` `#scopes` `#verification` `#pr-1546` `#tool-035`
