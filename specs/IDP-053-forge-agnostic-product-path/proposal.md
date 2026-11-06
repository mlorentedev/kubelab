---
id: "IDP-053-forge-agnostic-product-path"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-11-03"
issue: "mlorentedev/kubelab#2612"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
owner: manu
wip_override: "spec-only change requested by the owner's lead (forge-agnostic product path); no implementation starts from it until slots free; the 14 active specs belong to other lanes (14 active, limit 10, 2026-11-03)"
---

# IDP-053: a product path that does not care which forge or registry a product lives on

## Why

<!-- from issue #2612: IDP-053: run the product path for products on the Gitea forge through a forge adapter -->

A product hands kubelab an immutable `sha-<short>` image, a `repository_dispatch` carrying
only `tag`, and a `kubelab.yaml` contract. None of the three names a forge or a registry, yet
the code that consumes them is bound to GitHub and Docker Hub. Today a product whose repository
is on the Gitea forge and whose image is private cannot reach staging by any path:

- the receiver refuses `forge != github` (`product-image-receiver.yml`) and runs on hosted
  runners that cannot reach Gitea;
- every image is derived as `<global registry>/<name>` (`product_registry.derived_image`,
  `generator_k8s._build_context`, `promotion._resolve_image`);
- nothing renders an `imagePullSecret`, so a private image is unpullable;
- the contract requires `hostnames.prod`, which forces a public DNS record and a prod
  commitment before a product has a beta;
- `registry.tag_exists`, `tag_digest` and `product_release` read Docker Hub anonymously and
  GitHub only.

Two products need this: `imagesensortool` (Gitea repository, private image at
`gitea.kubelab.live/personal/imagesensortool`, `sha-<12hex>`, port 8080, `/healthz`), which
wants a staging beta, and `resume` (#2366, `ghcr.io/mlorentedev/resume`), which has neither a
branch nor a spec here. The owner's direction (2026-11-04) is to make the path forge-agnostic
and registry-agnostic now so every later product benefits, and `imagesensortool` may be named
in this repository.

This spec implements ADR-073 D7's clause "the image source is declared in the registry, on the
platform side" and the owner rulings on #2449: Q3 and its amendment (platform-held pull
credential, private images on GHCR) and Q4(A) (IDP-053 covers the staging receiver and the
forge-neutral prod `release-contract`). ADR-073 is still `proposed`; this spec does not wait
for it and does not implement the rest of D7 (the prod copy of forge-only images by digest).

## What

Two tracks. Track 1 gates a staging beta of `imagesensortool`; Track 2 runs in parallel,
touches disjoint files, and gates nothing in Track 1.

**Track 1: the beta path (S1 to S4)**

- **S1, a per-product image source.** `products.yaml` entries gain `image_registry` (the
  *source* registry with its owner path, e.g. `gitea.kubelab.live/personal`) and `private`.
  The registry entry is the only place the host lives: `derived_image`, the generator,
  `promote`, `tag_exists` and the prune janitor read it from there. `web` keeps the global
  default and its generated overlays do not change by one byte.
