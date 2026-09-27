---
id: lesson-469-a-default-argument-binds-at-import-so-monkeypatch-misses-it
type: lesson
status: active
created: "2026-09-27"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, testing, pytest]
---

# A default argument binds at import, so monkeypatching the module constant misses it

**Context**: TOOL-080 PR 4 taught `toolkit/scripts/sync_k8s_images.py` a second, prod-only kustomization pass. Its tests redirect the module's `COMMON_YAML` and `KUSTOMIZATION` constants to `tmp_path` with `monkeypatch.setattr`, then call `main()`.

**Problem**: `sync()` declared those constants as default parameter values, and `main()` called `sync()` with no arguments. A default is evaluated once, when the `def` runs at import, so it held the real repository paths. The monkeypatch replaced the module attribute, and the function never read it again. `main()` wrote the real base `kustomization.yaml` instead of the test's temporary copy. The write was idempotent, so `git diff` showed nothing. The test only failed because its assertion on the temporary file did not hold.

**Solution**: `main()` now resolves the constants in its own body at call time and passes them to `sync()` explicitly. The monkeypatched values reach the call, and the test's temporary file is the one written.

**Rule**: If a test isolates a function by monkeypatching module constants, the code under test must read those constants at call time, never through `def f(path=CONSTANT)`. A write that lands on the real file with the same content passes silently, so assert on the temporary file, not only on the return value.

**Tags**: `#testing` `#monkeypatch` `#tool-080`
