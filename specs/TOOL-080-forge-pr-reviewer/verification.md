---
tags: [spec, verification]
created: "2026-09-23"
---

# Verification - TOOL-080-forge-pr-reviewer

## Evidence

- [ ] AC1: comment id, author and timestamp on a real `personal/resume` PR
- [ ] AC2: the same comment id after a push, with `updated_at` later than the push
- [ ] AC3: HTTP status for an unsigned and a wrongly signed POST; test `<name>`
- [ ] AC4: title and body byte-identical before and after; test `<name>`
- [ ] AC5: measured scope requirement (below); test `<name>`; `GET /users/<reviewer>/repos` returns `[]`
- [ ] AC6: tests `<names>`; orphan audit output
- [ ] AC7: reconcile apply output, then a second run with no changes
- [ ] AC8: alert fired, and its timestamp

## Pre-spec measurement (2026-09-24, read-only)

The probe from #1823:

- `pragent/pr-agent:0.45.0` in CLI mode, `CONFIG__GIT_PROVIDER=gitea`, NaN backend, `CONFIG__PUBLISH_OUTPUT=false`, run against resume PR 270 with the `hefesto` token (`read` on the repo).
- It fetched a full diff of 8,903 tokens, the model answered in about 2.5 s, and it produced a `PR Reviewer Guide`. Nothing was posted.
- The server image `pragent/pr-agent:0.45.0-gitea_app` is digest `sha256:750c6cf8532b7aa81ef55a71cce0d8c24485cd18cbdcca21d3885788ce2b69f4`. Its default command is gunicorn with UvicornWorker on `:3000` (2 to 4 workers from the cgroup CPU limit), and it declares no user.

## Scope and delivery measurement (2026-09-24, local lab)

`scope-lab.py` in this folder. Two runs, each with the same command:
`dotf secrets run --only NAN_API_KEY -- .venv/bin/python specs/TOOL-080-forge-pr-reviewer/scope-lab.py`.
- **Run A** uses the defaults: hook `["pull_request"]`, upstream `final_update_message`, and the per-scope table.
- **Run B** adds `LAB_HOOK_EVENTS='["pull_request_only","pull_request_sync"]' LAB_FINAL_UPDATE=false LAB_SKIP_SCOPES=1`.

- **Nothing touched the prod forge.** A prod probe was considered and dropped: the only non-admin account there, `hefesto`, is in `reconcilers`, a team with per-unit **write** on every `personal/` repo (`includes_all_repositories: true`), so a probe with it measures a writer, not a reader. Minting a throwaway token on prod would also be a manual operation.
- **Topology.** `gitea/gitea:1.25.5` (`sha256:f846d26a…`, the prod pin) and `pragent/pr-agent:0.45.0-gitea_app` (`sha256:750c6cf8…`) on a private Docker network. A public org `personal`, public repo `resume`, `REQUIRE_SIGNIN_VIEW=true`. `reviewer` is a plain user in a team with `repo.code`, `repo.issues` and `repo.pulls` at `read`. The server gets `proposal.md`'s original settings: `CONFIG__GIT_PROVIDER`, `GITEA__URL`, the NaN base and models, `GITEA__PR_COMMANDS` and `GITEA__PUSH_COMMANDS` = `["/review"]`, `GITEA__HANDLE_PUSH_TRIGGER=true`, and `PR_REVIEWER__PERSISTENT_COMMENT=true`. The webhook is signed.
  - The lab does **not** set the keys this measurement then added to the proposal: both `ENABLE_REVIEW_LABELS_*` keep upstream's `true`, which is how the label 403s were observed, and `REPO_CONTEXT_FROM_DEFAULT_BRANCH` keeps its upstream default, `true`.
  - `FINAL_UPDATE_MESSAGE` is upstream's `true` in run A and `false` in run B.
- **Reading back.** Calls were read from Gitea's access log (`[log].logger.access.MODE=console`; the older `ENABLE_ACCESS_LOG` is ignored in 1.25). The lab removes its containers and network on exit.

