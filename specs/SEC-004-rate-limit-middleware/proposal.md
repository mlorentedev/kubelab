---
id: "SEC-004-rate-limit-middleware"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-14"
issue: "kubelab#970"
tags: [spec, proposal]
template_version: "1.0"
---

# SEC-004: Rate limit middleware

> **Naming**: file lives at `<repo>/specs/<feature-id>/proposal.md`. `<feature-id>` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #970: SEC-004: no rate-limit middleware exists on any K3s route -->

Every existing IngressRoute on K3s Traefik (base and both overlays, static and generator-produced) lacks any rate-limit middleware — the VPS's Docker Compose Traefik has one (`edge.traefik.rate_limit_*` in `common.yaml`, applied via Ansible), but that value set has never had a K3s consumer. Cloudflare is not proxied for any hostname except `api` (#704), so CrowdSec's reputation/behavior-based bouncer is currently the *only* thing between the public internet and K3s Traefik for every other route. CrowdSec answers "is this a known-bad actor" — nothing today answers "is total request volume about to exceed what the origin can serve."

## What

A shared `rate-limit` Traefik Middleware, sourced from the existing `edge.traefik.rate_limit_{average,burst,period}` SSOT in `common.yaml`, applied to every public-facing K3s IngressRoute alongside `secure-headers`/`crowdsec-bouncer`/`error-pages`. **Scoped to a single global bucket, not per-client**, per the investigation below — this is a volumetric backstop protecting origin capacity, not a per-abuser throttle.

## Out of scope

- Per-client / per-IP rate limiting — blocked on #1067 (klipper-lb MASQUERADEs every client's source IP to an internal pod-CIDR address before Traefik ever sees it; a per-IP bucket today would either share one bucket across all real clients, or bucket by the wrong, unstable internal IP). Revisit once #1067 lands a real client-IP signal (most likely a MetalLB migration).
- Any change to the VPS Docker Compose Traefik's existing `rate-limit@file` middleware — that one already works correctly and is untouched.
- Rate-limiting VPN-only / Tailscale-only routes (Loki, pihole, argocd, headscale, n8n if VPN-gated) — exposure there is the tailnet, not the internet; applying the same global bucket to them is harmless but adds no protection. `[AGENT-DRAFT — review before archive]` recommend blanket application (simpler, consistent with staging-mirrors-prod, and the shared bucket is harmless-if-sized-right) over selective (public routes only, tighter but adds a per-route decision that rots) — needs explicit user confirmation before `tasks.md` is frozen, not a silent default.

## Risks / open questions

- **[MUST resolve before tasks.md] Values need re-measurement, not blind reuse.** The VPS's `50/s average, 25 burst` were tuned for that topology (one Middleware per app, no ForwardAuth fan-out in the hot path for most apps). K3s routes include Authelia-gated ones (ForwardAuth sub-request per page-load) and the Homepage cockpit (multi-tile dashboard, bursty asset fetch on load). Exercise the noisiest known UI path in staging and record real request-per-second counts before freezing the threshold — reusing the VPS numbers unmeasured risks 429s on legitimate traffic, which is the failure this ticket's own existence is supposed to prevent, not cause.
- **[Resolved by this investigation, load-bearing]** A per-client-IP `sourceCriterion` would be actively harmful, not just ineffective — see #1067. Confirmed empirically in staging on 2026-08-14 (temporary Traefik accesslog + `externalTrafficPolicy: Local` test, both reverted): every request reaches Traefik under an internal pod-CIDR address regardless of real source. This spec commits to a global (non-keyed) rate limit as a direct consequence; do not revisit the per-client design without #1067 first.
- **CI-GATE-002 drift gate**: any change to `_build_middlewares()` in `toolkit/features/generator_k8s.py` must be paired with regenerating and committing `infra/k8s/overlays/{staging,prod}/generated/ingress.yaml` in the same commit, or `make config-check-drift` fails in CI. This is not new risk — it's the exact failure shape SEC-K8S-001 already documented in that gate's own comments — but it is a concrete task-ordering constraint for `tasks.md`.
- Middleware ordering: VPS convention is `[secure-headers@file, rate-limit@file, error-pages]` (dashboard adds `auth@file` first). K3s's existing `_build_middlewares()` emits `[secure-headers, (authelia), error-pages]` with inconsistent relative ordering across some hand-written IngressRoutes (n8n vs headscale differ). Insert `rate-limit` relative to what's already there per-route; do not use this ticket to silently reorder unrelated middleware.

## Acceptance criteria

- [ ] A `rate-limit` Middleware object exists (mirrors `secure-headers.yaml`'s pattern), values sourced from `edge.traefik.rate_limit_*` in `common.yaml`, no hardcoded duplicate.
- [ ] Every public-facing K3s IngressRoute (base + generated `ingress.yaml` for both envs) includes `rate-limit` in its middlewares list, positioned consistently with the existing `secure-headers`/`error-pages`/optional-auth chain.
- [ ] A synthetic burst test (staging) proves the limit fires above threshold (HTTP 429) and passes clean below it — exercised, not assumed, matching this session's established verification discipline (OBS-010's `max_over_time`→`last_over_time` catch was found exactly this way).
- [ ] `make config-check-drift` stays green after the `_build_middlewares()` change — regenerated `ingress.yaml` for both envs is part of the same commit as the generator change.

## References

- Bitácora board: kubelab#970 (this spec), kubelab#1067 (blocking follow-up: real client IP / per-client rate limiting)
- Related issue: kubelab#704 (CF-PROXY-001 — a different, Cloudflare-side hop; not a substitute for #1067's K3s-internal finding)
- Precedent: `infra/k8s/base/edge/secure-headers.yaml` (shared Middleware pattern to mirror), `infra/ansible/roles/traefik_vps/templates/middlewares.yml.j2` (working VPS `rate-limit@file` reference implementation)
- Drift gate: `make config-check-drift` in the root `Makefile` (~lines 215-286), its comments cite SEC-K8S-001 as the incident this gate exists to prevent recurring
