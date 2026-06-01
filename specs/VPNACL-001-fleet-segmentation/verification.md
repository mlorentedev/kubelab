---
tags: [spec, verification]
created: "2026-05-31"
---

# Verification - VPNACL-001-fleet-segmentation

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, observed behavior). Filled during implementation.

- [x] AC1 (role policy-path param + reload-on-change) -> render/static-YAML test `tests/test_headscale_role.py` (7 tests green); reload is SIGHUP `docker kill --signal=HUP headscale` (NOT restart), policy path SEPARATE from config.yaml restart path. On-VPS reload exercised in VPN-ACL-002 (dormant until then: default `headscale_policy_path: ""`). _(commit pending)_
- [ ] AC2 (`headscale policy check` CI gate) -> CI run `<link>` — VPN-ACL-002
- [ ] AC3 (permissive baseline preserves flows + auto-revert) -> probe output `<evidence>` — VPN-ACL-002
- [ ] AC4 (hermes SSH-reachable, tagged, own-credential auth) -> `headscale nodes list` + service-auth observation — VPN-ACL-003

## Test status

- Test suite: `<command> -> <output>`
- Manual smoke test: probe of preserved flows post-reload; deliberately-broken-policy auto-revert exercised
- No regressions in existing test suite: yes / no

## Decisions made during implementation

- **Reload = SIGHUP via Docker, not `systemctl`** (corrects ADR-041 wording for this deployment). Headscale runs in Docker Compose (distroless), and the official policy docs state file-policy changes "require ... a SIGHUP signal" → handler is `docker kill --signal=HUP headscale` (PID 1). Verified against the live v0.28.0 install + Headscale docs.
- **Two separate change paths** (finding #1): policy-file change → SIGHUP `reload headscale` handler (no downtime); `config.yaml`/compose change → `restart` (server config is read only at startup). Conflating them in the old single handler would mean a policy change either silently doesn't apply or needlessly drops sessions.
- **VPN-ACL-001 ships a permissive-first allow-all seed** (`policy.hujson.j2` = `{"acls":[{"accept",*→*:*}]}`) so the role is internally consistent and independently deployable. The enumerated baseline (preserved flows) + `agents`/`tagOwners` + `tag:hermes` dst matrix, all rendered from the `networking` SSOT (no hardcoded IPs), are authored in VPN-ACL-002. Dormant by default (`headscale_policy_path: ""` → allow-all, byte-identical to today's render).
- **Test tier**: pure render (jinja2) + static-YAML assertions in `tests/test_headscale_role.py` (root `tests/`, marker-less) → runs under `make test` with no VPN/SSH, unlike `tests/infra/` live tests.
- **Fix #5**: removed the redundant `wait for headscale` handler + its only notify; the always-run inline "Wait for Headscale to be healthy" task remains the single readiness gate.

## Promotion candidates

- [ ] Lesson for `90-lessons.md`? <likely yes — permissive-first + external-probe rollout on a single Headscale control plane without the v0.29 tests block>
- [ ] ADR-worthy decision? <no — ADR-041 already covers the model>
- [ ] New pattern candidate for `00_meta/patterns/`? <maybe — "deny-by-default rollout on a single control plane via permissive-first + external probe + auto-revert" if it recurs>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/VPNACL-001-fleet-segmentation/` -> `specs/archive/VPNACL-001-fleet-segmentation/`
- [ ] Backlog entries `VPN-ACL-001/002/003` ticked in vault `11-tasks.md` with PR link
- [ ] Promotions above executed (if any)
