---
id: lesson-767-a-forge-2xx-to-a-write-does-not-say-it-took
type: lesson
status: active
created: "2026-11-17"
owner: manu
category: apps-web
tags: [kubelab, apps-web, forge, gitea, github, console]
---

# A forge's 2xx to a write does not say the write took

**Context**: Writing the forge writer adapter (CONSOLE-004 AC2): create, label, assign, close and reopen on GitHub and on Gitea, with the worker's retry classes of ADR-066 W3 on top.

**Problem**: Reading Gitea v1.27.3 (`routers/api/v1/repo/issue_label.go`, `issue_assignee.go`, `issue.go`) and GitHub's REST description for what each endpoint answers turned up four places where the status code and the effect part ways:

- Gitea's add-label (`prepareForReplaceOrAdd`) turns a label name into ids and drops every name no label has. With none left it still answers 200 with the issue's labels. A write that names a label the repository does not have is a 200 that changed nothing.
- GitHub's add-assignees ignores users who cannot be assigned and answers 201 with the issue. Same shape.
- Gitea's label DELETE takes only the numeric id, so removing "by name" is a read of the issue's labels and then a delete.
- GitHub answers 404 to a label removal both when the label is not on the issue and when the issue is gone. A retry of a removal whose answer was lost is a 404 on a change that applied.

And on the way in: Go's HTTP client follows a 301 on a POST, PATCH or DELETE by re-issuing it as a GET, whose 200 reads as an applied write. GitHub's description lists a 301 for a moved repository on the label and update endpoints.

**Solution**: `apps/api/src/internal/forge/issue_write.go` treats the answer's body as the proof: add-label and add-assignee check that the label or login is in what the forge returned, and fail terminally with the forge's own 200 when it is not. Label removal on Gitea reads the labels first and treats an absent label as applied; on GitHub a 404 is followed by a read of the issue's labels, which tells "already removed" from "issue gone". The writer's client returns the last response instead of following a redirect, and a 3xx is a terminal failure. The contract tests serve each forge's real success status, which differ (Gitea's PATCH answers 201, its label DELETE 204).

**Rule**: For a write to an external system, the adapter's "applied" is the forge's confirmation of the effect, not of the request: where an endpoint ignores what it cannot honour, read the effect from the answer. Read the forge's source or description for what each endpoint answers when the change is already made, and never let a client follow a redirect on a write.

**Tags**: `#forge` `#gitea` `#github` `#idempotency` `#console-004`
