---
id: lesson-299-a-tag-asymmetry-made-the-play-report-success-
type: lesson
status: active
created: "2026-08-08"
owner: manu
tags: [kubelab, lesson, ansible, sops, tags, verification, false-green, ansible-033, gotcha]
---

# A tag asymmetry made the play report success while delivering no credential — and the acceptance probe agreed (ANSIBLE-033)

**Context:** `make provision NODE=ace2 ENV=staging TAGS=dev_node` — the exact command the spec's acceptance criterion prescribes.

**Problem:** In every `provision-*.yml`, the config-loading `pre_tasks` carry `tags: [always]` but the three SOPS decryption tasks carry no tags. A `TAGS=` run therefore skipped decryption and left `secrets` undefined — while `config` stayed fully populated, which is precisely what made it look healthy. The role var used `| default('')` (deliberately, so an operator without the secret gets a node with no identity rather than a failed play), so the token silently became the empty string and all four identity tasks skipped. The play reported `ok=29 changed=2 failed=0`.

Worse, the acceptance probe passed. It asserted convergence — a second pass reporting `changed=0` — which cannot distinguish "converged with the credential in place" from "converged because every task that would install it was skipped". A criterion claiming *delivery* was verified by a command that only measured *stability*.

**Solution:** Tag the decryption tasks `always`, matching the config loads directly above them. Then strengthen the probe to also assert the role saw a non-empty token — keyed on the token *read* rather than the login, because the login legitimately skips on an already-converged node while the read is guarded only by the token being non-empty. The same untagged pattern in the other playbooks is tracked separately (#893); those fail loudly instead of silently, because their secret vars carry no `default`.

**Rule:** A `default` on a value sourced from a secret store converts a loud failure into a silent one — pair it with something that proves the value actually arrived. And when writing an acceptance command, ask what *else* could make it exit 0: if the answer includes "the feature was never installed", the command measures the wrong thing. Convergence is not delivery.

**Tags:** `#ansible` `#sops` `#tags` `#verification` `#false-green` `#ansible-033` `#gotcha`
