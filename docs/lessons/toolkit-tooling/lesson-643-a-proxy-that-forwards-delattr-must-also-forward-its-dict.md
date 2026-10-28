---
id: lesson-643-a-proxy-that-forwards-delattr-must-also-forward-its-dict
type: lesson
status: active
created: "2026-10-28"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, pytest, monkeypatch, settings, ci]
---

# A proxy that forwards `delattr` must also forward its `__dict__`

**Context**: CI on 2026-10-28. Three unrelated PRs failed `Tests` with the same 97
failures. Each failure raised `'PlatformSettings' object has no attribute
'project_root'`. Master had been green the day before.

**Problem**: `poetry.lock` is gitignored, so CI resolved pytest 9.2.0, released that
day. In 9.2, `monkeypatch.setattr` on an instance takes the value to restore from
the target's `__dict__`. If the name is not there, the undo uses `delattr` instead of
`setattr` (pytest #10644). The toolkit's `settings` is a `_LazySettings` proxy. Reads,
writes and deletes go to the real `PlatformSettings`, but its own `__dict__` holds
only `_env`. So the first test that patched `settings.project_root` ended by deleting
that field from the real object. Every later test that read it failed. Each failing
test passed on its own, which is the signature of ordering pollution.

**Solution**: `_LazySettings.__dict__` is a property that returns the real object's
`__dict__`. A pydantic model keeps its field values there, so pytest finds the old
value and restores it with `setattr`. A test patches and undoes through the proxy and
asserts that the field is back. Its mutant goes red.

**Rule**: a proxy that forwards attribute reads, writes and deletes must also forward
`__dict__`. A tool that reads the proxy's own `__dict__` sees an empty object, and
acts on that answer through the deletes the proxy forwards.
