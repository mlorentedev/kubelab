# Run ap-20261102-kubelab-console

**Verdict:** ended queue-empty after about 9h of a 12h window: 9 PRs on the objective, 8 merged by the run, 1 (#2933) merged from the operator's account during the run, 0 unmerged, 4 items parked. Nothing irreversible is waiting; prod secrets and the Postgres tenant are live and unused until a release ships.

## Waiting on you

1. **Release PR #2890.** Prod's API is 1.1.6 and the tag api-v1.2.0 does not contain the driver, so prod has the tenant and the tables but nothing using them. Prod image promotion was authorized but could not happen: there is no released image with the code. Merging the release unblocks it, and it is also the only way to measure the Gitea grant (the token is prod-only).
2. **Staging deploy PRs #3007, #3005, #3003, #3002, #2968, #2967, #2966.** Staging runs `sha-80171ff`, without the forge code, because these wait for a human. #3007 (`sha-75346a3`) is the one validated below.
3. **Parked, with the question:**
   - Queue endpoint and Authelia in front of it. The route is public-facing, which this envelope forbids, and ADR-074 is undecided. Also the inbox reasons (requested reviewer, failing CI) need data the listing does not return: (A) extra calls per item against the hourly ceiling, or (B) add them from webhooks only.
   - Which Gitea repository is a source, and wiring its reader: (A) one org-wide source, (B) a list of repositories.
   - Delivering `FORGE_GITHUB_WEBHOOK_SECRET` and `FORGE_GITEA_WEBHOOK_SECRET`: touches SECRET_CATALOG, which this envelope kept open. Until then every delivery is refused with 401 and only the reconcile feeds the model.
   - Atlas in CI: `.github` was frozen and `migrate lint` is paid: (A) pay, (B) keep the local check.
   Secondary, #279 AC2: widening `config-check-drift` to `deployments.yaml` collides with the generated deploy PRs; a DELIVERY-004 call.

## Done and merged

#2932 driver, #2933 migration, #2943 tenant, #2999 migration Job, #2976 App tokens, #2997 webhook receiver, #3001 reconcile, #3004 projection, #3008 record of the live read.

## Not clean, say so

- **Reviewed by PR-Agent alone.** Codex was out of quota and CodeRabbit limited or summary-only all run. Commits pushed after PR-Agent's pass on some PRs merged without a further pass from it.
- **Two hours lost** to a wait loop silently broken by an unquoted `?` in zsh.
- **Staging `grafana-admin` Secret was rewritten** by `apply-secrets ENV=staging` and Grafana restarted. It differed from SOPS beforehand, cause unknown: #3006.
- **First read after pod start failed** with connection refused from Postgres, and the reconcile then waits a full 10 minutes. Cause not established; a NetworkPolicy race on the new pod is the guess. Not ticketed as a defect until seen again.
- Old branch `feat/data-007-migration-job` remains on the remote; deleting is forbidden to the run.

## Evidence

- Staging, 2026-11-02 14:38:53Z, image `sha-75346a3`: `forge_source` reachable with `as_of` set; `forge_item` 612/14/584/1726, identical to `gh api search/issues`; pod 11 MiB, 0 restarts; unsigned webhook 401. Slot returned to master, peer told.
- Prod: Job `api-migrate-0af59188bc` Complete, `/health` 200.
- Local: `FORGE_TEST_POSTGRES_PORT=55432 go test ./internal/forge/ ./internal/store/ -count=1` exit 0, twice on one database.
- `dotf pr triage-queue --pr N` clear before each land; `## Review triage` on each PR.

## Budget

9 items against max_items 8 counting the record PR; no breaker tripped. No dollar figure exists.

## Host

Wake-lock held the whole window (caffeinate); homelab reachable throughout.

## Next action

Merge #2890, then #3007.

## CONSOLE-005 parity: what is still missing

Read path works without a UI. Missing: queue endpoint and page behind Authelia, narrow writes with outbox and audit, Slack capture re-pointed (#2586), Gitea source, webhook secrets, Grafana statistics and alert, restore rehearsal and runbook, the e2e probe, then A8's 14 days. Vikunja untouched.
