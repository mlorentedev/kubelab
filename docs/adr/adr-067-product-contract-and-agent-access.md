---
id: "adr-067"
type: adr
status: proposed
owner: manu
date: "2026-09-30"
issue: "kubelab#1924"
tags: [architecture, decision, platform, product-contract, agents, mcp, tenancy, gitops]
depends_on: [adr-042-reference-architecture, adr-046-gitops-delivery-promotion-strategy, adr-048-platform-consumer-repo-boundary, adr-050-cross-context-command-center, adr-052-cluster-access-transport, adr-053-platform-product-repos, adr-062-platform-identity-model, adr-064-agentic-observability-and-auto-triage]
created: "2026-09-30"
---

# ADR-067: Product Contract and Agent Access Surface

## Status

Proposed, 2026-09-30. It is the output of an architecture session on kubelab#1924. It amends [ADR-053](adr-053-platform-product-repos.md) §2 and §5, [ADR-064](adr-064-agentic-observability-and-auto-triage.md) (its MCP clause), [ADR-048](adr-048-platform-consumer-repo-boundary.md) (the `kubelab-cli` publish), and [ADR-043](adr-043-unified-knowledge-memory-plane.md) (where its thin MCP tool is served). It does not activate the gateway role that [ADR-029](adr-029-intelligence-layer.md) gives the Go API. [ADR-042](adr-042-reference-architecture.md) D4 was re-examined and stands: single-tenant per client.

## Context

Agents working in product repositories have started to deploy onto kubelab. kubelab is the stack under all of the operator's work: their own products, client work in staging, and the blueprint a client replicates. A product therefore has to reach the platform without the operator hand-editing kubelab, and an agent has to be able to ask the platform questions without holding its keys.

What exists, measured on 2026-09-30:

