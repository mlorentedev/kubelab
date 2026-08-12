---
tags: [spec, verification, templates]
created: "2026-08-11"
---

# Verification - OPS-022-pihole-apex-rename

## Evidence

- [x] AC1 (staging e2e 200/302) -> `poetry run pytest tests/e2e/ -m e2e --env staging -k pihole` — 5 passed. Live manual check: `curl -sk https://pihole.kubelab.live/admin/` → `HTTP 302`.
- [x] AC2 (public resolution to ace1) -> `dig +short pihole.kubelab.live @vita.ns.cloudflare.com` → `100.64.0.11`, matches `networking.nodes.ace1.tailscale_ip`.
- [x] AC3 (prod absence, staging presence) -> `pytest tests/test_pihole_overlay_render.py` — 2 passed (`test_staging_renders_all_three_pihole_objects`, `test_prod_renders_nothing_pihole`).
- [x] AC4 (target field backward-inert) -> `make tf-dns-plan` → `Plan: 1 to add, 0 to change, 0 to destroy.`, content `100.64.0.11`, all 11 existing records untouched. Applied via `make tf-dns-apply` → `Apply complete! Resources: 1 added, 0 changed, 0 destroyed.`
- [x] AC5 (old name dark) -> `curl -sk https://pihole.staging.kubelab.live/admin/` → `HTTP 404`.

Commit: implementation on `feat/OPS-022-pihole-apex-rename` (pre-PR at verification time). Spec scaffold: `cb4ebb3`.

## Test status

- Test suite: `make test` -> 458 passed, 0 failed (2026-08-11, before the staging deploy pass).
- `tests/test_pihole_overlay_render.py` -> 2 passed. `tests/e2e/ -k pihole --env staging` -> 5 passed.
- Manual smoke test — split-DNS resolution: not run from tailnet MagicDNS specifically (the authoritative-NS check in AC2 and the live `curl` in AC1 together cover the same resolution path from this session's tailnet client — no separate MagicDNS-only client was available to test in isolation). Not a blocking criterion per the design note below.
- No regressions in existing test suite: yes — 458/458 passed before the deploy pass; the render test (2) and e2e pihole subset (5) both green after.

## Live-verification incident (found and worked around during this pass, not part of OPS-022's own scope)

1. **n8n exec flake** — `import-n8n`'s `kubectl exec` failed once (exit 137) because the n8n pod restarted mid-exec (liveness probe timeout under CPU throttling — confirmed via `cpu.stat`: `nr_throttled=211/554` periods). Filed **#1009** with the cgroup evidence. Fixed the underlying flakiness with a bounded retry (`_run_with_retry` in `toolkit/features/n8n_import.py`, waits for rollout-Ready before retrying) and decoupled `deploy-k8s`'s exit code from `import-n8n`'s (Makefile `||` with a loud warning) so a transient import failure no longer reports the whole K8s deploy as failed. This fix is orthogonal to OPS-022 — landing in its own branch/PR, not this one.
2. **Argo CD staging selfHeal drift** — the live `kubelab-staging` Argo CD Application had `selfHeal: true` although git has said `false` since PR #211 (ADR-037, merged 2026-05-24); nobody ran `make deploy-apps` after that PR merged. This reverted the first staging deploy of this change 19 seconds after applying it. Confirmed via `kubectl diff -f infra/k8s/argocd/applications/` (staging: exactly the `selfHeal` field differs; prod: zero diff). Filed **#1016** with the full timeline (`managedFields` predates PR #211's merge) and a proposed structural fix (`kubectl diff` folded into `check-apps`). The live fix (`make deploy-apps`) is NOT yet applied — blocked on aws1 (Argo CD hub) being unreachable (Spot reclaim in progress, user is tracking via Uptime Kuma). Worked around for this verification pass because the same outage means nothing can revert a direct `kubectl apply` right now — re-ran `make deploy-k8s ENV=staging` and confirmed the IngressRoute's `Host()` before running the ACs above. This is a point-in-time verification, not proof the drift is fixed; #1016 tracks the real fix for whenever the hub returns.

## Decisions made during implementation

- Risk 2 (prod-absence assertion): resolved via advisor consult — a static `kubectl kustomize` render test, not a `ServiceExpectation` field, because after the rename no live HTTP probe can ever see a regression (the apex name resolves to ace1 regardless of what prod ships). See `proposal.md` Risk 2 for the full argument.
- `target` field content resolution lives in Terraform `locals` (`services_resolved`), computed once and shared by both `records_kubelab.tf` and `records_mlorente.tf` — kept symmetric even though only a kubelab-zone record uses it today, so a future mlorente-zone `target` doesn't silently no-op.
- An unresolvable `target` name is a hard Terraform error (direct map index, not wrapped in `try`), not a silent fallback to `var.vps_ip` — deliberate, matches the repo's "loud failure over silent" convention.

## Independent review (adversarial-review, post-merge)

Requested from an independent session/subagent since self-review is forbidden by the skill's own guardrail (this session implemented the change). **First pass: FAIL.** Real, REAL-reality, UNTESTED Major finding: `toolkit/scripts/sync_homepage_config.py` hardcoded `pihole.staging.{base}` for the Homepage dashboard's Pi-hole tile (`url` + `health`, plus a DNS-map row and a mermaid diagram edge) — never updated by the rename PR. Behaviorally real, not just stale text: `custom.js`'s `checkHealth()` does a live client-side `fetch(url, {mode:"no-cors"})` on every dashboard load, and `no-cors` resolves `.then()` (green) for any reachable response including the staging catch-all's 404 — so the dashboard would have shown a false "up" status and a dead link for exactly the service this spec renamed, the same "SSOT keeps lying, nothing tells us" failure the proposal's own "Why" section names as its motivation, recurring one layer up. Full review: `review.md` in this folder.

**Fixed, same session:** `sync_homepage_config.py`'s Pi-hole entry aligned with its own `shared`-list siblings (Argo CD, Headscale, Uptime Kuma all use `{base}` with no env prefix — Pi-hole's `staging.` insertion was inconsistent with its own categorization); the DNS-map's stale `pihole.staging.*` row and the always-dead "Headscale extra_records" row (extra_records has never resolved for anything, #964) replaced with an accurate `pihole.kubelab.live → ace1 Tailscale IP` row under "PROD (public DNS via Cloudflare)", matching the existing `vpn.kubelab.live` precedent; the mermaid DNS diagram gained the matching direct Cloudflare→ace1 edge and dropped "pihole" from the extra_records edge label. `CLAUDE.md`'s stale gotcha and `docs/architecture/dash-001-homepage-cockpit.md`'s two historical references fixed too. 4 new named regression tests added to `tests/test_sync_homepage_config.py`, each confirmed to fail against the pre-fix code (reverted the fix, re-ran, restored) before being confirmed green against the fix. `make sync-homepage` regenerated `custom.js`; `kubectl kustomize` on both overlays confirmed zero remaining `pihole.staging` references.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons.md`? Yes — three: n8n cgroup-throttling diagnosis and Argo CD live-vs-git drift (PR #1026, merged), plus the review's own finding (a domain rename silently staling a generator's hardcoded output, with no test coverage for generated-artifact accuracy).
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? No — this is a routing/naming fix within ADR-037's existing promotion strategy, not a new architectural decision.
- [x] New pattern candidate for `00_meta/patterns/`? No — single-occurrence so far (this repo, this generator); revisit if the same "generator hardcodes a domain instead of deriving it from SSOT" shape recurs elsewhere.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/<feature-id>/` -> `specs/archive/<feature-id>/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
