---
id: lesson-555-hermes-approvals-test-does-not-run-the-command-scanner
type: lesson
status: active
created: "2026-10-10"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, hermes, agents, approvals, tirith]
---

# `hermes approvals test` does not run the command scanner

**Context**: AI-012 PR 1 ported hermes-nan's `security.tirith_fail_open: false`
to hermes-kubelab. Every provision already reads the deny list back through
`hermes approvals test`, so that was the obvious place to prove the scanner ran.

**Problem**: The evaluator does not model Tirith. In v2026.9.24, inside the
gateway, a homograph URL (`curl http://g` + Cyrillic `оо` + `gle.com`) reads
`allow` from `approvals test` and `block` from
`tools.tirith_security.check_command_security`. A probe built on the evaluator
would pass with the scanner missing. With the scanner fail-closed, that state
blocks every scheduled command and puts an approval prompt in front of `ls`.
The config alone does not show it: the key reads `false` either way.

**Solution**: The role asks the scanner itself, as the gateway's user, for two
verdicts: a plain command must be `allow` and the homograph must be `block`.
Measured on ace2: with `TIRITH_BIN=/nonexistent` the plain command reads
`block`, `tirith spawn failed (fail-closed)`, so the pair tells a working
scanner from a missing one. The task retries twelve times, 5 s apart, because the
first start downloads the binary to `$HERMES_HOME/bin` in the background.

**Rule**: A dry-run tool proves only the guards it models. Before you build a
probe on one, feed it an input that only the guard you care about catches. If
the verdict does not change, call that guard directly.

**Tags**: `#hermes` `#approvals` `#tirith` `#spec-ai-012`
