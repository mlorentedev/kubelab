---
id: lesson-478-after-an-n8n-http-node-json-is-the-response-not-the-event
type: lesson
status: active
created: "2026-09-27"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, n8n, vikunja, testing]
---

# After an n8n HTTP Request node, `$json` is the response, not the event, and `options.continueOnFail` is read by nothing

**Context**: #1871 (APP-CONFIG-016). No pull request had ever reached its
Vikunja task through `multi-forge-sync`, and every unit test was green.

**Problem**: Three defects of two classes, none of which fails loudly.

1. **`$json` is the node's input.** After an HTTP Request node that is the
   response: Vikunja's task, Apprise's acknowledgement, Slack's answer. An
   expression such as `$json.taskKey` does not fail there. It evaluates to
   `undefined`, the request goes out with `undefined` in its URL or body, and
   the execution reports success. `Append PR URL Comment` posted to
   `/tasks/undefined/comments`. The same shape had already shipped in
   `Respond Task Created` (#1864), in both `Respond 200` bodies and in the
   `#dev-activity` notices, and each had been found one instance at a time.
   The search result had the matching trap: an HTTP node that receives a JSON
   array emits **one item per element**, so a Code node reading `$json` as
   "the results" saw only the first task, and `results[0]` of a substring
   search matched `TOOL-0350` for `TOOL-035` (#1692).
2. **`parameters.options.continueOnFail` is dead config.** n8n 2.12.3's HTTP
   Request node asks `this.continueOnFail()`, which reads only the node-level
   `onError` (or the node-level `continueOnFail`). The option under
   `parameters` exists in no version of the node's description. Five nodes
   declared it: the searches meant to survive a 401 halted the run instead,
   so the `searchFailed` branches written for them never ran, and the writes
   meant to swallow a failure failed loudly, correct only by accident.
3. **Vikunja 1.0's `POST /tasks/{id}` is a full update.** A body of
   `{done: true}` clears description, priority, dates and colour
   (`Task.updateSingleTask`), and an empty title fails validation. So the
   write that the first two defects kept from running would have erased the
   task it closed.

**Solution**: fixed as classes, not instances.

- `tests/test_n8n_event_reads.py` reads every key a Code node returns and
  fails when a node fed directly by an HTTP Request node reads one of them
  through `$json`. The event is read from its producer,
  `$('Extract Matched Task ID').first().json`.
- `tests/test_n8n_http_error_handling.py` fails on any
  `parameters.options.continueOnFail`. Intent is written where n8n reads it:
  `onError: continueRegularOutput` on the create-path searches whose Code
  nodes branch on `error`, nothing on the writes.
- The extractor reads `$input.all()`, handles the split, wrapped-array and
  `{data: [...]}` shapes, matches the key exactly, and builds the update body
  from the searched task with only `done` changed.
- `make n8n-probe` now sends a signed merge for a task it created and reads
  back `done`, a digest of the description and the PR comment, because only
  the deployed workflow shows which node actually ran.

**Rule**: in n8n, name the node you mean: `$json` only for the response the
previous node produced, `$('<producer>')` for anything else. Put error
handling at node level, where `continueOnFail()` reads it. Before writing to
an API, read its update semantics in the source: a partial body is a
different operation on a full-update endpoint. A green unit test of one node
says nothing about what the next node reads.

**Tags**: `#n8n` `#vikunja` `#issue-1871` `#pr-1864` `#issue-1692`
