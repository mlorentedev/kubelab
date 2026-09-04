---
id: lesson-421-secret-written-to-one-sops-store-read-from-another
type: lesson
status: active
created: "2026-09-02"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, sops, ansible, gitea, guards]
---

# A secret read from the wrong SOPS store resolves to `''`, so a presence gate on it is open forever

**Context**: Wiring the Gitea Actions runner into `beelink_services` (#1076 AC7, PR #1597).
The runner's registration token is minted on first provision and recorded in SOPS, and the
mint is gated on the key being absent — because `gitea actions generate-runner-token`
"reuses the latest active token or creates a new one, **invalidating all prior tokens for
the same scope**" (`models/actions/runner_token.go`). An ungated mint does not merely churn
a value; it revokes the token the running runner registered with.

**Problem**: The Beelink is the only node in the fleet holding **two** SOPS stores at once,
and it holds them deliberately (ADR-061: Gitea's *environment identity* is prod while the
node's `deploy_env` is staging). `provision-bee.yml` builds `secrets` from
`common + deploy_env` and `gitea_secrets` from `common + gitea_identity_env`.

The role writes the token with `--env {{ gitea_identity_env }}`, so it lands in
`prod.enc.yaml`. The playbook read it from `secrets` — staging. The value was never found.

**That does not fail.** Every one of those reads carries `| default('', true)`, and an
empty string is a perfectly good value. Nothing raises, nothing warns, the playbook goes
green. The consequence is `when: not act_runner_token` true on *every* provision, so each
re-provision would have re-minted and deregistered its own running runner while reporting
success. And a workflow whose `runs-on` matches no runner is **queued, not failed** — no
error, no red check — so nothing downstream would have reported it either.

The guard that should have caught it passed throughout.
`test_the_mint_is_gated_on_the_secret_being_absent` asserts the mint task *has* a `when:`.
It does. **A gate that can never be satisfied is indistinguishable from a working one to
that assertion** — the reading is identical in both worlds.

**Solution**: Read from `gitea_secrets`, and add a guard that derives *both* sides from the
files rather than listing known pairs — the role's `toolkit secrets set <path> --env {{ V }}`
writes, the playbook's `sops -d {{ V }}.enc.yaml` -> `register` -> `set_fact` chain, and the
playbook's `{{ store.path }}` dereferences. A hand-maintained list would have to be updated
by the same person who introduces the next mismatch.

Proven by mutation: restoring the wrong store turns
`test_every_written_secret_is_read_from_the_store_it_was_written_to` red. Proven on the
node by consequence, which is the measurement that matters here — the *second* provision,
not the first:

```
make provision NODE=bee ENV=prod   ok=134 changed=10 failed=0
make provision NODE=bee ENV=prod   ok=129 changed=0  failed=0   <- the mint did not re-run
{'id': 1, 'name': 'kubelab-bee-gitea', 'status': 'online'} labels: ['ubuntu-latest']
```

The guard's own first version was itself vacuous: the regex used `\S*` for a path
containing `{{ playbook_dir }}`, whose inner spaces end a non-whitespace run, so it matched
nothing, the store map was `{}`, and all six checks looped over it and passed. The
anti-vacuity floor on the *derived* map refused it (lesson-416).

**Rule**: On a node with more than one secret store, **which store a variable reads is a
choice, and reading the wrong one is silent** — `| default('', true)` converts the mistake
into a valid empty value. So assert the property, not the syntax: a secret written under
env `X` must be read from the store built from `X`, derived from the files.

More generally, and this is the part worth carrying past SOPS: **a guard that asserts a
condition is *present* does not assert it can be *satisfied*.** Before trusting one, ask
what it would report if the thing it guards were broken in the way you actually fear. If
the answer is "the same", the guard is inert regardless of how carefully it is read.

**Tags**: `#sops` `#ansible` `#gitea` `#guards` `#adr-061` `#pr-1597` `#lesson-416`
`#lesson-418`
