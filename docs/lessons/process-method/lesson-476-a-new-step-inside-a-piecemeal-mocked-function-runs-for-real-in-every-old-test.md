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
test off the cluster. The class was closed by #1886 (TEST-003): a
default-deny in `tests/conftest.py` that refuses, in any test outside
`tests/e2e` and `tests/infra`, a subprocess whose command is a cluster or host
client (`kubectl`, `helm`, `ssh`, `scp`, `rsync`, `ansible*`, `terraform`,
`tofu`, `tailscale`, `headscale`, `restic`). Local subcommands stay allowed
(`kubectl kustomize`, `kubectl version --client`, `helm template`). A test that
must reach a host opts in with `@pytest.mark.allow_host_clients(reason=...)`;
`integration`, `e2e` and `infra` are exempt by marker.

Three details decide whether such a barrier works, and each was a choice:

- **It sits on `subprocess.Popen.__init__`**, installed in `pytest_configure`.
  `run`, `check_output`, `call` and asyncio's subprocess transport all construct
  a `Popen`, and `from subprocess import Popen` is the same class object, so
  one patch covers all of them. `os.system` does not build a `Popen`, so it is
  patched too (#2007). `os.exec*` and `os.posix_spawn` are left unguarded and
  named as such, since nothing here uses them. An autouse fixture would miss
  module- and session-scoped fixtures, which run before it.
- **The refusal is a `BaseException`**. The toolkit wraps its subprocess calls
  in `except OSError` and `except Exception` (29 handlers), because a missing
  binary must not crash a CLI. A refusal raised as an ordinary exception would
  be swallowed by exactly the code it is meant to stop, and the test would pass.
  The hit is also recorded on the test and its report forced red, so even code
  that catches `BaseException` cannot hide it. The record is consumed by the
  phase that reports it, teardown included. The first version excluded
  teardown instead, which kept a failed call from being reported twice and
  also let a finalizer that swallowed the refusal pass (#2007).
- **It reads the command position, not every token**. `argv[0]`, the command
  after `sudo`/`timeout`/`env`, and each command inside an `sh -c` string
  count; an argument that happens to be named `restic` does not.

**Rule**: When you add a side-effecting step to a function, grep the tests
that mock that function's *other* steps. Each one now runs your step for real.
Isolation that depends on listing every dangerous call fails open, and it fails
at the moment someone adds one. Deny by default at the process boundary, and
let a test opt in, never out.

**Verify**: the mutation needs two edits, because `RETIRED_SECRETS` has been
empty since the MinIO retirement and an empty list spawns nothing. In
`tests/test_secret_consumers.py`, drop `d58a5e05`'s mock of
`delete_retired_secrets` and its `retired_for` assertion; in
`toolkit/features/k8s_secrets.py`, give `RETIRED_SECRETS` one entry. The test
must then fail with ``HostClientRefused: unit test spawned `kubectl delete` ``,
on a machine with kubectl as well as on one without it. With only the first
edit it passes, which says nothing about the barrier.

**Tags**: `#testing` `#mocks` `#pr-1788` `#issue-1886`
