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
  → make configure-oidc     (plaintext → Gitea/MinIO/... admin API)
  → restart each consumer pod
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

The decisive observation is that **the OIDC secret has two structurally different faces**,
and they do not fit the same model:

| Face | Where it lives | Can it be *generated* from SSOT? |
|------|----------------|----------------------------------|
| **Provider (Authelia)** | argon2 hash in `configuration.yml`, a file the toolkit already renders | **Yes** — it is already a generated artifact ([ADR-038](adr-038-secret-delivery-paths.md) Path 3). Drift here can be made structurally impossible. |
| **Consumer (Gitea/MinIO/…)** | plaintext inside the app's own datastore (Gitea SQLite, MinIO config), reachable only through an imperative admin API | **No** — there is no declarative K8s resource for "Gitea's OAuth source row". It is mutable runtime state behind an API. The best available primitive is *push then verify*. |

Direction B breaks on the consumer face: you cannot declaratively generate a row in
Gitea's SQLite. Direction A under-serves the provider face: it keeps treating a
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

### 2. Consumer side (Gitea/MinIO): imperative push, mandatory verification

The consumer secret cannot be generated; it is pushed through an admin API. Therefore every
push **must** be followed by an automated proof that the round-trip actually works — an
imperative write without verification is the exact shape that failed silently.

- `configure-oidc` performs a **token-endpoint round-trip** after every update and fails
  loud on `invalid_client` (**OIDC-DRIFT-001**, #231). Per RFC 6749 §5.2, `invalid_client`
  is the only error code that denotes failed client authentication, so it is the precise
  signal that the consumer plaintext disagrees with the provider hash.
- CI gains a **programmatic OIDC flow test** per registered client (**OIDC-E2E-001**) so the
  disagreement surfaces in PR review, not in a manual prod smoke.

### 3. Rotation composes the two

**OIDC-SYNC-002** (`make rotate-oidc-secret`) is **re-scoped** by this ADR. It is not "an
imperative sequence with guard rails" (Direction A). It is the orchestrator that:

1. rotates the SOPS plaintext (SSOT),
2. triggers the provider-side **generation** (§1),
3. performs the consumer-side **push + verify** (§2, reusing DRIFT-001 as its verification
   step),

and treats the **verification, not the exit code of each step, as the definition of
success**. A rotation that cannot prove a working token round-trip fails and rolls back.

### Invariant

> The provider side is *generated* (drift impossible). The consumer side is *pushed and
> proven* (drift caught immediately). No OIDC secret operation reports success without a
> verification that the full SOPS → Authelia → consumer chain agrees.

## Consequences

### Positive

- **Eliminates a whole bug class.** Once §1 lands, the OIDC-SYNC-001/001b family (a separate
  sync step pointing at the wrong file) cannot recur — there is no separate step.
- **Silent success becomes impossible** on the consumer side: the only definition of done is
  a proven token round-trip.
- **Reframes the backlog into a coherent plan** instead of four loosely related tickets:
  SYNC-002 (provider generation + orchestration), DRIFT-001 (consumer verify, shipped),
  E2E-001 (CI proof). Each now has a clear role.
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
- **OIDC-DRIFT-001** (#231) — the consumer-side verification primitive; shipped per this ADR's
  §2.
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
