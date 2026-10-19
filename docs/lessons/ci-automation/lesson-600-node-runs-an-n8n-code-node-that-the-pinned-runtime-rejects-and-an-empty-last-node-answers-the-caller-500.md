---
id: lesson-600-node-runs-an-n8n-code-node-that-the-pinned-runtime-rejects-and-an-empty-last-node-answers-the-caller-500
type: lesson
status: active
created: "2026-10-18"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, n8n, grafana, tool-093]
---

# Node runs an n8n Code node that the pinned runtime rejects, and an empty last node answers the caller 500

**Context**: TOOL-093 (#1957) added `forge-review-failed`, the n8n workflow Grafana calls to comment on a pull request whose review failed. Its two Code nodes were written and tested the way `tests/n8n_code_node.py` runs them: the committed `jsCode` in Node, on the item shape captured from n8n. Every test was green.

**Problem**: Run once in the pinned image (n8nio/n8n 2.12.3) against a Gitea 1.27.3, the workflow failed on the first call. Two facts that Node cannot show:
- The task runner's sandbox has no `URL` global. `new URL(label)` throws `ReferenceError: URL is not defined`; it exists in the Node that runs the tests.
- A webhook in `responseMode: lastNode` answers with the last node's items, and a run that ends on a node with none (a dedup, an empty `alerts`, a label that is not a pull request of this forge) answers `500 No item to return was found`. Grafana counts that as a failed notification and retries it.

**Solution**: Match the label with a pattern instead of parsing it, and end every path in a node that always emits an item (`Parse Alerts` returns one `skip` item when nothing is valid; the `false` branches of both IF nodes go to a `noOp`). Gitea lists 30 comments a page, so the comment list is read with `since=<startsAt>&limit=50`. `tests/test_n8n_forge_review_failed.py` pins each of these (a `new URL` in a Code node fails it; so does a terminal node that can emit nothing), each checked by mutating the workflow.

**Rule**: A Code node tested in Node has been tested against Node. Before a new workflow ships, run it once in the pinned n8n image against the real peer and read the execution (`database.sqlite`, `execution_data`), then turn what that run found into a test that fails if it returns. Treat "ends with no items" as a response, not as a clean exit.

**Tags**: `#n8n` `#webhook` `#grafana` `#tool-093`
