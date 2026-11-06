# Run report: 20261106-kubelab-obs

- Armed: 2026-11-06T06:52:25Z, expires 14:52:25Z. Envelope: `.agent/unattended.yml` at 0119c6d5.
- Objective: close observability, alerting and load-test debt tickets from the queue, each landed with tests and its knowledge recorded.
- End reason: queue-empty (every remaining item ineligible, see below).

## Items

| Item | Outcome | PR |
|---|---|---|
| #3010 Headscale health probe | Premise measured false (v0.28 answers `/health` with `{"status":"pass"}`); record corrected, manifest reads `health_path`, e2e asserts the key. Merged. | #3168 |
| #3012 load-test review gaps | Quoting, `measured` flag, comment pin, pod-less edge tests; four review passes applied. Merged. The leftover-route detection is parked: issue Blocked, options (A) per-run random header / (B) watcher + Grafana rule, owner decides. | #3173 |
| #2998 PVC drill false green | A firing sooner than the rule's `for:` is reported not measured. Staging drill on the head fired at 42.3m and was counted. Merged. | #3174 |
| #2195 ACME rule quiet check | `make acme-quiet-check ENV=<staging|prod>`, read-only, exit 0/1/3. Prod green, live mutations red. OBS-007 f3 points at it. Five review passes; the last moved an unreadable rule from exit 1 to 2 so 1 means only a regression. Merged. | #3176 |
| #2942 | Skipped: touches `.github/workflows` (frozen, owner merges). | |
| #2207 | Skipped: needs ace2 powered off physically. | |
| #3156, #2391 | Skipped: covered by the peer's #3169. Note posted on #2391. | |

## Filed during the run

- #3164 (OPS-068): Headscale healthcheck `headscale version` -> `headscale health`, after an in-container read; carries the CLAUDE.md line to replace (CLAUDE.md was frozen for this run).
- #3181: `platform_manifest.py` `health_path` fallbacks hide a missing SSOT key, all eight rows.

## For the owner

1. #3012: choose option A or B for leftover-route detection.
2. #3164: the CLAUDE.md gotcha "Headscale v0.28 has no HTTP /health endpoint" is false; the replacement line is in the issue.
3. #2942: yours to merge (workflow change).
4. Staging (ace1, ace2) stopped answering on the tailnet some time after 07:25Z; rpi4 still answers. Nothing in the repo can bring them back remotely. #3176's staging run therefore reads `not measured` (exit 3); its prod run is green.

## Reviews

CodeRabbit was rate limited and Codex out of usage for the whole run: every PR was reviewed by PR-Agent only, and each triage comment says so.

## Incidents

- GitHub Actions queues of about an hour; GraphQL secondary rate limit blocked `dotf pr land` from 08:48Z to 09:40Z (rate_limit reported quota left). Waited instead of merging by hand.
