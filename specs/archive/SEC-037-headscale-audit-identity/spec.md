---
id: SEC-037-headscale-audit-identity
type: spec
status: archived
created: "2026-10-27"
owner: manu
issue: "mlorentedev/kubelab#2734"
review: waived
review_waived_reason: "Reviewed on PR #2764 by CodeRabbit and pr-agent (five findings, all applied), mutation-tested, and verified live on the VPS (AC3). An adversarial pass would re-review merged, deployed code."
---
# SEC-037: Headscale audit identity

## Intent

Unattended read-only audits of the Headscale host have no identity they can
use. `deployer` is root-equivalent on the VPS (passwordless `sudo` and the
`docker` group), so loading a personal key into an agent would hand automation
full control of the host, revocable only by revoking the person. A consumer
that segments this Headscale instance needs to read its policy, nodes and users
before any of its nodes enrolls.

Adding the key by hand would create the undeclared-key debt #2246 (SEC-033)
removes, and its first `exclusive: true` run would delete it. So the host's
state is declared here, where the host is owned.

## Scope

**In:**

- `infra/ansible/roles/headscale/files/headscale-audit.sh`: forced command.
  Exact-match allowlist (quoted `case` patterns, never globs or arguments):
  - `''` and `true`: liveness, exit 0 without running anything.
  - `hostname`, `id`, `uname -a`, `uptime`.
  - `docker exec headscale headscale nodes list -o json`
  - `docker exec headscale headscale users list -o json`
  - `docker exec headscale headscale policy get`
  - `docker exec headscale headscale version`

  Subcommands and `-o json` verified against the v0.28.0 source
  (`cmd/headscale/cli/{root,nodes,users,policy}.go`). The container is
  `headscale` (`templates/docker-compose.yml.j2`). Anything else exits 126 with
  `command not allowed`. Every attempt, allowed or refused, goes to
  `logger -t headscale-audit`. `SSH_CLIENT` defaults to `unknown` so `set -u`
  can never abort before a refusal is logged. The file is LF only.
