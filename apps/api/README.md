# kubelab platform API

The unified Go API of the kubelab platform (L1). One binary, hosted in this monorepo, consumed by products over HTTP.

**This is not a website backend.** It was framed as one for a long time — the module was called `mlorente-backend` and this file said "the backend for my personal website" — and that framing was the drift [ADR-057](../../docs/adr/adr-057-kubelab-api-boundaries.md) was written to end. `web` is a **consumer**, and the first of several. See D1 there, and [ADR-048](../../docs/adr/adr-048-platform-consumer-repo-boundary.md), which rejected extracting this service for exactly that reason.

Module path: `github.com/mlorentedev/kubelab/apps/api`.

## What belongs in here, and what does not

[ADR-057 D3](../../docs/adr/adr-057-kubelab-api-boundaries.md) is the test, and it is worth reading before adding an endpoint:

> A capability belongs in this API **iff** it is consumed by **two or more products**, **or** it is genuinely cross-cutting (auth, LLM, knowledge/RAG, notifications, shared growth/identity).

A capability bespoke to a single product is product logic and its principled home is that product's repo. The deciding axis is the number of independent consumers and lifecycle ownership — **never how large the code is**. D4 lists the triggers that make a module leave.

The shape is a **modular monolith**: one deployable, clean internal modules. Not a microservice per capability — that was considered and rejected at this scale (ADR-029, ADR-057 D2).

## Status

| Module | State |
|---|---|
| `newsletter` (Beehiiv) + lead magnet | **built** — a platform capability with one tenant today (the brand list), per ADR-057 D6 |
| health / readiness | built |
| `/v1/knowledge/*` — RAG search and chat | **decided, not built** — [#396](https://github.com/mlorentedev/kubelab/issues/396), [#607](https://github.com/mlorentedev/kubelab/issues/607); see [ADR-043](../../docs/adr/adr-043-unified-knowledge-memory-plane.md) |
| `/v1/llm/*` — LLM gateway | **decided, not built** — [#375](https://github.com/mlorentedev/kubelab/issues/375); see [ADR-029](../../docs/adr/adr-029-intelligence-layer.md) |

The two unbuilt rows are the reason this service's identity matters: they have a named home, and it is here.

## Endpoints

```
GET  /health           liveness
GET  /healthz          liveness (Kubernetes-style)
GET  /ready            readiness

POST /api/subscribe    newsletter subscription (Beehiiv)
POST /api/unsubscribe  newsletter unsubscription
POST /api/lead-magnet  lead-magnet delivery
```

## Layout

```
src/
├── cmd/server/main.go        entry point
├── internal/
│   ├── api/                  HTTP handlers + routing + middleware
│   ├── constants/
│   ├── models/               request/response types
│   └── services/             business logic (beehiiv, email, subscription)
├── pkg/
│   ├── config/               environment configuration
│   └── logger/               zerolog setup
└── Dockerfile                multi-stage: golang builder -> alpine runtime
```

## Stack

Go 1.25 · [Gin](https://github.com/gin-gonic/gin) · [zerolog](https://github.com/rs/zerolog) · Beehiiv API.

`web` reaches this API same-origin under `/api` through a reverse proxy ([ADR-054](../../docs/adr/adr-054-web-runtime-config.md)), so the API's language is independent of any consumer's ([ADR-034](../../docs/adr/adr-034-polyglot-apps-language-per-service.md), ADR-057 D5).

## Running it

```bash
cd apps/api/src
go mod tidy
go run cmd/server/main.go       # or: air, for hot reload
```

Configuration comes from the environment. **Values are generated from the SSOT** (`infra/config/values/*.yaml` plus SOPS for secrets) — never hand-write a `.env` for staging or prod:

```bash
PORT=8080                       # apps.platform.api.default_port; 8080 in every environment
LOG_LEVEL=info
GIN_MODE=release
BEEHIIV_API_KEY=...             # SOPS
BEEHIIV_PUBLICATION_ID=...
ALLOWED_ORIGINS=...             # derived from the environment's site domain
```

## Deployment

Built and published by `.github/workflows/ci-publish.yml` as `kubelab-api`, multi-arch (`linux/amd64`, `linux/arm64`).

Tags follow the build-once rule ([ADR-056](../../docs/adr/adr-056-build-once-monorepo-apps.md)): merges publish an immutable `sha-<short>` that staging tracks, and a release **re-tags that exact digest** to `X.Y.Z` and `latest` — never a rebuild, so prod runs the bytes staging validated. Releases are cut by release-please from conventional commits (`api-vX.Y.Z`).

Serves `api.staging.kubelab.live` and `api.kubelab.live`.

## A note on this file

Until 2026-08-25 this README described a personal-website backend, and it had also been mangled at some point — markdown headings had lost their `#`, and every digit had been stripped (`Go .+`, `PORT=`, `localhost:/api/subscribe`, `api-v..`). It additionally referenced `apps/blog` and `apps/wiki`, neither of which exists; `apps/` now holds this service alone, `web` having moved to its own repository ([ADR-053](../../docs/adr/adr-053-platform-product-repos.md)).

Worth recording rather than quietly fixing: a decision written only in an ADR does not reach anyone if the file they actually open still says the old thing. That gap is what kept regenerating the question ADR-057 already answered.
