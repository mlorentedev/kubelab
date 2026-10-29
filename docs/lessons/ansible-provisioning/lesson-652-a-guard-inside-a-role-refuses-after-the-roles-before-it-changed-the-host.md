---
id: lesson-652-a-guard-inside-a-role-refuses-after-the-roles-before-it-changed-the-host
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, edge, preflight]
---

# A guard inside a role refuses after the roles before it changed the host

**Context**: ADR-075 D7 says edge changes run over the homelab LAN, because applying the uplink can cut a session that rides the tailnet it carries. The `gateway` role asserted it: the run's `ansible_host` had to be the edge's LAN address.

**Problem**: The role is the fifth in `provision-rpi4.yml`. On 2026-10-29 a `make provision NODE=rpi4 ENV=prod` without `BOOTSTRAP=1` failed on that assert only after `rpi_boot`, `base_system`, `ssh_hardening` and `node_notify` had made 6 changes on the edge, over the very tailnet the guard exists to keep the run off (#2775). The guard was correct and placed where it could not protect anything: a refusal that comes after changes is a partial run, not a refusal.

**Solution**: The assert moved to the play's `pre_tasks`, tagged `always`, after the config merge and before any role. Every pre_task before it runs on the controller (`include_vars`, `set_fact`), so a refused run has changed nothing. Its `when` keeps the role's scope: every run that applies the `gateway` role (`all`, `tagged` or `gateway` in `ansible_run_tags`, and `gateway` not skipped). `tests/test_gateway_role_tasks.py` holds the position, the scope, and that the role keeps no second copy.

**Rule**: A precondition for a run goes where nothing has run yet: a pre-flight play or the first `pre_tasks`, after only controller-side tasks. Inside a role it guards that role, and only after every role before it has already acted on its own terms.

**Tags**: `#adr-075` `#preflight` `#issue-2775`
