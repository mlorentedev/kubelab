---
id: lesson-425-a-capability-probe-can-stop-at-the-first-authorization-layer
type: lesson
status: active
created: "2026-09-04"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, gitea, git, permissions, verification]
---

# A capability probe can stop at the first authorization layer and report the whole answer

**Context**: AC6 needs a commit pushed to `personal/resume` on the Gitea forge,
and no credential on the workstation could. Three candidates lived in SOPS, so the
question was which one may push — asked by consequence, per
[[lesson-413-a-credential-can-exist-authenticate-and-not-work]].

**Problem**: The obvious non-destructive probe is `git push --dry-run`. It gave a
confident answer, and the answer was wrong:

```
git push --dry-run, new branch
  admin_token     403 Forbidden        <- conclusive
  bot_token       "* [new branch]"     <- NOT conclusive
  admin_password  "* [new branch]"

the same forge, about the same bot, at the same moment
  GET /repos/personal/resume/collaborators/hefesto/permission -> "read"
  the bot's own view: {"admin": false, "push": false, "pull": true}
```

Gitea authorizes a git push in **two** places, and `--dry-run` crosses only the
first. The HTTP layer checks the token's SCOPE and refuses `git-receive-pack`
outright — which is where `admin_token` died, and why its 403 *was* the whole
answer. Past that gate, `--dry-run` gets the ref advertisement, computes what it
would do, and prints it. The account's WRITE PERMISSION on the repository is
checked by the pre-receive hook, when a ref is actually updated — which
`--dry-run` never reaches.

So the probe told two credentials apart for the wrong reason: it distinguished
"may speak receive-pack" from "may not", and was read as "may push".

A real push settled it, and cost one ref:

```
bot_token   -> remote: error: User permission denied for writing  (pre-receive)
admin_password -> created the ref, deleted in the same run, verified absent
```

**Solution**: Probe the operation whose refusal you care about, all the way to its
last gate. Here that means creating a ref and deleting it — pointed at a commit
the remote already has, so no object is transferred and the only change is one
branch name, removed and then verified gone by listing the remote's branches.

The API's permission field is no substitute, and it failed in the opposite
direction: after the team was widened, `collaborators/hefesto/permission` still
answered `read` while the bot's push SUCCEEDED. Team-derived access is not
collaborator access, and that endpoint only knows about the latter. It answers a
narrower question than its name suggests.

**Rule**: A permission system with more than one gate will happily answer for the
gate you reached. Before trusting a probe, ask **which refusal it is capable of
observing** — and prefer the operation itself, made harmless by choosing a target
that is trivially reversible, over any dry run or any field that describes the
permission.

Corollary for reporting: a probe that crosses gate 1 of 2 is not "inconclusive
because it was cheap". It is a check that confirms a weaker claim than it appears
to, which is the same failure as
[[lesson-416-a-guard-the-guard-belongs-on-the-last-value-before-the-assertion]]
and [[lesson-423-a-fake-cannot-verify-a-request-only-agree-with-it]]. Ninth
instance in this area, and the first one inside the measuring instrument rather
than in the code being measured.

**Tags**: `#gitea` `#git` `#permissions` `#verification` `#tool-035`