### Scopes. The requirement is `write:issue` + `read:repository`

HTTP status per call, for a read-team member's token:

| Call | `write:issue` | `+ read:repository` | `+ read:user` |
|---|---|---|---|
| `GET /user` | 403 | 403 | 200 |
| `GET /repos/{r}`, `pulls/{n}`, `.diff`, `/files`, `/commits`, `languages`, `contents` | 403 | 200 | 200 |
| `GET issues/{n}/comments`, `issues/{n}/labels` | 200 | 200 | 200 |
| `POST issues/{n}/comments`, then `PATCH` and `DELETE` of that own comment, a reaction on it | 201 / 200 / 204 / 201 | same | same |
| `POST pulls/{n}/reviews` (event `COMMENT`) | 403 | 403 | 403 |
| `POST /labels`, `POST issues/{n}/labels` | 403 | 403 | 403 |
| `PATCH pulls/{n}` (title) | 403 | 403 | 403 |

- `write:issue` alone can comment but cannot read the PR it reviews.
- The webhook server never called `/user` (below), so `read:user` is not required.
- Read access is the containment. Creating labels, attaching them, submitting a PR review and editing a PR all need write (`reqRepoWriter`, `CanWriteIssuesOrPulls` in `routers/api/v1/api.go` and `repo/issue_label.go` at v1.25.5). The read-team member gets 403 on each.

### What the server calls

On `opened`, the server made 18 calls: reads, one refused label write and one comment.
- `pulls/{n}`, `/files`, `.diff`, `/commits`, `languages`, the repo, and `raw/<changed file>` twice (200, then 404);
- `raw/AGENTS.md`, which got 404 in the lab;
- `issues/{n}/labels`, then **`POST issues/{n}/labels` → 403**;
- `issues/{n}/comments`, then `POST issues/{n}/comments` → 201.

On a push, it made the same reads, then `PATCH issues/comments/{id}` → 200.

- **`AGENTS.md` is prompt context, read from the default branch.** `repo_context_files = ["AGENTS.md"]` and `repo_context_from_default_branch = true` are upstream defaults. The provider's `get_repo_file_content` reads the base or default branch, never the PR head (`gitea_provider.py:885`), so an author cannot instruct the review of their own PR.
- **Labels 403 on every review**: `enable_review_labels_effort` and `enable_review_labels_security` default to true. Harmless, but it is an error per review.

### Delivery. The hook's `events` list decides whether slash commands are live

Two runs of the same lab, differing only in the webhook `events` and `PR_REVIEWER__FINAL_UPDATE_MESSAGE`:

B changes two variables at once, so the table is not a single-variable A/B. Each effect still has one mechanism.
- Comment delivery depends only on the events the hook stores. That is Gitea's `pullHook`, read at v1.25.5.
- The extra "updated" comment depends only on `final_update_message`. That is PR-Agent's `publish_persistent_comment`, `git_provider.py:547` in 0.45.0.
Neither setting reaches the other's code path.

| | A: `["pull_request"]`, upstream default | B: `["pull_request_only", "pull_request_sync"]`, `false` |
|---|---|---|
| Events Gitea stores | all 8 PR sub-events, `pull_request_comment` and `pull_request_review` included | `pull_request`, `pull_request_sync` |
| On open | 1 `PR Reviewer Guide` | 1 `PR Reviewer Guide` |
| On push | the same comment edited, **plus a second "updated" comment** | the same comment edited, nothing added |
| Author comments `/ask …` | **answered by the reviewer** (an LLM call on NaN) | no delivery, no reviewer call |
| Author comments `/describe` | tried `PATCH pulls/{n}` → 403 | no delivery |
| PR title and body | unchanged | unchanged |

