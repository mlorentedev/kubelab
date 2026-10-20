---
id: lesson-599-a-rotation-command-with-its-own-client-list-drifts-both-ways-and-the-env-it-runs-in-stops-scoping-it
type: lesson
status: active
created: "2026-10-18"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, oidc, credentials, ssot]
---

# A rotation command with its own client list drifts both ways, and the env it runs in stops scoping it

**Context**: `toolkit credentials generate` rotated the OIDC client secrets from a sequence written into
`setup_authelia_secrets`: one block per client. The registered clients have been declared once in
`apps.services.security.authelia.oidc_clients` since SSOT-017, and each declares the envs it exists in.

**Problem**: The written sequence had drifted from the declaration in both directions (#1777). It rotated a
pair for `kubelab-oidc`, which no Authelia config registers and nothing reads. It never rotated
`vikunja-oidc` or `open-webui-oidc`, which are registered, so "rotate every OIDC secret" left two untouched.
The test written for #1777 found a third failure that the ticket had not named. The sequence ignored the
`envs` each client declares, so a staging or dev run minted Gitea and Argo CD secrets, which exist only in
prod. Argo CD's pair goes to `common.enc.yaml`, the file the singleton hub reads. That means a run that said
`--env staging` replaced prod's Argo CD client secret, and Authelia's prod digest stayed as it was. This is
the same `invalid_client` split that SSOT-028 measured.

**Solution**: The minted set is derived. For every client the SSOT declares for the env, the digest key comes
from `oidc_clients.digest_key` and the plaintext from that SECRET_CATALOG entry's `derived_from`; a
`HUB_MANAGED` digest sends the pair to common. `tests/test_credentials_oidc_from_ssot.py` runs the generator
with its I/O mocked in each env and compares the keys it writes against the declaration. It was red on master
in all three envs before the change. The `kubelab-oidc` pair is no longer minted. #1777 AC3 then unset it
from the dev, staging and prod vaults and removed both catalog entries. The test now also fails on any
catalogued `oidc_client_secret*` key that no declared client uses, apart from a ticketed exception.

**Rule**: Where a list of things to act on is already declared, a command must read that list and not keep
its own copy. Read the scoping fields as well as the names: a copy that matches the names can still lose the
per-env scope. Test it as a set comparison against the declaration, run once per env. A count or a check of
one client passes while the list is wrong.

**Tags**: `#oidc` `#credentials` `#ssot` `#issue-1777`
