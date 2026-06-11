---
id: adr-042-reference-architecture
type: adr
status: accepted
created: "2026-06-10"
owner: manu
tags: [architecture, reference-architecture, blueprint, substrate, finops, tenancy, ai-workloads]
depends_on: [adr-023-hub-spoke-multicloud-gitops, adr-028-operational-topology, adr-029-intelligence-layer, adr-031-positioning-pivot]
---

# ADR-042: Reference Architecture — Blueprint vs Substrate (client-replicable)

> **Status:** Accepted
> **Date:** 2026-06-10
> **Related:** ADR-031 (positioning), ADR-028 (operational topology), ADR-029 (intelligence layer), ADR-023 (hub-and-spoke GitOps)

## Context

KubeLab's topology grew organically around personal hardware (ace1/ace2/Beelink/rpi4 + a Hetzner VPS). Per ADR-031 the brand is now **"Platform Engineering for AI Workloads — production-grade Kubernetes for ML inference"**, and the goal stated this session is for the infrastructure itself to be the **reference architecture the startup sells and replicates for clients** (Series A-C migrating inference off SageMaker/Vertex to self-managed K8s).

That goal exposed the root confusion behind months of circular discussion: **the homelab-specific topology is not replicable for a client** — a client does not have the user's Acemagic boxes. Recurring symptoms of conflating "my cheap hardware" with "the architecture":

- `ollama.kubelab.live` is a **public prod URL backed by an on-demand homelab node (ace2)** — a prod always-on promise that only holds when the homelab is powered (violates ADR-028).
- `tests/e2e/expectations.py` marks Ollama `skip_in_envs=("prod")` ("staging-only") while the prod overlay exposes it — the repo contradicts itself.
- `homepage/custom.js` still says Ollama runs on Beelink; it moved to ace2 in ADR-029.
- "staging has more nodes than prod" — an inversion that only makes sense if "staging" = a powerful homelab and "prod" = a small VPS.

## Reference Audit (Regla del 3, ADR-015)

The decision affects cross-instance reuse (a client-replicable blueprint), so N≥2 references were audited before generalizing. Sources verified against 2025-2026 primary docs.

