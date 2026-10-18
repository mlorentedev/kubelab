# Run 2026-10-18-vk

**Verdict:** run 2026-10-18-vk ended `window-expired` after about 8h, 2 PRs merged (#2464, #2475), 1 ready but unlanded (#2481), 0 parked, 0 prod writes. Waiting on the operator: land #2481, the `errors` release and promotion PRs (both reach prod), and the prod label sync. Nothing irreversible was done by this run.

## Waiting on you (irreversible first)

0. **Land #2481** (area labels): head `dd0fb297` (CodeRabbit and PR-Agent findings applied, triaged, master merged); CI was still running at 16:35Z. When Tests are green: `dotf pr triage-queue --pr 2481 && dotf pr land 2481`. If `attestation` shows a cancelled run, re-run the latest `review-attestation` (cancelled by design when a reviewer comments).
1. **Merge the `errors` release PR, then the promotion PR** (#2475 shipped `feat(errors):` so release-please will open one; promotion PRs are operator-merge only, #2431). This is what makes the new logo reach `assets.<env>.kubelab.live/brand/` and Vikunja. After promotion: check `logo.png` serves the new bytes, and that the Authelia portal shows the new mark. `authelia-assets` has a stable ConfigMap name, so if the old mark persists, restart Authelia.
2. **`make sync-vikunja ENV=prod` twice** after #2481 lands: the first creates the 37 `area:*` labels, the second must report `changed=0`. Staging was off (503), so AC1 of #2480 has no live proof yet.
3. **Record the two Vikunja token expiry dates** in `values/staging.yaml` and `values/prod.yaml` under `secret_expiry.declared` (#2464 reports their absence as a finding by design).
4. Not touched, yours: #2320 (Vikunja 2.7.0, irreversible), #1981 (BACKUP-065, needs a provider/credential decision), importer #2465 (no spec; WIP limit 20 > 10), Gitea logo #2473 (after #2375), content-hashed brand URLs #2472.
5. Browser check as `manu` that the Vikunja board shows the labels and the new logo (AC7).

## Done (merged unless marked)

| PR | Result |
|---|---|
| #2464 | Vikunja tokens catalogued as declared-expiry; never-raise report; `UNWRITTEN` entry removed. |
| #2475 | New node-graph brand mark across edge assets, Authelia copies and Vikunja URLs (`?v=2026-10-18`); lesson-597; byte-identity, RGBA, 400x400 and no-rect tests. |
| #2481 (open) | Area labels declared once in `common.yaml` (37 areas), created by the reconciler; refuses non-AREA, duplicate, trailing-newline, empty and scalar values. Not merged: CI pending on `dd0fb297` at window end. |

Each PR carries `## Review triage` comments (PR-Agent reviewed; CodeRabbit and Codex posted quota notices, not reviews).

## Parked / not picked

#2320, #1981, #2465 as listed above.

## Notes

- A force-push to the rebased #2481 branch was denied; I merged master instead and pushed normally.
- One Tests failure on #2481 was an unrelated socketio timeout (`test_monitoring_integration`), green on re-run.
- PR-Agent `review` jobs sat queued for 40+ min on two PRs (see #2420).
- Tickets filed: #2471, #2472, #2473, #2480.

## Evidence index

CI green on each landed head (`gh pr checks`), `dotf pr triage-queue --pr N` clear before each `dotf pr land`; mutation proofs via `make mutate` (rect, fullmatch).

## Budget

Wake-lock `caffeinate -i -t 30000` held for the window.
