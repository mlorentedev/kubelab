---
id: lesson-405-the-gh-cli-reports-success-it-did-not-achieve-in-two-places
type: lesson
status: active
created: "2026-08-26"
owner: manu
category: process-method
tags: [kubelab, process-method, github, gh-cli, rate-limit]
---

# The `gh` CLI reports success it did not achieve, in two unrelated places

**Context**: A long session doing board queries, issue reads and PR body edits through `gh`, alongside two parallel sessions doing the same against the same account.

**Problem**: Two independent cases where the tool exited without doing the work.

**1. `gh pr edit --body-file` silently does nothing.** Updating #1455's body printed a deprecation notice and returned:

```
GraphQL: Projects (classic) is being deprecated ... (repository.pullRequest.projectCards)
```

The body was unchanged. The notice is about a field `gh` requests incidentally, not about the edit — but it aborts the mutation and the failure reads as a warning. Caught only by grepping the live body afterwards and finding the old text. `gh api -X PATCH repos/{owner}/{repo}/pulls/{n} -F body=@file` performed the edit.

**2. `gh api rate_limit` reports a bucket as full while that bucket rejects.** After GraphQL calls started failing with *"API rate limit already exceeded"*:

```
$ gh api rate_limit --jq '.resources.graphql'
graphql: 5000/5000       # while every GraphQL call is refused
```

Filtering for buckets actually below their limit told the true story — `graphql: 0/5000, reset in 12m` — so the summary path and the detail path disagreed within the same response. REST (`core`) was untouched at 4980/5000, which is what made the workaround obvious once the real number was visible: `gh issue view` is GraphQL, `gh api repos/.../issues/N` is REST, and the same information is reachable by both.

**Solution**: For the edit, verify the effect rather than the exit code — re-read the body and grep for a string only the new version contains. For the limit, never read the top-line number; filter for resources where `remaining < limit`, and know which subcommands are GraphQL (`gh issue view`, `gh pr checks`, `gh project`) versus REST (`gh api repos/...`), because a GraphQL exhaustion leaves 4/5 of the work still possible.

**Rule**: Both cases are the same failure as [lesson-402](lesson-402-a-push-to-a-merged-prs-branch-recreates-it-and-exits-zero.md)'s `git push` — **a tool reporting success it did not achieve** — and they share a remedy: for any operation whose effect lives on another system, verify by asking that system what it now believes, not by reading the exit code of the thing that asked it to change.

Two smaller rules worth keeping on their own:

- A deprecation notice that appears on stderr while a mutation fails is indistinguishable from a warning on a successful mutation. Treat any unexpected output from a write command as a failure until the effect is confirmed.
- The GraphQL budget is scored by query *complexity*, not by call count, and it is shared across every session and agent on the account. Nested board queries (`projectItems` → `fieldValues`) are expensive; running several sessions in parallel makes the ceiling arrive far sooner than the call count suggests.

**Tags**: `#gh-cli` `#rate-limit` `#github` `#pr-1455`
