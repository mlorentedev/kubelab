---
id: "SSOT-017-oidc-client-ssot"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-09-22"
issue: "#1332"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, authelia, oidc, ssot]
template_version: "1.0"
---

# SSOT-017: one declared list of OIDC clients

## Why

<!-- from issue #1332: SSOT-017: the K8s Authelia config is a second, hand-maintained copy of the OIDC client list -->

The OIDC clients that prod Authelia accepts are hand-written into two `configuration.yml` files, one for staging (the base) and one for prod (the overlay, `behavior: replace`). They disagree with the declared list in `common.yaml`. The declared list names `kubelab-oidc`, `grafana-oidc` and `minio-oidc`, and is missing `gitea` and `argocd`. The files register `minio`, `grafana`, `gitea`, `argocd` and `vikunja-oidc`.

Three writers touch those files: hand edits, `toolkit/scripts/sync_oidc_hashes.py` (a regex that rewrites `client_secret:` after `client_id:`), and `make credentials-generate`, which chains `sync all`. The 2026-08-23 prod SSO outage came from that chain: a regenerated config that was never committed, reverted by Argo CD `selfHeal`.

This is also the target state that ADR-040 §1 already accepted on 2026-05-29: "the provider side is *generated*", with `sync_oidc_hashes` recorded as "a transitional mechanism, not the end state". It was never built.

This spec is leg 1 of #1775 (IDP-040). The identity work needs a client list that can be read and trusted. It gives `toolkit auth review` something to compare the live issuer against. It is also the only place `authorization_policy: two_factor` can be declared for the admin surfaces.

## What

- `apps.services.security.authelia.oidc_clients` in `common.yaml` is the **only** declaration of an OIDC client. Each entry carries:
  - `client_id`, `client_name` and `scopes`;
  - `envs`, the environments it is registered in;
  - `token_endpoint_auth_method`;
  - `authorization_policy`;
  - `consent_mode` (its current value is kept);
  - a redirect, given as a reference to the service's declared domain plus a callback path. The host is therefore resolved per environment, never written twice.
- `toolkit` generates `oidc-clients.yml` per environment from that list, taking the `client_secret` digests from SOPS:
  - staging: `infra/k8s/base/services/authelia-config/oidc-clients.yml`;
  - prod: `infra/k8s/overlays/prod/authelia-config/oidc-clients.yml`.
  The file holds the **whole** `identity_providers.oidc.clients` list. Authelia 4.39 merges multiple config files, but it does not combine lists across files, so the list cannot be split. `configuration.yml` keeps everything else and loses its `clients:` block.
- **One resolver, two renderers.** A single function turns `oidc_clients` into the list of clients for an environment. It resolves hosts, filters by `envs` and looks up digests. It feeds both the K8s generator and the Compose dev renderer (`generator_authelia.py`, `configuration.yml.j2`). Today the Compose renderer reads the same list by its own mechanism: literal `redirect_uris`, and a digest key derived at `generator_authelia.py:138`. Changing the schema without it would break dev.
- **Digest lookup is a declared convention, not a per-client field.** The key is `apps.services.security.authelia.oidc_client_secret_<id>_hash`, where `<id>` is the `client_id` with a trailing `-oidc` removed and `-` replaced by `_`. This is the convention already in `generator_authelia.py:138`, and it yields exactly the keys that exist for all five live clients (`vikunja-oidc` → `..._vikunja_hash`). Lookup is per environment: a client whose `envs` exclude an environment is never looked up there. gitea's digest is `envs=("dev","prod")` in `SECRET_CATALOG`, so staging does not ask for it.
- `public: false` is set by the generator, not declared: every client here is confidential. A public client would be a schema change, made deliberately.
- The generator is the **sole writer** of the client list. `sync_oidc_hashes.py` is retired, and `make credentials-generate` / `sync all` call the generator instead.
- A test fails if the rendered client file for either environment differs from the SSOT in anything but `client_secret`. It needs no SOPS, so it runs in CI, where the OIDC drift check is skipped today (`toolkit/cli/sync.py:356`).
- Registration changes that fall out of aligning to the SSOT:
  - `kubelab-oidc` is removed from the SSOT, because nothing registers it in K8s;
  - `argocd` becomes prod-only, because the hub's issuer is `https://auth.kubelab.live` (`infra/helm/argocd/values.yaml:208`) and the staging registration is unreachable;
  - SSOT `client_id`s align to the registered ones: `grafana`, `minio`, `gitea`, `argocd`, `vikunja-oidc`.

## Out of scope

- **Secret minting from the client list.** `credentials generate` mints from a hardcoded sequence that includes `kubelab-oidc` and omits `vikunja-oidc`. Tracked as #1777 (SSOT-026), which reads the list this spec produces.
- **Moving `client_secret` out of the ConfigMap.** `_FILE` env overrides do not reach array-indexed keys (CLAUDE.md, Authelia OIDC JWKS gotcha), so the digests stay inline. They are one-way digests, not secrets, and that is Authelia's documented model.
- **Changing any client's `authorization_policy`.** This spec declares today's value (`one_factor` everywhere). Raising admin surfaces to `two_factor` is a later IDP-040 step, and after this spec it will be a one-line SSOT edit.
- **Whether the Compose dev path should exist at all.** It is migrated onto the shared resolver (see What). Retiring it would need evidence that nothing runs it, and that is a separate question.
- **Rotating any client secret.**

## Risks / open questions

