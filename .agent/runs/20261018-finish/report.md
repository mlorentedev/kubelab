# Run 20261018-finish: disarm report

run 20261018-finish ended goal-done after about 1h15m: 2 merged (#2495, #2502), 1 held (#2514), 1 follow-up PR opened (#2537), 0 parked. Objective: land #2495, #2502 and #2514 when green, clean and triaged, then sweep worktrees and hand off.

## Waiting on you, irreversible first

1. **#2502 merged (`ac1a2c5d`).** Nothing reaches a node until you provision. In this order:
   1. `make provision NODE=ace1 ENV=staging`, then the VPS (`make provision NODE=vps ENV=prod`).
   2. Check that a zone-settings call with the in-cluster token returns 403 (it holds DNS: Edit only).
   3. Issue a staging cert for a new host through DNS-01.
   4. Rotate `cloudflare.api_token`. Until then the old token still exists on the nodes.
   - #2459 stays open (`Refs`) until these four are done.
2. **#2495 merged (`87be6b2b`).** Live Cloudflare is unchanged until the apply.
   - `make tf-dns-apply`: 4 to add (imagesensortool.com zone settings with HSTS off, plus 3 CAA), 0 to change, 0 to destroy, the rest moves.
   - Then `make tf-dns-plan` should read no changes, and #2460 can be closed (it now says `Refs`, AC2).
   - Check first that the `kubelab-terraform` token can still edit DNS records: in the Cloudflare list it shows only Zone Settings and Zone.
3. **#2537 (docs, follow-up to #2495), open for you.** Two live docs still named `records_kubelab.tf`/`records_mlorente.tf`. It is not in this run's `merge_allowed`.

1. **#2514 (#378, ingress NetworkPolicies): not merged, on purpose.**
   - The staging check passed every step except `n8n-probe` (PR comment issuecomment-6256369624). The probe could not run because staging Vikunja is stuck in `wait-for-idp` (`bad address 'auth.staging.kubelab.live'`, 7h+, #1783, comment issuecomment-6256369817).
   - So n8n → vikunja:3456 and a fresh vikunja → postgres connection are not measured. Merging would deploy to prod through `selfHeal` with that path unproven.
   - To unblock: fix #1783, then `make argo-set-revision APP=kubelab-staging REV=feat/issue-378-netpol-ingress`, then `make n8n-probe ENV=staging`, then `make argo-set-revision APP=kubelab-staging REV=master`. The PR body carries the same recipe.
   - Optional: a `kubectl exec` denial probe from a pod that no policy names, run by you.
   - Staging was returned to `master`.

## Findings outside this run (not acted on)

`toolkit secrets check-expiry` (run for the ACME token) also reported:

- `apps.services.core.gitea.github_migration_token` expires 2026-10-27.
- `cloudflare.r2_token_minter` expires 2026-11-03.
- `dev_node.github_token` expires 2026-11-06.
- An old Headscale key has already expired, and the n8n `sale_digest` analytics token is expiring.

## Done

| Item | Result | Evidence |
|---|---|---|
| #2495 | Merged `87be6b2b`. HSTS off for imagesensortool.com (it serves nothing), CAA kept, runbook and README match the zones map | mutation RED; `make test-fast` 5928 passed; `make tf-dns-plan` 4 to add, 0 change, 0 destroy, rest moves; triage issuecomment-6256289934 |
| #2502 | Merged `ac1a2c5d`. `cloudflare.acme_dns_token` stored by you, committed `1365f2e8` | check-expiry: valid, no expiry; triage issuecomment-6256274488 |
| #2514 | Empty selector reads as every pod; each caller source has its own floor | mutation RED x2; 11 tests pass; triage issuecomment-6256272109 |

## Not done, and why

- #2514 is not merged: see above.
- Master was red from `51e12b25` on the lesson index count (600 declared, 601 files), which blocked #2495 and #2502. The run waited for peer PR #2531 (merged 23:33Z), merged master into both branches, re-triaged PR-Agent's updated guides (issuecomment-6256748926, issuecomment-6256749127), then landed them.
- One disclosed gap on #2514: the port filter mutation stays green, because no current input exercises it.
