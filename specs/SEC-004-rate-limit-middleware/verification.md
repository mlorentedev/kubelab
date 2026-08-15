---
tags: [spec, verification, templates]
created: "2026-08-14"
---

# Verification - SEC-004-rate-limit-middleware

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] Criterion 1 (Middleware object, SSOT-sourced) -> commit `5806f13` / test `tests/test_rate_limit_middleware.py` (4/4 passing)
- [x] Criterion 2 (every IngressRoute references it) -> commits `9e96098` (generated routes) + `e5c70b0` (17 hand-written files) / tests `tests/test_k8s_generator_middlewares.py` (3/3) + `tests/test_rate_limit_coverage.py` (2/2)
- [x] Criterion 3 (burst drill: fires above threshold, clean below, isolated, shared-vs-per-router settled) -> manual staging drill, 2026-08-15 (see below) — no permanent test, same treatment OBS-010's surge drill and IDP-031's prod-ordering checks got: a one-time measured event against live infrastructure, not a repeatable assertion
- [x] Criterion 4 (`config-check-drift` stays green) -> commit `9e96098` / `make config-check-drift ENV=staging` and `ENV=prod`, both green

## Test status

- Test suite: `make test-fast` -> 519 passed, 136 deselected (zero regressions; +9 from this spec's new tests: 4 + 3 + 2)
- Manual smoke test (staging, 2026-08-15):
  - Burst drill on `home.staging.kubelab.live`: `ab -n 300 -c 100` -> 88/300 HTTP 429, 212/300 HTTP 200 (expected ≈223 admits at burst=150 + ~2.45s refill at average=30/s — 212 observed, consistent with configured values)
  - Cross-route probe (bucket-sharing test): immediately after exhausting Homepage's bucket, 5/5 requests to `grafana.staging.kubelab.live` returned clean 302 (not 429) — no shared state
  - Grafana burst-tested directly, to rule out "exempt route": `ab -n 300 -c 100` -> 104/300 HTTP 429 — confirms an independent bucket, not exemption
  - Clean-below-threshold, properly discriminated: deploy -> read live middlewares list (`rate-limit` present) -> single probe, all chained -> HTTP 200
  - `kubectl kustomize` cross-check for both envs: 14 staging + 16 prod rendered `IngressRoute` routes, zero missing `rate-limit`
- No regressions in existing test suite: yes

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- **Pre-implementation investigation (2026-08-14) already produced one significant finding, captured here for continuity even though implementation hasn't started**: klipper-lb (K3s's built-in ServiceLB) MASQUERADEs every client's source IP before Traefik sees it, confirmed empirically in staging (temporary access log + `externalTrafficPolicy: Local` test, both reverted cleanly). This forced the scope from a per-client to a global rate limit and spawned a separate prerequisite issue (#1067) rather than silently narrowing this ticket. See `proposal.md` Risks section and #970's issue comments for full detail.
- **Values measurement (2026-08-14) hit an unrelated live incident first.** The planned Homepage-cockpit reload for burst measurement instead surfaced Homepage crash-looping (kubelet probes failing Next.js's `Host` header validation, compounded by an unpinned `:latest` image that had just pulled a breaking major version). Fixed and merged separately (#1073, not part of this spec) rather than blocking the measurement on an SEC-004-scoped fix — the bug was in Homepage's own manifest, unrelated to rate-limiting. Re-measured against the healthy, pinned pod: peak 49 req/s in the worst 1-second window, ~193 requests/60s, periodic client-side widget-refresh clusters of 15-20 req/s. Full detail in `proposal.md` Risks.
- **AC1's original wording pointed at the VPS's own `edge.traefik.rate_limit_*` keys — a real conflict, not a style choice.** K3s's measured values differ from the VPS's tuned-for-a-different-topology numbers, and those keys feed the VPS's Ansible-rendered middleware directly; writing K3s numbers there would have silently re-tuned the VPS on its next Ansible deploy. This lane also cannot touch `infra/ansible/` to restructure safely. Raised to the user rather than decided solo (per this project's naming-decision convention); resolved as new sibling keys, `edge.traefik.rate_limit_k3s_*`.
- **`sourceCriterion.requestHost: {}` (from the proposal) was schema-invalid — caught by a rejected dry-run, not a design review.** Traefik's CRD requires a boolean: `requestHost: true`. The dry-run apply failed loudly (`expected boolean, got &{map[]}`) before touching the cluster, exactly the failure mode a dry-run gate exists to catch. Fixed in the manifest, its test, and retroactively in `proposal.md`'s wording.
- **The burst drill required diagnosing and working around a live, unplanned Argo CD sync race (filed as #1083) before it could produce trustworthy numbers.** Staging's Application (`selfHeal: false`) still auto-syncs on any new master revision, and master moved several times during this session from parallel worktree lanes. Two early drill attempts produced zero 429s across 2000+ requests — not because the limiter was ineffective, but because Argo CD had silently reverted the Middleware reference minutes earlier, mid-investigation. Diagnosed via `kubectl get application ... status.history` (a new-revision sync landed at the exact moment of the false-negative) rather than assumed. Final drill numbers were produced by chaining deploy -> verify-live-state -> fire-immediately in single commands to close the race window, not by hoping it wouldn't recur.
- **Per-router bucket confirmed as the better outcome, not just the observed one.** A shared cluster-wide bucket would mean any one route's legitimate burst (or an attacker hitting the cheapest route) starves every other route's capacity — a rate-limiter-induced cross-route DoS. Independent per-router buckets (Traefik's actual behavior here) avoid that. Recorded as a deliberate design confirmation in `proposal.md`, not a footnote.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons.md`? Yes — two: (1) already captured pre-implementation: "K3s's built-in ServiceLB masks every client's real IP — `externalTrafficPolicy: Local` cannot fix it" (2026-08-14, tags `#k3s #networking #servicelb #klipper-lb #sec-004 #gotcha`). (2) New, this session: staging's Argo CD auto-syncs on any new master revision even with `selfHeal: false`, which can silently revert an in-progress manual staging deploy on a multi-lane day — see #1083 for the diagnosed mechanism.
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? No — the per-router-bucket behavior is a Traefik implementation fact this spec discovered and now depends on, not a decision this project made; the Argo CD sync gap is tracked as #1083 (its own future fix may warrant an ADR, this spec's job was diagnosis, not remediation).
- [ ] New pattern candidate for `00_meta/patterns/`? No — the "chain deploy -> verify-live-state -> act-immediately" technique used to work around the Argo CD race is specific to this one investigation, not a recurring pattern yet.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/<feature-id>/` -> `specs/archive/<feature-id>/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
