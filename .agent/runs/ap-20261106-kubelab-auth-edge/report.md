# Run report: ap-20261106-kubelab-auth-edge

- Armed 2026-11-06T06:51:37Z, ended 2026-11-06T10:35Z. Reason: queue-empty (all four items worked).
- Wake lock: caffeinate (pid 58903), AC power.

## Queue

| Item | Result |
| --- | --- |
| #3154 Argo CD passthrough ties the catch-all | Merged d37bafa. Verified in prod: `/api/version` 200, sign-in redirect works. Lesson-717. |
| #3138 Authelia per-host rules (#2669) | Merged f8fefafb by the operator's account at 06:45, before arming. Verified in prod after the restart: config has no `networks`, `default_policy: deny`, 9 rules; health OK; guarded hosts 302. |
| #3156 Detection gap (PR #3169) | Merged e93ea86. `make alerts` now lists Uptime Kuma DOWN monitors (also when Grafana is blind); Argo CD and API monitors use keywords only the service sends. Lesson-719. **`make monitoring-apply` NOT run**: Tailscale was stopped on the Mac from about 09:30 UTC, so Uptime Kuma (100.64.0.6) was unreachable. Not started without the operator. |
| #3135 Unserved staging routes (PR #3180) | Merged 6370024. Validated on staging via Argo revision pin, then pinned back to master. |

## Filed during the run

- #3167 n8n monitors measure Authelia, not n8n.
- #3172 Pi-hole staging monitor checks a retired name.
- #3179 break-glass `dev-node` entry outlived its route; no stale-entry check.

## Review notes

- Codex and CodeRabbit hit quota on most PRs; pr-agent reviewed every PR; all findings triaged on the PRs.
- pr-agent serializes reviews repo-wide (`pr-agent-nan-inference` group): up to about 90 min queue with parallel sessions.
- `dotf pr land` refused #3169 on a cancelled duplicate `attestation` check-run while a green one existed for the same head; rerunning the cancelled run unblocked it.

## For the operator

1. Start Tailscale on the Mac, then `make monitoring-apply CHECK=1` and `make monitoring-apply` (no PRUNE) for #3156.
2. Confirm the #3138 merge at 06:45 was yours.
3. #3110 and #3127 are owner merges; #2227 AC4 pending.
