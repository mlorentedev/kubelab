# Run 20261022-kubelab-auth

Verdict: queue-empty after one item. #1876 landed (#2642, `c2404176`, merged under
the grant at 09:27Z; issue closed, board Done).

Objective: work the remaining auth epic #2390 children that pass the 3 a.m. test
inside the envelope.

## Worked

- #1876 AUTH-012, PR #2642: `make auth-review` judges Argo CD's live RBAC policy
  per tier (reads `policy.csv` and `policy.default` from the hub, asks the pinned
  image's evaluator one shared matrix). Live read-only check against the hub:
  admin ok, operator ok, viewer ok. 233 executable lines. Lesson-618.
  PR-Agent, two runs: 1 applied (`-o json`; its "always fails" claim was refuted by
  the live read), 2 declined with reasons. CodeRabbit and Codex had no quota.

## Waiting on you

1. Run `make auth-review ENV=prod` once after #2642 merges (it opens break-glass
   paths, which page the operator channel; not run at night).

## Parked

None.

## Not eligible (why the queue is empty)

The open #2390 children need a SOPS write (#1796, #1884), frozen paths
(`infra/k8s`, `infra/ansible`: #1783, #2339, #1389), a spec (#952, #1742, #474,
#477), a browser (#2154), or an operator decision (#1845 changes prod Authelia on
merge, #1822, #2296, #2227). #2632 has a peer PR (#2633).

## Evidence index

- `make lint`, `poetry run mypy toolkit`, `make test-fast` (6521 passed), access
  review tests with docker integration (82 passed).
- Mutation proofs red: live default ignored, work dir out of `$HOME`, docker
  missing reads ok, inverted predicate. `--user` survives on Colima (lesson-618).
- #2415 confirmed Done on the board after the GraphQL reset.

## Budget

1 of 4 items. GraphQL primary and secondary limits cost about 35 minutes
(07:55Z-08:35Z); issue and PR writes went through REST meanwhile.

## Host

caffeinate on for the run (30000s from arming).

## Next action

After #2642 lands, run `make auth-review ENV=prod` and read the three argocd
policy rows.
