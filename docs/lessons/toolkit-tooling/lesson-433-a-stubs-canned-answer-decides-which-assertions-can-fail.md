---
id: lesson-433-a-stubs-canned-answer-decides-which-assertions-can-fail
type: lesson
status: active
created: "2026-09-05"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, testing, stubs, mutation-testing, ci]
---

# A stub's canned answer decides which of your assertions can fail

**Context**: Fixing #1651 — `web-image-receiver.yml` pushes a staging branch and
then opens the PR that offers it, and six runs had failed between the two,
leaving the branch orphaned. The fix wraps the create in `if !` so the branch can
be deleted before the step exits red. Tests execute the shipped step with `gh`
replaced by a stub that logs every invocation, following
`test_pr_agent_workflow.py`.

One test guarded a risk the *fix itself* introduces. `if !` suspends `errexit`,
so an edit dropping the `exit 1` would fall through into the coalescing loop,
which closes the previous staging PR on the premise that a new one supersedes
it — leaving staging with no offer at all. Strictly worse than the orphan branch.
So: after a failed create, assert no `pr close` was issued.

**Problem**: The assertion could not fail. The stub answered `gh pr list` with
nothing, so **no `pr close` was reachable under any code at all** — not the fixed
step, not the broken one, not any step anyone could write.

This was not caught by reading it. It was caught by deleting `exit 1` from the
workflow and re-running:

```
FAILED test_a_failed_create_leaves_no_branch_behind
2 failed, 3 passed
```

Two failed, and the one named for this exact regression was not among them. A
different test caught the mutation, which is the detail that makes it dangerous:
the suite went red, so nothing looked wrong. Had that neighbour not existed, the
mutation would have shipped past a test whose name says it prevents it.

**Solution**: Give the stub an answer under which the forbidden call is possible.

```diff
-  "pr list"*) ;;
+  "pr list"*) printf '%s\t%s\n' "$STUB_STALE_PR" "deploy/staging-web-sha-0000000" ;;
```

With one stale PR in the listing, the mutation now fails the test that names it,
and the success path gained a real assertion for free — that coalescing still
closes `#1234` once the offer exists, so the change did not quietly break it.

**Rule**: An empty stub response is the most common way an assertion becomes
unfailable, because "returns nothing" is the laziest fixture and it silently
deletes the code path under test. Before trusting a negative assertion — *this
call must not happen*, *this field must be absent* — ask what the stub would have
to return for it to fail, and make sure the stub returns it.

The general check is cheaper than the reasoning: **break the code on purpose and
watch which test goes red.** Not *whether* the suite goes red — *which test*. A
suite that fails for the wrong reason is a suite that will pass for the wrong
reason later, when the neighbour that happened to cover you is refactored away.

This is the sibling of [lesson-423](lesson-423-a-fake-cannot-verify-a-request-only-agree-with-it.md),
not a repeat of it. That one says a fake cannot verify the *request*, so assert
at the transport. This test did assert at the transport, on the real call log —
and was still vacuous, because what the stub *answered* decided which calls the
code would ever make. Correct boundary, inert fixture.

**Tags**: `#testing` `#stubs` `#mutation-testing` `#pr-1660`