- **R1: auth method per client. Resolve before code.** The method differs by client:
  - argocd is `client_secret_post`;
  - minio, grafana and gitea are `client_secret_basic` (gitea was measured 2026-08-23, see `overlays/prod/.../configuration.yml:190`; #1332's body says the opposite and is stale);
  - vikunja-oidc is `basic` but **unverified** (comment at `:223`).
  A default applied to all clients breaks exactly one of them at token exchange, and it reads as that client's own bug. Mitigation: the field is required and has no default in the schema. Before cutover, a live SSO login proves each client in each environment it is registered in (AC5).
- **R2: rotating is not landing.** Prod runs `selfHeal: true`. A generated file that is applied but not committed is reverted within seconds, taking SSO down (08-23). Every change to either file reaches git before or together with its apply. The validation flow never applies to prod by hand.
- **R3: staging validation window (#1083).** A worktree apply to staging is reverted by the next commit to master from any lane, in about 30 seconds. Validate by pointing the staging Application's `targetRevision` at the branch (lesson-256), then point it back after merge.
- **R4: the config mount changes shape.** Authelia mounts `configuration.yml` with `subPath`. A second file needs a second mount or a directory mount, plus `--config` / `X_AUTHELIA_CONFIG` naming both files. An error there fails Authelia's startup, which is loud, not silent. The hash suffix on `authelia-config` must still roll the pod when only `oidc-clients.yml` changes (lesson-404). This is verified by reading the emitted object from `kubectl kustomize`.
- **R5: prod consumers of removed or renamed ids.**
  - No consumer references `kubelab-oidc` in K8s.
  - `grafana-oidc` and `minio-oidc` exist only in the SSOT; live clients already use the short ids.
  - Staging `argocd` has no consumer, because the hub issuer is prod.
  Each is re-confirmed by grep at implementation time, not asserted from this list.
- **R6: Argo CD domain. Resolved 2026-09-22.** `argo.kubelab.live` has no SSOT key; it appears only as an Uptime Kuma `ping_url` and in the Helm values. Decision: add `argocd.domain` under the existing `argocd:` block in `common.yaml`. The hub is env-independent, so the key goes in common. Making the Helm values read the key is out of scope here, and is ticketed in this spec's Closing section.
- **Names. Resolved 2026-09-22.** `toolkit sync oidc` and `make sync-oidc-hashes` keep their names; 17 files cite them, including ADRs and lessons. The generated file is `oidc-clients.yml`.
- **R7: deliberate deviation from ADR-040 §1's wording.** ADR-040 says rendering "computes each client's argon2 hash from the SOPS plaintext inline". argon2 is salted, so recomputing on every run yields a new digest each time. Every render would be a diff, and the drift gate would fire forever. The generator therefore reads the digest already **stored** in SOPS (`oidc_client_secret_<client>_hash`, produced by `toolkit secrets hash`). The ADR's intent still holds: one pass, no second writer, no path-drift class. ADR-040 gets an amendment note recording this.

- **R8: which clients dev gets. Resolve during implementation, by measurement.** Today the Compose renderer registers every SSOT client in dev with the **prod** redirect URIs, which suggests OIDC in dev is already non-functional. Whether `dev` goes in any client's `envs` is decided by checking whether any dev Compose service is configured as an Authelia OIDC client. The spec does not assume the answer.

## Acceptance criteria

- [ ] AC1: for each of staging and prod, the rendered `oidc-clients.yml` registers exactly the SSOT clients whose `envs` include that environment. Every field except `client_secret` equals the SSOT-derived value. A test asserts this without SOPS, and it was shown red against the hand-written files before migration.
- [ ] AC2: `configuration.yml` in both the base and the prod overlay has no `clients:` key. The emitted `authelia-config` ConfigMap (`kubectl kustomize`) carries both files for each environment, and its name hash changes when only the client file changes.
- [ ] AC3: the only writer of the client list is the generator. `sync_oidc_hashes.py` is removed. `toolkit sync all` and `make credentials-generate` regenerate the client files. `toolkit sync all --check` reports drift when a SOPS digest changes and the file was not regenerated.
- [ ] AC4: the SSOT schema requires `token_endpoint_auth_method` and `authorization_policy` on every client. A client missing either fails generation with an error that names the client. Test-covered.
- [ ] AC5: a live SSO login succeeds after cutover for every client in every environment it is registered in. That is staging (grafana, minio, vikunja-oidc) and prod (grafana, minio, gitea, argocd, vikunja-oidc). vikunja-oidc's auth method is recorded as measured, and its "unverified" comment is removed or corrected. Evidence is in `verification.md`.
- [ ] AC6: the K8s generator and the Compose dev renderer get their clients from the same resolver function. A test asserts that both produce the same `client_id` set for the same environment, and that neither contains its own derivation of the digest key.

## References

- Work gate: #1332 (SSOT-017). Parent: #1775 (IDP-040). Follow-up: #1777 (SSOT-026).
- `docs/adr/adr-040-oidc-secret-lifecycle.md` §1: the accepted target state this spec builds, with the R7 deviation.
- `docs/adr/adr-062-platform-identity-model.md`: identity model, the rules this list feeds.
- ADR-061: Gitea is a prod singleton, so it has no staging client.
- ADR-027: generated code drift detection, the pattern for the committed, drift-gated output.
- lesson-404: hash-suffixed ConfigMaps; lesson-256 and #1083: the staging validation window.
- Authelia multi-file configuration: <https://www.authelia.com/configuration/methods/files>.
- Scaffolded with `dotf spec init --force-no-gate`: GraphQL was secondary-rate-limited, and #1332 was verified OPEN via REST (`gh api repos/mlorentedev/kubelab/issues/1332`).
