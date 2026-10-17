---
id: lesson-423-a-fake-cannot-verify-a-request-only-agree-with-it
type: lesson
status: active
created: "2026-09-03"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, testing, mutation-testing, gitea, guards]
---

# A fake cannot verify a request — it can only agree with whoever wrote it

**Context**: The Gitea `reconcilers` team granted `repo.code -> write` and covered
zero repositories, because `includes_all_repositories` defaults to `false`. The fix
adds it to `create_team`'s payload. Four tests already exercised team creation
through a `FakeClient`, and a fifth was written specifically to assert that a
freshly created team covers the organization.

**Problem**: Deleting `includes_all_repositories` from the real `create_team`
payload left **all 24 tests green**, the new one included.

`FakeClient.create_team` records the call and returns a team assembled from its own
constructor arguments. It never sees the JSON body. So the fake reported a
correctly-scoped team no matter what the client actually sent, and every assertion
downstream — including the one written to catch this exact regression — was
asserting against a value the test file had authored.

This is the second time the same file did it. Its docstring already records
2026-09-02, when the fake echoed `permission: "write"` — a value no real Gitea ever
returns — and 14 tests passed while the live reconcile answered 500.

The tests were not weak. They were pointed at the wrong object: at what the code
does with a response, when the defect was in the request.

**Solution**: Assert the request on the real client, with no fake in the path. A
subclass overriding only `_request` captures method, endpoint and body:

```python
class _CapturingClient(GiteaClient):
    def _request(self, method, endpoint, **kwargs):
        self.sent.append((method, endpoint, kwargs.get("json") or {}))
        return {}
```

```
mutation: create_team stops sending includes_all_repositories
  before  24 passed          # through the fake
  after    3 failed          # tests/test_gitea_team_grant_payload.py
```

**Rule**: A test that runs through a fake asserts the fake's behaviour, and a fake
is a written record of what its author believed. When the defect can live in the
*request* — a missing field, a wrong endpoint, an omitted flag — no amount of
assertion on the other side of the fake can reach it. Put the boundary at the
transport (`_request`, the HTTP verb, the emitted body) and assert what leaves the
process.

The tell that you need this: the code under test **sends** something. Then ask what
the fake would do if the field vanished. If the answer is "return the same object",
the test is a mirror.

And the check applies to the guard you just wrote, not only to the old ones —
`test_a_freshly_created_team_covers_the_organization` was written *for* this
regression and did not catch it. Mutation is what told them apart; nothing about
reading either test would have.

**Tags**: `#testing` `#mutation-testing` `#fakes` `#gitea` `#pr-1611`
