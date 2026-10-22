# Run ap-20261022-kubelab-idp

Verdict: run ap-20261022-kubelab-idp ended `queue-empty` after 2 items, about 1h20 (07:36Z to 08:58Z).
- Done 2, parked 0, merged 2, unmerged 0.
- Nothing irreversible is waiting on you. Both merges are docs, toolkit and tests only, and each can be reverted with a PR.

## Waiting on you, irreversible first

- #2630 `promote: prod web to 1.16.2` is human-gated, so it was not merged by this run. It is the first real release through #2624's `contract` step:
  - run 39737786611 ran `product release-contract` for 1.16.2 with no `::error::`;
  - the render then printed `web/prod: nothing to write`;
  - the PR carries only the version pin and the generated deployment, because the 1.16.2 contract equals the committed prod snapshot.

  Merging it deploys web 1.16.2 to prod.
- #1926 (IDP-042):
  - AC1's live unmapped dispatch, using the command in the AC1 row of `verification.md`;
  - then `dotf spec archive IDP-042-product-contract-registry`;
  - then close #1926.

## Parked

None. #2627 was not claimed: its AC1 (which `sha-` tag the proof looks up) is in the two functions #2449 Q4 covers, so it waits for that ruling (commented on #2627). #2611 is SPECULATIVE and has no design, so it was not picked.

## Done but unmerged

None.

## Evidence index

- #2628, merged `326e56dd` (`dotf pr land`, exit 0). IDP-042 closeout:
  - the round-3 review (PASS-WITH-GAPS) is recorded and its gaps are dispositioned;
  - the `cicd.md` rollback path is documented.
  - Triage comments: 6335115553 and 6335682051.
- #2641, merged `4c97ddd5` (`dotf pr land`, exit 0). It closes #2610 (board: Done). `site_domain` and `site_url` are rendered from the contract hostname.
  - `make test-fast`: 6516 passed, exit 0.
  - `make mutate` went RED three times: staging `site_domain`, prod `site_url`, and the renderer's derivation.
  - `render --check`: 8 keys compared in both envs.
  - Drift / staging and Drift / prod were green on the head.
- #2627 (IDP-054) was filed and is in the board's Backlog.

## Budget spent

2 iterations of 6, about 1h20 wall clock, 2 items of 3. There is no dollar figure.

The GraphQL quota was spent from 07:40Z to 08:32Z by parallel sessions. #2628's land was withheld until the reset, then landed.

## Host suspend

`caffeinate -i -t 36000` ran from 07:36Z. The window was covered.

## Next action

Decide #2630 (prod web 1.16.2).
