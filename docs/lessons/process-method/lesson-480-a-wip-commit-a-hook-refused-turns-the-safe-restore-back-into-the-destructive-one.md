---
id: lesson-480-a-wip-commit-a-hook-refused-turns-the-safe-restore-back-into-the-destructive-one
type: lesson
status: active
created: "2026-09-27"
owner: manu
category: process-method
tags: [kubelab, process-method, git, mutation-testing, pre-commit]
---

# A WIP commit that a hook refused turns the safe restore back into the destructive one

**Context**: APP-CONFIG-016 (#1871). The n8n probe had just gone green, and a
mutation was needed to show that its description check could fail. The
procedure from lesson-365 was followed: commit, mutate, `git checkout HEAD --`.

**Problem**: the commit never happened. `ruff format` reformatted a file, and
pre-commit refuses a commit whose hooks modified files. The command's output
had been discarded (`>/dev/null 2>&1`), so the refusal went unseen. HEAD was
still the previous *red* commit, and `git checkout HEAD -- toolkit/features/n8n_probe.py`
restored the file to its state before the implementation. The whole probe was
gone, and the tell was lesson-365's own: a file that `grep` said held
`signed_pr_merge_closes_its_task` a minute earlier now held nothing.

Lesson-365 calls the restore "safe by construction". The construction has a
precondition that nothing checked: **the commit landed**. A refused commit
leaves the command's text unchanged and removes the only thing that made it
safe.

**Solution**: the implementation was rebuilt from the edit scripts still in
the transcript, and this time they were written to a file first. The loop now
proves the precondition before mutating, and stops if it fails:

```bash
git add -A && git commit -q -m "wip: <what is being proven>" \
  && test -z "$(git status --porcelain)" \
  || { echo "WIP commit did not land; not mutating"; exit 1; }
# mutate, observe red, then:
git checkout HEAD -- <file>
```

Two habits make the failure visible instead of silent:

- never discard a commit's output, since a hook refusal is only reported there;
- check `git log -1` or a clean tree after the commit, not the exit status of a
  pipeline whose last command was a `grep`.

**Rule**: a "safe by construction" step is only as safe as the check that its
construction actually happened. When a procedure's safety rests on an earlier
command succeeding, chain it with `&&` and verify its effect (HEAD moved, tree
clean). Never assume it succeeded because it usually does.

**Addendum (2026-09-30, TOOL-090, #1941)**: it recurred with the rule followed
half-way. The guard *was* chained with `&&` (`commit && test -z "$(git status
--porcelain)" && checkout <base> -- f && pytest`), so when mypy refused the
commit the mutation did not run. But the restore that closed the experiment
came after a `;`: `...; git checkout HEAD -- f`. It ran anyway, onto a HEAD
that never received the work, and removed three files' uncommitted changes. The
next commit then landed only the tests. The work came back from the blobs `git
add` had written (`git fsck --unreachable`, matched by content), which is the
only reason this is an addendum and not a loss. The whole experiment,
restore included, belongs inside the guarded group, and the group has to return
the test's status rather than the restore's, or a restore that succeeds hides
what the test said:
`test -z "$(git status --porcelain)" && { mutate && test; rc=$?; restore || rc=1; exit $rc; }`
(run it in a subshell, `( ... )`, so the `exit` ends only the experiment).

**Addendum (2026-10-07, MON-012, #2078)**: it recurred a third time, and a
new way: the commit's output was redirected (`>/dev/null 2>&1`), so the
`ruff format` refusal never showed. The `test -z ... && echo CLEAN` printed
nothing, and nobody noticed the silence. A `;` ran the experiment and the
restore anyway, and `git checkout HEAD -- toolkit/features/monitoring.py` reset
the file to `master`. The implementation came back from the session transcript.
Three recurrences by agents that knew the rule are the evidence lesson-365
predicts. The fix is a mechanism, not a fourth reminder: #2104 (TOOL-100), a
`make mutate` target that owns the order.

**Tags**: `#git` `#pre-commit` `#mutation-testing` `#lesson-365` `#issue-1871` `#issue-1941` `#issue-2104`
