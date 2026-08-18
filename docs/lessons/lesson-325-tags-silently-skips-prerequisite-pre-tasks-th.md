---
id: lesson-325-tags-silently-skips-prerequisite-pre-tasks-th
type: lesson
status: active
created: "2026-08-14"
owner: manu
tags: [kubelab, lesson, ansible, tags, secrets, sops, merge-order, ansible-035, gotcha]
---

# `--tags` silently skips prerequisite `pre_tasks` that were never tagged, and a shared secret key collides across an Ansible env-override merge

**Context:** ANSIBLE-035 (#928) rolled a systemd maintenance timer out to 7 nodes as a property of provisioning, then wired its failure to POST a notification through n8n's webhook. Both bugs below were caught before shipping — one by a live failure, one by simulating the merge before writing any Ansible task — but both were the kind of thing that would otherwise have shipped silently.

**Bug 1 — `--tags` skips config/secrets loading that nothing marks as prerequisite.** Adding a task that referenced `secrets.*` under `--tags maintenance` failed with `'secrets' is undefined` on 4 of the 7 playbooks (vps, aws1, rpi3, rpi4). Their `pre_tasks` that decrypt SOPS and build the `secrets` fact carried no `tags:` at all, so Ansible's normal tag-filtering behavior — a task with no matching tag and no `always` tag is skipped when a `--tags` filter is active — silently dropped them, while the new role task (which *did* inherit a matching tag from its role invocation) still ran and referenced an undefined fact. The other 3 playbooks (beelink, ace1, ace2) already had `tags: [always]` on the equivalent tasks, each with a comment naming this exact scenario — the fix was bringing the 4 stragglers in line with an already-correct, already-documented pattern already living in the same repo, not inventing one.

**Bug 2 — reusing a secret's key path across a merge context it wasn't scoped for.** The plan was for all 7 nodes to authenticate to n8n's webhook using the existing `apps.services.automation.notify.webhook_secret`. Before writing the Ansible task, the exact `combine()` merge every playbook performs (`common.enc.yaml` deep-merged with that node's own `{env}.enc.yaml`) was simulated in a throwaway script for all three node contexts in play (common-only, common+staging, common+prod) — and it showed that 3 of 7 nodes (the ones with `deploy_env: staging`) would resolve *staging's own, different* value for that key, because staging's env-file override wins the merge. Those nodes would have sent prod n8n a token it doesn't recognize, and gotten a silent 403 nobody was watching for. Fixed with a new key, `fleet_webhook_secret`, stored *only* in `common.enc.yaml` — no per-env override exists for it, so there's nothing for any env file to win against.

**Rule:**
- **A `pre_tasks` block with no tags is invisible to `--tags` filtering, even if a task three roles later assumes its output exists.** Any fact another task might reference under a narrower `--tags` run needs `tags: [always]` on the tasks that build it — grep for the pattern already established elsewhere in the same repo before assuming a new playbook needs to invent one.
- **Reusing an existing secret's key path for a new consumer is only safe if that consumer resolves config exactly the same way every existing consumer does.** Before wiring a secret into a new set of callers, simulate (or trace by hand) the actual merge/override chain each caller goes through — "it's the same key, so it'll be the same value" is an assumption, not a fact, the moment more than one file can define that key.
- **Both of these were caught by measuring the actual resolved state (a live error; a simulated merge output) rather than reading the Ansible source and reasoning about what "should" happen.** Neither is discoverable by code review alone — `--tags` skip behavior and merge-precedence collisions both only manifest at the exact invocation that exercises them.

**Tags:** `#ansible` `#tags` `#secrets` `#sops` `#merge-order` `#ansible-035` `#gotcha`

---