| Dimension | R1 · Cloud-managed (EKS/GKE) | R2 · KServe/vLLM (inference) | R3 · helmcode/agent_crew (self-hosted peer) |
|---|---|---|---|
| Control plane | Managed, vendor-isolated; EKS Provisioned CP / GKE Autopilot | Operator stack ON the base cluster (CRDs + Knative + Gateway API) | App orchestrator (Go/NATS); runtime-pluggable `docker\|k8s` |
| Node pools | Auto-provisioned tiers general/GPU/spot, **scale-to-zero** (Karpenter/NAP) | Dedicated GPU pool, **taint-isolated**, device-plugin, MIG/DRA | N/A (it is an app, not infra) |
| Data backends | Off-node: S3/GCS (CSI) + RDS/CloudSQL; weights stream from object store | Weights from S3/PVC/OCI; **hot state = KV-cache, not a DB** | GORM/**SQLite** (no Postgres) + Qdrant |
| CI / registry | ECR/Artifact Registry (images + model artifacts) | Images + model artifacts (`storageUri` by digest) | GH Actions + Dockerfile marketplace |
| GitOps + SSO | Argo/ConfigSync; **Pod Identity / Workload Identity** (ephemeral creds); OIDC SSO | Argo declarative; **Envoy AI Gateway** (OIDC + API-keys + token rate-limit) | JWT local; **OIDC declared but NOT wired (gap)** |
| Tenancy | Soft multi-tenant default (ns+pools+policy); hard = cluster/vCluster per tenant | Shared GPU via **LoRA multiplexing** + model routing at gateway | **Multi-tenant (`OrgID`)** + self-hosted |
| FinOps | Spot for fault-tolerant only; scale-to-zero; vendor silicon (Inferentia/TPU); MIG | **Core:** scale-to-zero + spot GPU + continuous batching (vLLM) + prefix-cache routing | Not a focus (orchestration app) |

R3 evidence sourced from the `iris` prestudy deep-dive (`10_projects/iris/25-prestudy/competition/agent-crew-analysis.md`); helmcode == NaN Builders, an ADR-031 competitor.

### Divergence log

**Intersection (≥2 references → blueprint candidates):**

1. **Node pools by role** (general/stateful-always-on vs compute/burst-GPU) — R1+R2.
2. **State off compute nodes** (object store + DB as tiers) — R1+R2+R3.
3. **GitOps declarative deploy** (Argo CD) — R1+R2.
4. **OIDC wired + token/API-key gating** — R1+R2 (R3's declared-not-wired OIDC is the anti-pattern to avoid).
5. **AI-aware L7 gateway** (model routing, token rate-limit) — R1+R2 (future candidate for the inference tier).
6. **Tenancy is an explicit axis** — R1 (soft multi) vs R3 (multi-tenant).

**Unique to one (NOT generalizable):** vendor silicon Inferentia/TPU (R1); KV-cache hot-state + cache-affinity routing (R2, GPU-bound); NATS-bus + sidecar-per-agent (R3, app-internal).

**Triangulated strategic findings:** (A) GPU is mandatory for the inference paradigm — without it the FinOps thesis evaporates; the homelab cannot demonstrate it. (B) The cloud paradigm assumes dynamic node lifecycle; the homelab is fixed inventory. (C) Identity is federated/ephemeral (cloud) vs static SOPS+Headscale (homelab); wired OIDC is a strength vs helmcode. (D) Tenancy (single vs multi) is a business-architecture fork.

## Constraints

| # | Constraint | Origin |
|---|---|---|
| C1 | Blueprint ≠ substrate: parameterized logical plan, substrate-agnostic; homelab+VPS is one instance | user goal + flag B |
| C2 | Node pools by role (general/always-on vs compute/burst-GPU), with lifecycle | intersection #1 |
| C3 | Stateful data off compute nodes (object store + Postgres tiers) | intersection #2 |
| C4 | FinOps node-type rule: stable for always-on stateful; spot/scale-to-zero for burst+GPU | intersection #1/#7 |
| C5 | GitOps declarative (Argo CD) | intersection #3 + ADR-023 |
| C6 | OIDC wired, not declared (Authelia SSO + token/API-key gating) | intersection #4 + flag C |
| C7 | Tenancy is an explicit decision (single vs multi-tenant) | iris + ADR-031 |
| C8 | Prod never promises always-on backed by an on-demand node | ADR-028 + ollama drift |
| C9 | Staging validates the change before prod (permanent twin only where it adds value; global singletons get canary+rollback) | session |
| C10 | Agent-workloads are a parity-bearing class (staging/prod instances + per-instance scoped credentials) | HERMES-002 (#239) |
| C11a | No discrete GPU on-prem (hard limit) | confirmed |
| C11b | Inference *capability* for tooling = consume NaN cloud (GPU-backed, always-on, zero ops) | session refinement |
| C11c | Inference *demonstration* for the brand = a built cloud-GPU showcase (spot, scale-to-zero) | flag A + ADR-031 |
| C12 | The architecture itself must demonstrate the ADR-031 brand (deliberate placement, legible FinOps, replicability) | ADR-031 |

## Options Considered

| Option | Summary | C2 | C4 | C8 | C11c | C12 |
|---|---|---|---|---|---|---|
| A | Upsize single VPS (one big node) | gap | gap | ok | gap | weak |
| B | Second stable node → multi-node prod cluster | ok | partial | ok | gap | ok |
| C | Managed-cloud backends (S3/R2 + managed Postgres) + small compute | ok | partial | ok | gap | ok |
| **D** | **Hybrid: always-on tier (B) + ephemeral cloud GPU pool (vLLM/KServe, scale-to-zero)** | ok | ok | ok | ok | ok |
| E | Defer / document only (blueprint as IaC, no faithful prod) | ok | n/a | weak | gap | weak |

## Decision

**Target blueprint = B + D**, instantiated incrementally:

1. **Logical blueprint (substrate-agnostic):** control plane + node pools *by role* (general/stateful-always-on vs compute/burst-GPU) + backend tiers (object store, Postgres) + GitOps/SSO/observability. The homelab+VPS is one (degenerate, fixed-inventory) instance; a client's cloud is another. The deliverable is the parameterized IaC, not a node list.
2. **Always-on prod tier (Option B):** a real multi-node prod cluster of *stable* nodes for the platform/always-on services (object store, CI, Postgres/pgvector, registry). Current Hetzner CAX21 (8GB) is near-full and cannot host them all on one node.
3. **Ephemeral GPU inference showcase (Option D):** a cloud GPU node pool (spot, scale-to-zero) running vLLM/KServe — the brand centerpiece demonstrating GPU scheduling + FinOps. Not on-prem (C11a).
4. **Tenancy = single-tenant-per-client** (C7). ADR-031 positions consulting + content, not SaaS; the blueprint is instantiated fresh per client. Multi-tenant (helmcode model) is explicitly rejected as a SaaS pivot.
5. **Inference buy/build split:** consume NaN cloud for operator tooling (Open WebUI, Hermes) — C11b; build the cloud-GPU showcase only for the brand demonstration — C11c.

**Substrate is instantiated by phases, not all at once** (anti-paralysis, ADR-031): the blueprint is decided now; the always-on tier and GPU showcase are built after a first demonstrable artifact ships.

## Rationale

- Knowing what **not** to homogenize into one cluster is the senior signal: deliberate placement under one control plane over a heterogeneous fleet beats "everything in K8s." The decision record itself is the portfolio artifact.
- B+D mirrors how real production GenAI platforms are built (serving tier in-cluster, inference as a dedicated/external GPU tier), which is exactly the ADR-031 audience's world.
- Single-tenant matches the consulting model and keeps the blueprint a replicable IaC artifact rather than a multi-tenant product to operate.
- Consuming NaN for tooling avoids GPU ops for zero brand cost; building one GPU showcase supplies the FinOps story (ephemeral scale-to-zero ≈ tens of $/month vs ~$1-2k/month always-on — a 50-100x gap that *is* the demo).

## Consequences

**Positive:** ends the substrate/blueprint conflation; resolves the `ollama.kubelab.live` availability incoherence by design; gives a clear, sequenced backlog; aligns the infra with the ADR-031 brand; the blueprint is sellable IaC.

**Negative:** the always-on tier and GPU showcase cost money (second node + cloud GPU hours); more moving parts than a single VPS; the homelab remains a *degenerate* instance (fixed inventory, no scale-to-zero) that cannot demonstrate the dynamic-lifecycle story on-prem.

**Neutral:** Open WebUI and Hermes are unchanged in intent (serving/agent workloads consuming NaN + optional local Ollama); the homelab keeps serving as the cheap staging substrate.

## Implementation / Backlog (sequenced)

1. **Now:** this ADR (decision record) + GPU-showcase ticket.
2. **Next:** AI-003 Open WebUI on staging (consume NaN) — fastest demonstrable artifact; resolves the `ollama` exposure drift in-place (VPN-only vs best-effort, decided here: keep Ollama VPN-only; prod tooling consumes NaN, so `ollama.kubelab.live` public exposure is removed).
3. **Later ($$):** Option B always-on prod tier (second stable node) + the ephemeral cloud-GPU inference showcase (vLLM/KServe).
4. **Tracked separately:** HERMES-002 (#239); drift fixes (homepage Beelink→ace2; MinIO placement clarification).

## References

- Reference audit sources: `awslabs/ai-on-eks`, GKE AI/ML orchestration docs, `kserve.github.io`, `llm-d.ai`, Red Hat KServe+vLLM autoscaling articles (2025-2026).
- `10_projects/iris/25-prestudy/competition/agent-crew-analysis.md` (helmcode/agent_crew deep-dive).
- ADR-031 (positioning), ADR-028 (operational topology), ADR-029 (intelligence layer), ADR-023 (hub-and-spoke GitOps), ADR-015 (Regla del 3).
