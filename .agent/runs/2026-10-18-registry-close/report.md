# Run 2026-10-18-registry-close

run 2026-10-18-registry-close ended objective-met after 1 item / ~2h (armed 22:55Z, envelope expiry 00:55Z): 1 done, 0 parked, 0 merged by this run, 1 unmerged (#2526, operator merge only).

**What is waiting on a human, and is anything in it irreversible?** Only #2526, which is yours to review and merge because it touches `.github/workflows/promote-prod.yml`. Nothing irreversible happened in this run: no merge, no deploy, no prod write. #2470 had already landed (`5ca78385`, closes #1815) before the run was armed.

## Waiting on you, irreversible first

1. **#2526 (IDP-042 PR 5, literals from the registry): ready, triaged, operator merge.** Head `359c3106`. Master was merged in at `f99cef84` after #2531 landed, and again at `359c3106` after #2486 landed. The conflicts were in `tests/test_product_cli.py`, where both blocks were kept, and in `toolkit/README.md`, which was regenerated with `toolkit tools cli-reference --write`. #2520, from the peer session, adds `render` to the same `product.py`. If it lands first, #2526 needs one more merge of master. CI state at disarm: see *CI at disarm* below. The two judgment calls in its body still stand: (a) without `types`, every dispatch starts the workflow and staging events end green as "not this lane"; (b) `inputs.app` loses its dropdown.
2. **What CI and review found on #2526 after master was merged in, all fixed with red-first tests and `make mutate` proofs:**
   - **CI-only failure, root cause:** hosted runners have no sops. `product_registry.registry_path()` read the lazy `settings`, which builds `ConfigurationManager`, which prints `[WARNING] SOPS is not installed...` **on stdout**. That line came before `app-for-event --json`'s object, and jq failed at column 9 (the `]` of `[WARNING]`). It never showed locally because sops is on the Mac's PATH. Fix `ce78a4ef`: the registry reads `PROJECT_ROOT`.
   - **A fail-open in the workflow, which that failure exposed:** a non-JSON or lane-less answer read as an empty lane, which is not `prod`, so a web release would have ended **green as a skip**. It now fails, naming what the toolkit printed (`9101442b`, `efd69fb9`). PR-Agent tagged this THEORETICAL; it was real.
   - **`make promote-prod APP=-vweb` was dispatched:** grep took the value as options. Now `grep -qxF --`. PR-Agent tagged this THEORETICAL as well; it was real.
3. **#2536 (filed this run):** the toolkit logger writes diagnostics to stdout, so every `--json` command is one warning away from corrupt output. Two options are in the ticket: (A) `Console(stderr=True)`, broad; (B) per-command subprocess guards. It needs your call.

## Parked

None.

## Worktree sweep (coordinated with the peer sessions)

The removal commands are in the final chat message and in the vault handoff (thread `feat-idp-042-product-registry`). Unfinished worktrees are deliberately absent from the list.

## Evidence

- **Reproduction, before the fix:** with `PATH="$(dirname $PY):/usr/bin:/bin"`, `python -m toolkit.main product app-for-event web-release-published --json` printed two `[WARNING] SOPS is not installed.` lines and then the object.
- **New tests, each red before its fix:**
  - `test_app_for_event_json_is_the_only_stdout_without_sops`
  - `test_product_list_prints_only_the_products_without_sops`
  - `test_no_registry_read_builds_the_settings`
  - `test_an_answer_that_is_not_json_fails_instead_of_skipping`
  - `test_an_answer_without_a_lane_fails_instead_of_skipping`
  - `test_a_toolkit_failure_that_is_not_json_names_its_output`
  - `test_an_app_that_looks_like_a_grep_option_is_not_a_product`
- **`make mutate`:** RED for each of these mutants:
  - `settings.project_root` restored in `registry_path()` and `platform_registry()`
  - the lane read made lenient (`|| true`)
  - `-e` removed
  - the raw-output fallback emptied
  - `--` removed

  The first `-e` mutation came back GREEN against the non-JSON test, because the two forms are equivalent for parse errors. That gap is why `test_an_answer_without_a_lane_fails_instead_of_skipping` exists.
- **`make test-fast` on `efd69fb9`:** 6020 passed, 3 failed. All three were the lesson-index count tests (master drift, removed by #2531). Master `3a30a025` (#2531) was then merged in as `f99cef84`, and those three tests plus the PR's tests passed: 138.
- **Checks:** `make lint`, `make type` and `actionlint promote-prod.yml` were clean. The six PR test files passed (132, then 133 after the no-lane test).
- **Triage:** `## Review triage` posted on #2526 at `#issuecomment-6256545906`. PR-Agent's 2 findings were applied. Codex hit its usage limit, which is a notice, not a review.

## CI at disarm

- **`f99cef84`:** every check green, including `Tests`, `Drift / staging|prod`, `review-attestation` and CodeRabbit.
- **PR-Agent re-reviewed that head** and posted 4 findings. Triaged at `#issuecomment-6256812148`:
  - **REAL, applied:** `registry prune --apps ""` would have pruned every registered product. It now prunes nothing, as before.
  - **Applied:** a failing `product list` in the workflow now annotates the run.
  - **Two declined, with reasons:** both concern stderr and a registry that does not parse, which cannot reach the default branch.
- **The fixes are on `415b1247`.** It was pushed at 00:02Z and superseded by the merge `359c3106` (00:16Z), whose CI result is **green on every check, `Tests` included** (00:36Z; the merge state is `MERGEABLE`/`CLEAN`). PR-Agent re-reviewed `359c3106` and repeated only the two declined findings, one of them reworded under a new ID; this is recorded in `#issuecomment-6257043746`. `dotf pr triage-queue --pr 2526` exit 0. The affected suites passed locally on the merge: 199 tests. `dotf pr triage-queue --pr 2526` exit 0.

## Budget

- 1 item (#2526), within 4 iterations, with no consecutive failures.
- Host: `caffeinate` held the Mac awake for the window.

## Next action

Review and merge #2526 yourself once its checks are green on `359c3106`. Then decide #2536 (A or B).
