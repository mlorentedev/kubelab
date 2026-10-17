---
id: gitea-upgrade
type: runbook
status: active
owner: manu
created: "2026-10-17"
tags: [gitea, upgrade, forge, backup, sre]
---

# Upgrading the Gitea forge

> **Thesis:** Gitea's schema migrations run at start and cannot be undone, so the only way back is the
> snapshot taken just before. An upgrade is therefore rehearsed on a restored copy first, then applied
> through the IaC path, never by hand on the node. Spec: `specs/OPS-038-gitea-forge-upgrade/`.

## When

A pinned version (`apps.services.core.gitea.image` in `infra/config/values/common.yaml`) moves, for a feature
or a security fix. The 1.25.5 to 1.27.3 move (OPS-038, #2375) is the worked example: workflow `concurrency`
needs 1.26 or later.

## 1. Read the notes between the two versions

Release posts at blog.gitea.com for every version in between, and the upgrade guide at
docs.gitea.com/installation/upgrade-from-gitea. Look for: removed or renamed `app.ini` keys, changed
defaults, removed API endpoints, a new minimum runner version, and anything under authentication.
Migrations run in order at start, so skipping minors is supported; the rehearsal is what proves it on our data.

## 2. Rehearse on the newest snapshot

1. Pin the candidate on a branch (`image: gitea/gitea:<version>`), commit and push it. The drill refuses a
   dirty tree and a commit the host has not got.
2. Run the baseline first, on the deployed version, with the same probes (lesson-585). Pin the old image on a
   throwaway branch and run the drill; record which probes fail there.
3. Run `make backup-drill-gitea ENV=prod HOST=ace2` on the candidate. It restores the newest R2 snapshot into
   a scratch directory on ace2, starts the pinned image on it **with no network**, and passes only if:
   - every restored repository passes `git fsck --full` and its branch heads are known to live;
   - `gitea doctor check --all` shows nothing the baseline did not (`KNOWN_BASELINE_FAILURES` names the rest);
   - the REST v1 contract answers: issue create, comment (2xx with `html_url`), edit;
   - `PATCH /repos/{o}/{r}` merge settings are applied and read back.
4. What the drill cannot reach (it has no network) is checked another way before the live step: Authelia OIDC
   login, the PR-Agent app and runner registration. Record each result on the spec.

`make backup-drill-gitea` without `HOST` needs `restic` and `docker` on the machine running it; the ace2 path
needs neither locally.

## 3. Window and backup

Tell the peers that call the API (`dotf forge` in dotfiles#2649 and #2635, the forge reviewer) the date and
the downtime. Then take a fresh node backup so the restore point is minutes old:

```bash
make backup-node NODE=bee ENV=prod
make backup-drill-gitea ENV=prod HOST=ace2   # on the CURRENT pin: proves this backup restores
```

## 4. Apply

```bash
make sync-platform-json        # platform.json mirrors the pin
make provision NODE=bee ENV=prod TAGS=gitea
make provision NODE=bee ENV=prod TAGS=gitea   # second run: changed=0
```

Then check `/api/healthz`, one push, one PR, one OIDC login, the runner listing (`Settings > Actions >
Runners`) and the anonymous surface (`tests/infra/test_gitea_anonymous_surface_live.py`: its recorded answers are
the 1.25.5 ones, so a changed default shows up there first). A forge workflow that sets `concurrency` is the measurement for the ticket: two quick pushes to
one branch, the second run cancels the first, including when the first is already running.

## 5. Roll back

There is no downgrade of a migrated database. Stop Gitea, restore the snapshot taken in step 3 into
`/opt/gitea/data` (restic restore to a scratch directory, `PRAGMA integrity_check` on `gitea/gitea.db`, then
move it in; see `docs/runbooks/offsite-backup-restore.md`), pin the previous image in `common.yaml`, and
provision again. Pushes made after the snapshot are lost: that is the cost, which is why the window is short
and announced.

## Known quirks

- `gitea doctor check --all` reports `Garbage collect LFS` as an error on 1.25.5 and 1.27.3 alike against our
  data, and still exits 0. The text is read, not the status.
- 1.25.5 ignores `PUBLIC_URL_DETECTION`; 1.27.3 accepts `legacy`, `auto`, `never` and refuses anything else at
  start. The compose template pins `legacy` (the 1.25 behaviour) so the upgrade changes one thing at a time.
- The runner (`gitea/act_runner:0.2.13`) is upgraded by OPS-034 (#2063). The Cancelling state for running
  jobs needs Gitea Runner 2.0.0 or later on a 1.27 server.
