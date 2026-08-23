---
tags: [spec, verification]
created: "2026-08-15"
---

# Verification - AUTH-004-identity-and-machine-access

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 (identity resolves from `apps.auth.identities`) -> Part 1, not started
- [ ] Criterion 2 (`operator` is refused what the superadmin can do) -> Part 2, not started
- [ ] Criterion 3 (SSO onboarding creates an account with no manual step) -> Part 2, gated on R1. **Measured failing 2026-08-23 (R1a): the flow parks at `/user/link_account`.** The baseline is now a transcript rather than an assumption, so Part 2 has something to demonstrate a change against.
- [ ] Criterion 4 (unauthenticated registration refused) -> Part 2, not started
- [ ] Criterion 5 (bot account, scoped token, both halves of the scope proven) -> Part 3, not started
- [ ] Criterion 6 (test fails when admin identity resolves from anything else) -> Part 1, not started
- [ ] Criterion 7 (break-glass drill) -> Part 4, not started

## Open questions, settled

Part 0 of `tasks.md`. Each entry is the command and its output, run against the live
instance — never read off documentation. **R1 remains open** and is deliberately not
run here: its throwaway-user SSO test touches **prod** Authelia, so it needs the
operator's explicit go-ahead first.

**Update 2026-08-23** — that go-ahead was given for the reversible half only. R1 is now
half-settled: **R1a** is recorded below under its own heading. **R1b — an SSO login as
`manu` — was not run and stays parked**, because that account holds no OIDC linkage and
its first SSO login is therefore a one-shot, irreversible event on the sole admin
account. The paragraph above still governs R1b.

Environment: Gitea `1.25.5`, Docker Compose on the Beelink (`beelink_services` role,
post-ADR-061), reached over Tailscale (`100.64.0.3`). Reachability confirmed with
`tailscale ping beelink` -> `pong ... via 172.16.1.3:41641 in 17ms` before any query,
because `tailscale status` shows an ambiguous `-` for an idle on-demand node.

All queries below are read-only: `sqlite3` opened via the `file:...?mode=ro` URI, and
**no credential column was selected** — not `token_hash`, `token_salt`, `passwd`,
`rands` or `salt`. The question is what is *attached* to a user id, not what any
secret's value is.

### R2 — what is attached to Gitea's existing `manu` user id

**Settled 2026-08-15. The two-tier model's central claim holds: nothing of
consequence hangs off uid 1, so `manu` survives in place — no account is deleted, no
ownership migrates, and the pre-first-push deadline stays dissolved.**

```
$ docker exec gitea su git -c "gitea admin user list"
ID   Username Email             IsActive IsAdmin 2FA
1    manu     info@kubelab.live true     true    false
```

```
$ sqlite3 -header -column "file:/data/gitea/gitea.db?mode=ro" ...

===== users =====
id  lower_name  full_name  email              is_active  is_admin  is_restricted  login_type  login_source  login_name  type  num_repos  created_unix
1   manu                   info@kubelab.live  1          1         0              0           0                         0     0          1786669068

===== public_key — registered SSH keys =====
id  owner_id  name             fingerprint                                         type  mode  created_unix
1   1         msi-workstation  SHA256:3PVtUoAotdnrlbsxuRIU17Qy9B+Ig15PYgAQYdBxT1w  1     2     1786669484

===== access_token =====            (0 rows)
===== external_login_user =====     (0 rows)
===== repository =====              (0 rows)
===== org_user / team =====         (0 rows)

===== row counts =====
user                 1
public_key           1
access_token         0
external_login_user  0
repository           0
org_user             0
```

```
$ docker exec gitea sh -c 'wget -qO- http://localhost:3000/api/v1/repos/search?limit=1'
{"ok":true,"data":[]}
```

Reading of the above:

1. **One user exists, and it is `manu`, not `operator`.** The listing was taken
   unfiltered precisely so this would surface: `common.yaml:469` declares
   `apps.auth.admin_username: operator`, and the live admin is `manu`. This is #951's
   admin-username drift, now measured rather than inferred.
2. **Root cause of that drift, traced in the same pass:**
   `infra/ansible/playbooks/provision-bee.yml:222` sets
   `gitea_admin_user: "{{ gitea_secrets.basic_auth.user }}"`, rendered into the compose
   file at `roles/beelink_services/templates/compose.yml.j2:48`. Gitea's admin identity
   resolves from the **Traefik basic-auth user**, never from the declared SSOT. This is
   the same defect as `toolkit/features/k8s_secrets.py:52`'s `BASIC_AUTH_USER` mapping,
   on a second delivery path — exactly the pair Part 1 must decouple.
