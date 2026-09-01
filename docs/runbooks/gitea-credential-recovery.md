---
id: gitea-credential-recovery
type: runbook
status: active
owner: manu
created: "2026-08-31"
tags: [gitea, credentials, recovery, sre]
---

# Gitea credential recovery

> **Thesis:** the root of trust is SSH to the node. From there every Gitea credential is
> re-establishable without rebuilding the service, and no credential loss is unrecoverable.
> This document exists because that was true by accident and is now true by construction.

## The problem class

Three properties combined to make a Gitea credential loss look unrecoverable. None is a bug on
its own; the combination is.

**1. A write-once credential that can drift.** `GITEA_ADMIN_PASSWORD` (`compose.yml.j2`) is read by
the container's first-boot setup and never again. Change it in SOPS and Gitea does not learn: the
two diverge silently, and nothing reports the divergence because nothing compares them.

**2. A credential that only that password can reach.** Gitea's token endpoints
(`DELETE /users/{u}/tokens/{id}` and the sibling listing) sit behind `reqBasicOrRevProxyAuth()` —
verified in `routers/api/v1/api.go` on 1.25.x. **They reject bearer tokens before the handler
runs.** So token rotation requires the admin password, and only the admin password.

**3. A machine account that cannot log in.** `hefesto` holds the provisioning token. It has no
interactive login, and the admin UI does not expose another account's tokens — so there is no page
anywhere a human can click to revoke it.

Chain them and the failure is: *the admin password drifts → token rotation becomes impossible →
the bot's credential cannot be replaced → the natural conclusion is "rebuild Gitea".* Every step
is individually reasonable and the endpoint is a service rebuild over a forgotten password.

**Why it presents as something else.** The symptom is a 401 from a token operation. That reads as
"my token is wrong", which sends you to fix the token — the one thing you cannot fix, because
fixing it needs the password that is actually broken. The diagnosis points away from the cause.

## What now makes it recoverable

**The container CLI needs no authentication.** `gitea admin user change-password` operates on the
database directly. It does not care whether the web login works, whether Authelia is up, or
whether any password is known. Reaching it needs SSH to the Beelink and nothing else — which is
why the root of trust is the node, not any credential.

**So SOPS is made authoritative rather than merely recorded.** `provision-bee.yml` now carries a
pair of tasks:

| Task | Behaviour |
|---|---|
| *Probe whether the recorded admin password still authenticates* | `GET /api/v1/user` with Basic Auth over the node-local address. `changed_when: false`, always. |
| *Reassert the admin password from SOPS when it has drifted* | Runs **only** on a non-200. `gitea admin user change-password --must-change-password=false`. |

Verify by consequence, not by comparison: the probe asks the API whether the credential works
rather than diffing two strings. A converged host reports `changed=0`; a drifted one repairs
itself on the next `make provision NODE=bee ENV=prod`.

### Two details that are load-bearing, not stylistic

- **`--must-change-password=false` is mandatory.** The flag **defaults to `true`** (verified against
  1.25.5, `gitea admin user change-password --help`, 2026-08-31). A `true` value puts the account
  behind a forced interactive password change — which breaks the Basic Auth the repair exists to
  restore. Without the flag, the fix bricks the credential it is fixing.
- **The probe uses the node-local address**, not `https://gitea.kubelab.live`. A credential-recovery
  path must not depend on Traefik, DNS or TLS: those break at the same time as everything else, and
  a probe failing for a routing reason would trigger a password reset that was never needed.

## Recovery: I have lost access to Gitea

Work down the list. Each step assumes the ones above it failed.

**1. SSO is the daily path.** `https://gitea.kubelab.live` → *Sign in with Authelia*, as `manu`.
Per ADR-062 D-88 this is the normal route; the local password is break-glass "when Authelia is
unavailable, and at no other time".

**2. Local password, break-glass.** Gitea's own login form. The value is in SOPS and is recoverable
by design (ADR-062 line 92 — machine credentials stay reversible):

```
make secrets-show KEY=apps.services.core.gitea.admin_password SECRETS_ENV=prod
```

**`SECRETS_ENV`, not `ENV`.** The target hardcodes `ENV=dev` internally; passing `ENV=prod` reads
`common` silently and reports "key not found", which looks like an absent key rather than a wrong
flag.

**3. The password in SOPS does not work.** It has drifted. Re-provision and the probe repairs it:

```
make provision NODE=bee ENV=prod
```

**4. Gitea is up but the API refuses everything.** Reset directly, from the node:

```
ssh bee
docker exec gitea su git -c "gitea admin user change-password \
  --username manu --password '<new>' --must-change-password=false"
```

**The alias, not the address.** `bee` resolves through `~/.ssh/config`, which also defines `bee-lan`
(home LAN) and `bee-ext` (through the VPS bastion) — see `non-admin-workstation-access.md`. Writing
the mesh IP here would pin a *recovery* runbook to the one path most likely to be down when it is
being read, and would duplicate a value whose SSOT is `networking.nodes.beelink.tailscale_ip` in
`common.yaml`. If no alias is configured, take the address from there rather than from this page —
and note the two namespaces disagree: the SSH alias is **`bee`**, the config key is **`beelink`**.

Then record it so SOPS stops being wrong — otherwise step 3 will "repair" it back:

```
printf %s '<new>' | toolkit secrets set apps.services.core.gitea.admin_password --env prod --stdin
```

**5. The account itself is gone.** `gitea admin user create --username manu --admin ...` from the
same shell. Nothing here requires rebuilding the container or restoring a backup.

## Rotating the machine token

**Revoke alone bricks the bot.** SOPS still holds the dead value, and the mint task is gated on the
key being **absent** — so nothing re-mints, and every consumer of `bot_token` fails until someone
remembers to unset it. Rotation is one flow, not one step:

1. **Revoke** — `GiteaBasicAuthClient.revoke_token("hefesto", "kubelab-provisioning")`. Idempotent
   by 404: an already-absent token reports "no change" rather than raising, so a re-run converges.
2. **Unset** — `toolkit secrets unset apps.services.core.gitea.bot_token --env prod`, which
   re-opens the mint gate.
3. **Re-mint** — `make provision NODE=bee ENV=prod`.

Never mint a second token without revoking the first: the account would hold two live credentials
with nothing recording which consumer holds which.

**There is an outage window.** Between (1) and (3) nothing holding `bot_token` can authenticate.
Short, but real — run it deliberately, not as a side effect.

**Two tokens sharing a name** makes Gitea answer 422 and `revoke_token` propagates it rather than
guessing. That state needs a human.

## Verification

```
make provision NODE=bee ENV=prod      # twice: the second must report changed=0
make test-infra ENV=prod              # the live Gitea guards
```

`changed=0` on the second run is the claim, and it is the one worth checking: the probe/reassert
pair is only correct if a converged host does nothing.

## References

- ADR-062 — platform identity model; D-88 (SSO daily, local password break-glass), line 92
  (machine credentials reversible in SOPS by design).
- `infra/ansible/roles/beelink_services/tasks/main.yml` — probe, reassert, and both mint tasks.
- `toolkit/features/gitea_client.py` — `GiteaBasicAuthClient`, and why the endpoint refuses tokens.
- #1076 (TOOL-035), #1389 (SEC-GITEA-001).
