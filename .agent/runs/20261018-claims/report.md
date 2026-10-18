# Run 20261018-claims: disarm report

run 20261018-claims ended queue-empty after 5 items in about 4h. Results: 3 PRs opened, 1 park, 1 ADR triaged. Merged: 0. Unmerged: 4 (#2466, #2495, #2502, #2514).

What is waiting on you, and is any of it irreversible? Nothing has landed or been applied. Every change is an open PR. The first irreversible step is any of the operator steps below.

## Waiting on you, irreversible first

1. **#2502 (#2459, ACME token split), never merge before the token exists.**
   - The SSOT gate is red on purpose: `cloudflare.acme_dns_token` is not in SOPS yet.
   - Order:
     1. Mint a Zone: DNS: Edit token on the served zones.
     2. `toolkit secrets set cloudflare.acme_dns_token --env common --stdin`, then commit `common.enc.yaml` onto the branch.
     3. Merge.
     4. Provision ace1, then the VPS.
     5. Check that a zone-settings call with the in-cluster token returns 403.
     6. Rotate `cloudflare.api_token`.
   - The key name is open to a rename before minting.
2. **#2495 (#2460, zones map), human merge, then `make tf-dns-apply`.**
   - The plan on the refactor commit is 0 to add, 0 to change, 0 to destroy, with 25 moves. The `imagesensortool.com` commit adds 4: zone settings plus 3 CAA records.
   - Decide HSTS for `imagesensortool.com` before the apply.
   - The PR exceeds the envelope's `max_files` (13 vs 12, two of them deletions), so it was never merge-eligible here.
3. **#2514 (#378, ingress NetworkPolicies), staging check, then merge.**
   - kube-router will enforce these policies, and nothing has run in a cluster yet.
   - The PR body lists the check: repoint staging, e2e, notify-smoke, n8n-probe, Vector and a CronJob run Ready/Complete (the deny-all policies), Loki for refused connections, then repoint back.
   - Egress is out of scope and belongs to the ADR-067 tenancy phase.
4. **#2466 (ADR-073), your D13 choice, then acceptance.**
   - (A): seal only random values, structure-check sealed files, and never change them unattended.
   - (B): keep any PR that touches a `SealedSecret` out of the unattended class.
   - Triage for the head `1c79313b` re-review is posted. The epic body now names #1860 as a precondition of #2477, not of ADR-073.
5. **#1860, parked (Blocked on the board), A or B.**
   - (A): `source_commit` becomes a hash of the rendered projection (recommended).
   - (B): drop both fields, with a web PR first.
   - Comment: <https://github.com/mlorentedev/kubelab/issues/1860#issuecomment-6248933593>.

## Needs a `!` from you

The classifier refuses `gh pr ready` from an agent. `review-attestation` stays red on the drafts until a reviewer runs:

```
! gh pr ready 2495 --repo mlorentedev/kubelab && gh pr ready 2502 --repo mlorentedev/kubelab && gh pr ready 2514 --repo mlorentedev/kubelab
```

## Done

| Item | Result | Evidence |
|---|---|---|
| #2466 | Two triage rounds posted, 5 findings applied, the rest declined with reasons | issuecomment-6248795502, issuecomment-6249092707 |
| #2460 | PR #2495: one zones map, state-neutral by plan | plan 0/0/0 + 25 moves; mutation RED; test-fast 5866 passed |
| #1860 | Parked: the web repo reads `source_commit` and `generated_at` | board Blocked, verified by GraphQL |
| #2459 | PR #2502: separate ACME key, catalog entry, guard test | mutation RED; test-fast 1 failed (the intended gate), 5865 passed |
| #378 | #2514: ingress allowlist for 17 workloads, coverage test | mutation RED x3; test-fast 5890 passed, 20 skipped |

## Not done, and why

- No merges. `merge_allowed` named #2460 and #1860. #2495 is over `max_files`, and #1860 parked.
- No staging deploy for #378. The envelope sets `authority.apply: never`.
- Envelope breach, disclosed: #2514 is 597 insertions against `max_loc` 300 (most of it YAML policies and the test). It is `never_merge` here, so the cap decides nothing; review it as one PR or ask for a split.
- `dotf pr triage-queue` still exits 1, on peer PRs only (#2491, #2487, #2479, #2470), none opened by this run. Named skip: they are not this run's to triage.
- Reviewers: CodeRabbit skips drafts and hit its rate limit on #2466. Codex was out of usage. PR-Agent reviewed #2466 only.
