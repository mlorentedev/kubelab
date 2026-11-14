---
id: lesson-752-a-guard-that-pairs-a-file-with-a-pin-makes-the-bots-first-deploy-pr-red
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, delivery, console, dependabot, pr-3443]
---

# A guard that pairs a file with the pin makes the bot's first deploy PR red, and the bot's branch is not the place to fix it

**Context**: The console's delivery was built so that nothing releases before an image can be re-tagged: `tests/test_console_image.py` ties the `commit-message.prefix` of the console's docker entry in `.github/dependabot.yml` to the presence of `apps.platform.console.version` in `values/staging.yaml`. The prefix is `chore` until the pin exists and api's `fix` after. The pin is written by the deploy PR the staging workflow opens.

**Problem**: The first deploy PR (#3532) adds the pin and nothing else, because that is all the bot writes. The pairing test then expects `fix` and finds `chore`, so shard 1 failed on a PR that did exactly what the bot is for. The two halves of the pair cannot land separately: with the prefix flipped first on master, the test fails there (no pin yet), and with the pin first it fails on the pin. And the bot's branch is the wrong place to add the second half: the workflow rebuilds `deploy/staging-console` from master and force-pushes it on every console build, so a commit added to it survives only until the next push to master that builds the console. PR-Agent also skips `deploy/` branches by design (a `/review` comment on the PR does run it), so a bot-branch PR carries two extra frictions beyond the red test.

**Solution**: The first pin is a hand-made PR from a normal branch that carries both halves: the pin and the generated overlay copied from the bot's PR, and the prefix flip. The bot's PR is then closed as superseded; a later dispatch for the same sha finds the pin already in master and changes nothing, and one for a newer sha is an ordinary mechanical bump.

**Rule**: When a guard pairs a file with a value the bot writes, the bot cannot produce the first change alone: plan the first pin as a hand-made PR that carries both halves, and say so in the delivery plan before the bot opens its PR. A fix pushed to a bot-owned branch is a fix with a lifetime of one build.

**Tags**: `#delivery` `#dependabot` `#pr-3443`
