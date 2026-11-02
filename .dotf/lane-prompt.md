KubeLab lane. Your ticket: #{{.Number}} {{.Title}}. This worktree exists on branch {{.Branch}}, created from origin/master.{{if .Remaining}} Behind it in the queue:{{range .Remaining}} #{{.}}{{end}}.{{end}}

Read AGENTS.md and CLAUDE.md before your first tool call. Run `make worktree-init` once. Reply to the user in Spanish; every durable artifact stays in English.

One ticket, one branch, one PR. Open it as a draft, mark it ready, record `## Review triage`, then `dotf pr triage-queue --pr <N> --repo mlorentedev/kubelab && dotf pr land <N> --repo mlorentedev/kubelab`. Take the next free lesson number from origin/master and the open PRs. Do not touch other lanes' branches or PRs.

When you land, do not delete your worktree. Run /handoff, run `dotf lane next` to start the successor, and stop.
