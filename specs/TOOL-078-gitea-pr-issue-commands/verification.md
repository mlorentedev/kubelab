# TOOL-078 verification

| AC | Evidence |
|---|---|
| AC1 `pr create` opens a PR on `personal/resume` and prints its URL | Live, 2026-09-22, from this branch: `pr create --repo personal/resume --head fix/onboarding-figure --base main ...` printed `#263 https://gitea.kubelab.live/personal/resume/pulls/263` |
| AC2 `issue create` opens an issue on `personal/resume` | Live, 2026-09-22: printed `#264 https://gitea.kubelab.live/personal/resume/issues/264` (the worktree `make check` defect, the first consumer named in #1792) |
| AC3 the credential is absent from argv and from captured output | `tests/test_gitea_authoring.py`: basic-auth tuple only, no `Authorization` header, not in URL or JSON; CLI output carries the URL and not the password (17 passed, 2026-09-22) |
| AC4 `resume`'s "open the PR in the web UI" instruction is replaced by the command | Vault `10_projects/resume/memory/MEMORY.md` forge line now names `toolkit services gitea pr create` / `issue create` (vault `22b6dbaa`). `resume`'s `AGENTS.md` never carried the instruction |