3. **The only attachment is one SSH key** (`msi-workstation`, write mode). Zero repos,
   zero tokens, zero org membership. Re-registering a public key is trivial and
   non-destructive, so nothing here forces a recreate.
4. **`manu` is a local-password account with no OIDC linkage at all** — `login_type: 0`
   (plain), `login_source: 0`, and `external_login_user` is empty, while the `authelia`
   OAuth2 source itself exists and is active (`login_source` id 1, type 6). ADR-062
   assumes this account becomes the Authelia-backed superadmin, so the *linking* step is
   real work that the model presupposes rather than describes. **New risk, not in
   `proposal.md`:** the first SSO login as `manu` either links to uid 1 or creates a
   second account. Which one happens is precisely what R1 must observe, and it is now a
   sharper question than when R1 was written.
5. **Zero repositories confirms the pre-first-push window is still open** — it was not
   closed while the plan was being reversed.

### R5 — does Gitea derive admin from a group claim?

**Settled 2026-08-15. Yes — the superadmin bit can be declarative, so it is
reconcilable rather than a one-shot provisioning step.**

```
$ docker exec gitea su git -c "gitea admin auth update-oauth --help"
...
   --group-claim-name string            Claim name providing group names for this source
   --admin-group string                 Group Claim value for administrator users
   --restricted-group string            Group Claim value for restricted users
   --group-team-map string              JSON mapping between groups and org teams
   --group-team-map-removal             Activate automatic team membership removal depending on groups
```

Consequences for the plan:

- `--admin-group admins` + `--group-claim-name groups` makes ADR-062's privilege
  boundary declarative on Gitea's side: Authelia's `admins` group grants the admin bit,
  and revoking group membership revokes it on next login. No `--admin` flag on an
  account, no drift between the group and the bit.
- `--restricted-group` is a ready-made mechanism for the `operator` tier — a lever
  ADR-062 did not know existed when D2 was written.
- **None of these flags is currently passed.** `roles/beelink_services/files/gitea-bootstrap.sh`
  requests `--scopes openid,profile,email,groups`, so the groups claim is *sent* and then
  *ignored*: nothing maps it to a privilege. That is the gap Part 2 closes, and the
  bootstrap script (not `configure_oidc.py`, see below) is where it belongs.

### R6 — what does MinIO do with the `groups` claim?

**Settled 2026-08-15. Nothing. MinIO has no OIDC configured at all, so its tier is
unenforced — recorded as a named gap per ADR-062 D5 rather than passed over.**

```
$ docker inspect minio --format '{{range .Config.Env}}{{println .}}{{end}}' | cut -d= -f1 | sort
MC_CONFIG_DIR
MINIO_ACCESS_KEY_FILE
MINIO_CONFIG_ENV_FILE
MINIO_KMS_SECRET_KEY_FILE
MINIO_ROOT_PASSWORD
MINIO_ROOT_PASSWORD_FILE
MINIO_ROOT_USER
MINIO_ROOT_USER_FILE
MINIO_SECRET_KEY_FILE
MINIO_UPDATE_MINISIGN_PUBKEY
PATH
```

Not one `MINIO_IDENTITY_OPENID_*` variable. MinIO authenticates with root credentials
only; there is no identity provider, therefore no groups claim reaching it and no
group-to-policy mapping to inspect. ADR-016's assertion that MinIO maps groups to
policies is **aspirational, not implemented** — true of neither the repo's
configuration nor the running container.

This does not block Part 1. It does mean AC2 cannot be demonstrated on MinIO, and per
ADR-062 D5 an unenforced tier must be recorded as a named gap with its issue rather
than quietly counted as passing.


### R4 — how is login prohibited on a bot account

**Settled 2026-08-23. Not through the CLI, which has no such verb — through the
admin API's `PATCH /api/v1/admin/users/{username}` with `prohibit_login: true`.**

R4 was never in Part 0's task list. It is named as a risk in `proposal.md` and
Part 3 is written as *"gated on R4, R5"*, but no task existed to settle it, so
nobody was going to. Found while re-reading the spec, measured the same pass.

The CLI's whole surface for users, from the live binary:

```
$ docker exec -u git gitea gitea admin user --help
COMMANDS:
   create                 Create a new user in database
   list                   List users
   change-password        Change a user's password
   delete                 Delete specific user by id, name or email
   generate-access-token  Generate an access token for a specific user
   must-change-password   Set the must change password flag for the provided users or all users
```

Six subcommands, none of which touches `prohibit_login`. `create` offers
`--restricted`, and that is **not a substitute**: restricted is a visibility
tier, not a login block. A restricted user still authenticates.

The admin API does expose it. From the running instance's own schema:

