# Run 20261018-kubelab-auth

**Verdict:** run 20261018-kubelab-auth ended `queue-empty` after 4 items in about 7h15m (08:27Z to 15:45Z). 2 items were done and 2 were disposed as not eligible; 2 PRs merged, 0 left unmerged. **Irreversible:** one prod auth change landed (#2491) and was verified in prod. No SOPS, Ansible or Terraform change was made.

## Waiting on you

The irreversible items come first.

1. **#2491 — Uptime Kuma edge perimeter (prod auth change).** **Merged** as `4cf03845` at about 15:36Z, under the standing grant, after two PR-Agent reviews, both triaged. One finding was applied, three were declined with evidence. Prod was verified at 15:40Z: `/dashboard`, `/`, `/socket.io/` and `/metrics` → 302 to auth.kubelab.live; `/api/entry-page` 200; `/api/push/not-a-token` 404; `make monitoring-apply` made 1 edit, and a re-run then planned 0 changes; `make test-e2e ENV=prod` 71 passed, 0 failed; `make alerts` showed nothing firing. **To revert it**, open a revert PR of `4cf03845`. Prod self-heals to master.
2. **#2513 — `credentials generate` mints OIDC secrets from `oidc_clients` (#1777 AC1 and AC2).** **Merged** as `5fa8138d`, under the grant, after a PR-Agent review (partial run): 1 finding ticketed as #2522, 1 known gap (#1356), 3 declined. Correction recorded in the triage: my first disposition of finding 1 claimed an existing test covered the case, and it does not. That is why #2522 exists.
   No prod deploy follows the merge. The next `make credentials-generate ENV=prod` will also rotate Vikunja and Open WebUI. It prints the delivery each one still needs.
3. **#1777 AC3 — retire the `kubelab-oidc` pair.** This needs one of two things, and both were outside this run's write scope:
   - (A) Remove the two catalog entries and list both keys in `infra/config/orphan-secrets-baseline.yaml`. The baseline holds 14 of 16 entries today, so both fit without raising the cap.
   - (B) Run `toolkit secrets unset` on both keys in the dev, staging and prod vaults, then remove the catalog entries.
   A draft of (A) was audited: both keys showed as baselined orphans in all three envs.
4. **#1355 and #1356 were not taken: no plan, and a new `SecretSpec` contract would need a spec, which the WIP gate refuses at 20 of 10.** Both tickets carry the same fork:
   - (A) Preserve the existing identities.
   - (B) Stop writing identities and resolve them from `apps.auth.identities`.
   My suggestion is to fold #1355 into #1356.
5. **#2493 — Kuma `admin_user` shadow in `prod.enc.yaml`.** The writer is `setup_authelia_secrets`, so a SOPS edit alone is undone by the next run. That shadow also makes the Kuma reconcile sign in as the Authelia login instead of the Kuma superadmin.
6. **Kuma phase 2 (#2482, after #2491 lands):** check the perimeter in a browser, then decide whether to turn off Kuma's own login. Also parked on #2482: the Argo CD cold-visit route (needs `make deploy-argocd`), the Gitea, Open WebUI and Vikunja perimeters, and branding (now #2471).
7. **Peer PRs awaiting triage at session start:** #2481, #2479, #2475, #2474, #2470, #2466. Not this lane's to triage.

## Done

| Item | Result | Evidence |
|---|---|---|
| Kuma perimeter phase 1 (#2483) | PR #2491 (merged, verified in prod) | Staging, with the slot repointed and then restored to master: `/`, `/dashboard`, `/socket.io/` and `/metrics` → 302 to auth.staging; `/api/entry-page` 200; `/api/push/not-a-token` 404; statics 200. `make test-e2e ENV=staging`: 66 passed, 2 failed. Both failures are API `/health` checks broken by #2387, filed as #2492. |
| #1777 AC1 and AC2 | PR #2513 (merged) | The AC2 test was red on master in dev, staging and prod. `make test-fast`: 5872 passed. Mutation of the per-file print guard: RED. |
| #1355, #1356 | Disposition comments | Each lists two options. |

## Filed during the run (detect → ticket)

- #2482 AUTH-020: umbrella for the parked perimeter rows.
- #2483 AUTH-021: Kuma perimeter.
- #2492: API e2e checks broken by #2387.
- #2493: Kuma `admin_user` shadow. A comment adds the writer.
- #2508: stale `core.vikunja.oidc_client_secret` catalog entry. Nothing reads it, and its value differs from the live key.
- #2522: refuse an OIDC secret pair whose halves disagree on HUB_MANAGED (PR-Agent finding on #2513).

## Observed state, not new debt

- `make secrets-audit` exits non-zero on master. There are four `[ERROR]` expiry lines: `gitea.github_migration_token` on 10-27, `n8n.sale_digest.analytics_token`, `cloudflare.r2_token_minter` on 11-03, and `dev_node.github_token` on 11-06. Before #2464 merged, the uncatalogued `vikunja.reconciler_api_token` also counted against it.
- The pr-agent FIFO ran about 11 reviews deep at roughly 15 minutes each. Codex and CodeRabbit posted quota notices on #2491, not reviews.

## Budget

4 of the 4 `max_items` were touched and 2 of them were built. Iterations stayed within 8, with no consecutive failures. Spend was dominated by the PR-Agent FIFO (about 14 reviews deep) and one push to #2491 that re-queued its review. Codex and CodeRabbit sent quota notices for the whole run.

## Host

A `caffeinate -i` wake-lock held for the whole window. **The window was only partly covered:** a claude.ai usage-limit gap stopped the run from about 08:50Z to 10:30Z.
