---
id: lesson-371-a-truncated-listing-reads-exactly-like-a-complete-one
type: lesson
status: active
created: "2026-08-23"
owner: manu
category: process-method
tags: [kubelab, process-method, verification, gh, planning]
---

# A truncated listing reads exactly like a complete one, and planning built on it stays coherent for hours

**Context**: Orienting at the start of a session, to decide which of the forge
sequence's steps (#1077) were unblocked. The gating step is AUTH-004 (#1013).
The orientation command was:

```bash
gh issue list --repo mlorentedev/kubelab --state open --limit 60 ...
```

#1013 was not in the output, so it was read as closed and the sequence as
unblocked. Everything downstream followed from that: which ticket to pick, what
the next session's first action would be, what the handoff said.

**Problem**: The repository has **467 open issues**. The listing returned 13% of
them, ordered by update time, and #1013 was not in the slice.

No command failed. No error appeared. The listing was exactly as long as it was
asked to be, and a listing of 60 that contains everything is textually
indistinguishable from a listing of 60 that contains 13% of everything.

The premise then survived hours *because* it was self-consistent — every plan
built on it hung together, and nothing downstream had a reason to question it.
It only broke when a spec's grounding step went looking for a concrete symbol,
`apps.auth.identities` (ADR-062 D3), which #1075's AC2 requires, and found it
declared nowhere: not in `common.yaml`, not in `toolkit/features/`, not in the
`dev_node` role. Decided and unbuilt — because the ticket that builds it was
open the whole time.

**Solution**: Ask a question whose answer cannot be truncated. Either learn the
size of the universe:

```bash
gh issue list --repo <r> --state open --limit 500 --json number --jq 'length'
# 467
```

or, better when a specific ticket gates the decision, query that ticket by
number and never infer its state from a list at all:

```bash
gh issue view 1013 --repo <r> --json state,title
# OPEN  AUTH-004: MinIO and Gitea admin usernames still 'manu', ...
```

The second is what the situation actually called for: the decision depended on
one issue, and it was answered by scanning a list of sixty others.

**Rule**: **Absence from a bounded query is not evidence of absence.** `--limit
N`, `head`, `| tail`, a page of API results and a `LIMIT` clause all answer
"the first N", never "all of them", and none of them says so in its output.

When a decision turns on whether a specific thing exists, ask about **that
thing**, by name or id. Reserve listings for discovery, never for proof of
absence.

This is the same shape as [`dig` exiting 0 on
SERVFAIL](lesson-370-nine-green-signals-described-a-broken-hub.md)
— the channel that measured was not the channel that answered — with one extra
property that makes it more expensive: a wrong command result is usually caught
by the next command, while a wrong *premise* is confirmed by everything built on
top of it.

**Tags**: `#process` `#verification` `#gh` `#planning` `#issue-1013`
