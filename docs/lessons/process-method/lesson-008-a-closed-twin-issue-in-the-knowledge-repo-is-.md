---
id: lesson-008-a-closed-twin-issue-in-the-knowledge-repo-is-
type: lesson
status: active
created: "2026-06-23"
owner: manu
category: process-method
tags: [kubelab, process-method, governance, bitacora, double-board, duplicates, verification, console-003]
---

# A CLOSED twin issue in the `knowledge` repo is not evidence the work shipped — verify master

**Context**: Reconciling the double-board (the kubelab bitácora vs. the mirror issues in the `knowledge` repo). `knowledge#100` (NOTIFY-007, kubelab #686) and `knowledge#102` (APP-CONFIG-003, kubelab #688) were both **CLOSED**. On a single-board project that reads as "done", so the first instinct was to close the kubelab duplicates #686/#688 as already-shipped.

**Problem**: The two boards track the same work but transition independently. A CLOSED state on the `knowledge` twin records only that *someone marked the mirror issue closed* — it says nothing about whether the deliverable exists in `kubelab` master. Checking the code showed neither NOTIFY-007 nor APP-CONFIG-003 was actually implemented: the close was bookkeeping drift, not a shipped feature. Closing the kubelab issues on the strength of the twin would have buried two unimplemented features as "done" — no code, no test, and gone from the backlog where the remaining work was visible.

**Solution**: Kept #686/#688 open, commented the discrepancy on the board as double-board debt (CONSOLE-003), and made "verify in master" a gate before closing any issue as a duplicate. The twin's status became a hint to investigate, never proof of completion.

**Rule**: Before closing an issue as a duplicate of a CLOSED twin — or trusting any second board's "done" — verify the deliverable exists in `master`: grep the code, run the test, check the artifact. A CLOSED issue is a claim about a *tracker*, not about the *codebase*; on a multi-board setup the two drift, and "done" on the mirror can mask "never built". Trust the code, not the gemelo.

**Tags**: `#governance` `#bitacora` `#double-board` `#duplicates` `#verification` `#console-003`
