---
id: SEC-037-headscale-audit-identity
type: spec
status: draft
created: "2026-10-27"
owner: manu
issue: "mlorentedev/kubelab#2734"
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

- [ ] [AC1] Write `tests/test_headscale_audit.py` first and watch it fail:
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
- [ ] [AC1] Add `files/headscale-audit.sh` and make the tests pass.
- [ ] [AC2] Static tests: the task installs `root:root 0755`; `key_options`
      contains `restrict` and `command=`; `exclusive` is never set; no IPv4
      literal in `common.yaml` under `audit_identities`.
- [ ] [AC2] Add `tasks/audit_identity.yml`, defaults (`headscale_audit_identities: []`),
      the include, the `deploy-vps.yml` wiring and the `common.yaml` declaration.
- [ ] [AC2] `make lint-ansible` and the targeted `pytest` run green; PR with
      `Closes #2734`.
- [ ] [AC3] Operator adds the source address to SOPS and runs
      `deploy-vps --tags headscale` twice: second run `changed=0`.
- [ ] [AC3] From the client: `true` and an allowlisted read exit 0; `bash` and
      `hostname; id` exit 126; `journalctl -t headscale-audit` shows both.

Acceptance criteria: AC1 forced command proven by tests in CI; AC2 the role
declares and installs it idempotently with no plaintext source address; AC3 a
live apply converges and the restricted key works and is refused as designed.

## Evidence

None yet. Design decided 2026-10-27; implementation not started.

## Next

Write `tests/test_headscale_audit.py` (first checklist item) and watch it fail.

## Promotion candidates

- [ ] Lesson? `no`
- [ ] ADR? `no`
- [ ] Pattern? `no`