- **S2, the pull credential.** A private entry names its credential (`pull_credential`: a
  username and the catalog key of the token). `apply-secrets` renders one
  `kubernetes.io/dockerconfigjson` Secret per registry host, and the Deployment template emits
  `imagePullSecrets` for private entries only. `imagesensortool` names a Gitea
  `read:package` token; `resume` will name `ghcr.pull_token` (already catalogued by #3036).
- **S3, staging-only products.** `hostnames.prod` becomes optional in the contract schema.
  The registry's `events.prod` is the declaration of a prod lane: without it a product has no
  prod snapshot and no prod values block, `promote --env prod` refuses it, and the DNS, tile
  and registry tests skip prod for it. The onboarding PR for `imagesensortool` (registry
  entry, snapshot, staging values block, platform tile, e2e expectation, staging DNS zone) is
  its own slice. Before it, **S3c makes a product's staging zone a declaration**: the hostname
  convention (owner ruling, 2026-11-05) is checked at render time, and the per-zone hairpin
  block is generated from `networking.staging_zones` instead of hand-written, so the next
  product on its own domain adds one line, not an edge edit.
- **S4, the first deploy** by a hand-run `toolkit deployment promote` and a deploy PR, with the
  runbook updated.

**Track 2: the forge-agnostic receiver (S5 to S9)**

- **S5, a forge adapter** in the toolkit: one interface (resolve a short sha, check a commit
  is on the default branch, read a file at a ref, resolve a tag to a commit), a GitHub
  implementation extracted from the `gh api` calls of the receiver, `product_ready` and
  `product_release`, and a Gitea implementation on `gitea_client.py` with a read-only Gitea
  token catalogued (not the admin token).
- **S6, the receiver** drops the `forge != github` refusal, moves its forge logic into toolkit
  commands that go through the adapter, and picks `runs-on` per forge through a `route` job.
- **S7, the trigger** from Gitea CI to the receiver. D1 is deferred to S7 by the owner: the
  beta needs no trigger, and the evidence for each option is below.
- **S8, the prod half** (owner ruling #2449 Q4(A)): an authenticated, forge-neutral
  `release-contract` and digest read, closing #2627 AC2 and AC1.
- **S9, later:** `deploy_shape` provenance through the adapter, after DELIVERY-004 (#3063)
  settles. No earlier slice touches `deploy_shape.py`. #2612's own acceptance (`deploy-shape`
  judges a Gitea product's PR `mechanical`, and no forge names in `deploy_shape.py`) is met
  only by S9, so #2612 stays open until S9 lands, and the no-forge-names test allow-lists
  `deploy_shape.py` until then.

### Slices at a glance

Full per-slice detail (files, tests, commands, size, merge owner) is in `tasks.md`.

| Slice | Subject | Depends on | Merges | Size (prod LOC, est.) |
|---|---|---|---|---|
| S1a | registry fields, `derived_image`, prune exclusion | none | agent, under the merge grant | ~90 |
| S1b | generator, `promote`, `tag_exists`, prod-lane guard | S1a | agent, under the merge grant | ~130 |
| S2a | dockerconfigjson Secret through `apply-secrets` | S1a | owner (secret delivery path) | ~140 |
| S2b | `imagePullSecrets` in the Deployment template | S1b, S2a | owner (`infra/`) | ~50 |
| S2c | Gitea pull-token catalog entry, mint, `registry-check` | none | owner (`infra/`, mint) | ~140 |
| S3a | optional `hostnames.prod`, staging-only guards | none | agent, under the merge grant | ~90 |
| S3c | hostname convention check, hairpin generated from `staging_zones`, ADR-067 amendment | S3a | owner (`infra/`) | ~120 |
| S3b | onboarding PR for `imagesensortool` | S1, S2, S3a, S3c, product `kubelab.yaml` | owner (`infra/`) | ~70 + data |
| S4 | first deploy by hand, runbook | S3b merged, image published | owner | ~80 (doc) |
| S5a | forge adapter, GitHub implementation, `product resolve` | none | agent, under the merge grant | ~200 |
| S5b | Gitea implementation | S5a, API note | agent, under the merge grant | ~170 |
| S5c | read-only Gitea token catalog and mint | none (sequence after S2c) | owner (`infra/`, mint) | ~100 |
| S6a | receiver logic as toolkit commands | S5a | agent, under the merge grant | ~150 |
| S6b | receiver workflow: `route` job, per-forge runner | S6a, S5b, S5c | owner (`.github/workflows/`) | ~120 |
| S7 | trigger | D1 | owner | per option |
| S8 | prod half | S5b, S1b | agent; the credential is owner | ~200 |
| S9 | `deploy_shape` through the adapter | S5b, #3063 settled | owner (judge code) | ~80 |

"Under the merge grant" means the PR touches neither `infra/` nor `.github/workflows/` nor a
secret (ADR-073 D13). Sizes are estimates of production LOC; tests, snapshots and generated
files are excluded. A slice that lands over 300 splits before review.

### Facts the design rests on (read from `origin/master` while writing)

- `Product` (`product_registry.py`) has `forge`, `repository`, `receiver`, `events`,
  `image_name` and is `extra="forbid"`; `derived_image` returns
  `<platform_registry()>/<image_name or app>` and `platform_registry()` is `common.yaml`'s
  `registry: docker.io/mlorentedev`.
- `generator_k8s._build_context` and `promotion._resolve_image` read the global `REGISTRY`, not
  the product. `registry.image_repositories` (the prune janitor, `ci-cleanup.yml`) does
  `image.removeprefix(platform_registry() + "/")` and raises on a name that still contains `/`,
  so **the first product on another registry breaks `toolkit registry prune`** unless S1a
  excludes it.
- `registry.tag_exists` returns `None` ("skip") for any host that is not `docker.io/`;
  `tag_digest` likewise. `promote` proceeds with a warning on `None`.
- All products share namespace `kubelab` (`namespace = "kubelab"`); ADR-067 D5 per-product
  namespaces are not built. A pull Secret is therefore one per registry host, not per product.
- `_render_secret_manifest` hardcodes `type: Opaque`, and the secret definitions are a static
  list.
- Every Gitea machine token here is `ROTATABLE_TOKENS` + an Ansible mint task gated on the SOPS
  key being absent + a grant in `common.yaml` `token_scopes` pinned by a test + a
  revoke-then-unset rotation; `issue_reader` (CONSOLE-004) is the latest and the template.
  `r2-documents-token` is a Cloudflare API mint and does not transfer (decision D2).
- `personal/imagesensortool` already has a registry *push* credential
  (`...actions_secrets.personal.imagesensortool.registry_user` / `registry_token`,
  `forge_actions`). No pull credential exists.
- Anonymous probes of `https://gitea.kubelab.live` while writing this spec answered `401` for
  `/v2/`, for `/v2/token?...scope=repository:personal/imagesensortool:pull` and for
  `/v2/personal/imagesensortool/tags/list`, and `403` for `/api/v1/orgs/personal`. The instance
  refuses anonymous reads, so the cluster needs a credential whatever the package's visibility
  (`personal/imagesensortool` is declared `private: false` in `common.yaml`).
- The receiver's `resolve` job mixes the registry lookup with the `gh api` calls; to choose
  `runs-on` per forge it needs a first job that reads `products.yaml` and nothing else.
- `product_ready.py:58` and `product_release.py:52` also refuse `forge != github`, and
  `product_release._release_commit` resolves a **git tag** (`commits/v<version>`), which the
  issue's three-method interface cannot do. The adapter needs the fourth method.
- `deploy_shape._provenance` and the receiver's resolve step make the same three calls
  (`commits/<short>`, `repos/<r>`, `compare/<default>...<sha>`); `deploy_shape.evaluate` answers
  `not-mechanical` for any forge but `github`.
- Tests that go red when a product has no prod hostname or lives on another registry (found by
  adding such a fixture on a scratch copy of the tree; reverted): `test_product_contract_schema`
  (committed schema), `test_product_contract` (`hostname-prod-absent` case),
  `test_product_registry` (`..._deploys_in_each_cluster_env[staging|prod]`,
  `..._derives_the_image_its_values_deploy`), `test_platform_tiles_cover_registry`
  (a tile is required in **both** envs and `hostnames[env]` raises `KeyError`),
  `test_e2e_expectations_cover_registry`, `test_registry_prune`
  (`..._three_kubelab_repositories`). `test_dns_contract_hostnames` is already safe
  (`host and host not in records`); S3a pins that with a case.

## Decisions

Each one is stated with the evidence and a recommendation. The owner ruled D1 and D2 on
2026-11-05 (below each); D3 to D7 are decided in this spec and reversible; D8 is the owner's
convention and is not reversible by this spec.

### D1 (decided 2026-11-05, owner: deferred to S7): how an image published from Gitea CI reaches the receiver (S7)

**Ruling** (under the owner's standing instruction of 2026-11-05 to apply the advisor's
recommendation). No trigger is built for the beta. S4 is a hand-run `promote`, so until S7 each new
image reaches staging by the same hand-run step, and no dispatch token is minted. The choice
between (a) and (b) is made when S7 starts, with Track 2's adapter and receiver in place and
the minimum-permission spike done; the recommendation below stands as the starting point.

The receiver is a GitHub `repository_dispatch` consumer. Gitea Actions cannot call it without
a GitHub credential somewhere. Evidence for each option:

| | (a) GitHub token in the product's Gitea CI | (b) Bridge from the Go API's forge webhooks (#3068) |
|---|---|---|
| Credential holder | the product's repository, as a forge Actions secret | the Go API pod |
| Existing machinery | `SecretSpec.forge_actions=` delivers a catalogued value to a repository; `GHCR_TOKEN` (#3036) already travels this way | `forge.Receiver` verifies `X-Gitea-Signature` and `X-GitHub-Signature-256` and stores any event type |
| New always-on code | none | an outbound GitHub client and a registry-to-app map in the Go API |
| Blast radius | A token able to create `repository_dispatch` on `mlorentedev/kubelab`. GitHub's REST docs require `Contents: write` (fine-grained) or `repo` (classic), which can also create branches and tags on a repository whose `master` is protected. The receiver cannot be steered by the payload (app from event type, tag shape, commit on the default branch), so a leaked token mostly buys re-promotion of an already-merged commit plus branch and tag noise. **Verify before choosing:** the minimum permission, by dispatching with a token that has less | The same token, inside the cluster rather than in a product's CI; no product repository holds a GitHub credential |
| Fit with decisions | ADR-053 already says "PAT-scoped cross-repo dispatch"; ADR-073 D9 lists a `forge-ci` claim type whose per-forge plugin would later deliver exactly this secret, so (a) is the interim form of the end state | ADR-067 option E rejected putting control-plane logic in the Go API process (a fault in the newsletter endpoints reaching the control plane); ADR-066 A2 limits what the console stores to declared sources |
| Facts from #3068 | | The handler is generic over event type but stores a delivery **only** when its repository is in `infra.forge.sources` (the console's reconcile sources, not products), answers 204 otherwise, and has **no outbound code**. **No Gitea webhook is registered yet**, so the Go API receives no Gitea events today. A `push` event fires before the image exists; a trigger needs Gitea's `package` event (or a completed `workflow_run`), whose payload may carry no repository for an unlinked package, in which case `declares()` drops it. **Unmeasured** |

(c) Other candidates, considered and set aside: a scheduled poller on the self-hosted runner
(rejected by ADR-053: a pull loop, and the runner is off when the homelab is off); a Gitea
webhook that calls `api.github.com/.../dispatches` directly (not possible: Gitea posts its own
body, GitHub requires `event_type`); a Gitea-side receiver (the issue's option B, #1928's
private tenant path, rejected for now by the operator); `workflow_dispatch` instead of
`repository_dispatch` (needs `Actions: write`, which can also start `promote-prod.yml`, a
wider grant); n8n (rejected by ADR-053).

**Recommendation:** (a) for the first Gitea product, because it adds no component, reuses the
`forge_actions` delivery path and keeps the credential out of the always-on API. Document it as
interim, replaced by the `forge-ci` provider when ADR-073 is accepted. Reopen (b) if a second
Gitea product arrives or the owner does not want a GitHub credential in product CI. S7 is not
on the beta's critical path: S4 is a hand-run promote.

### D2 (decided 2026-11-05, owner: the reviewer account): which Gitea account holds the pull token and the repo reader token (S2c, S5c)

**Ruling** (owner, direct). The recommendation below, as written, including the consequence
check as S2c's first task.

Note (spec, not the owner's): the agents' forge account (AUTH-022, #3085) is not a fallback if
the check fails. It is a writer identity, and a pull credential on it would join deploy and
authorship. A failed check still goes back to the architect.

Recommendation: two **new tokens on the reviewer account** (`registry_pull`: `read:package`;
`repo_reader`: `read:repository`), each pinned by equality, one token per consumer. That is the
repository's habit (reviewer, review_notice, issue_reader). The account already sits in each
organization's read team, so it is the cheapest identity, but whether a `read:package` token on
it reaches `personal/imagesensortool` depends on the team's units and the package owner's
visibility and is **not established**. S2c's first task is that consequence check (AC4). If it
fails, a new machine identity is an identity-model question (ADR-062, ADR-065) and goes back
to the architect; the spec does not settle it.

The pull token's SOPS file is also open: Gitea tokens live in `prod.enc.yaml`
(`envs=("prod",)`), but the staging cluster applies staging plus common. Recommendation:
`common.enc.yaml`, audited for staging, like `ghcr.pull_token`.

### D8 (decided 2026-11-05, owner): one hostname convention for every hosted product

- **Staging:** `staging.<product domain>`, reachable on the VPN only (Headscale split DNS);
  testers join the mesh.
- **Prod:** `<product domain>`, public, its zone in `infra/terraform/dns/zones.json`.
- **A product with no domain yet:** `<product>.staging.kubelab.live`, under the existing
  wildcard, as the exception.
- `web` already follows it (`staging.mlorente.dev`, `mlorente.dev`); nothing migrates.

The rule binds today's contract, so it is written as an amendment to ADR-067 D2 (accepted),
not only in ADR-073 D8 (proposed), which replaces it with the domain registry on acceptance.
It is enforced, not remembered: S3c's render-time check refuses a `hostnames.staging` that
breaks it. Considered: the platform wildcard for every product, which needs no zone work but
leaves `web` the odd one out and the staging name unrelated to prod's. Consequence, raised to
the owner before the ruling: issuing a certificate for `staging.<domain>` writes that name to
the public Certificate Transparency logs before launch.

Placing the work in this spec as S3c, rather than a spec of its own, was ruled under the
owner's standing instruction to apply the advisor's recommendation (2026-11-05): S3b depends
on it, and a new spec would add to a WIP count already over its limit.

For `imagesensortool` this gives `staging.imagesensortool.com`, so risk 7 applies to it.

### D3 (decided): `tag_exists` for non-`docker.io` registries

Tri-state, as today, with a real transport: an anonymous OCI
`HEAD /v2/<name>/manifests/<tag>` answers `True` (200) or `False` (404); `401`/`403` (private)
or an unreachable host answers `None` with a warning that names the registry and says
"unverified". `promote` keeps proceeding on `None`. Reason: the receiver on a hosted runner has
no SOPS key and cannot hold a registry credential (ADR-067 C2), and the Gitea forge is
on-demand. The authenticated read is S8's (it is #2627 AC2's).

### D4 (decided): the registry entry, not the values, holds the host; `CONTRACT_KEYS` does not change

The brief's list included `CONTRACT_KEYS`. It stays as is, on purpose: `image_name` is already
`c.image.rsplit("/", 1)[1]`, correct for any host, and an `image_registry` values key would be
a second copy of a fact the registry owns (ADR-067 C7). A test pins
`"image_registry" not in CONTRACT_KEYS` and that the generated image equals
`<entry registry>/<name>:<tag>`. The contract's `image` is still pinned to `derived_image`, so
a product cannot point itself at another registry.

### D5 (decided, my addition): `events.prod` is the declaration of a prod lane

A product with no `events.prod` has no prod lane: `promote --env prod` refuses it, and a
committed test fails if it has a prod snapshot or a prod values block. This answers the hazard
that a prod block without `version` falls back to `:latest` with a refusal at the command, not
only a convention. `hostnames.prod` optional in the schema is the contract-side half.
`imagesensortool` declares no `events.prod`.

### D6 (decided): the pull Secret is per registry host, one credential per host

Everything shares namespace `kubelab`, so the Secret is named from the host
(`pull-<host-slug>`), and the registry validator refuses two private entries that name
different credentials for one host. `private: true` requires an explicit `image_registry`
(Docker Hub private is not supported; #2449 Q3 moved private images to GHCR) and a
`pull_credential`. The dockerconfigjson is a rendered literal, never stored in SOPS: only the
token is.

### D7 (decided): `image_registry` is the source registry; the prod copy is instance config

Per ADR-073 D7, prod pulls only from always-on registries, and forge-only images are copied by
digest at promotion. `image_registry` names the **source** (where CI pushed it). The copy
target is the instance's registry, not per product, and is not built here. A committed test
(S1b) fails if any prod overlay image points at the forge's host. Consequence: for
`imagesensortool` prod stays closed until the copy exists; for `resume` (GHCR, always on) it
does not.

## Out of scope

- The OIDC contract path (#2573), `resume`'s volume/job/group claims (#2449 Q1 and Q2), the
  claims engine and Sealed Secrets (ADR-073 D1 to D6).
- The ADR-073 D7 prod copy of forge-only images by digest, and prod for `imagesensortool`.
- Private tenant products (#1928) and the merge step (DELIVERY-004).
- Per-product namespaces (ADR-067 D5). Pull Secrets are per host until they land.
- Gitea package retention: the prune janitor is Docker Hub only and excluded products are not
  pruned. File a ticket when the first Gitea image set grows.
- `deploy_shape.py` in any slice before S9. The DELIVERY-004 lane (#3063) owns that file until
  it settles.
- Writing the product-side files (`kubelab.yaml`, the Gitea CI workflow) in
  `personal/imagesensortool`; S3b lists what that repository must commit first.

## Risks / open questions

Must be resolved before the named slice starts; none blocks writing the others.

1. **Before S2c's mint:** can a `read:package` token on the reviewer account pull
   `personal/imagesensortool`? (D2.)
2. **Before S5b:** the Gitea 1.27.3 API behaviour the adapter relies on is measured, not
   assumed, against a local Gitea of that version (as TOOL-080 did with `scope-lab.py`):
   short-sha resolution and whether unknown and ambiguous are told apart;
   `compare/{default}...{sha}` (reachability from the default branch); raw file at a commit
   via `raw/{path}?ref=`; tag to commit including annotated tags. S5b's first task is a
   verification note recording the answers; the implementation follows them.
3. **Before S6b go-live:** #2611 (IDP-051). `imagesensortool` is the second `receiver: generic`
   product, and two generic products force-push deploy branches that rewrite the same
   `values/staging.yaml`. #2611 has an acceptance test but no decided shape. S4 (a hand-run
   promote) does not touch the receiver's force-push, so **#2611 does not block S1 to S4**; it
   blocks the first generic receipt of `imagesensortool`. The registry entry declares
   `receiver: generic` from S3b (`Product` requires `receiver` with `repository`), and it stays
   dormant by construction: the receiver refuses `forge != github` until S6b, and no trigger
   exists until S7. **S6b is held, not merged dormant, until #2611 settles**: once S6b drops the
   refusal, a manual `workflow_dispatch` reaches the generic receipt path with no trigger at
   all, so dormancy would no longer hold by construction. AC9's dry run is therefore S6b's own
   gate, run before it merges.
4. **Self-hosted runner exposure (S6b).** A dispatch-triggered `promote` job holding
   `RELEASE_PLEASE_TOKEN` would run on `kubelab-bee`, a runner with the Docker socket mounted
   (ADR-030). `repository_dispatch` runs master's code only and the contract is parsed by the
   toolkit's safe loader, but a Gitea product's content now reaches that host. S6b keeps the
   write step (`promote`) on a hosted runner and moves only the forge reads (`resolve`) to the
   self-hosted one; the contract travels as an artifact. This is the smallest exposure that
   works and what the tasks assume.
5. **The homelab is on demand (ADR-028).** A Gitea product's receipt waits for `kubelab-bee`,
   and a queued self-hosted job on GitHub fails after 24 hours. Accepted and documented in the
   runbook (S4, S6b), as the issue states.
6. **Unknown product facts:** the auth level for the beta and whether `/healthz` answers a
   kubelet probe. They come from the product's `kubelab.yaml`, not from this spec; S3b is
   blocked until that file exists. The staging hostname is no longer open: D8 gives
   `staging.imagesensortool.com` (`imagesensortool.com` is in `zones.json` with no records),
   so risk 7 applies.
7. **Staging DNS and TLS for a new zone, only when the hostname is outside
   `staging.kubelab.live`.** `networking.staging_zones` (`common.yaml`) feeds
   Headscale split DNS, the RPi4 CoreDNS and Pi-hole; the hairpin block in
   `coredns-custom.yaml` is hand-written per staging zone until S3c generates it. A new staging
   zone needs a provision run on the VPS and the RPi4 (not verifiable from a diff), and an ACME
   DNS-01 certificate whose token must cover `imagesensortool.com` (`toolkit secrets
   acme-token-scope` asks Cloudflare). That token (`kubelab-acme-dns`, #2459) is scoped to named
   zones and is not managed by Terraform: #2459 is closed, and its closing comment records the
   in-cluster Secret on both clusters as token `cee3a546` (`kubelab-acme-dns`, not Terraform's
   `dde8b6cb`), answering 403 on zone settings for `kubelab.live` and `mlorente.dev`
   (2026-11-02). S3b re-runs `acme-token-scope` before widening it. Widening is an owner step in Cloudflare per new
   domain; deriving its zones from `zones.json` is a separate ticket, not this spec.

## Acceptance criteria

Each criterion names the command that settles it. Properties of a deployed machine are marked
**(deployed)**; no diff settles them, and their commands run after the named operation and are
recorded in `verification.md`. Test files marked (new) are created by the slice.

- [ ] **AC1 (S1a).** A registry entry may declare `image_registry` and `private`; `derived_image`
  honours the first; a private entry without `image_registry` or `pull_credential` is refused;
  `toolkit registry prune` skips a product whose registry is not Docker Hub and the committed
  set is unchanged.
  `.venv/bin/python -m pytest -q tests/test_product_registry.py tests/test_registry_prune.py`
- [ ] **AC2 (S1b).** The generated overlays and `promote` use the entry's registry; the committed
  overlays are byte-identical for `web`; `promote --env prod` refuses a product with no
  `events.prod`; `tag_exists` is tri-state as in D3; no prod overlay image points at the
  forge's host.
  `make validate-sync ENV=staging && make validate-sync ENV=prod` and
  `.venv/bin/python -m pytest -q tests/test_promotion.py tests/test_prod_images_always_on.py` (new)
- [ ] **AC3 (S2a, S2b).** A private entry yields a `kubernetes.io/dockerconfigjson` Secret
  `pull-<host-slug>` from `apply-secrets --dry-run`, and `imagePullSecrets` only on that
  product's Deployment; `web`'s manifests are byte-identical; the credential never appears in
  an argv or a log line.
  `.venv/bin/python -m pytest -q tests/test_image_pull_secret.py tests/test_k8s_secrets_apply.py`
- [ ] **AC4 (S2c).** The pull token is catalogued, pinned by equality to `read:package`, minted
  once (gated on the SOPS key being absent) and rotatable.
  `.venv/bin/python -m pytest -q tests/test_gitea_registry_pull_token.py tests/test_gitea_token_rotation_registry.py tests/test_gitea_token_scopes.py`.
  **(deployed)** after the owner's mint: `toolkit secrets audit --env staging` counts the key;
  `toolkit services gitea registry-check --app imagesensortool` exits 0 by pulling a manifest
  with the token; and `toolkit services gitea registry-check --app imagesensortool --package
  <owner>/<package outside the token's reach> --expect-denied` exits 0 only when the registry
  answers 401 or 403 for that package (any other status, an empty `--package`, or a pull that
  succeeds exits non-zero). Both runs are recorded.
- [ ] **AC5 (S3a).** A contract with no `hostnames.prod` validates; the committed JSON Schema
  equals the model; `product render --env prod` refuses it; a product with no `events.prod` has
  no prod snapshot and no prod values block; the DNS, tile and registry tests skip prod for
  it.
  `.venv/bin/python -m pytest -q tests/test_product_contract.py tests/test_product_contract_schema.py tests/test_product_contract_drift.py tests/test_product_contract_guards.py tests/test_dns_contract_hostnames.py tests/test_platform_tiles_cover_registry.py tests/test_e2e_expectations_cover_registry.py tests/test_product_registry.py`
- [ ] **AC13 (S3c).** `product render` accepts a `hostnames.staging` only if it is exactly a
  zone in `networking.staging_zones` (other than `staging.kubelab.live`) or a single label
  under `staging.kubelab.live`; when `hostnames.prod` is declared, `hostnames.staging` must
  also equal `staging.` + `hostnames.prod`. Anything else is refused with an ERROR / WHY / FIX
  naming D8 and, for a missing zone, the `staging_zones` line to add. `web` passes, and
  staging-only `staging.imagesensortool.com` passes once its zone is listed.
  The staging server blocks of `coredns-custom.yaml` are rendered from
  `networking.staging_zones`, byte-identical to today's for the current two zones, and a third
  zone in the list yields a third block. ADR-067 carries the D8 amendment.
  `.venv/bin/python -m pytest -q tests/test_product_staging_hostname.py tests/test_coredns_hairpin_zones.py tests/test_coredns_hairpin_answer.py` (the first two new)
- [ ] **AC6 (S3b).** The onboarding PR leaves the tree green:
  `make test`, `make validate-sync ENV=staging`, and
  `toolkit product render --contract infra/config/products/contracts/imagesensortool.yaml --env staging --check`
  exits 0.
- [ ] **AC7 (S4) (deployed).** `imagesensortool` runs on staging from the Gitea registry:
  `kubectl -n kubelab get deploy imagesensortool` shows the pinned `sha-<12hex>` ready, its Pod
  has no `ImagePullBackOff`, and
  `curl -sS -o /dev/null -w '%{http_code}' https://<staging host>/healthz` answers 200 from a
  tailnet host. The deploy PR's number is recorded.
- [ ] **AC8 (S5).** One interface with a GitHub and a Gitea implementation; no module outside
  `forge_adapter.py` compares a registry entry's `forge` with a forge name (a test scans
  `deploy_shape.py` (until S9, by allow-list), `product_ready.py`, `product_release.py`,
  `cli/product.py` and the receiver workflow text). The Gitea implementation uses a token that
  holds `read:repository` and nothing else.
  `.venv/bin/python -m pytest -q tests/test_forge_adapter.py tests/test_no_forge_names_outside_adapter.py tests/test_gitea_repo_reader_token.py` (all new)
- [ ] **AC9 (S6).** The receiver has a `route` job that selects `runs-on` per forge; the
  `forge != github` refusal is gone; a GitHub product's jobs run on the same runners as today;
  all forge reads go through `toolkit product resolve` and `toolkit product fetch-contract`.
  `.venv/bin/python -m pytest -q tests/test_product_image_receiver_workflow.py tests/test_receiver_pr_step.py && actionlint`.
  **(deployed)** a `workflow_dispatch` dry run for the Gitea product succeeds on the
  self-hosted runner and writes nothing; it is S6b's merge gate, run after #2611 settles.
- [ ] **AC10 (S7).** The chosen D1 option is recorded on #2612 and in `docs/runbooks/cicd.md`
  under a heading `Gitea product trigger (IDP-053 D1)`, whose section names the option, the
  credential's catalog key and the command or CI step that fires it.
  `.venv/bin/python -m pytest -q tests/test_runbook_gitea_trigger.py` (new): the heading exists,
  and its section names a catalog key present in `secrets_manager.py` and a firing step.
- [ ] **AC11 (S8).** `toolkit product release-contract` works for a non-GitHub forge; an
  unsupported or private registry is refused with an ERROR / WHY / FIX naming the registry
  (#2627 AC2); `sha-` tags of 7 and of 10 hex digits are both proven, so a check that only
  accepts 7 fails (#2627 AC1).
  `.venv/bin/python -m pytest -q tests/test_product_release.py tests/test_registry_digest.py` (the second is new)
- [ ] **AC12 (S9).** `deploy-shape` answers `mechanical` for a Gitea product's deploy PR with
  provenance proven against Gitea.
  `.venv/bin/python -m pytest -q tests/test_deploy_shape.py tests/test_deploy_shape_widening.py`

Each new test that guards a boundary is mutation-checked with
`make mutate FILE=<module> TEST=<test>`; the slice PR body quotes the output.

## What cannot be verified from a diff

| Property | Command that settles it | When |
|---|---|---|
| The reviewer-account token reaches the package | `toolkit services gitea registry-check --app imagesensortool` | after S2c mint |
| The receiver can read `repo_reader` (S5c): `forge_actions` writes Gitea Actions secrets only (`gitea_client` `PUT /repos/{owner}/{name}/actions/secrets`), so the owner sets the `mlorentedev/kubelab` GitHub Actions secret by hand from SOPS | `gh secret list -R mlorentedev/kubelab` names it; the S6b dry run's `resolve` job reads a commit | after S5c mint |
| Staging pulls from `gitea.kubelab.live` (DNS and TLS from the node, credential accepted) | `kubectl -n kubelab describe pod -l app.kubernetes.io/name=imagesensortool` shows `Pulled`, not `Failed` | S4 |
| Split DNS and the staging certificate for the new zone (risk 7) | `dig +short <staging host> @<rpi4>` returns the staging node; `toolkit secrets acme-token-scope` names `imagesensortool.com` | after S3b provision |
| The Gitea 1.27.3 API behaves as the adapter assumes | S5b's verification note, measured on a local Gitea 1.27.3 | before S5b code |
| The self-hosted runner accepts the `route`-selected label and reaches Gitea | the dry run in AC9 | S6b |
| The minimum GitHub permission for a dispatch token | dispatch with a token narrower than `repo`, record the status | before D1 is decided |
| Homelab off: a Gitea product's deploy waits | queue a dispatch with the node off, record the run state | S6b |

## References

- Bitácora: kubelab#2612. Related: #2449 (rulings Q1 to Q4, Q3 amendment), #2611 (IDP-051),
  #2627 (IDP-054), #2884 and #3036 (GHCR tokens), #2573, #1928, #2366, #3068, #3063.
- ADR-067 (contract, C2, C3, C7, D3), ADR-073 (proposed; D7, D9, D12, D13), ADR-030 and ADR-028
  (runner, on-demand node), ADR-046, ADR-053, ADR-065.
- Code read: `.github/workflows/product-image-receiver.yml`,
  `toolkit/features/{product_registry,product_render,product_contract,product_guards,product_release,product_ready,generator_k8s,promotion,registry,k8s_secrets,deploy_shape,gitea_client,gitea_tokens,secrets_manager}.py`,
  `infra/k8s/templates/deployments.yaml.j2`, `toolkit/schemas/kubelab-product.schema.json`,
  `tests/test_dns_contract_hostnames.py`, `tests/test_gitea_issue_reader_token.py`.
