---
id: lesson-517-a-per-env-copy-of-a-common-secret-wins-the-merge-and-every-pair-check-passes
type: lesson
status: active
created: "2026-09-23"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, sops, argocd, oidc, ssot, uptime-kuma]
---

# A per-env copy of a common secret wins the merge, and every check that compares a pair with itself passes

**Context**: Argo CD SSO in prod failed with `invalid_client` (#1789). The hub's OIDC
client secret is `HUB_MANAGED`: it belongs in `common.enc.yaml`, where the hub, Secret
Manager and `deploy-argocd` read it.

**Problem**: `prod.enc.yaml` carried its own `oidc_client_secret_argocd{,_hash}` pair.
`get_merged_config(env)` deep-merges the env file over common, so every prod generator
used the copy. Authelia registered prod's digest, the hub sent common's plaintext, and
they disagreed. Both pairs were internally consistent, so every check that compares a
plaintext with its own hash passed. The writer re-created the copy on every run:
`credentials generate` put the argocd pair in the per-env `generated_secrets`. Probing
Authelia's token endpoint told the two apart: prod's plaintext answered
`unauthorized_client` (authenticated), common's answered `did not match`.

**Solution** (#1790): unset both keys from `prod.enc.yaml` and re-render with `make
sync-oidc-hashes ENV=prod`. The new digest verifies common's plaintext, so nothing on
the hub changed. `credentials generate` now writes all four hub keys to `hub_secrets`
(common), asserted by `TestCredentialsGenerateWritesHubKeysToCommon` with I/O mocked.
That fix covers the argocd pair only. The rest of the writer's hardcoded client list
has drifted from the registered clients and is still open as #1777 (SSOT-026).
`tests/test_hub_secrets_not_shadowed.py` fails CI when any `HUB_MANAGED` or
`sync_to_secret_manager` key appears in a per-env file. SOPS leaves key names in
plaintext, so the test needs no decryption. The key set is derived from the catalog, with
a check that fails if it is ever empty. It was red on the first commit, for exactly
`prod.enc.yaml`.

**Second instance** (#2599, 2026-10-22): Uptime Kuma's `admin_password` was a per-env
`PASSWORD`. So `credentials generate --env <env>` wrote it to `{env}.enc.yaml` and changed
the one Kuma on rpi3 to it, while `monitoring-apply` reads common only. `secrets rotate`
was a second path to the same split: it wrote SOPS and never touched Kuma. Nothing had
failed only because prod's copy still equalled common's (compared without printing). The
key is now `HUB_MANAGED`: the guard above covers it, `rotate` refuses it, and Kuma changes
only after the common write succeeds, starting from common's previous value.

**Rule**: in a layered config, a key's location is part of its value. It follows from how
many instances read it, not from where they run: one instance means one value in common,
whether or not that instance is "the hub". A secret that must
have one owner needs a guard on where it may appear, not only on whether it is
consistent. Two self-consistent copies are the failure that consistency checks cannot
see. Fix the writer that created the copy in the same change, or it comes back on the
next run. Here that holds for the argocd pair only; #1777 tracks the remaining clients.

**Tags**: `#sops` `#ssot` `#argocd` `#oidc` `#pr-1790` `#issue-1789`
