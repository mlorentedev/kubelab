# Run 20261018-idp042-land: disarm report

run 20261018-idp042-land: ended goal-met after about 2 h of a 3 h window (armed 22:55Z, expires 01:55Z). 2 merged, 0 parked, 0 unmerged.

What is waiting on a human: nothing from this run. Both merges are ordinary feature PRs with no `infra/config/values` change; nothing irreversible beyond the merges.

## Merged

- #2486 (IDP-042 PR 4, contract guards + registry wiring): squash `ee2cb80f`, landed with `dotf pr land` at head `bb7f6df7`. Four PR-Agent rounds triaged on the PR. The real catch: the hostname guard only read values declarations, so 8 of 31 route hosts in `infra/k8s` (hand-written IngressRoutes such as `argo.kubelab.live`) were claimable. It now also reads the committed manifests.
- #2520 (IDP-042 PR 3, render + drift + snapshot completeness): squash `df21c254`, landed at head `f47c276c`. Four PR-Agent findings applied: `write()` refuses a missing values block instead of raising `KeyError`; `render` requires `--app` outside the snapshot directory; a test holds every `auth_level` in the values to what a contract can render; the committed registry's exempt set is checked too.

## Not done, and why

- Force-push is denied to this session, so both branches took master by merge instead of rebase.
- The board Status of #1926 was not updated: GraphQL had been rate limited all evening. #1926 stays open, with PR 5-8 still to go.

## Waiting on others

- #2526 (PR 5, peer lane feat-idp-042-product-registry-7c, operator merge only: touches promote-prod.yml): it needs one more merge from master after #2520 (expected overlap `toolkit/cli/product.py`, `toolkit/README.md`).
- For PR 6 (receiver): `toolkit product render` requires `--app` for a fetched `kubelab.yaml`.
- The repo-wide triage queue lists #2517 and #2498 (feat-1957 lane, not this run).

## Evidence

- #2486: `make test-fast` 6001 passed before the README regeneration (the one failure was the stale CLI table); `make mutate` RED on: the in-tree refusal, the manifest hosts, the own-host exclusion, and the registry override.
- #2520: `make test-fast` 6020 passed; drift tests 22 passed, also with `SOPS_AGE_KEY_FILE`/`SOPS_AGE_KEY` unset. `make mutate` RED on: snapshot completeness (3 directions), the missing-block refusal, the `--app` requirement, and the auth mapping. The first auth test stayed GREEN under mutation (it read only `apps.platform`) and was widened until RED.
- `dotf pr triage-queue --pr 2486` and `--pr 2520`: exit 0 before each land.

## Host

Wake-lock `caffeinate -i -s -t 12600` was held for the window.
