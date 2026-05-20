---
tags: [spec, verification, ansible, observability]
created: "2026-05-13"
updated: "2026-05-19"
---

# Verification - DT-014-glances-coverage (PR3a)

## Evidence

- [x] **AC1** Shared role exists -> `infra/ansible/roles/glances/{defaults,handlers,tasks,templates}` in commit `090e9de`. Tailscale-bind compose template, image from `config.apps.services.observability.glances.image`.
- [x] **AC2** `provision-ace1.yml` invokes shared role -> playbook role block with `tags: [monitoring, glances]`, vars from `config.networking.nodes.ace1.tailscale_ip` and `config.apps.services.observability.glances.*`.
- [x] **AC3** `provision-ace2.yml` invokes shared role -> same pattern, vars from `ace2.tailscale_ip`.
- [x] **AC4** `ace2_services` cleanup removed -> 3 tasks (Check legacy compose, Stop legacy, Remove `/opt/glances` paths from loop) deleted from `roles/ace2_services/tasks/main.yml`.
- [x] **AC5** Lint clean -> `yamllint` only reports pre-existing line-length warnings consistent with provision-bee.yml:177 and provision-rpi4.yml:133 (same `glances_memory_limit` line). `ansible-playbook --syntax-check` passes both playbooks. `ansible-lint` not re-run; TOOL-009 owns repo-wide cleanup.
- [x] **AC6** ace1 smoke -> `make provision NODE=ace1 ENV=staging TAGS=monitoring` first run `ok=13 changed=3` (template, container start, restart handler). `curl http://100.64.0.11:61208/api/4/quicklook` -> HTTP 200. Bind verified `100.64.0.11:61208` (tailscale_ip, NOT 0.0.0.0).
- [x] **AC7** ace2 smoke -> `make provision NODE=ace2 ENV=staging TAGS=monitoring` first run `ok=13 changed=4` (dir create + template + start + handler). `curl http://100.64.0.5:61208/api/4/quicklook` -> HTTP 200. Bind verified `100.64.0.5:61208`.
- [x] **AC8** Homepage cockpit tiles -> verified 2026-05-19 by user post-merge: ace1 and ace2 tiles render live Glances metrics. Other tiles (VPS, RPi4, RPi3, Jetson) also live. aws1 (no widget by design, ADR-033) and Beelink (widget intentionally absent due to pre-existing broken container, tracked in DASH-DT-014b sub-bullet) excluded from PR3a scope.

**Idempotency**: second `provision NODE=ace1` and `NODE=ace2` runs report `changed=0` for the glances role -> confirms no spurious changes on re-apply.

**Self-migration evidence**: ace1 had a previous ad-hoc deploy from outside git (`/opt/glances/docker-compose.yml`, container `Up 5 minutes` at audit time, bind `0.0.0.0:61208`). New role detected and removed it before deploying its own `/opt/glances/compose.yml` with tailscale-bind. Container_name `glances` reclaimed cleanly via `docker compose down --remove-orphans`.

## Test status

- Test suite: no unit tests applicable (Ansible role + playbook wiring).
- Manual smoke test: see AC6/AC7 above. Both nodes return HTTP 200 from `/api/4/quicklook`. Bindings are tailscale_ip-scoped.
- No regressions in existing test suite: yamllint warnings stable (pre-existing line-length only, no new violations). Idempotency verified.

## Decisions made during implementation

- **Self-migration logic added to the role** (8 LOC). Detects legacy `docker-compose.yml` from prior ad-hoc deploys, runs `docker compose down --remove-orphans`, and removes the file before templating the new `compose.yml`. Added in this PR because ace1 turned out to have an out-of-git ad-hoc deploy; also pre-positions the role for PR3b which will encounter the same situation on 4 more nodes.
- **`tags: [always]` added to 3 pre_tasks in provision-ace1.yml and provision-ace2.yml** (config load + env overrides + merge config). Without this, `--tags monitoring` skipped the pre_tasks and `config` was undefined when the role ran. This is the standard Ansible pattern for SSOT-loading pre_tasks; benefits all future tag-selective deploys, not just glances.
- **ace1 ad-hoc cleanup via role, NOT manual SSH**: rejected the option of `ssh + docker rm` (violates `feedback_never_adhoc_commands`). The role's self-migration step handles it idempotently.
- **Scope kept as PR3a despite ace1 state change**: rejected re-scoping to "ace2 only" because the legacy compose on ace1 needed cleanup anyway and the role's self-migration code is the right place for it.

## Promotion candidates

- [x] **Lesson** for `10_projects/kubelab/lessons.md`: "Ansible pre_tasks that load SSOT config MUST be tagged `[always]` for tag-selective provisioning to work" - non-obvious failure mode; surfaced when running `--tags monitoring` against ace1/ace2.
- [x] ADR-worthy decision: ADR-033 `no-glances-on-hub-until-reliab-009` created during archive (decision surfaced when user asked why aws1 has no widget).
- [x] New pattern for `00_meta/patterns/`: `pattern-self-migrating-role` created — the legacy-cleanup-as-first-task approach used in `roles/glances/` is general enough to recur in future migrations (PR3b is the immediate second occurrence). Promoted during archive.

## Archive checklist

- [x] `proposal.md` frontmatter set to `status: archived`
- [x] Folder moved: `specs/DT-014-glances-coverage/` -> `specs/archive/DT-014-glances-coverage/`
- [x] Backlog entry in vault `11-tasks.md` ticked with PR #175 link
- [x] Promotions executed in vault: 2 lessons (`pre_tasks tags:[always]` + `revert for atomic PR scope`), 1 ADR (ADR-033), 1 pattern (`pattern-self-migrating-role`)

## Spillover (created during archive, separately tracked)

- **DASH-DT-014b**: expanded with Beelink Homepage cockpit widget sub-bullet (cockpit shows `(no Glances)` but Glances container exists, currently broken).
- **SSOT-005..008**: 4 antipattern tickets created when user audited "hardcoded IPs in manifests" post-merge.
- **Beelink Glances broken**: container in restart loop (RestartCount=48, ExitCode=1). Compose file references a `docker-compose.yml.j2` template that never existed in git — same mystery as the ace1 ad-hoc deploy cleaned in PR3a. User self-assigned debug + fix.
