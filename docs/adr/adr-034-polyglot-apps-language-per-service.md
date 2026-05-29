---
id: adr-034-polyglot-apps-language-per-service
type: adr
status: active
created: "2026-05-19"
---

# ADR-034: Polyglot `apps/*` — Pick the Language per Service

> **Date:** 2026-05-20
> **Status:** Accepted
> **Stakeholders:** Manu (sole operator)
> **Related:** DASH-DT-004 (first decision under this ADR), [adr-032-observability-stack-execution](adr-032-observability-stack-execution.md)

## Context

`apps/` already hosts services in different stacks: `apps/api` is Go (Gin + zerolog, Go 1.25 multistage `golang:alpine`), `apps/web` is a JS framework build, `apps/blog` and `apps/wiki` are doc-site generators. The toolkit at `toolkit/` is Python (Typer + Pydantic + Poetry) and is *not* containerised — it is a CLI for the operator. The repo is *de facto* polyglot.

DASH-DT-004 (server-side health check `widget-proxy`) was the first new microservice in months that forced an explicit "which language" decision. The reflex "all microservices in Python because toolkit is Python" was tempting but does not match how `apps/api` already lives.

## Decision

**Each service under `apps/*` picks the language that fits the service.** The repo embraces polyglot architecture rather than forcing a single runtime.

- **Default to Go** when the service is a lightweight HTTP component (proxy, health checker, edge handler) where image footprint, cold start, and stdlib `net/http` ergonomics matter. Use Go 1.25+ multistage scratch images, matching the `apps/api` pattern.
- **Default to Python** when the service is CLI / generator / orchestration glue that benefits from the existing toolkit ecosystem (Typer, Pydantic, Poetry, asyncio). Keep these in `toolkit/` if they are not user-facing services; promote to `apps/<service>/` only if they need an HTTP surface and independent deployment lifecycle.
- **Other runtimes** (Rust, Node, Deno, JVM) need an explicit "why this is better than Go or Python here" note in the spec / proposal. Adding a runtime is cheap once; adding the *fifth* runtime is expensive because the operator has to context-switch across maintenance, debugging, and CI.

The decision is per-service, not per-monorepo. Reviewing the spec at SDD `init` time should answer "Go, Python, or argue for something else" as a BLOCKER.

## Consequences

- **Positive**: services fit their language; nobody fights aiohttp for a 200-LOC HTTP proxy or shoehorns a Pydantic config into a Go binary. Image sizes, cold starts, and CI build times stay appropriate.
- **Positive**: the repo signals "this is a real platform, not a Python script collection" — useful as the surface grows.
- **Negative**: cognitive overhead. The operator must keep two (potentially more) toolchains warm: Go modules + Python Poetry + JS/build pipelines. Mitigated by Makefile targets that hide the per-app build commands.
- **Negative**: shared code is harder. Schemas duplicated across Go structs and Python Pydantic models. Mitigated by keeping shared schemas tiny and machine-generating from YAML SSOT where possible.

## Anchored decisions under this ADR

| Service | Language | Reason |
|---------|----------|--------|
| `apps/api` (existed before this ADR) | Go (Gin) | HTTP API, low footprint, stdlib net/http strong |
| `apps/web` (existed) | JS framework | Site generation |
| `apps/widget-proxy` (DASH-DT-004) | Go | Lightweight HTTP proxy, ~5 MB scratch image, fits sweet spot |
| `toolkit/*` | Python | CLI + generators + orchestration, not user-facing services |

Future entries: append a row when a new service is added; link the spec/PR.

## Alternatives considered

1. **Force all microservices to Python** — rejected. `apps/api` is already Go and works well; forcing widget-proxy to Python would have meant 16× larger image for a 200-LOC use case where Go stdlib is a closer fit.
2. **Force all microservices to Go** — rejected. Python is the right language for orchestration / generators / quick scripts. Toolkit would be miserable in Go.
3. **Single-language consolidation later** — explicitly deferred. The cost of "everything in one language" exceeds the cost of "two well-chosen languages" at this scale. Revisit if the operator headcount changes.

## References

- DASH-DT-004 spec at `specs/DT-004-widget-proxy/proposal.md` (first BLOCKER resolved by this ADR).
- `apps/api/src/go.mod` — precedent.
- CLAUDE.md "Workflow rules" — adds this ADR as the canonical answer to "which language for app X".