- **Why.** Gitea's hook API expands `pull_request` into every PR sub-event (`pullHook` in `routers/api/v1/utils/hook.go` at v1.25.5). PR comments are delivered as `issue_comment`, and `gitea_app.handle_comment_event` runs any `/` command from any author. `pull_request_only` is the API's name for opened, closed, reopened and edited alone.
- **Stored under different names.** Gitea stores and returns `pull_request_only` as `pull_request`. So a reconciler that compares declared events to live ones as a superset never converges on `pull_request_only`, and it would not notice a widened hook either. For this hook a surplus event is not fail-closed, unlike n8n's.

### Signatures and login

- Unsigned POST → 400 (`Missing signature header`). Wrongly signed → 401 (`Invalid signature`).
- **`prohibit_login=true` kills the account's API tokens.** The same token gave 200 on `GET /user`, then 403 after the flag was set (`This account is prohibited from signing in…`, `api.go:818`). So a machine identity that must call the API cannot carry the flag. "Login prohibited" can only mean no usable password. This applies to AUTH-007's pusher as much as to this reviewer.

## Test status

- PR 2 (reviewer identity), 2026-09-24: `poetry run pytest -q tests/` → 2661 passed, 15 skipped. The new files are `tests/test_gitea_review_team.py` (24) and `tests/test_gitea_reviewer_identity.py` (10), plus `test_the_reviewer_grant_is_exactly_the_measured_requirement`. Each was red before its implementation.
- No regressions in the existing suite: yes. The reconciler's fakes gained the `can_create_org_repo` keyword, and the compose render test gained the two reviewer variables. No assertion changed.

## Decisions made during implementation

- 2026-09-24, Manu: run it in the cluster, copy `NAN_API_KEY` into SOPS, and write the spec before any code.
- 2026-09-24, Manu: PR 2 carries the ADR-062 D1 amendment for both machine exceptions. That is AUTH-007's owner-level pusher, with the content decided on #1781 on 2026-09-22, and this read-only reviewer. It is one amendment, not two in parallel on the same section.
- 2026-09-24, Manu: the reviewer account is **`mentor`**, separate from `hefesto`. Three reasons:
  - `hefesto` holds per-unit write on every `personal/` repo, and read-only access is what contained the reviewer in the lab.
  - The token lives in an internet-facing pod that reads untrusted diffs, so it should not share a blast radius with the reconciler, or its rotation.
  - Separate authorship lets a triage tell a review from reconciler output.
- 2026-09-24, implementation: the reviewer's `reviewers` team is converged in **both** directions. A team widened to write is narrowed back, unlike `reconcilers`, which only widens. The reviewer's membership is part of the plan, because a correct team it is not in grants it nothing.
- 2026-09-24, implementation: `reviewer_token` keeps `Expiry.NEVER`, like `bot_token`. The declared-rotation-date control the amendment gives AUTH-007's owner-level pusher is for organization ownership. The reviewer is bounded by read access to code.
- 2026-09-24, implementation: `gitea-bootstrap.sh`'s machine account block became `ensure_machine_account`, called for the bot and the reviewer. The log lines are unchanged apart from the account name, so the bot's tests and `changed_when` still match.
- 2026-09-24, Manu: the scope is **the whole forge, `teledyne/` included**. `teledyne/` holds a third party's material (ADR-065 D2), so this is the deliberate decision that ADR asks for, not an inherited one. Manu accepts that its PR diffs go to NaN and that `mentor` holds read access to its code.
- Hook events are `pull_request_only` and `pull_request_sync` (corrected 2026-09-24 from `pull_request`, which the lab showed also delivers comments). Slash commands stay out until an author filter exists (proposal, Out of scope).

## Promotion candidates

- [ ] Lesson: <yes / no>
- [ ] ADR: the ADR-062 D1 amendment for a reviewer identity, shared with AUTH-007
- [ ] Pattern: <yes / no>

## Archive checklist

- [ ] `status: archived`, folder moved to `specs/archive/`
- [ ] #1823 closed by the PR that archives this spec