```
$ curl -s http://100.64.0.3:3000/swagger.v1.json    # http=200, 816675 bytes
EditUserOption:   ['admin', 'prohibit_login', 'restricted']
CreateUserOption: ['restricted']
paths admin/users: ['/admin/users', '/admin/users/{username}',
                    '/admin/users/{username}/badges', '/admin/users/{username}/keys']
```

**The asymmetry is the operative detail**: `prohibit_login` is in
`EditUserOption` and *not* in `CreateUserOption`, so it cannot be set at
creation. The bot account therefore exists briefly in a loginable state, and
the provisioning order is fixed rather than free:

1. `gitea admin user create` (CLI)
2. `PATCH /api/v1/admin/users/<bot>` with `prohibit_login: true` (API, superadmin token)
3. `gitea admin user generate-access-token --username <bot> --scopes <...>` (CLI)

All three are reproducible from Ansible, so AC5's "provisioned end to end from
Ansible" survives — but it needs a superadmin token to exist before the bot can
be locked, which the task line in Part 3 does not currently say.

ADR-062 D1's second candidate mechanism — *never declaring the bot in Authelia*
— remains available and costs nothing, but it is a convention rather than an
enforcement: it prevents an SSO login by omission, and omission is not a
control. `prohibit_login` is the enforced half. Belt and braces is the
defensible answer; the spec asked for "enforced, not conventional", and only
one of the two is.

#### A measurement error, recorded because it nearly shipped the opposite answer

The first pass at this ran `docker exec gitea gitea admin auth add-oauth --help`
and grepped for `admin|group|claim`. It printed nothing, and nothing was read as
*"no such flags"* — the conclusion that would have made R5's superadmin tier a
provisioning step rather than a claim mapping.

The command had not run at all:

```
$ docker exec gitea gitea admin auth add-oauth --help
[F] Gitea is not supposed to be run as root. Sorry.
```

`docker exec` enters as root and Gitea refuses to start as root, so the grep was
searching an error message. Re-run as `-u git`, the same command returns
`--group-claim-name`, `--admin-group`, `--restricted-group` and
`--group-team-map` — which is what R5 already recorded on 2026-08-15, and the
duplicate measurement only survived long enough to disagree with the record.

The same shape recurred minutes later: `curl http://localhost:3000/swagger.v1.json`
from inside the node returned **0 bytes**, because the compose file binds Gitea to
`{{ tailscale_ip }}:3000` and not to loopback (the DNAT rule in CLAUDE.md). Zero
bytes is not an absent endpoint. Fetched from the Tailscale address it is 816 KB.

Both are `dig ... && echo YES` again: **grepping an output without establishing
that the output exists is not a measurement.** Every read-only probe in this file
should carry a control that fails loudly — here, `GET /api/v1/version` returning
`{"version":"1.25.5"}` before anything else is asked.

### R1a — does an SSO login by a non-admin Authelia user onboard itself into Gitea?

**Settled 2026-08-23. No. The flow completes cleanly and then stops at a manual step,
which is the specific failure AC3 forbids — not a refusal, and not an auto-created
account.**

Authorised by the operator on 2026-08-23, scoped to the reversible half. **R1b — an SSO
login as `manu` — was not run and stays parked.**

Prod Authelia needed no change at all. `common.yaml:982` already declares a non-admin
`testuser` (groups: `users` only) for the e2e suite, and
`apps.services.security.authelia.users_testuser_password_hash` is present in
`prod.enc.yaml`, so the subject of the experiment already existed. Reusing it made the
prod mutation for R1a **zero**, and left nothing to revert. Note the trap that makes
this worth stating: `_build_users_database` (`k8s_secrets.py:313-315`) skips a declared
user whose hash is missing from that env's SOPS *with a log warning only*, so "declared
in `common.yaml`" never implies "exists in this environment" — the hash key does.

The probe resolves the password **in-process** from the SOPS-merged config, the same
source `tests/e2e/conftest.py:149-150` uses. It is never exported to the environment,
never passed as an argument, and never printed; the transcript below carries only URLs,
status codes and page titles, with `code` and `state` redacted at capture time.

Baseline first, so the result is interpretable (and so the negative is a measurement
rather than an absence — lesson 374):

```
$ docker exec gitea grep -nE '^\[(service|oauth2_client|openid)\]|^(DISABLE_REGISTRATION|...)' /data/gitea/conf/app.ini
59:[service]
60:DISABLE_REGISTRATION = true
61:REQUIRE_SIGNIN_VIEW = false
66:[openid]
67:ENABLE_OPENID_SIGNIN = false
68:ENABLE_OPENID_SIGNUP = false

$ docker exec -u git gitea gitea admin user list
ID   Username Email             IsActive IsAdmin 2FA
1    manu     info@kubelab.live true     true    false

$ docker exec -u git gitea gitea admin auth list
ID	Name		Type	Enabled
1	authelia	OAuth2	true
```

