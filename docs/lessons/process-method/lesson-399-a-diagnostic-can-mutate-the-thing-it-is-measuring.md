---
id: lesson-399-a-diagnostic-can-mutate-the-thing-it-is-measuring
type: lesson
status: active
created: "2026-08-26"
owner: manu
category: process-method
tags: [kubelab, process-method, debugging, gitea]
---

# A diagnostic can mutate the thing it is measuring, and the mutation can be invisible in the channel you check with

**Context**: AUTH-004 C5 (#1013). Proving a machine account's token worked. Mid
way through, every request began returning `403` — including a token freshly
minted by the play, and another minted by hand seconds earlier.

**Problem**: Two hypotheses were formed and both were rejected on evidence that
could not actually distinguish them.

- *The recording path corrupts the token.* Rejected because a hand-minted token,
  never written to SOPS, failed identically.
- *The account is blocked.* Rejected because the API said it was not:

```json
{"login":"hefesto","active":true,"prohibit_login":false,"restricted":false}
```

The account was in fact rejected, by a field that record does not contain:

```
sqlite> select name, must_change_password, prohibit_login, is_active from user where name='hefesto';
hefesto|1|0|1
```

**Gitea refuses API *token* authentication for a user with
`must_change_password`, not only the login form** — and `must_change_password`
is absent from `GET /api/v1/users/{username}`. The healthy-looking response was
true about every field it carried.

**And I set it myself.** An earlier step of the same investigation ran
`gitea admin user change-password` to test an unrelated property. That command
defaults `must_change_password` to true. The provisioning path uses
`--must-change-password=false` and never had the problem; the diagnostic
introduced the fault it then spent an hour chasing.

**Solution**: `gitea admin user must-change-password --unset`, after dropping to
the database because the API could not answer. The measurement that mattered was
then re-run from a verified-clean state, in both directions, so the finding it
supports does not rest on a contaminated instance.

**Rule**: Two rules, and the second is the one that generalises.

1. **Before believing "it broke on its own", list what you ran against it.** A
   read-only investigation is a claim, not a property — `change-password`,
   `restart`, `apply`, `--force-recreate` and `delete` all appear in diagnostics
   and all mutate. If the timeline of failures starts immediately after one of
   your own commands, that is the first suspect, not the last.
2. **A resource that reports healthy has only reported on the fields it
   carries.** When an API and a symptom disagree, the API is answering a
   narrower question than the one you asked — go one layer down before rejecting
   a hypothesis, because a field that is absent reads exactly like a field that
   is fine. Same family as lesson-382: the channel that measured was not the
   channel that answered.

**Tags**: `#debugging` `#gitea` `#controls` `#pr-1437`
