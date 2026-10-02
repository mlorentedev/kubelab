---
id: lesson-502-a-patch-applied-after-import-cannot-see-what-the-import-did
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, testing, issue-2011, issue-2021]
---

# A patch applied after import cannot see what the import already did

**Context**: BACKUP-071 runs the Gitea and Headscale restore drills on ace2, a host with no SOPS key. The spec said the remote entrypoint "never builds a `ConfigurationManager`". `tests/test_drill_remote.py` checked it by patching `ConfigurationManager.__init__` to raise and invoking `toolkit backup drill-<x> --inputs-stdin` through Typer's `CliRunner`. The test passed.

**Problem**: The first live run on ace2 printed `SOPS is not installed. Skipping secret decryption.` twice before the drill started. Something had built a `ConfigurationManager` after all. A spy on `_decrypt_sops` installed *before* `import toolkit.main` traced it: `main.py` imports `cli/auth.py`, which imports `config/settings.py`, whose last line is `settings = get_settings()`. That builds a `ConfigurationManager("dev")` and decrypts `common.enc.yaml` and `dev.enc.yaml` on every toolkit invocation (#2021). pytest had already imported `toolkit.cli.backup` at collection, so by the time the fixture patched `__init__`, the construction it was meant to catch had happened. The test proved "the drill's own code path builds none", a narrower claim than the one in the spec.

**Solution**: The narrower claim was kept, and stated as such in the fixture's docstring, because it is the one the drill controls. The process-wide claim went to its own ticket (#2021, TOOL-097), whose acceptance test patches before the import (`python -c` in a subprocess). The verification for BACKUP-040 and BACKUP-067 names the two warnings and why nothing was decrypted: ace2 has no sops binary and no key.

**Rule**: A patch applied in a test body sees only what runs after it. Anything a module does at import (a module-level call, a default argument as in lesson-469, a registry filled on import) already ran during collection. To claim "this process never does X", patch before the first import: in a subprocess, or with `sitecustomize`. Otherwise, write the claim down as "this code path never does X". A live run on the real host is what found the gap here; the unit test alone could not have.

**Tags**: `#testing` `#monkeypatch` `#import-time` `#issue-2011` `#issue-2021`
