---
id: lesson-730-gitea-drops-a-push-whitelist-entry-without-write-and-answers-200
type: lesson
status: active
created: "2026-11-09"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, gitea, auth-024]
---

# Gitea drops a push whitelist entry for an account without write, and answers 200

**Context**: AUTH-024 AC2 (#3148) protects the default branch of every
repository that declares `writers:`, with a push whitelist naming the accounts
still allowed to push directly.

**Problem**: Measured on a local `gitea/gitea:1.27.3`, both
`POST` and `PATCH /repos/{o}/{r}/branch_protections` keep a whitelist entry only
when that account has write on the repository. Any other entry is dropped, the
request still answers 2xx, and the read-back no longer lists it. Whitelisting
`operator`, an account with no write on the repository, would therefore have
failed the reconcile's read-back on every run. Two more measured facts shape
the rule: a site admin does not bypass a protection rule, so the admin has to
be named; and the push whitelist does not limit merges, so a `write`
collaborator can still merge its own pull request.

**Solution**: `gitea.branch_protection.push_exempt` names the superadmin, which
holds write everywhere, and the loader refuses machine identities and declared
writers. `ensure_branch_protection` reads the rule back and raises on drift, so
a dropped entry fails loudly.

**Rule**: For a Gitea write, a 2xx response only means the request was
accepted. Read the object back and compare it with what you sent, field by
field. The repository merge settings behave the same way
(`has_pull_requests`, TOOL-063).

**Tags**: `#gitea` `#auth-024` `#issue-3148`
