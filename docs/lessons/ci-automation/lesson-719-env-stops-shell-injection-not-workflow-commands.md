---
id: lesson-719-env-stops-shell-injection-not-workflow-commands
type: lesson
status: active
created: "2026-11-06"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, security]
---

# Passing untrusted text through `env:` stops shell injection, not workflow commands

**Context**: `deploy-verify.yml`'s `on-status` job prints Argo CD's commit-status description, which is
the message of whatever made the sync fail. GITOPS-003 routed it through `env:` so that no `${{ }}`
reaches the shell, which is the standard fix for workflow injection.

**Problem**: the runner reads stdout line by line, and any line starting with `::` is a workflow
command: `::add-mask::`, `::stop-commands::`, or a forged `::error::`. `env:` keeps the text out of the
shell parser, but `echo "$DESCRIPTION"` still writes every line of it to stdout. A message with an
embedded newline therefore controls the runner, even though it cannot run a shell command. The same
holds for the data part of our own `::error::` annotation: a newline there ends the command and starts
a new line the runner obeys (signed review of GITOPS-003, #2942).

**Solution**: read the variable once into a sanitized copy, with CR and LF turned into spaces
(`desc="${DESCRIPTION//[$'\r\n']/ }"`). Every output then uses `$desc`, and the annotation data is
escaped further with `${desc//%/%25}`. The status context gets the same collapse, since the poster
chooses it too. `tests/test_deploy_verify_workflow.py` runs the shipped step with a hostile description
and context, and asserts three things. The only command in the output is the step's own `::error`. A
literal `%` arrives as `%25`. Each field appears in the script exactly once.

**Rule**: untrusted text printed by a step is input to the runner as well as to the shell. Collapse it
to one line before any `echo`, and escape `%` before using it as a command's data. Pin both with a test
that executes the step rather than reading it.

**Tags**: `#github-actions` `#issue-2942`