**There is no `[oauth2_client]` section in `app.ini` at all**, so
`ENABLE_AUTO_REGISTRATION` sits at its built-in default and neither candidate from R1's
text is currently set. That is the configuration the result below describes.

The attempt:

```
[setup] env=prod user=testuser credential resolved in-process (not emitted)
[reach] authelia https://auth.kubelab.live/api/health -> 200
[reach] gitea    https://gitea.kubelab.live/api/healthz -> 200

[authelia] POST /api/firstfactor as 'testuser' -> 200
[authelia] status field: 'OK'  message: None
[authelia] session cookie acquired: True

[flow] GET https://gitea.kubelab.live/user/oauth2/authelia
   1. 307 https://gitea.kubelab.live/user/oauth2/authelia
   2. 303 https://auth.kubelab.live/api/oidc/authorization?client_id=gitea&...&state=<redacted>
   3. 303 https://gitea.kubelab.live/user/oauth2/authelia/callback?code=<redacted>&iss=...
   4. 200 https://gitea.kubelab.live/user/link_account

[final] title: 'Link Account - Gitea: Git with a cup of tea'
[final] gitea session established: False
[link_account] form actions: ['/user/link_account_signin', '/user/link_account_signup']
[link_account] offers 'create new account' (signup): True
[link_account] offers 'link to existing'  (signin):  True
```

And the control that makes the negative real — the user list *after* the attempt:

```
$ docker exec -u git gitea gitea admin user list
ID   Username Email             IsActive IsAdmin 2FA
1    manu     info@kubelab.live true     true    false
```

Unchanged. No account was created, so there was nothing to delete.

What this settles, and what it does not:

- **AC3 fails today, and now by measurement.** The OIDC leg is entirely healthy —
  Authelia issued a code, Gitea exchanged it and read the identity — and Gitea still
  refuses to conclude without a human at a form. "SSO onboarding creates an account
  with no manual step" is false on the current configuration.
- **The failure mode is `link_account`, not a refusal.** This matters for how Part 2 is
  tested: a probe asserting "login is not refused" would pass here while the criterion
  fails. Assert on reaching an authenticated Gitea session, never on the absence of an
  error.
- **`DISABLE_REGISTRATION = true` does not remove the signup branch from that page.**
  Gitea renders `link_account_signup` regardless. Whether that form is *honoured* on
  POST is unmeasured — it was outside the authorised scope, and it is the sharp form of
  R1's original question. **Do not infer it from the rendered page**: a form that
  renders and then refuses is exactly the "looks right and silently refuses" outcome R1
  was written to prevent.
- **R1's headline question — which flag combination admits a new user — remains open**,
  and cannot be closed without changing a flag on the live instance. That is a separate
  authorisation, and the change belongs in
  `roles/beelink_services/files/gitea-bootstrap.sh` per R5, not by hand.

## Test status

Part 0 is observation only — no code changed, so no suite was run against it. The
transcripts above are the deliverable.

## Follow-ups found while settling these questions

- **`toolkit/scripts/configure_oidc.py` targets a Gitea that no longer exists.** It
  reaches the service with `kubectl exec -n kubelab deploy/gitea` (module docstring and
  `kubectl_exec()`), but ADR-061 moved Gitea to Docker Compose on the Beelink; there is
  no Gitea pod in either cluster. `tasks.md` Part 2's first task plans to drive R1's
  answer *through this script*, so the plan currently depends on a dead code path.
  The live equivalent is `roles/beelink_services/files/gitea-bootstrap.sh`, which
  already does `docker exec gitea su git -c "gitea admin auth update-oauth ..."`
  idempotently from Ansible.
- **The `authelia` OAuth2 source is live and its `groups` scope is requested but
  unmapped** (R5 above) — the fix is additive flags on the existing bootstrap call.
- **AC3 needs an assertion that cannot pass on a `link_account` page.** R1a's probe walks
  the OIDC chain by hand and reports whether a Gitea *session* was established, which is
  the property AC3 actually claims. Part 2 should land that as a test rather than a
  scratch script; the naive assertion ("the SSO login was not refused") passes today,
  against a criterion that fails today.
- **`DISABLE_REGISTRATION = true` and a rendered `link_account_signup` form coexist.**
  Whether the POST is honoured is unmeasured and needs its own authorisation. Worth
  knowing before Part 2 assumes the global flag is sufficient to close self-service
  registration — AC4 asserts exactly that, and this is the page where it would leak.
