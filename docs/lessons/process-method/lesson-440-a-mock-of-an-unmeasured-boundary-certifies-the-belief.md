---
id: lesson-440-a-mock-of-an-unmeasured-boundary-certifies-the-belief
type: lesson
status: active
created: "2026-09-05"
owner: manu
category: process-method
tags: [kubelab, process-method, testing, n8n, automation]
---

# Running the real code against a mocked boundary tests the code and certifies the mock

**Context**: Adding an `issue opened` -> create-Vikunja-task path to
`multi-forge-sync` (#1684, PR #1693). The tests were built deliberately well: each
one executes the workflow's **own JavaScript** in Node rather than a Python
re-implementation, because lesson-413 records that a fake encoding a wrong belief
does not fail — it certifies the belief. Nineteen tests, eight mutations applied to
the shipped JSON, eight killed.

**Problem**: Three defects shipped past all of it, and the tests could not have
caught any of them, because they all lived in the one thing that was still a fake:
the helper mocked `$json` as the whole HTTP response array.

n8n passes data between nodes as an **array of items**, and an HTTP Request node
handed a JSON array emits **one item per element**. So at every node after a
request, `$json` is the *first record*, not the list:

| node | `$json` really is | consequence |
|---|---|---|
| the search-result reader | the first task | `Array.isArray` false -> no results -> **creates a duplicate of a task it is looking straight at** |
| the project resolver | the first project | nothing ever matches -> **422 for every repository, forever** |
| the two post-create nodes | Vikunja's *new task object* | `$json.taskKey` undefined -> notice reads `Task created: undefined`, and `JSON.stringify` **silently drops** every undefined field from the response body |

And a fourth, worse than a wrong answer: **a node that yields no data emits no item,
and a node with no input does not run.** `GET /tasks?s=<a brand-new key>` returns
`[]` — the single most common input on a create path — so the chain would have
stopped dead with no response node firing and the webhook timing out. Nothing about
that failure names its cause.

The mutation testing gave real confidence and was real: it proved the assertions
bite. It could not prove the *inputs* were shapes that occur, because every mutation
was fed through the same mock. **A mutation suite measures the assertions, never the
fixtures.**

**Solution**: Found by an independent review pass reading the graph against n8n's
item model, then confirmed against the docs (`$input.all()`, and the Always Output
Data setting — *"returning an empty item if execution yields no data"*) before any
edit. The fix is small and uniform: gather with `$input.all()` and normalise every
shape the request can produce, set `alwaysOutputData` on both GET nodes, and have
the post-create nodes reach back with `$('<node>').first().json` for the event,
taking only `id` from `$json`. Tests now run each code node against **all three item
shapes** plus the empty and the error item; 11/11 mutations killed, three new and
aimed at exactly these defects.

**Rule**: Executing the real code is only half of fidelity. The other half is the
**shape of what you feed it**, and that shape is a property of the platform you did
not write. Before mocking a boundary, ask what measurement establishes the shape —
if the answer is "it is obviously the response body", that is a belief, and the mock
will certify it exactly as a fake object would.

Two cheap tests apply to any such boundary:

- **Run every unit against every shape the boundary can produce**, not the one you
  pictured. Here that is one-item-per-element, one item wrapping an array, one
  wrapping `{data: [...]}`, the empty item, and the error item — parametrise, and
  the belief has nowhere to hide.
- **Ask what happens on the empty result**, and treat it as a first-class case
  rather than an edge. On a create path the empty result is not the edge case, it is
  the *primary* one, and a pipeline that silently stops on it looks identical to one
  that was never triggered.

Related: [lesson-413](../identity-secrets/lesson-413-a-credential-can-exist-authenticate-and-not-work.md)
is the same shape one level down — there a fake returned a field no real server
sends; here a fake returned a *container* no real node emits. And
[lesson-416](../ci-automation/lesson-416-a-guard-the-guard-must-assert-on-the-derived-artifact.md):
an empty expectation is not a weak expectation. An unmeasured mock is the same
failure with the emptiness hidden inside a plausible-looking value.

**Tags**: `#testing` `#mocks` `#n8n` `#automation` `#pr-1693` `#issue-1684`
