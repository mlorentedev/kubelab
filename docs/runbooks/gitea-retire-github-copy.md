---
id: gitea-retire-github-copy
type: runbook
status: active
owner: manu
created: "2026-10-08"
tags: [gitea, github, migration, backup]
---

# Retire a repository's GitHub copy once Gitea holds it

> **Thesis:** a repository declared in `apps.services.core.gitea.organizations` lives only in
> Gitea, and the Beelink's R2 backups are its second copy (#1922, operator decision 2026-10-08).
> The GitHub repository it was migrated from is deleted, but only after Gitea is shown to hold
> everything the delete would destroy. Each gate below is a reading taken on the day, not a
> belief carried over from the migration.

Deleting a GitHub repository is irreversible for anyone but its owner and outward-facing. The
agent's `gh` token has no `delete_repo` scope on purpose, so **every `gh repo` write in this
runbook is run by the operator**. GitHub keeps a deleted repository restorable for 90 days
from Settings → Repositories → Deleted repositories; after that it is gone.

## Order

One repository at a time, in this order, because each is less settled than the one before:

1. `personal/resume`: already archived on GitHub, and complete in Gitea.
2. `teledyne/fae-brain`: needs the fast-forward below, and the operator's call on its GitHub-only
   CI (`eval.yml`) and Dependabot.
3. `teledyne/openkm-brain`: Gitea holds no code yet (#2133). Blocked until it is re-migrated.

## Gate 1: the reconciler is green

```bash
make gitea-reconcile ENV=prod
```

It must exit 0. Since #2133 it exits 1 on a declared migration whose repository is git-empty,
naming the repair. Do not read "forge matches the declaration" from an older checkout: before
#2133 it printed that over `teledyne/openkm-brain` with no code in it.

## Gate 2: every commit a GitHub ref points at is in Gitea

Every branch and tag GitHub holds must point at a commit Gitea also holds. Not "at the same
commit": Gitea may be AHEAD, which is the normal state once work moved there (`resume`'s `main`
differs between the two for exactly that reason), and comparing ref values would report that as
a loss.

```bash
S=$(mktemp -d)
R=<name>; O=<gitea-org>
make gitea-git ARGS="clone --quiet --mirror https://gitea.kubelab.live/$O/$R.git $S/$R.git"
git ls-remote --heads --tags https://github.com/mlorentedev/$R.git | while read -r sha ref; do
  git -C "$S/$R.git" cat-file -e "$sha^{commit}" 2>/dev/null || echo "MISSING $ref $sha"
done    # must print nothing
```

A `MISSING` line is history the delete would lose. If it is a branch GitHub moved ahead of
Gitea, fast-forward it (next section) and run the gate again.

Measured 2026-10-08: `resume` prints nothing (44 tags, every branch). `fae-brain` prints
`MISSING refs/heads/main`: GitHub is 8 commits ahead (4 Dependabot merges, #43 to #46) and 0
behind. `openkm-brain` holds no refs in Gitea at all.

## Fast-forward a branch GitHub moved

Only when Gate 2 shows a GitHub branch AHEAD of Gitea and Gitea has nothing GitHub lacks. A
branch that has diverged is a merge decision for the operator, not a step in this runbook.

```bash
git clone --quiet --mirror https://github.com/mlorentedev/$R.git "$S/$R-github.git"
make gitea-git ARGS="-C $S/$R-github.git push https://gitea.kubelab.live/$O/$R.git main"
# then re-run Gate 2
```

A push that Gitea refuses as non-fast-forward means the branch diverged: stop. Never `--force`.

**`fae-brain`: the push runs CI.** Gitea Actions reads `.github/workflows/` when a repository
has no `.gitea/workflows/`, and `eval.yml` runs on a push to `main` touching `package.json`,
`package-lock.json` and the source paths, which the Dependabot merges do. It needs
`NAN_API_KEY`, which Gitea does not hold, so the run fails. Push only once the operator has
decided whether that eval moves to Gitea (secret declared through TOOL-062) or is retired.

## Gate 3: the tracker is in Gitea

Issues and pull requests do not travel with git, and a deleted repository takes them with it.
Gitea's count must be at least GitHub's for both, in every state:

```bash
gh issue list --repo mlorentedev/<name> --state all --limit 1000 --json number --jq length
gh pr list    --repo mlorentedev/<name> --state all --limit 1000 --json number --jq length
```

Read Gitea's totals from the repository's Issues and Pull Requests tabs (open plus closed).
Any GitHub item opened after the migration exists only on GitHub. Decide each one explicitly:
a Dependabot pull request whose commits arrived through the fast-forward can be let go, and
anything a human wrote cannot.

Measured 2026-10-08:

| Repository | GitHub issues / PRs | Gitea issues / PRs | Gap |
|---|---|---|---|
| `personal/resume` | 93 / 165 | 154 / 276 | none |
| `teledyne/fae-brain` | 16 / 30 | 16 / 26 | 4 Dependabot PRs (#43 to #46), commits covered by the fast-forward |
| `teledyne/openkm-brain` | 18 / 17 | 2 / 0 (native) | everything: blocked on #2133 |

## Gate 4: nothing outside the repository depends on the GitHub copy

```bash
gh secret list --repo mlorentedev/<name>
gh api repos/mlorentedev/<name>/hooks --jq length
gh api repos/mlorentedev/<name>/keys --jq length
gh api repos/mlorentedev/<name>/pages 2>&1 | head -1
```

Secrets are names only, and their values cannot be read back, so a secret GitHub holds and
Gitea does not is one whose job stops existing with the delete. Measured 2026-10-08:

| Repository | GitHub Actions secrets | In Gitea |
|---|---|---|
| `personal/resume` | 4 × `GDRIVE_*`, `RELEASE_PLEASE_TOKEN` | the 4 `GDRIVE_*` (TOOL-062) |
| `teledyne/fae-brain` | `BITACORA_PAT`, `NAN_API_KEY`, `RELEASE_TOKEN` | none |
| `teledyne/openkm-brain` | `BITACORA_PAT` | none |

No hooks, deploy keys or Pages on any of the three. Outside the repository, the dotfiles repo
names two of them: `secrets/registry.yaml` lists `ci:mlorentedev/fae-brain` and
`ci:mlorentedev/openkm-brain` as targets of `BITACORA_PAT`, and `forge/branch-protection.json`
carries an entry for each. Remove those entries in a dotfiles PR in the same sitting as the
delete, or the next secret sync fails on a repository that no longer exists.

## Retire

Archive first. It is reversible, it stops Dependabot and every workflow, and it surfaces any
consumer that writes to the repository before the irreversible step does.

```bash
gh repo archive mlorentedev/<name> --yes
```

Leave it archived for a day. Then, with Gates 1 to 4 re-run and clean:

```bash
gh auth refresh -h github.com -s delete_repo
gh repo delete mlorentedev/<name> --yes
gh auth refresh -h github.com --remove-scopes delete_repo
```

Then remove any `github` remote from local clones (`git -C ~/Projects/resume remote remove
github`), and record the deletion on #2133.

## After the delete: `migrate_from` stays

The declaration keeps `migrate_from: github:mlorentedev/<name>`. It is the repository's
provenance, not a live remote. The alternative is worse: without it, a repository that
disappears from Gitea is planned as a CREATE and comes back as an empty shell, the state #2133
was about. With it, the reconciler plans a migration from a source that no longer exists and
fails loudly, which is the right signal. **A lost Gitea repository is restored from the R2
backup, never re-migrated** (`docs/runbooks/offsite-backup-restore.md`; the Gitea restore was
drilled in BACKUP-040 on 2026-10-01).