- Role tasks (new `tasks/audit_identity.yml`, included from `tasks/main.yml`):
  install the script `root:root 0755` at `/usr/local/bin/headscale-audit`;
  for each declared identity, `ansible.posix.authorized_key` on `deployer` with
  `key_options: restrict,command="/usr/local/bin/headscale-audit"` plus
  `from="<source>"` when a source is declared, `state: present`, never
  `exclusive` (that is SEC-033's switch).
- Declaration: public key and owner in `common.yaml` under
  `apps.services.core.headscale.audit_identities` (shape compatible with
  SEC-033's per-user declarations). The optional source address comes from SOPS
  (`infra/config/secrets/common.enc.yaml`), because it is network inventory and
  this repository is public. Key comments stay neutral, with no host names.
- Wiring in `playbooks/deploy-vps.yml` (headscale role vars).
- `tests/test_headscale_audit.py`: runs the script under `sh` in CI (Linux).

**Out:** exclusive `authorized_keys` and the unknown key (#2246); root login
on the public address (#2224); any write command in the allowlist, ever.

## Checklist

- [x] [AC1] Write `tests/test_headscale_audit.py` first and watch it fail: ✓ 2026-10-28
  - LF-only bytes check of the script;
  - liveness (`''`, `true`) exits 0, also with `SSH_CLIENT` unset;
  - `hostname` exits 0 with output;
  - each refusal exits 126 with `command not allowed`, including:
    `rm -rf /tmp/canary`, `bash`, `hostname; id`, `true && id`,
    `hostname | sh`, `hostname $(id)`, `headscale nodes list -o json` (bare),
    `docker exec headscale headscale nodes delete -i 1 --force`,
    `docker exec headscale headscale policy set -f /tmp/p.hujson`,
    `docker exec headscale headscale nodes list -o json; id`,
    `docker exec -it headscale sh`,
    `docker run --rm -v /:/host alpine cat /host/etc/shadow`, `docker ps`,
    `sudo -n true`;
  - refusal with `SSH_CLIENT` unset exits 126 without `unbound variable`.
- [x] [AC1] Add `files/headscale-audit.sh` and make the tests pass. ✓ 2026-10-28
- [x] [AC2] Static tests: the task installs `root:root 0755`; `key_options`
      contains `restrict` and `command=`; `exclusive` is never set; no IPv4
      literal in `common.yaml` under `audit_identities`. ✓ 2026-10-28
- [x] [AC2] Add `tasks/audit_identity.yml`, defaults (`headscale_audit_identities: []`),
      the include, the `deploy-vps.yml` wiring and the `common.yaml` declaration. ✓ 2026-10-28
- [x] [AC2] `make lint-ansible` and the targeted `pytest` run green; PR with
      `Closes #2734`. ✓ 2026-10-28 (#2764, CI green)
- [x] [AC3] Operator runs the full `make deploy TARGET=vps ENV=prod` twice:
      second run `changed=0`. No source address yet (see Evidence). ✓ 2026-10-29
- [x] [AC3] From the client: `true` and an allowlisted read exit 0; `bash` and
      `hostname; id` exit 126; `journalctl -t headscale-audit` shows both. ✓ 2026-10-29

Acceptance criteria: AC1 forced command proven by tests in CI; AC2 the role
declares and installs it idempotently with no plaintext source address; AC3 a
live apply converges and the restricted key works and is refused as designed.

## Evidence

- 2026-10-28: `tests/test_headscale_audit.py` red first (42 failed, nothing
  implemented), then 45 passed locally under busybox `sh`. The run also caught a
  portability bug: busybox `tr -c '[:print:]'` treats the class as literal
  characters, so the log sanitizer uses the octal range `\001-\037\177`.
- Design additions while implementing: the key comment comes from `name`, never
  from the key file (the generated comment carried a host name); the source
  address is catalogued in `SECRET_CATALOG`
  (`apps.services.core.headscale.audit_sources.audit_automation`, EXTERNAL, prod)
  so the orphan audit does not flag it once the operator adds it.
- yamllint and `shellcheck -s sh` clean on the changed files. `make lint-ansible`
  runs in CI (Ansible does not run on the Windows controller).

- Review (#2764): removing a declaration now revokes the key (every line that
  carries the forced command and is no longer declared is removed; personal keys
  are untouched), the authorize task is `no_log` because its diff carries the
  source, and the allowlist guard reads every `case` arm. Mutations: dropping
  the declared-key filter and adding an unquoted `approve-routes*` arm both go red.

- 2026-10-29, live (AC3): from msi, `make deploy TARGET=vps ENV=prod` with
  `CHECK=1`, then twice; the second run reported `changed=0`. On the host the
  script is `root:root 0755` and `authorized_keys` holds one line carrying it.
  From the client: `true`, `headscale version` and `nodes list -o json` (valid
  JSON) exited 0, while `bash` and `hostname; id` exited 126 with
  `command not allowed`. `journalctl -t headscale-audit` showed the allowed and
  refused attempts.
- The checklist's `deploy-vps --tags headscale` was wrong: the playbook's
  `pre_tasks` (config load, SOPS decrypt) carry no `always` tag, so a tag
  filter skips them and the role fails on undefined facts. lesson-325 recorded
  this mechanism on 2026-08-14 for the provision playbooks, and `deploy-vps.yml`
  was never brought in line. The full deploy is the supported path.
- `from=` is not set: the client's egress is a corporate address that may
  rotate, and a stale pin would silently lock the audit out. The key is still
  bound to `restrict` and the read-only allowlist. To pin later, set
  `apps.services.core.headscale.audit_sources.audit_automation` (an address or
  CIDR) in `common.enc.yaml` and run the deploy again.

## Next

Done. Follow-ups: the `deploy-vps.yml` pre_tasks tag gap (lesson-325
recurrence) and the stable controller path for the VPS.

## Promotion candidates

- [x] Lesson? yes: docs/lessons/ansible-provisioning/lesson-325-tags-silently-skips-prerequisite-pre-tasks-th.md (recurrence appended)
- [x] ADR? no: no new architectural decision; the forced-command design is local to the headscale role and is recorded in this spec
- [x] Pattern? no: restricted forced-command SSH identities appear in this repo only so far; the pixelnam-lab prototype is retired in favour of this one
