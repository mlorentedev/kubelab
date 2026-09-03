---
id: lesson-415-discriminate-a-refusal-by-asking-for-something-that-already-exists
type: lesson
status: active
created: "2026-09-02"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, gitea, authorization, verification]
---

# To learn whether a credential *may* do something, ask it to do something already done

**Context**: TOOL-035 needed to know which of three Gitea credentials could migrate a repository into
an organization, and which could delete an empty one. The spec had assigned both to the machine
identity by analogy with repository creation. Gitea disagreed, and the refusals did not say why in a
way that could be told apart.

**Problem**: Every refusal is `403`, and `403` has at least three distinct causes — token scope,
repository or organization permission, and account state. Reading the status code alone had already
voided a check once (AUTH-004 AC5) and cost a session in TOOL-035 Risk 1. Worse, the obvious way to
find out whether a credential *may* perform a destructive operation is to let it try — which, when the
answer is yes, performs the destructive operation.

**Solution**: Ask the credential to perform the operation against a target where success is
**impossible for a harmless reason**. For a create-shaped call, that is a target that already exists:
`409` then means *"you may, the target merely exists"* and `403` means *"you may not"*. Measured
against live prod on an existing repository:

```text
bot token             -> 403 "Given user is not owner of organization."
admin token           -> 403 required=[write:repository], token scope=read:admin,write:organization,...
superadmin basic auth -> 409 "The repository with the same name already exists."
```

Three credentials discriminated in one non-destructive pass, and the two 403s turned out to be
*different walls*: the bot is stopped by organization **ownership**, which ADR-065 D1 requires it
never to have — so no scope widening fixes it, only violating D1 — while the admin token is stopped by
**scope**, and granting it `write:repository` would hand a long-lived reconciler credential a standing
`DELETE /repos/...`. Both refusals were correct and neither was worth demolishing; migration and
deletion both moved to the superadmin's basic-auth session, which grants nothing durable.

**Rule**: **Probe authorization with a request that cannot succeed for a reason unrelated to
authorization.** A conflict, a duplicate, a not-modified — any second-order refusal proves the caller
got *past* the authorization layer. And when a 403 blocks you, **read the body before reaching for a
scope**: "not owner of organization" and `required=[write:repository]` demand opposite responses, and
the wrong one grants a permanent capability to work around a temporary obstacle.

**Tags**: `#gitea` `#authorization` `#403` `#least-privilege` `#pr-1563` `#pr-1564`
