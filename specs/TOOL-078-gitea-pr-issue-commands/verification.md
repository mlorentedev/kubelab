# TOOL-078 verification

| AC | Evidence |
|---|---|
| AC1 `pr create` opens a PR on `personal/resume` and prints its URL | _pending_ |
| AC2 `issue create` opens an issue on `personal/resume` | _pending_ |
| AC3 the credential is absent from argv and from captured output | `tests/test_gitea_authoring.py`: basic-auth tuple only, no `Authorization` header, not in URL or JSON; CLI output carries the URL and not the password (17 passed, 2026-09-22) |
| AC4 `resume`'s "open the PR in the web UI" instruction is replaced by the command | _pending_ |
