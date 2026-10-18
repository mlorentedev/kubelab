---
id: "adr-073"
type: adr
status: proposed
owner: manu
date: "2026-10-18"
issue: "kubelab#2449"
tags: [architecture, decision, platform, product-contract, resource-claims, secrets, gitops, self-service]
depends_on: [adr-014-secrets-management-strategy, adr-038-secret-delivery-paths, adr-042-reference-architecture, adr-046-gitops-delivery-promotion-strategy, adr-049-edge-object-storage-placement, adr-050-cross-context-command-center, adr-067-product-contract-and-agent-access]
created: "2026-10-18"
---

# ADR-073: Self-Service Resource Claims

## Status

Proposed, 2026-10-18. It is the output of an architecture session on kubelab#2449. Once accepted, it extends [ADR-067](adr-067-product-contract-and-agent-access.md) D2 (the product contract) and D5 (tenancy). It also fires the deferred decision in [ADR-038](adr-038-secret-delivery-paths.md) and scopes [ADR-014](adr-014-secrets-management-strategy.md)'s Phase 2. The amendment notes on those ADRs are added in the same PR once the decision is accepted, not before.

## Context

ADR-067 gives a product a contract, `kubelab.yaml`, covering its image, port, health path, hostnames, auth level and secret *names*. Anything else a product needs still takes a kubelab change and an operator step: a database, a volume and its backup, a route on another domain, an OIDC client, a bucket, a cache, a model endpoint. The product author's target is to declare what the product uses, and have the platform provision it. They should not open a kubelab PR or type a secret value. The intended consumer is a developer with no platform background, for example one who generated an application with an assistant and wants to keep building on real infrastructure.

What exists, measured on 2026-10-18:

