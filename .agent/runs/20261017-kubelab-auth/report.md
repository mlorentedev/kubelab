# Run 20261017-kubelab-auth

run 20261017-kubelab-auth ended queue-empty: all 8 items done (max_items 8), none parked. 9 PRs merged, 0 unmerged. Armed 07:38Z, closed ~13:40Z.

What waits on a human: the owner-only steps listed below. Irreversible actions taken: nine merges (seven with prod effect, all verified live) and one prod session flush.

## Waiting on you, irreversible first

Already landed in prod. Each is verified, with the evidence on its PR:

| PR | Item | Merge | Prod evidence |
|---|---|---|---|
| #2395 | Renovate note on Authelia approval | `443027ae` | docs only |
| #2402 | #456: prod Homepage behind Authelia | `e501ce3a` | anonymous `/` and `/api/services` answer 302 to Authelia, `/api/healthcheck` answers 200. Uptime Kuma monitor id=499 edited, re-check plans 0 changes |
| #2403 | #1593 (+#900): self-service password reset off | `9aebb07a` | `tests/infra/test_authelia_password_reset_closed_live.py -m infra`: 2 passed (red before the merge) |
| #2404 | #2374: dead Loki Bearer route deleted | `407cc110` | before merge, a Bearer probe on staging hit Authelia (302), so the router was never live. Prod emitted object unchanged |
| #2405 | #2377 part 1: webauthn key moved to 4.39 | `0f1548a1` | prod Authelia logs show only the `issuer_private_key` deprecation (part 2) |
| #2410 | #1813: remember_me disabled | `c93a2d4a` | portal `data-rememberme="false"` |
| #2412 | #1813: Grafana bounded by Authelia, signs out through it | `d0456613` | pod env `8h` / `1h` / `SIGNOUT_REDIRECT_URL`, `/logout?rd=` answers 200 |
| #2411 | #1782: OIDC consumers held to the SSOT client_id; Compose Grafana id derived (#1782 closed) | `bd84bbfd` | loader and tests only; `make test` 5748 passed on the merged head |

**Prod sessions flushed** (`make flush-sessions ENV=prod`, ~13:00Z, after prod Authelia read `authelia-config-c26dchgmf4`). Every SSO user signs in again. This was promised in #2410's body and is not reversible, but it costs only a login.

Owner-only steps. None of them blocks anything already merged:

1. **#900 / #1593 AC4**: retire `jwt_secret_reset_password`. Remove the SOPS key in each env and the `SECRET_CATALOG` entry in one change, because `tests/test_secrets_orphan_audit.py` fails if only one goes. `validate-config` measured that the secret is required only while reset is enabled. #900 was changed from Closes to Refs, so it stays open.
2. **Browser round trip for #2412**: sign out of Grafana, and the next sign-in must prompt.
3. **Passkey ceremony for #2405**: check that a passkey login still asks for the same user verification.
4. **#2397**: the `merge-grant.yml` PR stays yours (a PR that changes the grant is never merged under it).
5. **Argo CD logout URL and lifetime** (#1813, ADR-062 amendment table): reaching the hub needs `make deploy-argocd`, which is owner-gated.
6. **Homepage's future** (#2416): #2402 put the cockpit behind Authelia. Whether to fold it into the public web or retire it is your decision, recorded on #2416.

## Parked

None.

## Done but unmerged

None. #2411 conflicted twice on the generated `platform.json` as peers landed (#2400). It was regenerated each time and merged at `e2a5a7d5`.

## Filed during the run

- **#2415**: the dev Compose Grafana sets no session bound and no Authelia sign-out (`infra/stacks/**` was outside the envelope). ADR-062's table names it as open.
- **#2416**: decide the Homepage cockpit's future, following the owner's statement of 2026-10-17.
- **#2419**: hold Grafana's OAuth endpoint URLs to each overlay's Authelia (epic DoD: no hand-written IdP URL).

## Evidence index

| Item | Command | Result |
|---|---|---|
| #2403 | `pytest tests/infra/test_authelia_password_reset_closed_live.py -m infra` | 2 passed |
| #2402 | `make monitoring-apply CHECK=1` after the apply | `0 create, 0 edit, 0 delete` |
| #2410 | `make mutate` on the template mapping, and on `common.yaml` `session_remember_me` | RED both times |
| #2411 | `make mutate`: derivation call removed, `setdefault` restored | RED both times; `make test` 5748 passed |
| #2412, #2410 | live config hash compared with `kubectl kustomize infra/k8s/overlays/prod` | equal (`c26dchgmf4`, `7ttt26fbkb`) |

## Notes

- Out of this run by `max_items: 8`: #1777, #1355, #1356 (epic #2390 continues).
- Debt observed, not mine: PR-Agent run `32217810608` (`docs/attestation-gate-docs`, created 2026-08-19) still shows `queued`. It does not block the FIFO; reviews ran past it all day.
- The session was paused ~10:15–12:40Z by a usage limit. No work was lost: nothing was in flight.
- Leftover worktrees: `dotf worktree done` refuses some of them over ignored files (`poetry.lock`). Removing those is your call, as in earlier runs.
