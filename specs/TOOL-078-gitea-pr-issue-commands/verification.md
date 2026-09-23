# TOOL-078 verification

| AC | Evidence |
|---|---|
| AC1 `pr create` opens a PR on `personal/resume` and prints its URL | Live, 2026-09-22, from this branch: `pr create --repo personal/resume --head fix/onboarding-figure --base main ...` printed `#263 https://gitea.kubelab.live/personal/resume/pulls/263` |
| AC2 `issue create` opens an issue on `personal/resume` | Live, 2026-09-22: printed `#264 https://gitea.kubelab.live/personal/resume/issues/264` (the worktree `make check` defect, the first consumer named in #1792) |
| AC3 the credential is absent from argv and from captured output | `tests/test_gitea_authoring.py`: basic-auth tuple only, no `Authorization` header, not in URL or JSON; CLI output carries the URL and not the password (17 passed, 2026-09-22) |
| AC4 `resume`'s "open the PR in the web UI" instruction is replaced by the command | Vault `10_projects/resume/memory/MEMORY.md` forge line now names `toolkit services gitea pr create` / `issue create` (vault `22b6dbaa`). `resume`'s `AGENTS.md` never carried the instruction |

## Review findings applied (review.md, nan/mimo-v2.5, PASS-WITH-GAPS)

| Finding | Fix | Test |
|---|---|---|
| Major: `head`/`base` not stripped, whitespace-only names reached Gitea | stripped before the check, like the title | `test_blank_or_padded_branch_names_are_refused_or_normalised`, `test_padding_around_a_valid_branch_is_removed` |
| Minor: `_opened` raised a raw `KeyError` on a malformed record | refused as `AuthoringError` naming the fields | `test_a_response_without_number_or_url_is_a_clean_error` |
| Minor: no CLI test for `issue create` | added | `test_the_issue_command_prints_the_url_and_never_the_password` |
| Minor: network errors surfaced as tracebacks | `requests.RequestException` exits 1 with a message | `test_an_unreachable_forge_is_a_clean_exit_not_a_traceback` |
