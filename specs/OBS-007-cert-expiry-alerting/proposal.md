---
id: "OBS-007-cert-expiry-alerting"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-09"
issue: "kubelab#799"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# OBS-007: Cert Expiry Alerting

> **Naming**: file lives at `<repo>/specs/OBS-007-cert-expiry-alerting/proposal.md`. `OBS-007-cert-expiry-alerting` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #799: OBS-007: alert on cert expiry and ACME renewal failure (staging on-demand) -->


Certificate automation in this estate works until it doesn't, and when it doesn't, nothing says so. In June 2026 staging's Let's Encrypt certificates failed to renew for roughly five weeks behind a stale Cloudflare API token, and the failure was discovered by a browser error rather than by any alert. The gap is not the renewal — Traefik renews on its own at 30 days remaining — it is that a renewal which stops working leaves no signal anywhere a human looks.

The cost of leaving it is measurable rather than hypothetical, because the same gap is still swallowing failures today. While building this spec, the first Traefik log line Loki returned for **prod** was a live ACME error that had been repeating roughly once a day for months, entirely unobserved (fixed in #927). Measured on the live cluster the same day: Grafana holds **zero alert rules and zero contact points**. There is nothing watching, so the honest description of the current state is not "alerting is thin" but "alerting does not exist".

This is MON-001's lesson arriving a second time: automation without observation converts a failure into an invisibility.

## What


Three observable changes, all provisioned as code rather than clicked into the Grafana UI:

1. **A Grafana alert rule evaluates a Loki query over Traefik's logs** and fires when Traefik reports an ACME failure. Today that query returns matching lines and nothing acts on them.
2. **A contact point and a notification policy exist**, so a firing alert reaches Telegram. Neither exists today — the substrate is the bulk of this work, not the rule.
3. **`kubectl exec deploy/grafana -- wget -qO- .../api/v1/provisioning/alert-rules` returns a rule instead of `[]`**, and the rule survives a pod restart because it is provisioned from a ConfigMap rather than stored in Grafana's database.

Two findings that shrink the work, both measured today rather than assumed:

- **The contact point needs no secret.** Per ADR-044 Option B, Apprise owns the tag→URL map: the Telegram bot token lives inside `apprise-secrets` and callers send only a tag. Grafana reaches Apprise in-cluster with no credential — verified by `kubectl exec -n kubelab deploy/grafana -- wget -qO- http://apprise:8000/status` returning `OK`. So the contact point is `http://apprise:8000/notify/kubelab` with a tag in the body: plain config, an ordinary ConfigMap, and none of the ADR-035 out-of-band machinery that a secret-bearing config would have forced.
- **Unified alerting is already on.** The provisioning API returned `[]`, not a 404. No Grafana configuration change is needed beyond mounting a `provisioning/alerting` directory.

**The two severity tiers already exist, and they carry the environment split.** Apprise routes tag `page` to the push channel and tag `log` to the archive channel. Decided 2026-08-09: **prod alerts go to `page`, staging alerts go to `log`.** Staging still alerts — it is where the June incident happened, and the issue asks for it explicitly — but it does not interrupt, which matches staging being on-demand and non-critical. No new severity model is invented.

## Out of scope


- **Layer 2 of the issue — the lagging time-to-expiry net.** Both halves: enabling Uptime Kuma's built-in cert-expiry notification on the RPi3 (different host, different deploy surface, Ansible not Kustomize) and the scheduled `test_tls_routing.py` run for staging. Genuinely useful, genuinely separate.
- **Layer 3 — evaluating cert-manager** to replace Traefik's built-in ACME. That is an ADR-sized decision about who owns certificate lifecycle, not a task inside an alerting spec.
- **#918 / OBS-010 (quota utilization alerting)**, even though it will reuse exactly this fabric. Building the fabric well is this spec's job; being the first consumer is enough.
- **Alerting on anything else Traefik logs.** The substrate makes more rules cheap; adding them here would hide the substrate's cost behind a pile of rules.

## Risks / open questions


- **RESOLVED 2026-08-09 — scope is any ACME failure, not just expiry or renewal.** The issue's title says "cert expiry and ACME renewal failure", but today's live bug was neither: it was an *impossible order* for a `.local` domain Let's Encrypt can never issue. The narrow framing would have excluded the very case that motivated the work, and it also rests on an unconfirmed log string (see below). Decision: **alert on any ACME failure Traefik reports, whatever its cause.** This widens the spec beyond its own issue title, deliberately.
- **RESOLVED 2026-08-09 — one rule, two delivery tiers.** Grafana runs in staging and prod from the shared base (ADR-028 as amended by #920), so a rule in `base/` fires from both into the same Telegram. Decision: **prod routes to tag `page` (push), staging routes to tag `log` (archive)** — using the two tiers Apprise already provides rather than inventing a severity model, and matching the fact that staging is on-demand and non-critical while prod is not. Staging still alerts, which the issue explicitly asks for ("staging on-demand") and which is where the June incident happened; it simply does not interrupt.

  The mechanism follows the repo's established idiom: `base/` carries the staging value and the prod overlay patches it. Note this puts the tier in a *patched* field, which is exactly the shape that failed silently in #927 — so the acceptance criteria verify the rendered output per environment, not the patch.
- **The renewal-failure log line is unverified.** Seven days of prod Traefik logs contain exactly two ACME-related lines: `Unable to obtain ACME certificate for domains error="…"` (the failure) and `Testing certificate renew… acmeCA=…` (a periodic heartbeat, not an error). The issue proposes matching `Error renewing ACME certificate`, which appears nowhere in the retained window. Traefik plausibly emits the same "unable to obtain" line for a failed renewal, since renewal re-enters the same resolver path — but **no renewal has failed inside Loki's retention, so this is a hypothesis, not an observation.** Matching a single exact English phrase is therefore the fragile choice; a pattern that catches ACME lines while excluding the known heartbeat is more robust and should be preferred until a real renewal failure confirms the wording.
- **Traefik's log lines carry ANSI escape codes.** The raw line is `[31mERR[0m [1mUnable to obtain ACME certificate[0m …`. A substring match still works because the phrase is contiguous between escapes, but Loki's `detected_level` reads `unknown` rather than `error` for these lines — so **filtering by log level will not work**, and the rule must match on text.
- **Verifying the alert requires inducing a failure, not waiting for one.** The only live firing signal is the prod loki error, and #927 removes it. Staging's DNS-01 flow works, so it produces no ACME failures at all. The acceptance test therefore has to create one deliberately — a throwaway IngressRoute requesting an unissuable domain — and clean it up. Same philosophy as IDP-031's surge test: exercise the case rather than trust the reasoning.
- **The Grafana Deployment gains a `provisioning/alerting` volume and mount.** This is the deployed-config-schema change that put this work through the Discipline Gate. Use `configMapGenerator` with `files:`, following the existing `grafana-dashboards` pattern — its hash suffix also gives rolling restarts on rule changes for free, which matters because Grafana does not hot-reload provisioning files.
- **Merge-order coordination.** #923 (IDP-031) and #927 (the loki ACME fix) are both open and both touch `infra/k8s/`. The files look disjoint from this work, but that should be stated in the PR rather than discovered during a rebase.

## Acceptance criteria


- [ ] `GET /api/v1/provisioning/alert-rules` on Grafana returns at least one rule, and `GET /api/v1/provisioning/contact-points` returns the Apprise contact point — both in staging and prod, and both surviving a `rollout restart` of Grafana.
- [ ] A deliberately induced ACME failure in staging (a throwaway IngressRoute for an unissuable domain) causes the rule to transition to `Alerting` and a message to arrive in Telegram, within the rule's evaluation interval plus its pending period.
- [ ] The rule does **not** fire on the `Testing certificate renew…` heartbeat, verified by leaving it enabled through at least one heartbeat with no ACME failure present.
- [ ] The alert payload names the affected domain and the environment it came from, so the recipient can act without opening Grafana.
- [ ] The teardown of the induced failure returns the rule to `Normal` and a resolved notification is delivered, confirming the rule recovers rather than latching.
- [ ] `kubectl kustomize` renders tag `log` for the staging overlay and tag `page` for the prod overlay — asserted against the **rendered output**, not the patch file. #927 is the precedent: a patch that looked correct changed nothing, and only reading the rendered field would have caught it.

## References

- Bitácora board: **kubelab#799**
- **PR #927** — the live prod ACME failure this spec would have caught; found while writing it, and the reason the framing question above is not academic.
- `docs/lessons.md` → MON-001 (2026-08-09) — automation without observation makes failure invisible; the same shape one layer down.
- **ADR-044** — Apprise owns the tag→URL map, which is why this contact point carries no credential. Implementation: `toolkit/features/k8s_secrets.py::_build_apprise_config`.
- `docs/adr/adr-028-operational-topology.md` (amended #920) — why Grafana runs in both environments, which is what makes the base-vs-overlay question above real.
- Sibling pattern to copy: `infra/k8s/base/services/grafana-dashboards/` — `configMapGenerator` with `files:`, hash-suffixed for rolling updates.
- **#918 / OBS-010** — the next consumer of this fabric; a reason to build it as code rather than by hand.
- Measurement method: Loki queried through the Grafana pod (`wget` is absent from the Loki image), `container="traefik"`, prod cluster, 2026-08-09.
