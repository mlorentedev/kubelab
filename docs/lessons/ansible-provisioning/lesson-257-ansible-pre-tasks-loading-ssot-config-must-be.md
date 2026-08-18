---
id: lesson-257-ansible-pre-tasks-loading-ssot-config-must-be
type: lesson
status: active
created: "2026-05-19"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# Ansible pre_tasks loading SSOT config MUST be tagged `[always]` for tag-selective deploys

**Context:** PR3a (DASH-DT-014a) wired the new `glances` Ansible role into `provision-ace1.yml` and `provision-ace2.yml`. Both playbooks have pre_tasks that load `common.yaml` + env override + merge them into a single `config` fact. The new role uses `config.networking.nodes.{ace1,ace2}.tailscale_ip` and `config.apps.services.observability.glances.*`. Live smoke was `make provision NODE=ace1 ENV=staging TAGS=monitoring` (tag-selective to avoid touching k3s/docker/tailscale roles).
**Problem:** First provision attempt failed immediately with `'config' is undefined`. Cause: ansible's `--tags monitoring` filter skips any task without a matching tag, including all pre_tasks that load `config`. Result: roles run before any config is loaded. Same playbooks (provision-bee, provision-vps, provision-rpi4) have the same bug latent — they have never been exercised with selective tags because nobody noticed.
**Solution:** Add `tags: [always]` to every pre_task that loads SSOT config (include_vars for common.yaml, env override, and the set_fact merge into `config`). Do NOT tag SOPS decrypt pre_tasks as always — those are only needed when the run actually consumes secrets (tailscale/k3s_server). With `tags: [always]`, `--tags monitoring` (or any tag) now correctly loads config before the role runs. Standard Ansible pattern; benefits all future tag-selective deploys, not just glances. Lesson: when adding a new role that depends on `config`, also verify the host playbook's pre_tasks are taggable.
**Tags:** `#ansible` `#playbooks` `#ssot` `#tags` `#gotcha`