- **Cluster Secrets are applied by hand.** `make apply-secrets` decrypts SOPS with the operator's key and runs `kubectl` (`toolkit/cli/infra.py:k8s_apply_secrets`). Argo CD decrypts nothing. `deploy-k8s` chains `apply-secrets`, `apply-middleware-secrets` and `provision-postgres-tenant`. Each is an operator step that a claimed resource would inherit.
- **A database tenant is provisioned imperatively.** `k8s_provision_postgres_tenant` runs `kubectl exec` as the superuser, with the password read from SOPS.
- **Backups are global.** One `pg_dumpall` cannot restore a single product's database.
- **DNS has no apply path in CI.** `infra/terraform/dns/records_kubelab.tf` creates one record per service from `services.json`, and `make tf-dns-apply` is run by hand. Terraform manages two zones. A third zone the operator holds is on Cloudflare but outside IaC (#2460).
- **TLS is ACME DNS-01 through Cloudflare**, with a `certResolver` per host. The in-cluster resolver uses the same Cloudflare token as Terraform (#2459).
- **No prod manifest pulls an image from the forge's registry.** The forge runs on an on-demand node (ADR-028). Private images built there already exist for products not yet in prod.
- **The existing Redis holds Authelia's sessions.**
- **The R2 credential minter already issues bucket-scoped tokens**, and it proves the scope by consequence: a token that can list another bucket is revoked (`tests/test_backup_node_credentials.py`).

An industry teardown of fourteen platforms with add-on or claim models, plus a component teardown of the gaps, is kept in the operator's research notes. The patterns this ADR adopts are named below where they are used.

## Decision Drivers

The full constraint table is kept in the operator's architecture notes. These bind here:

- **C1 GitOps only.** Every cluster change is a PR, and prod is promoted only after a human merge.
- **C2 No keys on agents.** No autonomous identity can read a SOPS key or a prod kubeconfig.
- **C4 One operator.** The design must be industry-defensible, not resume-driven.
- **C5 Single-tenant per client.** The blueprint must therefore run on an instance that is not kubelab.
- **C6 No client identity in public.**
- **C7 Declared once, derived everywhere**, with a test that fails on drift.
- **C11 No new recurring cost.**
- **C20 Data stays off the GCP data plane.**
- **C21 A product sets its own secret values** from its own repository, with no kubelab code change and no value typed by the operator.
- **C22 Every self-service write is attributable**, and can be read back afterwards.
- **C23 Derived state is reconciled by machinery.** No human runs `--apply` after a value changes.
- **C24 What prod pulls must be always-on.** An on-demand node is never a prod image source.
- **Consumer.** A developer with no platform background must be able to deploy with defaults. Every field beyond the minimum is optional.

## Considered Options

**Delivering a product's secrets into the cluster**

- **A. Sealed Secrets for product-owned values.** *Chosen.*
  - Operator secrets stay on SOPS with `apply-secrets`, unchanged.
  - Checked 2026-10-18:
    - `kubeseal --cert` seals offline with the public certificate alone.
    - The default scope is `strict`: the namespace and name are part of the ciphertext.
    - The controller image ships for arm64.
- **B. A SOPS decryption operator in each cluster.** *Rejected.* It keeps one at-rest format and maps naturally onto per-product age recipients. But it is a third-party controller from the same family as the KSOPS integration ADR-014 already rejected, and it is less defensible under C4. Reopen if Sealed Secrets stops being maintained.
- **C. The receiver runs `apply-secrets`.** *Rejected.* It breaks C2.
- **D. External Secrets Operator with a self-hosted vault.** *Rejected.* It adds two always-on components for value leases and rotation nobody needs yet. Reopen when credentials need leases or are rotated more than about twice a month.

**Where a generated credential is born**

- **E. The receiver generates it while rendering the PR.** *Chosen.* The receiver seals the value with the cluster's public certificate and commits two things: the `SealedSecret`, and the idempotent provider Job that consumes it.
- **F. A provider Job in the cluster generates it.** *Rejected.* The value never reaches git, so a rebuilt cluster has to reset every credential, and drift cannot be tested from the repository.

**Claim shape**

- **G. `resources: {name: {type, class?, params}}`, with an implementation table per instance.** *Chosen.* This is Score's `resources:` syntax and the matching-table pattern of orchestrator platforms, scoped to one instance.
- **H. One provider per type, with no class.** *Rejected.* It erases the seam between what is asked for and how it is provided, and that seam is what lets a client instance supply different implementations (C5).
- **I. Adopt Score whole.** *Not reopened.* ADR-067's trigger (Score v1 with route, secret and auth types) has not fired.
- **J. An in-cluster control plane (Crossplane, Kratix, Radius, Kubero).** *Rejected.* Each brings a CRD estate and an upgrade surface that one operator cannot carry (C4).
  - Kratix's flow (claim, stateless pipeline, a git state store, a GitOps agent that applies) is the one shape compatible with C1.
  - The receiver adopts that shape without the software.

**Routes**

- **K. A domain policy in the registry, with wildcard records opt-in per zone.** *Chosen.*
- **L. Records derived from the registry and applied by CI.** *Deferred.* It needs a Cloudflare credential in CI (C22). Reopen when a product needs a per-record setting that a wildcard cannot give.

**Image source for prod**

- **M. Prod pulls only from always-on registries. A promotion copies a forge-only image by digest to the instance's registry.** *Chosen.*
- **N. Prod pulls from the forge's registry.** *Rejected.* It breaks C24.
- **O. One SaaS registry for every product.** *Rejected.* The forge in use cannot push to it without one credential shared across products, which breaks C22.

**Agent and author surface**

- **P. Drop the planned MCP tool that writes a product's repository.** *Chosen.*
  - An agent working on a product already has git and file tools there.
  - A write adapter per forge would be pure cost.
  - Authors and agents get two things instead: the published JSON Schema, and `toolkit contract validate`.

## Decision

### D1. Two secret flows

- **Ingress** is a value the product supplies. It is write-only: the product seals it, and no platform API returns it.
- **Egress** is a value the platform generates, such as a DSN, a token or a host. The product's workload must be able to read it, so it lands in the product's namespace and is protected by namespace RBAC. Reads are audited (C22).

No platform in the teardown makes generated credentials unreadable to the workload. Write-only is a property of the API and of RBAC, never of the runtime.

### D2. Product secrets are decrypted in the cluster by Sealed Secrets

- **Product values and generated credentials become `SealedSecret` manifests in git.** The controller in each spoke decrypts them.
- **The hub never sees plaintext.** It applies ciphertext (C20).
- **Strict scope isolates products from each other without per-product keys.** A ciphertext moved to another product's namespace or name fails to decrypt.
- **The sealing key's master copy lives in SOPS** as an operator secret, applied by the bootstrap path. Automatic renewal is off, and rotation is a deliberate operation with a runbook. A rebuilt cluster therefore decrypts every existing `SealedSecret`.
- **Verification debt:** that the controller accepts an operator-supplied key is to be verified in the first implementation PR, before this ADR leaves `proposed`.
- **What stays on SOPS:** operator and platform secrets, and the Traefik Middleware path that ADR-038 explains cannot use indirection.
- **Forge-side secrets (CI tokens) are untouched.** The forge reconciler writes them through each forge's API, and they never pass through the cluster.

### D3. The `resources:` block and the instance table

- **The claim.** A product declares `resources: {name: {type, class?, params}}` in `kubelab.yaml`, where `class` is optional.
- **The instance table.** Each instance's registry maps `(type, class)` to an implementation. kubelab's implementations are its own choices, not part of the design: Cloudflare DNS, R2, the shared Postgres, Authelia, and the always-on registry.
- **Portability.** A client instance supplies its own table, which is how the blueprint stays portable under C5.

### D4. Outputs land in one Secret per product

- **One Secret.** Every claim writes its outputs into one `<product>-claims` Secret, using stable keys (`DATABASE_URL`, `REDIS_URL`, `S3_*` and so on).
- **Rendering.** Every workload of the product (web, worker, cron, migration) gets it through `envFrom`.
- **Aliases.** An optional `env:` map renames a key with `${resources.<name>.<key>}`, so an application keeps its own variable names.

### D5. Credentials are born at render time and survive re-renders

- **Render time.** The receiver generates the value in memory, seals it (D2) and commits it beside the provider Job that consumes it.
- **Re-renders.** One `SealedSecret` per credential keeps an existing credential: a re-render that finds the file leaves it alone.
- **Rotation.** Rotating a credential means replacing its file. The Job then re-applies it (for example with `ALTER ROLE`).

### D6. Providers are scoped Jobs, and removal retains

- **Providers.** A provider is a Kubernetes Job with its own ServiceAccount and a role scoped to its resource type. No provider uses a superuser path. The current `provision-postgres-tenant` is replaced, not wrapped.
- **Postgres roles.** A role created for a product carries `CONNECTION LIMIT` and `statement_timeout`.
- **Removing a claim detaches it.** The binding and the route go, and the data stays.
- **Destruction is its own change.** It is a separate, human-merged change that runs the type's delete Job after a verified backup. A database, a volume and a bucket are never dropped as a side effect of an edit to `kubelab.yaml`.

### D7. Image sources

- **Prod pulls only from an always-on registry.**
- **Images already on an always-on SaaS registry are pulled as they are.**
- **Images that exist only in an on-demand forge's registry are copied by digest** to the instance's registry at prod promotion (kubelab: a registry on the VPS). Staging keeps pulling from the forge.
- **The image source is declared in the registry, on the platform side.** It generalises the override that already exists for web. The product contract does not change. This corrects IDP-042's open question 7, which derived every image from one SaaS namespace.
- **Guard.** A committed test asserts that no prod manifest references an image on an on-demand host.
- **Trigger.** A free-tier pull limit becoming a constraint is the reopen trigger.

### D8. Routes on any domain the operator holds

- **The registry holds `domains: [{apex, reserved: [...], wildcard: bool}]`.**
- **A product claims `host:`.** The receiver refuses an apex that is not on the list, and a label reserved for that apex (`auth`, `api`, `www`, `status`, `mail` and the platform's own names). A mutation-proven test guards the check.
- **Wildcard records are opt-in per zone.** A zone whose edge serves Workers (ADR-049) keeps explicit records until checked.
- **Auth levels.** A product picks a level from ADR-067's fixed set; middlewares are never chosen freely.
- **Out of scope:** domains the operator does not hold, which would need HTTP-01 and CNAME onboarding.
- **Preconditions:** the zone map (#2460) and a zone-scoped ACME token (#2459).

### D9. Catalog v1

| Type | Implementation on kubelab | Origin |
|---|---|---|
| `registry` | D7 | demand |
| `forge-ci` | a per-forge plugin (write a secret, map repo to app, receive the webhook) | demand |
| `route` | D8 | demand |
| `postgres` | shared cluster, provider Job, one `pg_dump` per database to object storage | demand |
| `volume` | a PVC, with Litestream to object storage for SQLite and restic for other files | demand |
| `job` | a CronJob carrying the product's claims Secret | demand |
| `llm` | **outputs only** (endpoint, key, budget). The implementation is its own ADR (see below). | demand |
| `oidc` | an Authelia client per product, its secret born at render time | owner request |
| `object-storage` | a bucket per product with a bucket-scoped token, S3-generic interface | owner request |
| `redis` | one small instance per product namespace, never Authelia's | owner request |
| `review` | the PR reviewer as a hosted service (D12), one webhook receiver per forge, the model pool declared once | demand |

The demand counts came from the operator's product inventory. Types marked *owner request* did not meet the rule of three, and are recorded as the operator's call.

Deferred: SMTP, queues. n8n is not a resource: it is not multi-tenant, and the needs it was proposed for are CI plumbing.

### D10. Operational guarantees

**Required by v1:**

- **Restores are verified by machinery.** A CronJob restores each product's database or SQLite file into scratch, checks integrity and emits a metric. The alert fires when the metric goes stale.
- **Orphans are reported.** The drift test compares the registry with live state, and a purge runbook acts on the report.
- **Capacity is admitted, not discovered.** The receiver refuses a claim when the sum of the namespaces' quotas would exceed the node's allocatable capacity.
- **NetworkPolicy (#378) lands before the first claim is admitted.** It moves from ADR-067 D5's list to a dependency of this ADR.
- **There is a runbook for each operation:** restore, rotate, purge and add a domain.

**Triggered:**

- **A tier and an SLO per product, with generated burn-rate alerts.** The single prod node is declared as a single point of failure. Trigger: the first consumer who is not the operator.
- **Alert routing to a product's owner.** Trigger: the first team member.

### D11. Surfaces

- **For the product's author and the author's agent:** the JSON Schema, `toolkit contract validate` in the product's CI with errors that name the fix, and the read-only MCP of ADR-067 D6.
- **The receiver opens the kubelab PR.**
- **A portal is another read adapter over the same library (ADR-067 D1), and its writes stay PRs.** It follows the industry shape: a catalog of products with owners, a page per product that links into the existing tools (Argo CD, Grafana, logs, runbooks), and golden-path actions that open PRs. It never rebuilds those tools' interfaces. ADR-050 D1 places it in the console served by the Go API, which fires ADR-067's option-E trigger ("a consumer needs REST"). That question gets its own ADR, once the data this ADR defines exists.

### D12. Shared CI services are hosted once, never copied per repository

- **The problem, measured.** Today the reviewer's weighted model pool, its route script and its workflow are copied into each GitHub repository that uses them. The forge's reviewer is a separate webhook pod with one fixed model and no pool (#2295). Every new repository means another copy, and the copies drift.
- **The rule.** A capability every repository needs (the reviewer first; later the review attestation and the knowledge gate) runs as a platform service. A repository opts in, by a `review:` claim or by the receiver registering the forge webhook. It never carries the pool, the routing logic or the provider keys.
- **The shape** is the hosted-bot pattern the industry uses for review bots: an app installed per repository, configured centrally. It is not a reusable workflow, which still puts a caller file and the provider keys in every repository (C2, C22).
  - **One receiver per forge**, in webhook mode, on an always-on node (C24).
  - **The pool is read from one SSOT** and drawn per request.
  - **The publish guard** reports a run that published nothing as a failure, not as silence (#1957).
- **Per-forge adapter.** The forge plugin of `forge-ci` registers the webhook and maps the repository. Whether a forge's adapter can set the model per request, rather than per process, is checked in the first implementation PR.
- **Precondition for multi-forge.** The review attestation must read the hosted reviewer's comments on every forge it judges.

## Consequences

**Positive**

- A product gets a database, a volume, a route, an identity client, a bucket and a cache from its own repository, with no kubelab PR written by hand and no value typed by the operator.
- The three manual steps of `deploy-k8s` stop being in the path of a claimed resource.
- The blueprint runs on another instance by swapping the implementation table: a client brings its own forge, DNS, storage and registry.
- Every pattern adopted has a named industry precedent, so the design can be explained without inventing vocabulary.

**Negative**

- Two at-rest secret formats coexist: SOPS for operator secrets, Sealed Secrets for product secrets. The boundary has to be stated in the secrets catalog and tested.
- The sealing key becomes a disaster-recovery dependency. Its copy in SOPS and its rotation runbook are now load-bearing.
- A shared Postgres and a single prod node remain shared failure domains. D6 and D10 bound them; they do not remove them.
- The receiver grows: it generates and seals credentials, validates domains and admits capacity. Its tests become the platform's guard.

**Neutral**

- ADR-067 D5's per-product SOPS recipient (#889) no longer serves delivery into the cluster. It still serves the files in a private tenant repository (ADR-067 D4).

## Amendments to other ADRs (applied on acceptance)

- **ADR-067:**
  - D2 gains the `resources:` block, the optional `env:` map and `host:` per domain policy.
  - D5's NetworkPolicy becomes a precondition of the first claim.
  - D5's per-product SOPS recipient is scoped to the tenant repository.
- **ADR-038:** the trigger it deferred on is fired. "A product sets its own secret values and the platform applies them with no operator step" replaces the dead Image Updater condition. This closes #1613.
- **ADR-014:** Phase 2 (Sealed Secrets) is adopted for product-owned secrets only. Operator secrets stay on SOPS.
- **IDP-042:** open question 7 is corrected by D7. This is a spec note, not an ADR amendment.

Two ADRs are left unamended. The reasons are recorded here so the silence is not read as an oversight:

- **ADR-049 D5 and ADR-029** make the Go API the gateway. Choosing what implements `llm` (a proxy with virtual keys, or a module in the Go API, which has no authentication today) reopens that, so it gets its own ADR. This ADR fixes only the type's outputs.
- **ADR-050** keeps D1. The portal question in D11 is deferred to its own ADR, not decided here.

## Reopen triggers

- **Sealed Secrets** stops being maintained, or a SOPS operator becomes the Argo CD community default: revisit option B.
- **Leases or frequent rotation:** credentials need leases, or are rotated more than about twice a month. Revisit option D.
- **A per-record DNS need** that a wildcard cannot give: revisit option L.
- **Postgres:** more than about five product databases, a noisy-neighbour incident, or a hard per-product point-in-time recovery requirement. Move to an operator-managed cluster.
- **A free-tier registry limit** constrains prod pulls: revisit D7.
- **Hosting client prod:** the operator decides to offer it. That reopens ADR-042 D4, as ADR-067 already records.

## Implementation (children of #2449)

1. **Preconditions:**
   - the zone map (#2460);
   - the zone-scoped ACME token (#2459);
   - NetworkPolicy (#378);
   - the Sealed Secrets controller, with its key's master copy in SOPS and the operator-supplied key verified;
   - the always-on image guard test.
2. **Contract:** the `resources:` schema, the instance implementation table, `toolkit contract validate`, and the domain policy with its reserved-label test.
3. **Receiver:** credential generation and sealing, the claims Secret, capacity admission, the orphan report.
4. **Providers, one PR each:** `postgres` (replacing `provision-postgres-tenant`, with per-database dumps), `route`, `volume`, `job`, `oidc`, `object-storage`, `redis`, the per-forge `forge-ci` plugins, the `registry` promotion copy, and `review` (#2295, absorbing #1957 and #1963).
5. **Operations:** restore verification, the runbooks, and the triggered SLO and alert-routing work.
6. **Separate ADRs:** the `llm` implementation, and the portal's serving path.

## References

- kubelab#2449, #2459, #2460, #378, #889, #1613, #1931
- Sealed Secrets README (scope, offline sealing, key renewal and backup); Score specification (`resources:`); Kratix promises and state stores
