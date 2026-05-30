---
id: adr-040-oidc-secret-lifecycle
type: adr
status: active
created: "2026-05-29"
---

# ADR-040 — OIDC client-secret lifecycle: generate the provider side, verify the consumer side

## Status

**Accepted** — 2026-05-29. Gates the design of OIDC-SYNC-002 (atomic rotation): this ADR
decides the direction *before* that work is built, so the investment is not sunk into the
wrong model. Extends [ADR-016](adr-016-oidc-centralized-auth.md) (OIDC centralized auth)
and [ADR-038](adr-038-secret-delivery-paths.md) (secret delivery paths).

## Context

A single OIDC client secret (e.g. Gitea's) has to be in agreement across **three**
locations for a login to work:

1. **Plaintext in SOPS** — `apps.services.core.gitea.oidc_client_secret` — the source of truth.
2. **Argon2 hash in Authelia** — `identity_providers.oidc.clients[].client_secret` inside
   `authelia-config/configuration.yml` (the OIDC *provider* side).
3. **Plaintext in the consumer** — Gitea's SQLite OAuth source, written via
   `gitea admin auth update-oauth` (the OIDC *consumer* side).

Today the agreement is maintained by an imperative, multi-step ritual the operator has to
remember in order:

```
SOPS plaintext
  → make sync-oidc-hashes   (hash → Authelia configuration.yml)
  → commit + PR + deploy    (Authelia picks up new hash via PR #225 hash-suffix restart)
  → make configure-oidc     (plaintext → Gitea SQLite via admin API; Gitea only)
  → make apply-secrets + restart   (plaintext env var → MinIO/Grafana pods)
  → make deploy-argocd      (plaintext → Argo CD stored secret via helm --set; common SOPS)
```

Every step is a place to forget, and **drift is silent until a human attempts an
interactive login**. This pattern produced a cluster of incidents and follow-up tickets:

- **OIDC-SYNC-001** (#229, fixed) — `sync_oidc_hashes` wrote nothing yet reported "OK"
  after PR #225 moved the clients; the prod Gitea hash drifted undetected.
- **OIDC-SYNC-001b** (#230, fixed) — the `--check` drift guard compared the wrong files,
  so even the drift detector was blind.
- **OIDC-DRIFT-001** (#231) — `configure-oidc` exited 0 while the flow was broken, because
  it never verified the result.
- **OIDC-SYNC-002** (pending) — proposed atomic `make rotate-oidc-secret`.
- **OIDC-E2E-001** (pending) — proposed programmatic OIDC flow tests in CI.

These are not five independent bugs. They are the symptom of an **absent lifecycle
strategy**: there was no decision on record about *how the three locations are kept in
agreement and how that agreement is proven*. This ADR makes that decision.

### The fork

Two coherent directions were on the table:

- **Direction A — harden the imperative ritual.** Accept that secret propagation is a
  sequence of imperative steps; make the sequence robust (atomic `rotate-oidc-secret` with
  rollback + verification). Lower refactor cost, but the orchestration debt is permanent —
  every step remains a thing that can be skipped or mis-ordered, only now with guard rails.

- **Direction B — generate everything from SSOT.** Aim to eliminate every sync step: one
  pass over SOPS generates the Authelia config *and* pushes to every consumer, so there is
  nothing to drift. Architecturally the cleanest "generation over synchronization" stance —
  but it assumes the consumer side can be made declarative.

The decisive observation is that the OIDC secret has **one provider face plus three
distinct consumer faces**, each with a different propagation step — and grouping them
by what they are *not* (e.g. "not admin-API") hides exactly the differences that break a
rotation. The propagation step is what SYNC-002 must run; the verification is how it
proves the step worked:

| Face | How the secret gets there | Propagation step SYNC-002 must run | How it is proven |
|------|---------------------------|------------------------------------|------------------|
| **Provider (Authelia)** | argon2 hash in `configuration.yml`, a file the toolkit renders | **generate** the hash from SOPS (PROVIDER-GEN-001) | drift structurally impossible once generated ([ADR-038](adr-038-secret-delivery-paths.md) Path 3) |
| **Consumer — admin-API (Gitea)** | plaintext in Gitea's SQLite OAuth source | `make configure-oidc` (`gitea admin auth update-oauth`) | **DRIFT-001 token round-trip** (shipped #231) |
| **Consumer — env-var (MinIO, Grafana)** | plaintext as an env var from a K8s Secret ([ADR-038](adr-038-secret-delivery-paths.md) Path 1, e.g. `MINIO_IDENTITY_OPENID_CLIENT_SECRET`) | `make apply-secrets` + pod restart | OIDC-E2E-001 flow test (**pending**) |
| **Consumer — Helm `--set` (Argo CD)** | injected into Argo CD's stored secret at deploy via `helm upgrade --set configs.secret.extra.oidc\.authelia\.clientSecret=…`; source is **common** SOPS, not per-env | `make deploy-argocd` (NOT `apply-secrets`) | OIDC-E2E-001 flow test (**pending**) |

The trap — caught by Codex on this ADR — is conflating consumers by what verifies them
instead of by what *propagates* to them. An earlier draft lumped Argo CD into the
"env-var" bucket; but Argo CD's secret is **not** an env var. If SYNC-002 runs only
`apply-secrets + restart` for that bucket, it would rotate Authelia's hash and leave Argo
CD's stored client secret stale → Argo CD OIDC broken while the plan reports the consumer
handled. The same silent-success this ADR exists to kill, reintroduced through a wrong
taxonomy. Argo CD needs its own propagation (`make deploy-argocd`) and its secret lives in
common SOPS.

So: **four faces, four propagation steps, three verification strategies** (provider =
generation; Gitea = DRIFT-001; env-var + Helm consumers = OIDC-E2E-001). `configure-oidc`
covers Gitea only; it touches none of the others.

Direction B breaks on the admin-API consumer face: you cannot declaratively generate a
row in Gitea's SQLite. Direction A under-serves the provider face: it keeps treating a
*generatable* artifact as something to imperatively sync. The right answer is asymmetric.

## Decision

Adopt **Hybrid C — generate the provider side, verify the consumer side.**

### 1. Provider side (Authelia): generation, not synchronization

The argon2 hash in `configuration.yml` is a **derived artifact of the SOPS plaintext** and
must be produced by the same SSOT generation pass that already renders the Authelia config
([ADR-038](adr-038-secret-delivery-paths.md) Path 3), not patched in afterwards by a
separate `sync-oidc-hashes` step.

- **Target state:** rendering `configuration.yml` computes each client's argon2 hash from
  the SOPS plaintext inline. There is no second step, therefore no path/format drift class
  (the entire OIDC-SYNC-001 / 001b failure mode disappears — there is nothing to point at
  the wrong file).
- **Until that lands:** `sync_oidc_hashes` stays as the bridge, but it is now **fail-loud**
  (#229) and its `--check` set is **derived from a single source** (#230). It is explicitly
  a transitional mechanism, not the end state.

### 2. Consumer side: verify, with coverage matched to the delivery mechanism

The consumer secret cannot be generated into agreement; it must be **proven** to agree.
Each consumer face needs its own propagation step AND its own proof — and none may report
success without one:

**2a. Admin-API consumer (Gitea).** The secret is pushed via `gitea admin auth
update-oauth`. `configure-oidc` performs a **token-endpoint round-trip** after every
update and fails loud on `invalid_client` (**OIDC-DRIFT-001**, #231, merged
`2a771de`). Per RFC 6749 §5.2, `invalid_client` is the only error code that denotes
failed client authentication, so it is the precise signal that the Gitea plaintext
disagrees with the provider hash. **Scope: Gitea only** — `configure-oidc` does not
touch any other consumer.

**2b. Env-var consumers (MinIO, Grafana).** The secret is delivered as an env var from a
K8s Secret (Path 1) via `make apply-secrets` + pod restart; there is no push step and
**no verification today**. Provable only by a **programmatic OIDC flow test per client**
(**OIDC-E2E-001**, not yet implemented).

**2c. Helm `--set` consumer (Argo CD).** Argo CD is **not** an env-var consumer — its
client secret is injected into Argo CD's stored secret at deploy time by
`make deploy-argocd` (`helm upgrade --set configs.secret.extra.oidc\.authelia\.clientSecret=…`),
and its source is **common** SOPS, not per-env. Its propagation step is therefore
`make deploy-argocd`, **not** `apply-secrets`. Running the env-var path for Argo CD would
rotate the Authelia hash while leaving Argo CD's stored secret stale → Argo CD OIDC broken
while the plan claims the consumer was handled. Verification is the same OIDC-E2E-001 flow
test, but the propagation step is distinct.

> Do not assume "reuse DRIFT-001" covers all consumers, and do not assume one propagation
> step covers all non-Gitea consumers. DRIFT-001 proves Gitea only. MinIO/Grafana need
> `apply-secrets`; Argo CD needs `deploy-argocd` (common SOPS). All three non-Gitea
> consumers are **unverified** until OIDC-E2E-001 exists — SYNC-002 must treat that as an
> open gap, not delegate to a check that never runs for them.

### 3. Rotation composes the faces

**OIDC-SYNC-002** (`make rotate-oidc-secret`) is **re-scoped** by this ADR. It is not "an
imperative sequence with guard rails" (Direction A). It is the orchestrator that:

1. rotates the SOPS plaintext (SSOT) — at the **correct scope** (per-env for Gitea/MinIO/
   Grafana; **common** for Argo CD),
2. triggers the provider-side **generation** (§1),
3. runs the **propagation step that matches the target consumer** (§2): `configure-oidc`
   for Gitea, `apply-secrets` + restart for MinIO/Grafana, `deploy-argocd` for Argo CD —
   they are **not interchangeable**,
4. **verifies** that consumer with its matching proof: DRIFT-001 token round-trip for
   Gitea; OIDC-E2E-001 flow test for MinIO/Grafana/Argo CD — **a rotation that touches any
   non-Gitea consumer while E2E-001 is unimplemented is not fully verifiable and must say
   so, not report green**,

and treats the **verification, not the exit code of each step, as the definition of
success**. A rotation that cannot prove the affected consumer works fails and rolls back.

### Invariant

> The provider side is *generated* (drift impossible). Each consumer is *propagated by the
> step that matches its delivery* (Gitea = `configure-oidc`, MinIO/Grafana = `apply-secrets`,
> Argo CD = `deploy-argocd`) and *proven by the check that matches it* (Gitea = token
> round-trip, shipped; all others = E2E-001 flow test, pending). No OIDC secret operation
> reports success for a consumer it cannot actually verify; an unverifiable consumer is
> reported as a gap, never as green.

## Consequences

### Positive

- **Eliminates a whole bug class.** Once §1 lands, the OIDC-SYNC-001/001b family (a separate
  sync step pointing at the wrong file) cannot recur — there is no separate step.
- **Silent success becomes impossible *where a verifier exists*:** for Gitea, the only
  definition of done is a proven token round-trip (shipped). For the env-var consumers the
  ADR makes the absence of a verifier *explicit* (E2E-001 gap) rather than implying coverage.
- **Reframes the backlog into a coherent plan** instead of four loosely related tickets:
  SYNC-002 (provider generation + orchestration), DRIFT-001 (Gitea admin-API verify,
  shipped #231), E2E-001 (env-var consumer proof, still required). Each now has a clear role.
- **Honours existing patterns.** Provider-side generation is the same "generate, don't sync"
  stance already used for ConfigMaps; consumer-side verify-after-write mirrors Argo CD health
  checks. Nothing exotic is introduced.

### Negative / accepted

- **The consumer side stays imperative.** Hybrid C does not make Gitea's OAuth source
  declarative — that is a limitation of the consumer, not a choice we can refactor away. We
  accept an imperative push and pay for it with mandatory verification.
- **Provider-side generation is a non-trivial refactor.** Folding hash computation into the
  config render touches `generator_authelia.py` / the Authelia render path and must preserve
  the byte-for-byte stability that PR #225's hash-suffix restart depends on. It is scheduled,
  not immediate.
- **Two mechanisms during the transition.** Until §1 lands, both the generator and the
  fail-loud `sync_oidc_hashes` bridge exist. Accepted as explicitly temporary.

### Risks

- **Argon2 is non-deterministic by salt.** Generating the hash on every render would change
  the file every time and defeat hash-suffix stability. The generator must reuse the existing
  stored hash when the underlying plaintext is unchanged (same IMMUTABLE-style preservation
  the credentials generator already does), only recomputing on actual plaintext rotation.
  This is the main implementation subtlety for §1 and must be covered by a determinism test.
- **Verification must hit the external issuer.** Authelia's OIDC issuer is request-dependent
  (CLAUDE.md gotcha); a verification that hits the internal Service IP would test the wrong
  issuer. DRIFT-001 already uses the external URL — SYNC-002 must keep that.

## Alternatives considered

### Direction A — harden the imperative ritual only

Rejected as the *whole* answer. Building atomic rotation with rollback over the existing
imperative sync is genuinely useful for the consumer side and is retained there. But applying
it to the provider side too would keep treating a generatable artifact (`configuration.yml`
hash) as something to imperatively patch — which is the precise design that produced
OIDC-SYNC-001. A is a component of the solution (consumer side), not the strategy.

### Direction B — generate everything from SSOT

Rejected as unattainable for the consumer side. There is no declarative resource for "Gitea's
OAuth source"; it is mutable state behind an admin API in the app's own datastore. Forcing B
would require either a custom controller that reconciles each consumer's OAuth state (large
operational surface for a single-operator lab) or abandoning consumers that have no
declarative auth config. The generation half of B is adopted for the provider side; the
consumer half is replaced by verify-after-push.

### Sealed Secrets / External Secrets Operator

Out of scope here and already addressed in [ADR-038](adr-038-secret-delivery-paths.md)
(deferred as SEAL-001..004). Changing the at-rest secret format does not change the OIDC
*lifecycle* problem: the provider hash still has to be derived and the consumer still has to
be pushed and proven, regardless of whether the SSOT is SOPS or a SealedSecret.

## Backlog impact

- **OIDC-SYNC-001 / 001b** — done (#229, #230); reclassified as the *transitional bridge* for
  the provider side, to be retired when §1 generation lands.
- **OIDC-DRIFT-001** (#231, merged) — the **Gitea** (admin-API) verification primitive;
  shipped per §2a. Does **not** cover env-var consumers.
- **OIDC-E2E-001** — re-confirmed as **required, not optional**: it is the only verification
  for every non-Gitea consumer (env-var: MinIO/Grafana; Helm `--set`: Argo CD), all of which
  are unverified until it lands. Note their propagation steps differ (`apply-secrets` vs
  `deploy-argocd`) even though they share this one verifier.
- **OIDC-SYNC-002** — re-scoped per §3: generation + orchestration + verification, not a
  guard-railed imperative sequence. **Should not start until this ADR is accepted** (it was
  the reason to write the ADR first).
- **OIDC-E2E-001** — the CI proof of §2; unchanged in intent, now explicitly part of the
  verification half of the strategy.
- **New follow-up (PROVIDER-GEN-001, to file):** fold argon2 hash computation into the
  Authelia config render with hash-stability preservation; retires `sync_oidc_hashes`.

## Cross-references

- [ADR-016](adr-016-oidc-centralized-auth.md) — OIDC centralized auth (the tiers and clients
  this lifecycle serves).
- [ADR-038](adr-038-secret-delivery-paths.md) — Secret delivery paths (Authelia config is
  Path 3; this ADR governs how the OIDC secret *inside* that path is produced and proven).
- **ADR-039** (reserved, SECRET-RELOAD-001c) — Secret/ConfigMap reload policy; adjacent
  "how correct state reaches and stays in pods" decision.
- **CLAUDE.md gotchas** — "Authelia OIDC issuer is request-dependent", "Gitea OIDC CLI vs web
  process", "Authelia does NOT auto-reload configuration.yml".
- RFC 6749 §5.2 — OAuth2 error codes; basis for the `invalid_client` verification signal.
