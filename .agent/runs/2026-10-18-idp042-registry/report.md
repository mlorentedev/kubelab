# Run 2026-10-18-idp042-registry

run 2026-10-18-idp042-registry ended envelope-expiry after 3 items / ~8h (armed 08:34Z, envelope expiry 16:34Z): 2 done, 0 parked, 1 merged, 2 unmerged.

**What is waiting on a human, and is anything in it irreversible?** #2470 (registry, closes #1815) is ready but unlanded: head `b6ce4dd9` waits on its ~19-minute `Tests`, and every reviewer finding is already disposed in three triage comments. Land it with `dotf pr triage-queue --pr 2470` then `dotf pr land 2470` once that head is green. PR 5 waits on your review and merge, because it touches `.github/workflows/promote-prod.yml`, which the grant excludes.

## Waiting on you, irreversible first

1. **Landed (irreversible):** #2474 merged at `ac4b2831` under the standing grant (fixes #2469; `toolkit config generate` exits 0 for staging and prod again). #2470 is NOT landed. Its `Tests` failed on `2dd05b16` with 3 lesson-index tests (`596 lessons, 598 files`), a stale count in the master the CI merge ref picked up, not this diff. Current master declares 598, and `b6ce4dd9` merges it in. The re-run finishes after the envelope, so the run stopped there rather than landing out of window.
2. **PR 5 (IDP-042 literals from the registry): #2526 (draft, stacked on #2470: base `feat/idp-042-product-registry`; after #2470 squash-merges, `git rebase --onto origin/master 0b62c16f` plus a force-push, then retarget to master), open, operator merge only.** It touches `promote-prod.yml`. Two judgment calls are listed in its body:
   - (a) with `types` gone, every dispatch starts the workflow, and staging events end green as "not this lane";
   - (b) `inputs.app` loses its dropdown.

   If you prefer to keep `types: [web-release-published]` asserted against the registry, that is a one-line revert plus a test change.
3. **#2399** (dead `web_build_args` in `ci-pipeline.yml`): verified unreachable (callers pass only `api` and `errors`). Not fixed here because that workflow is outside the envelope's `write_paths`.
4. **#2511** (filed this run): `registry prune` names repositories `<prefix>-<app>`, while Q7 derives `<app>` for products without an override. Latent; no product hits it today.

## Parked

None.

## Evidence

- **#2474:**
  - Test `test_the_authelia_template_renders_clients_without_an_alg` covers staging and prod. `make mutate` (the `is defined` reverted to a truth test) turned it RED.
  - `poetry run toolkit config generate --env staging|prod --force` exit 0.
  - CI green, PR-Agent finding resolved, `dotf pr triage-queue --pr 2474` exit 0, then `dotf pr land 2474` printed `[MERGED] #2474 at 0e94e29`.
- **#2470:**
  - Overlays byte-identical before and after (`diff -r` empty for `infra/k8s/overlays/{staging,prod}/generated`).
  - `make test-fast`: 5881 passed. PR-Agent ran five passes. Every REAL finding was applied with a mutation proof:
    - the reverse drift guard;
    - the deploy fields;
    - the committed web pin;
    - the non-empty loop.
  - The THEORETICAL cache finding was declined with its reason. Triage comments `#issuecomment-6251728517` and `#issuecomment-6251890271`.
- **PR 5:**
  - `make test-fast`: 5906 passed, and 1 failed (`test_toolkit_readme`, a stale generated command table). Fixed by `toolkit tools cli-reference --write`, and that test passed afterwards.
  - `make lint`, `make type` and `actionlint promote-prod.yml` clean.
  - Six `make mutate` proofs RED. One was first GREEN (`grep -qxF` → `-qF`), which added `test_a_part_of_a_product_name_is_not_a_product`.
  - `github.event.action` carrying the dispatch `event_type` was confirmed against GitHub's webhook payload docs.

## Budget

- 3 items: #2474, #2470, PR 5.
- No consecutive failures.
- max_loc held: PR 5 adds about 105 executable non-test lines.
- **Host:** `caffeinate` held the Mac awake on AC power for the whole window.
- **Gap:** roughly 11:20Z to 15:30Z went to a claude.ai usage limit, not to host sleep. Nothing ran in that gap, which is why #2470 landed late in the window.

## Next action

When `b6ce4dd9` is green on #2470: `dotf pr triage-queue --pr 2470` and `dotf pr land 2470`. Then rebase #2526 onto master (`git rebase --onto origin/master 0b62c16f`), push, mark it ready, review and merge it yourself. The peer session (`feat-idp-042-contract-schema`, PR 4 #2486 and PR 3 #2520) waits on #2470 too.
