---
id: lesson-544-giteas-empty-flag-is-written-at-push-time-and-never-re-read-from-git
type: lesson
status: active
created: "2026-10-09"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, gitea, reconciler, backup]
---

# Gitea's `empty` flag is written at push time and never re-read from git

**Context**: lesson-541 made `make gitea-reconcile` read content, not existence: a declared
repository that the forge holds `empty: true` is reported and fails the run. PR-Agent flagged
the remaining gap on #2143: does the flag come back when a repository that held content loses
every ref, the shape a partial restore leaves (#2144)?

**Problem**: Measured on a throwaway `gitea/gitea:1.25.5`, the version prod runs:

- Zero refs cannot be reached by deletion. `DELETE .../branches/main` answers 403 `can not
  delete default branch`, and `git push --delete main` is rejected the same way.
- Zero refs reached on disk (every file under `refs/` and `packed-refs` removed) leaves
  `GET /repos/{o}/{r}` answering `empty: false` indefinitely. The flag is a database column set
  when a push is processed. Nothing re-reads git to clear or set it.
- `GET .../git/refs` answers 404, which is the truth. `GET .../commits` answers 500.
- Pushes are processed asynchronously: right after a push, `empty` still reads `true` for a
  few seconds. A measurement that does not wait for it reads its own race.

So a reconciler reading only the flag reports a repository that lost its content as converged.
The repair also differs from a never-filled shell: `drop-empty` refuses it, since the flag says
not empty, and a re-migration has no source once the GitHub copy is retired.

**Solution**: `GiteaClient.has_refs` reads `/git/refs` (404 means none; any other failure
raises). `plan_reconcile` takes the result as a required mapping and reports
`lost_content_repos`: present, flag not `true`, no refs. The CLI exits 1 with the R2 restore. A
`push --mirror` of the restored bare repository into the existing ref-less one brought back
every branch, tag and commit on the same scratch instance.

**Rule**: A forge's metadata flag answers "what did the last event write", not "what is in git
now". When a convergence check guards against content loss, read the content layer (refs), and
measure the loss on a scratch instance through the path the loss would actually take; here that
path was the disk, because the API forbids it.

**Tags**: `#gitea` `#reconciler` `#issue-2144`
