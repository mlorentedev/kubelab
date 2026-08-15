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

A shared `rate-limit` Traefik Middleware, sourced from the existing `edge.traefik.rate_limit_{average,burst,period}` SSOT in `common.yaml`, applied **blanket — every K3s IngressRoute, VPN-only routes included** (Loki, pihole, argocd, headscale, n8n) — alongside `secure-headers`/`crowdsec-bouncer`/`error-pages`. **Scoped to a single global bucket, not per-client**, per the investigation below — this is a volumetric backstop protecting origin capacity, not a per-abuser throttle. Blanket vs. selective (public-only) was an open question in this proposal; confirmed blanket by the user on 2026-08-14 — simpler, consistent with staging-mirrors-prod, and the shared bucket is harmless-if-sized-right on VPN-only routes rather than adding a per-route decision that rots.

## Out of scope

- Per-client / per-IP rate limiting — blocked on #1067 (klipper-lb MASQUERADEs every client's source IP to an internal pod-CIDR address before Traefik ever sees it; a per-IP bucket today would either share one bucket across all real clients, or bucket by the wrong, unstable internal IP). Revisit once #1067 lands a real client-IP signal (most likely a MetalLB migration).
- Any change to the VPS Docker Compose Traefik's existing `rate-limit@file` middleware — that one already works correctly and is untouched.

## Risks / open questions

- **[Resolved 2026-08-14, measured]** Exercised the noisiest known UI path (Homepage cockpit, full page reload) against staging Traefik's access log (temporary `--accesslog=true`, reverted after). Authelia-gated routes turned out not to need separate measurement: its ForwardAuth `address` is the internal Service DNS (`http://authelia.kubelab.svc.cluster.local:9091/...`), so the sub-request never traverses a Traefik router and never touches any route's rate-limit bucket. Real numbers from a single reload: **peak 49 req/s in the worst 1-second window**, ~193 requests over 60s (~3.2 req/s sustained average), with periodic client-side widget-refresh clusters of 15-20 req/s roughly every 30-40s. (The first measurement attempt hit a live, unrelated bug — Homepage was crash-looping on a kubelet-probe/Host-validation issue, fixed separately in #1073 and `docs/lessons.md`; these numbers are from the healthy, pinned-version pod.) Proposed starting values: **`average: 30/s`, `burst: 150`** (~3x the observed single-load peak, covering a few concurrent legitimate sessions) — a draft to be confirmed, not re-derived, by AC3's burst drill.
- **[Resolved by this investigation, load-bearing]** A per-client-IP `sourceCriterion` would be actively harmful, not just ineffective — see #1067. Confirmed empirically in staging on 2026-08-14 (temporary Traefik access log + `externalTrafficPolicy: Local` test, both reverted): every request reaches Traefik under an internal pod-CIDR address regardless of real source. This spec commits to a global (non-keyed) rate limit as a direct consequence; do not revisit the per-client design without #1067 first.
- **CI-GATE-002 drift gate**: any change to `_build_middlewares()` in `toolkit/features/generator_k8s.py` must be paired with regenerating and committing `infra/k8s/overlays/{staging,prod}/generated/ingress.yaml` in the same commit, or `make config-check-drift` fails in CI. This is not new risk — it's the exact failure shape SEC-K8S-001 already documented in that gate's own comments — but it is a concrete task-ordering constraint for `tasks.md`.
- Middleware ordering: VPS convention is `[secure-headers@file, rate-limit@file, error-pages]` (dashboard adds `auth@file` first). K3s's existing `_build_middlewares()` emits `[secure-headers, (authelia), error-pages]` with inconsistent relative ordering across some hand-written IngressRoutes (n8n vs headscale differ). Insert `rate-limit` relative to what's already there per-route; do not use this ticket to silently reorder unrelated middleware.
- **[Resolved 2026-08-14]** AC1 originally pointed at the VPS's own `edge.traefik.rate_limit_{average,burst,period}` keys — but K3s's measured values differ from the VPS's (see above), and those keys are consumed by the VPS's own Ansible-rendered `rate-limit@file` middleware. Writing K3s-specific numbers there would silently re-tune the VPS on its next Ansible deploy, and this lane cannot touch `infra/ansible/` to restructure them safely. User confirmed new, separate keys: `edge.traefik.rate_limit_k3s_{average,burst,period}` — flat siblings of the existing VPS keys, zero Ansible changes needed.
- **Two Traefik RateLimit semantics to pin explicitly during implementation, not assume:**
  - **`sourceCriterion`**: with klipper-lb masquerading every client to an internal pod-CIDR address (#1067), Traefik's *default* client-IP keying would accidentally collapse everyone into a near-global bucket anyway — but that's "global by accident," not by design. Set `sourceCriterion.requestHost: {}` explicitly so the behavior doesn't silently change the moment #1067 is fixed and real client IPs reappear.
  - **Shared vs. per-router bucket**: whether one Middleware object referenced by many IngressRoutes shares a single token bucket cluster-wide, or Traefik instantiates a separate bucket per router, is not something to trust from memory or docs — verify empirically as part of AC3's burst drill (exhaust route A, immediately probe route B; a 429 on B proves shared, a clean 200 proves per-router). This determines whether "blanket application" means one shared budget or N independent ones.

## Acceptance criteria

- [ ] A `rate-limit` Middleware object exists (mirrors `secure-headers.yaml`'s pattern), values sourced from `edge.traefik.rate_limit_k3s_*` in `common.yaml` (a new, K3s-specific SSOT key — see Risks above), no hardcoded duplicate.
- [ ] Every K3s IngressRoute, blanket — public and VPN-only alike (base + generated `ingress.yaml` for both envs) — includes `rate-limit` in its middlewares list, positioned consistently with the existing `secure-headers`/`error-pages`/optional-auth chain.
- [ ] A synthetic burst test (staging) proves the limit fires above threshold (HTTP 429) and passes clean below it — exercised, not assumed, matching this session's established verification discipline (OBS-010's `max_over_time`→`last_over_time` catch was found exactly this way). The clean-below-threshold case must not inherit token-bucket state consumed by the burst case: either wait for the bucket to refill (per the configured `average`/`period`) between the two runs, or exercise them against an isolated limiter fixture, so a false 429 from bucket exhaustion can't be mistaken for a real failure. The same drill also settles whether the bucket is shared across routers or per-router (exhaust route A, immediately probe route B) — record which, since it changes what "blanket application" actually guarantees.
- [ ] `make config-check-drift` stays green after the `_build_middlewares()` change — regenerated `ingress.yaml` for both envs is part of the same commit as the generator change.

## References

- Bitácora board: kubelab#970 (this spec), kubelab#1067 (blocking follow-up: real client IP / per-client rate limiting)
- Related issue: kubelab#704 (CF-PROXY-001 — a different, Cloudflare-side hop; not a substitute for #1067's K3s-internal finding)
- Precedent: `infra/k8s/base/edge/secure-headers.yaml` (shared Middleware pattern to mirror), `infra/ansible/roles/traefik_vps/templates/middlewares.yml.j2` (working VPS `rate-limit@file` reference implementation)
- Drift gate: `make config-check-drift` in the root `Makefile` (~lines 215-286), its comments cite SEC-K8S-001 as the incident this gate exists to prevent recurring
