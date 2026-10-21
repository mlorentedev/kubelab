# Run 20261021-kubelab-auth

Objective: land #2582, publish api 1.1.6 (#2558), and work the operator-decided
tickets (#1356 B, #2492 B) up to what needs the operator.

## Landed

- #2582 (`4d487337`): Uptime Kuma port allowlist (#2482 phase 1). Applied to rpi3
  from master: changed=7, then changed=0. Live chain verified (one copy, three
  sources, one jump), Kuma healthy, status.kubelab.live 302. Evidence on #2482.
- api 1.1.6 published from `sha-7d09373` (same digest
  `sha256:0b4a92ae...0415`), #2558.

## Open, waiting on the operator

- #2595 (part of #1356 B; closes #2493 and #1454): touches SOPS vaults and the
  secrets catalog, so the operator merges it. Head `497ff6fa`. Three PR-Agent
  rounds triaged: fail-loud on a missing derived Kuma username (`a6aa382f`), the
  rewrite count corrected in the `rotate_secret` docstring (`da2b4557`, #1454 AC5),
  a fixture comment reworded (`497ff6fa`). The first PR body line would have closed
  all of #1356; now "Part of". AC mapping posted on #1454.
- #2589 (#2492 B): draft until prod serves api 1.1.6. Staging 7 passed; prod
  (1.1.0) fails the 2 new tests as expected.

## Parked / decisions

1. Run `gh workflow run promote-prod.yml --repo mlorentedev/kubelab --ref master -f app=api -f version=1.1.6`
   (the dispatch was refused here), review and merge its PR; then mark #2589 ready.
2. Merge #2595.
3. #2482 phase 2: A (auth off, any pod on the spokes gets Kuma admin),
   B (NetworkPolicy to Traefik only, then auth off; recommended) or C (keep Kuma's password).
4. #2599 after phase 2 (Kuma password written per env, read from common).
5. #909 (TOOL-018, `make credentials-reset-password`): unblocked (#934 closed) but parked:
   no single default identity any more, and the Make variable cannot be `USER`. A/B on the issue.
6. #2565 in the operator's own worktree. #2562 reconfirmed by run 39542946736.

## Filed

- #2599.
- #2600 (certifi, Dependabot alert #96, critical; outside this run's scope).

## Worktrees removable

fix-kuma-port-allowlist-2482 (merged), fix-api-publish-2558, fix-authelia-jwks-2377,
fix-retire-kubelab-oidc-1777, fix-kuma-perimeter-2483, fix-oidc-mint-from-ssot-1777,
fix-oidc-pair-hub-agree-2522, chore-autopilot-run-20261018-auth. Keep
fix-e2e-api-health-2492 and fix-identities-out-of-sops-1356 while their PRs are open.

## Token expiries

github_migration_token 2026-10-27, r2_token_minter 2026-11-03, dev_node.github_token 2026-11-06.

## End

queue-empty: the remaining epic #2390 children need a browser (#2154), write SOPS (#1884) or change auth behaviour without a decided plan (#1845, #1876).