- **Onboarding a product is manual.** It takes 11 mandatory edits across kubelab, including `apps.platform.<app>` in `common.yaml`, env overrides, the hardcoded `PLATFORM_APPS` (`toolkit/config/constants.py:48`), one receiver workflow per product, `promote-prod.yml` guards and tests. Only `web` is wired. The third product is refused (#1815).
- **Only the operator's credentials exist.** One SOPS key decrypts every environment, and the kubeconfig is admin. There is no read-only or staging-only credential (ADR-052 D5).
- **No agent surface exists.** ADR-064 says `toolkit obs` is also exposed as MCP tools, but the repo has no MCP code. Only three `obs` commands emit `--json`. The toolkit is not installable outside the repo.
- **There is no tenancy.** One namespace (`kubelab`), one Argo CD AppProject (`default`), and no developer identity class (#1742).
- **The write path already exists.** Product CI sends a `repository_dispatch`, a receiver runs `toolkit deployment promote`, the promote opens a PR, a human merges it, and Argo CD syncs. The target app comes from the event type, never from the payload.

External facts that bound the options (verified 2026-09-30):

- Authelia 4.39 supports `client_credentials`, JWT access tokens (RFC 9068) and RFC 8707 `resource`. The `resource` parameter was broken in 4.39.21–22 and fixed in 4.39.23; the pin is 4.39.15. Authelia has no dynamic client registration (RFC 7591) and no client ID metadata documents. So MCP clients must be pre-registered, which the MCP authorization spec allows.
- Infrastructure MCP servers (Argo CD, Flux, kubernetes-mcp-server) default to write-enabled and offer a read-only flag. The GitHub MCP server is the only one whose writes go through PRs.
- Score's core spec has no auth, identity, route or secret types, and its schema is still v1b1.

## Decision Drivers

- **C1 GitOps only.** A cluster is written only through GitOps: every change is a PR, and prod is promoted only after a human merge (ADR-046, ADR-047).
- **C2 No keys on agents.** No agent host holds a SOPS key or a prod kubeconfig, and secret values never leave kubelab (ADR-052 D5).
- **C3 App from event type.** A deploy's target app comes from the event type, never from the payload.
- **C4 One operator.** The design must be industry-defensible, not resume-driven, and maintainable by one person (ADR-026).
- **C5 Single-tenant per client.** ADR-042 D4 is reaffirmed: the operator's infra hosts the operator's own products and client *staging*, and client prod runs on the client's own instance.
- **C6 No client identity in public.** Nothing that identifies a client enters the public kubelab repo or its public CI logs: no names, domains, auth levels or secret names.
- **C7 Declared once.** A product is declared once, and everything else is derived from it, with a test that fails on drift (the break-glass and OIDC-client shape).
- **C8 Always-on.** Anything an agent may call at any hour runs on an always-on host (ADR-028).
- **C9 Federate, don't absorb.** Products stay independently deployable and integrate by contract (ADR-050 C4).
- **C10 Automated, professional, maintainable.** kubelab is the stack under all the operator's work and the blueprint clients replicate.

The constraint table and the rejected alternatives are also kept in the operator's architecture notes, so later sessions do not re-derive them.

## Considered Options

**Contract location**

- **A. A file in the product repo, validated and ingested by kubelab.** *Chosen.*
- **B. Declare products in kubelab's `common.yaml` only, and have agents open PRs against kubelab.** *Rejected.* It breaks C6 for client products, and it gives product agents write access to kubelab.
- **C. Score (score.dev).** *Rejected.* It has none of the platform's concerns (auth tier, identity, SOPS secrets), so everything that matters would be custom provisioners. Reopen if Score v1 ships route, secret and auth types.

**Agent interface**

- **D. An MCP server that validates its own tokens, behind the existing Traefik edge. Writes go through the existing GitOps dispatch.** *Chosen.* The MCP authorization spec already requires the resource server to validate each token's audience, so the server has to do that work whatever sits in front of it.
- **E. The Go API as an application gateway, with MCP behind it.** *Rejected.* It would validate the same token twice and add a network hop and a second language. It would also put the platform's control plane in the same process as the web's newsletter endpoints, so a fault in either would reach the other. The edge that routes, terminates TLS, rate-limits and bans is Traefik already. First drafted as the choice, it was reversed in the same session on review.
- **F. A published CLI that agents install.** *Rejected as the agent surface.* It needs credentials on the agent host (C2). The operator CLI stays.
- **G. MCP write tools that call Argo CD or the Kubernetes API directly.** *Rejected.* They break C1. Reopen only when per-tenant AppProjects exist and every call requires approval.

## Decision

### D1. One library, thin adapters

Toolkit feature functions are the only implementation. The operator CLI (`toolkit`), the MCP tools and the receiver workflows are adapters over them, and none re-implements a rule. Every tool an agent can call exists as a CLI command with `--json` first, so every tool is testable offline and usable by the operator.

### D2. The product contract

A product declares itself in one file at its repository root. **File names:** the product contract is `kubelab.yaml`, because it is what a product author sees ("this deploys on kubelab"). The *instance* configuration of a replicated kubelab keeps the name `platform.yaml` whenever TOOLKIT-001 (#522) builds it, and #522–#528 are retitled to match.

The contract carries only what the product owns:

- image repository;
- port and health path;
- hostname per environment;
- auth level (`public`, `forwardauth` or `oidc`);
- the names of the secrets it expects. Values never appear here; the operator sets them in SOPS.

kubelab publishes the contract's JSON Schema. A **registry** of admitted products maps each app to its repository, forge and event types, and a product absent from it is refused. kubelab's registry lists only the products that may be named in public. A private product's entry lives in its tenant repository (D4). `PLATFORM_APPS` is derived from the registry (#1815).

### D3. One generic receiver

One workflow replaces the per-product receivers. It maps the event type to an app through the registry (C3), fetches that product's contract at the dispatched tag, validates it against the schema, renders the derived configuration, and opens the promotion PR. The payload carries only the tag. A contract change and an image change take the same path.

### D4. A private product's whole path runs in the private forge

Writing a private product's manifests to a private repository is not enough. On the public path, the registry entry, the public receiver's Actions logs and the Authelia OIDC client entry in `common.yaml` would all still name the client. GitHub-hosted runners also cannot reach Gitea on the tailnet to fetch a private contract.

So the public repo publishes only the **schema, the toolkit code and the tests**. For a product the registry would mark `private`, the whole path runs in a private **tenant repository** on the Gitea forge, which consumes the toolkit at a pinned version:

- the registry entry;
- the receiver, run on Gitea Actions with the act_runner on the platform node;
- the render and the promotion PR;
- the product's OIDC client declaration;
- the Argo CD source, as one extra Application per environment.

This is staging only: client prod runs on the client's own instance (C5, ADR-042 D4). The toolkit therefore has to be runnable from a repository other than kubelab. D8 names the minimum.

### D5. Soft tenancy per product

Every product onboarded through the contract gets these from its first deploy:

- a namespace, with a ResourceQuota and a LimitRange;
- a default-deny NetworkPolicy (#378);
- its own Argo CD Application and an AppProject restricted to that namespace;
- its own SOPS recipient (#889).

This changes ADR-047's least-privilege shape. The spoke's write role is scoped to `kubelab` today (`infra/k8s/argocd/spoke-rbac.yaml`, enforced by `tests/test_spoke_rbac_covers_manifests.py`), so it becomes one write role per product namespace, generated from the registry. Hard isolation (a cluster or vCluster per tenant) is not needed, because no client prod is hosted (C5). The existing `api` and `web` move out of `kubelab` too (about 129 manifests), under their own child of the epic, so there is one path and no permanent exception.

### D6. A read-only MCP server behind Traefik that validates its own tokens

- **The edge.** Traefik stays the only edge. The MCP server gets its own IngressRoute, which carries:
  - the rate limit and the CrowdSec bouncer every route already carries;
  - an IP allowlist for the tailnet CIDR (from `networking.*` in `common.yaml`), because agents reach it over the tailnet and nothing public needs it.
- **Agents outside the tailnet join it; the route does not open.** A CI job on a GitHub-hosted runner joins for the duration of the job with an ephemeral, pre-authorised Headscale key, and a Headscale ACL lets that tag reach only the MCP route. Network and identity stay two separate locks, as with a private cluster endpoint reached from CI over a VPN.
- **Token validation lives in the server.** `toolkit-mcp` validates Authelia-issued JWT access tokens itself: the issuer, its own audience (its resource identifier) and expiry. It uses FastMCP's JWT verifier against Authelia's JWKS, and it serves RFC 9728 protected-resource metadata. There is one validation, in the process that uses the token.
- **The MCP server.** `toolkit-mcp` is a Python FastMCP server over D1's functions, and it is stateless. It runs in prod, which is always-on (C8), with a read-only ServiceAccount. It reads staging spokes over the tailnet, and when the homelab is powered off it reports them as unreachable rather than failing.
- **Tools** are read-only: deploy status, promote dry-run, contract validation, and app-scoped logs and alerts. A token is scoped to one product by its client ID, and a tool refuses any other app. No tool returns a secret value.
- **Identity.** Each agent gets a pre-registered Authelia client, in ADR-062's machine class. CI agents use `client_credentials`; interactive agents use authorization code with PKCE and a fixed redirect URI. Authelia moves to 4.39.23 or later. Vector's redaction learns JWTs, because its `authelia_(at|rt|ac)_` pattern does not match them (SEC-021).
- **Known constraints the build must honour:**
  - `/mcp` carries a Bearer token, not a session cookie, so its route bypasses the `authelia` ForwardAuth middleware. This is the same exception ADR-066 D3 made for Vikunja's REST, and `tests/test_break_glass.py` has to know about it.
  - Authelia's issuer depends on the request's URL. The server validates `iss` against the **external** issuer even when it fetches the JWKS internally.
  - `toolkit-mcp` in prod needs read-only credentials for staging stored in prod: a staging ServiceAccount token and a Grafana viewer token per environment, registered in `SECRET_CATALOG`.
  - That a pod on the prod cluster can reach the staging spoke's API over the tailnet is assumed, not measured. The MCP phase verifies it first.

### D7. Writes stay GitOps

No tool writes. An agent changes what runs by changing its own repository: the contract, or a release that dispatches a tag. The platform turns that into a PR, and a human merges it.

A staging PR rendered from a validated contract is the case the operator's merge policy already names ("a diff nobody wrote"). It may merge unattended only when all four of that policy's conditions hold, prod is always excluded, and conditions (c) and (d) are built and tested. Until then, a human merges it.

### D8. The toolkit is consumable, not published

Agents never install the CLI; they use the MCP server. The toolkit still has to run from a tenant repository (D4), so the minimum is:

- it is installable at a pinned git tag (`uv tool install git+…@<tag>`);
- the contract commands (validate, render, promote) take the registry and the contract as inputs rather than reading kubelab's own tree;
- they need no SOPS key.

Publishing to PyPI (ADR-048's `kubelab-cli`) and the generic *instance* configuration (TOOLKIT-001..009) remain part of ADR-042's replicable blueprint and are out of scope here.

## Consequences

**Positive**

- Onboarding a product becomes a contract file plus one registry entry, instead of 11 hand edits.
- A client product can be staged on kubelab without its identity entering a public repo.
- ADR-064's MCP claim becomes true, and it is read-only by construction.
- Agents never hold platform credentials. An agent token is revocable per agent and scoped to one product.

**Negative**

- A tailnet-only route means an agent outside the tailnet cannot read anything. That is intended; public exposure is a reopen trigger, not a default.
- Token validation is code in the server, so it needs its own tests: no token, expired, wrong audience and wrong issuer are each refused.
- A second Argo CD source per environment (D4) is one more thing to keep in sync, and it depends on Gitea, which is on-demand. That is acceptable, because staging is on-demand too.
- Pre-registered clients mean each agent is onboarded by hand until Authelia ships DCR or CIMD.

**Neutral**

- The toolkit's library boundary becomes load-bearing: CLI-only logic has to move into `features/` before it can be a tool.

## Amendments to other ADRs

This PR adds an "Amended by ADR-067" note to each:

- **ADR-053:**
  - §2: the per-product receiver becomes one generic receiver fed by the registry.
  - §5: the rule of three is met (web, garsync and client staging), so the *contract* is built now; the scaffold template still waits.
  - ADR-053 is still `proposed` while every later ADR treats it as operative. This PR moves it to `accepted` with these amendments.
- **ADR-064:** the MCP exposure is real. It is read-only, served by a Python server behind Traefik that validates its own tokens, and not `toolkit obs` alone.
- **ADR-048:** the `kubelab-cli` publish moves to the instance-contract work; D8 above covers the consumable minimum.
- **ADR-043:** its thin MCP tool for coding agents is served by `toolkit-mcp` (D6). Option B, a network-served hive MCP, stays deferred on its own trigger.
- **ADR-062:** the machine class gains one pre-registered client per agent, scoped to one product.

Two ADRs are left unamended, and the reason is recorded here so the silence is not read as an oversight:

- **ADR-029:** its gateway role for the Go API covers `/v1/*`, which is still unbuilt. The agent surface does not start it (option E).
- **ADR-049 D5** says the Go API is *the* platform gateway. Its subject is Cloudflare edge Workers, which must never take auth or routing, and that still holds. The agent surface is a read-only control-plane service, not a `/v1/*` product endpoint, so it does not go through the Go API.

## Reopen triggers

- **Score:** v1 ships route, secret and auth types.
- **Write tools (G):** per-tenant AppProjects exist and every call requires approval.
- **Hosting client prod:** the operator decides to offer hosting as a product. That reopens ADR-042 D4 and requires hard isolation.
- **An application gateway (E):** a consumer needs REST rather than MCP, or ADR-029/043's `/v1/*` is built. The question then is whether both surfaces sit behind one service. Traefik stays the edge either way.
- **Public exposure of the MCP route:** an agent that cannot join the tailnet needs to read.
- **Self-registering MCP clients:** Authelia ships DCR or CIMD.

## Implementation (epic #1931)

1. **Contract and receiver:** the schema, the registry, the generic receiver and #1815. Migrate `web` first, then onboard garsync.
2. **Tenancy:** namespace, Application and AppProject per product, generated spoke write roles, NetworkPolicy (#378), a SOPS recipient per product (#889), then the migration of `api` and `web`.
3. **Private path:** the consumable toolkit (D8) and the tenant repository on Gitea with its runner, receiver and Argo source.
4. **Agent access and MCP:** verify the pod-to-tailnet reach, bump Authelia, register the agent clients, add the tailnet-only route without ForwardAuth, have the server validate its own JWTs, build the read tools with per-product scoping, redact JWTs, and audit every call in Loki (#1934).
5. **Supply chain:** sign every platform image, attach an SBOM, and verify the signature before promotion (#1935). A product admitted by its contract then runs only images the platform can attribute to a build.

## References

- kubelab#1931 (the epic), kubelab#1924 (research), #1815, #400, #889, #378, #1742, #522–#530, #406, #1322
- MCP authorization spec 2025-11-25; Authelia OIDC standards table; Authelia issues #12970 and #13113
