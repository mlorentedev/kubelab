---
id: lesson-476-a-new-step-inside-a-piecemeal-mocked-function-runs-for-real-in-every-old-test
type: lesson
status: active
created: "2026-09-24"
owner: manu
category: process-method
tags: [kubelab, process-method, testing, mocks, kubectl, isolation]
---

# A new step inside a function that tests mock piecemeal runs for real in every test written before it

**Context**: OPS-023 PR 1 (#1788) added a step to `apply_secrets()`:
`delete_retired_secrets()`, which runs `kubectl delete secret` for every entry
in `RETIRED_SECRETS`, so a retired Secret leaves the cluster on the next
`make apply-secrets` instead of by hand.

**Problem**: `tests/test_secret_consumers.py::test_apply_secrets_restarts_the_consumers_of_what_it_changed`
isolates `apply_secrets()` by mocking its steps **one by one**:
`ConfigurationManager`, `_build_dynamic_literals`, `SECRET_DEFINITIONS`,
`restart_consumers`. The new step was not on that list, and the test had no
way to know about it. A local `make test` therefore executed

```
kubectl delete secret minio-secrets --ignore-not-found
```

against **real staging**, through the workstation's kubeconfig. It was
harmless by luck, because that Secret was the one being retired. CI failed
only because its runner has no `kubectl`. So CI's red was an accident of the
runner, not a detection. On a machine with kubectl the same test passes,
and does the damage.

The piecemeal mock is an allow-list of what the test knows to be dangerous.
Every step added later is outside the list by construction, so it runs for
real. Nothing warns, because a real `kubectl` that succeeds looks exactly like
a mock that succeeds.

**Solution**: `d58a5e05` mocked the new step and asserted that it was called
(`retired_for == ["staging"]`). That proves the wiring, and it keeps this one
test off the cluster. The class stays open until the barrier is structural:
#1886 (TEST-003) is a default-deny in `tests/conftest.py` that raises when a
unit test reaches `kubectl`, `helm`, `ssh` or `ansible-playbook` without
opting in.

**Rule**: When you add a side-effecting step to a function, grep the tests
that mock that function's *other* steps. Each one now runs your step for real.
Isolation that depends on listing every dangerous call fails open, and it fails
at the moment someone adds one. Deny by default at the process boundary, and
let a test opt in, never out.

**Tags**: `#testing` `#mocks` `#pr-1788` `#issue-1886`
