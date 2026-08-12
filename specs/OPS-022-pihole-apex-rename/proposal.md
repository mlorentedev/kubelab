---
id: "OPS-022-pihole-apex-rename"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-08-11"
issue: "kubelab#969"
tags: [spec, proposal]
template_version: "1.0"
---

# OPS-022: Pihole apex rename

> **Naming**: file lives at `<repo>/specs/<feature-id>/proposal.md`. `<feature-id>` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #969: OPS-022: Pi-hole ships to prod from base/ and returns 502 where it belongs -->

Prod ships a Pi-hole route it can never serve as a matter of design: `pihole.yaml` lives in `base/`, so the VPS cluster carries an IngressRoute for a staging name whose EndpointSlice points at a LAN address on the on-demand homelab — reachable only while it happens to be powered, never a serviceable prod backend (ADR-028's 3 AM doctrine). Prod Traefik still orders ACME certificates for `pihole.staging.kubelab.live` regardless. The manifest has also drifted from its own SSOT — `common.yaml:762` has declared `pihole.kubelab.live` all along — and the staging-scoped name creates a circularity: resolving Pi-hole's admin UI depends on the split-DNS path that runs through Pi-hole itself, so the name goes dark exactly when Pi-hole is down and you need the UI to debug it. Without this change the SSOT keeps lying, prod keeps holding certs for a name it will never serve, and — with e2e skipping Pi-hole in every environment — nothing ever fails to tell us.

## What

After this PR, Pi-hole answers on one name, its SSOT name, from anywhere on the tailnet:

1. `https://pihole.kubelab.live/admin/` returns 200/302 from any tailnet client — resolvable by public DNS (a Cloudflare A record pointing at ace1's Tailscale IP, `100.64.0.11`), reachable only from the tailnet, TLS issued by staging Traefik via the existing DNS-01 resolver. Resolution no longer depends on Pi-hole being up.
2. Prod stops serving anything Pi-hole: `kubectl kustomize infra/k8s/overlays/prod` emits no pihole Service/EndpointSlice/IngressRoute, and prod Traefik stops ordering the `pihole.staging.kubelab.live` cert. (`pihole.yaml` moves from `base/external/` to the staging overlay — the same overlay-only pattern as prod's `headscale.yaml`.)
3. `infra/terraform/dns/services.json` supports an optional `target` field (absent → `var.vps_ip`, unchanged for all 11 existing records; present → that address). Pi-hole's record is its first consumer.
4. The e2e suite asserts Pi-hole instead of skipping it: `skip_in_envs` shrinks so a staging run must observe the 200/302, and a prod run must observe the route's absence.

## Out of scope

- No alias or redirect for the old name. After the rename, `pihole.staging.kubelab.live` goes dark deliberately — it falls through to staging's catch-all 404. No CoreDNS/Pi-hole local record, no Traefik redirect: a single name is the point of the decision (#977).
- No #973 generator work. The `target` field's schema is coordinated with #973 (recorded in Risks), but `sync_homepage_config.py` and the static URL-coverage test stay untouched here.
- No `*.kubelab.live` wildcard (#907). Deferred until #914 lands (decision documented on #907, 2026-08-11). This PR adds exactly one explicit A record.
- No rpi4-side work. Neither the Pi-hole container/Ansible stack nor diagnosing the #959 DNAT drift — OPS-016 owns that. If the 502 reappears during verification, it blocks the acceptance criteria; it does not expand this PR.

## Risks / open questions

1. **RESOLVED 2026-08-11: `target` field is a node-name reference, not a literal IP.** `services.json` carries `"target": "ace1"`; Terraform resolves it through a variable map in `dns.tfvars` (same indirection as `vpn_extra_records`' `node:` key), so no Tailscale IP is hardcoded anywhere in the DNS config — reproducible, idempotent, IaC, SSOT stays `networking.nodes.ace1.tailscale_ip`. A literal `100.64.0.11` was rejected: tailnet IPs are not stable across re-enrollment (aws1 moved .4→.7 after its Spot replacement), and JSON can't carry the repo's mirror-comment convention to flag the duplication. Post this schema on #973 before the implementation PR — its planned URL-coverage test reads `services.json` and must know the field.
2. **RESOLVED 2026-08-11: prod-absence is asserted by a static render test, not a `ServiceExpectation` field.** After the rename, `pihole.kubelab.live` resolves to ace1's Tailscale IP — every HTTP probe lands on staging's Traefik regardless of what prod ships, so a runtime check (which is all `ServiceExpectation` can express) structurally cannot see a regression where `pihole.yaml` drifts back into `base/`: that's the original #969 defect, and it would be invisible to any live check ever again. The property only exists in the render, so the check has to live there too. New single-purpose file `tests/test_pihole_overlay_render.py`, modeled on `test_grafana_alerting_render.py` (subprocess `kubectl kustomize`, skip-loudly-if-kubectl-missing per its "CANNOT CHECK, not OK" convention) — not `test_spoke_rbac_covers_manifests.py`, which deliberately reads manifest files rather than the render and is cited only for "runs with the homelab off." Positive control included: the same object matcher must find Service+EndpointSlice+IngressRoute in the staging render (>0) while finding none in prod (==0) — same shape as `test_prod_and_staging_differ`, so a matcher typo can't pass vacuously forever.
3. **#959 can return.** The DNAT-flush trigger is unreproduced and what repaired rpi4 was the reboot, not a deploy — the 200 measured 2026-08-11 is "working now", not "stable". The acceptance test asserts the 200 at verification time rather than assuming it; a reappearing 502 blocks this spec, it does not expand it.

## Acceptance criteria

- [ ] Staging e2e asserts Pi-hole instead of skipping it: `make test-e2e ENV=staging` checks `https://pihole.kubelab.live/admin/` and observes 200/302 — the 200 is asserted at verification time, never carried over from the 2026-08-11 measurement (#959's trigger is unreproduced; a reappearing 502 fails this criterion and blocks the spec). `skip_in_envs` shrinks to `("dev", "prod")` — and the prod entry's inline comment changes meaning: no longer "domain doesn't resolve outside VPN" (it does now), but "absence asserted by `tests/test_pihole_overlay_render.py`, not by the e2e HTTP suite" — a stale comment here is exactly the failure mode `uptime_kuma`'s left-over `skip_in_envs` entry already taught this repo to avoid.
- [ ] The name resolves publicly to the tailnet address: `dig +short pihole.kubelab.live @vita.ns.cloudflare.com` returns the address at `networking.nodes.ace1.tailscale_ip` (100.64.0.11 today). Authoritative NS, not 1.1.1.1 — public resolvers serve stale answers for a full TTL.
- [ ] Prod emits nothing Pi-hole, asserted with the homelab off, workstation-verified (no CI workflow runs pytest — `make test` or the narrower target, per `test_grafana_alerting_render.py`'s own docstring): `tests/test_pihole_overlay_render.py` renders both overlays via `kubectl kustomize`, finds zero pihole-named objects (Service, EndpointSlice, IngressRoute) in prod's render and the same three present in staging's — the positive control from Risk 2.
- [ ] The `target` field is backward-inert: `make tf-dns-plan` shows exactly `1 to add, 0 to change, 0 to destroy` — the new record with the node-resolved address, all 11 existing records untouched.
- [ ] The old name is dark, not aliased: `curl -sk https://pihole.staging.kubelab.live/admin/` from a tailnet client returns the staging catch-all 404 — not 502, not Pi-hole.

## References

- Bitácora board: the GitHub issue / Project item tracking this spec (see the `issue:` frontmatter field)
- Related ADR: `<repo>/docs/adr/adr-XXX.md` (if any)
- Related patterns: `00_meta/patterns/<pattern>.md` (if any)
