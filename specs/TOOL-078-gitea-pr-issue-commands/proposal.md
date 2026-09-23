---
id: "TOOL-078-gitea-pr-issue-commands"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-09-22"
issue: "kubelab#1792"
tags: [spec, proposal, gitea, forge, review-loop, migration]
template_version: "1.0"
---

# TOOL-078: open pull requests and issues on the Gitea forge from a session

<!-- from issue #1792: TOOL-078: the Gitea forge has no pull request or issue path from an agent session -->

## Why

TOOL-035 moved `personal/resume` onto the forge, and `toolkit services gitea git` made pushing to it
possible without a credential ever reaching a terminal. The review loop did not move with them. Nothing
can open a pull request or an issue on Gitea from a session: the wrapper exposes only `git`,
`GiteaClient` has no pull-request or issue method, `tea` is not installed (and would store a token in
plaintext), and `dotf pr` reads GitHub only.

Measured from local refs on 2026-09-22: five pushed branches of `personal/resume` carry commits that are
not on `main`, one of them the ADR that records the migration itself. Every branch an agent pushes waits
for a human to open its PR in the web UI, and a defect found in `resume` that day could not be filed where
it belongs.

## What

1. `GiteaBasicAuthClient.create_pull` and `create_issue`: `POST /repos/{o}/{r}/pulls` and `/issues`.
2. A small feature module that turns CLI input into those calls and holds the rules (repository shape,
   head differs from base, non-empty title), so the rules are tested without a network.
3. `toolkit services gitea pr create` and `toolkit services gitea issue create`. Each prints the created
   number and URL and nothing else.

## Which credential, and why

The same one `gitea git` pushes with: `apps.services.core.gitea.admin_password` through basic auth, via
`resolve_git_credential`. Opening a PR is the second half of the act a push begins, so it belongs to the
same **authoring** identity. `admin_token` deliberately lacks `write:repository`, and the bot is the
reconciliation identity, not an author (ADR-065 D1). Using a third credential would split one act across
two identities. The secret travels in the request's basic-auth header and nowhere else: not argv, not
stdout.

## Out of scope

- Reading PR state, comments or CI status, and posting comments (the `## Review triage` record). That is
  the next consumer (`dotf pr triage-queue` covering Gitea), and it deserves its own ticket once this lands.
- Merging. Merge stays a supervised human action in every repository.
- Editing or closing PRs and issues.

## Risks / open questions

- **Live verification needs the forge up.** AC1 and AC2 are verified against prod by opening a real PR and
  a real issue on `personal/resume`. The unit suite covers everything short of the network.
