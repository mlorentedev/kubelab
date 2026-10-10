---
tags: [spec, verification]
created: "2026-05-31"
---

# Verification - VPNACL-001-fleet-segmentation

## Evidence

Mapped 2026-10-10 against master `f1c952a8`, for DEBT-019 (#2034). The original 2026-05-31 notes follow the table, corrected where they overclaimed.

| AC | Status | Evidence |
|---|---|---|
| AC1: policy-path parameter, mounted file, reload not restart | met | #235 (`10966ba5`, 2026-06-01). `headscale_policy_path` in the role's defaults; the handler is `docker kill --signal=HUP headscale`. `TestPolicyPathParameterized`, `TestReloadHandler` and `TestPolicyFileDeploy` in `tests/test_headscale_role.py` (28 passed, 2026-10-10). |
| AC2: `headscale policy check` as a CI gate | met | `8b4e4a4d`. The step "Validate Headscale ACL policy" in `.github/workflows/check-config-drift.yml` runs `toolkit infra headscale policy-check` on PRs, pushes and nightly. `make check-headscale-policy`: "Policy is valid" (2026-10-10). |
| AC3: preserved flows after reload; a broken policy auto-reverts | partial | Flows: `toolkit infra headscale probe` 7/7 against the live mesh on 2026-05-31, with 9 nodes online. Auto-revert: proven statically only (`TestAutoRevert`). The restore of a previous policy has never run live, which #2184 (VPN-ACL-011) tracks. |
| AC4: hermes SSH-reachable, tagged, own scoped credential | partial, partly superseded | SSH and `tag:hermes` were proven for hermes-nan on 2026-05-31. hermes-nan was retired on 2026-09-30, so the SSH half has no subject. `tag:hermes` is now held by `hermes-kubelab` (AI-009, node 68), whose egress was measured on 2026-10-07: `vps:443` only. The own-credential (C6) half was never done and is handed to #590. |

### Correction, 2026-10-10

The AC3 line below said "auto-revert exercised for real". It was not. The first activation's probe failed in the propagation window, and the rescue ran with no `.prev` to restore, so it took the branch that `73cfeab7` added: it left the permissive baseline in place and failed loudly. The restore path did not run. #2184 is the drill that would prove it.

### Original notes (2026-05-31)

- [x] AC1 (role policy-path param + reload-on-change) -> render/static-YAML test `tests/test_headscale_role.py` (7 tests green); reload is SIGHUP `docker kill --signal=HUP headscale` (NOT restart), policy path SEPARATE from config.yaml restart path. On-VPS reload exercised in VPN-ACL-002 (dormant until then: default `headscale_policy_path: ""`). _(commit pending)_
- [x] AC2 (`headscale policy check` CI gate) -> `make check-headscale-policy` → "Policy is valid" (real v0.28 binary via Docker); CI gate in `check-config-drift.yml` (prod) via `toolkit infra headscale policy-check`. _(commit 8b4e4a4/2681f19)_
- [x] AC3 (permissive baseline preserves flows + auto-revert) -> activated on prod 2026-05-31; `toolkit infra headscale probe` 7/7 OK against the live mesh (admin→vps, hub→spoke :6443, monitoring, rpi4 route, intra-K3s); 9 nodes stayed online. Auto-revert exercised for real: the first-activation probe hit the post-reload propagation window (false negative) → fixed with probe retries + first-activation rescue tolerance (`73cfeab`). Re-deploy is clean/idempotent.
- [~] AC4 (hermes SSH-reachable, tagged, own-credential auth) -> hermes (node 22, `100.64.0.9`, `hermes-nan`) joined under user `agents`, carries `tag:hermes` (`headscale nodes list`). `ssh hermes-nan` works over VPN (admin→:22). **Segmentation proven in prod**: from hermes, `vps:443` reachable (rc=0), `beelink:9000` reached (refused=service down, ACL allowed), `vps:8080` + `ace1:6443` **dropped** (rc=124, deny) — per-port enforcement on the same node. **Own-credential service auth = C6 follow-up** (fresh session). hermes is a userspace-tailscale K8s pod; durable auto-start = VPN-ACL-008.

## Test status

- `poetry run pytest tests/test_headscale_role.py`: 28 passed (2026-10-10, master `f1c952a8`).
- `make check-headscale-policy`: "Policy is valid" (2026-10-10).
- Manual smoke test: probe of preserved flows after reload, 7/7 (2026-05-31). The deliberately broken policy was not exercised; see the correction above and #2184.
- No regressions: #235 merged with `Validate` and both `Drift` checks green. #235's checks did not include `Tests`; the role's tests ran green on master on 2026-10-10 (above).

## Adversarial review findings

`review.md`, **FAIL**, by `nan/mimo-v2.6-flash` on 2026-10-10, against `04d538e0`. The spec is not archived. Its contract pass (`proposal.md`, `tasks.md`, `features.json`) waits on the operator decisions below, then a new review.

| Finding | Disposition |
|---|---|
| F1 (Major, reproduced): the proposal and ADR-041 §3 say `tag:hermes` is reachable only by admin on `:22`; the rendered policy admits every port to all three user identities | Ticketed as #2189 (VPN-ACL-012). Headscale's policy is allow-only, so the clause cannot be written beside the user `*:*` baseline: it was never implementable under permissive-first. No escalation today, since all three identities already reach everything; it becomes one when #586 narrows user egress, so the two land together. Operator decision: correct the contract, or implement through #586. No policy was changed or probed for this disposition. |
| F2 (Major): the auto-revert restore has never run | Already ticketed: #2184 (VPN-ACL-011, renumbered from VPN-ACL-010, which #591 holds). AC3 stays `partial`. |
| F3 (Major): AC4's own-credential half was never delivered, and its SSH half has no live subject | Already ticketed: #590. Operator decision for the contract pass: amend AC4 to the superseded subject, or deliver through #590. AC4 stays `partial`. |
| F4 (Major, theoretical): a policy rejected on reload deploys green, and the CI and deploy host builders have no parity test | Ticketed as #2190 (VPN-ACL-013). |
| F5 (Minor): `features.json` f4's command runs an egress test, not the row's SSH or credential claims | Awaits the contract pass. f4 has no test to map to while hermes-nan is gone, which is the defect class of #2180. |
| F6 (Minor): the `rpi4 route` and intra-K3s probe flows are optional, so their regression would not trigger a revert | Declined: rpi4 is on-demand (ADR-028). A required route probe would fail every VPS deploy while the homelab is off, which is the reason `test_optional_broken_flow_is_logged_not_fatal` pins. |
| F7 (Minor): the AC checkboxes in `proposal.md` are unticked | Awaits the contract pass. AC3 and AC4 are not met, so they stay unticked. |

## Decisions made during implementation

- **Reload = SIGHUP via Docker, not `systemctl`** (corrects ADR-041 wording for this deployment). Headscale runs in Docker Compose (distroless), and the official policy docs state file-policy changes "require ... a SIGHUP signal" → handler is `docker kill --signal=HUP headscale` (PID 1). Verified against the live v0.28.0 install + Headscale docs.
- **Two separate change paths** (finding #1): policy-file change → SIGHUP `reload headscale` handler (no downtime); `config.yaml`/compose change → `restart` (server config is read only at startup). Conflating them in the old single handler would mean a policy change either silently doesn't apply or needlessly drops sessions.
- **VPN-ACL-001 ships a permissive-first allow-all seed** (`policy.hujson.j2` = `{"acls":[{"accept",*→*:*}]}`) so the role is internally consistent and independently deployable. The enumerated baseline (preserved flows) + `agents`/`tagOwners` + `tag:hermes` dst matrix, all rendered from the `networking` SSOT (no hardcoded IPs), are authored in VPN-ACL-002. Dormant by default (`headscale_policy_path: ""` → allow-all, byte-identical to today's render).
- **Test tier**: pure render (jinja2) + static-YAML assertions in `tests/test_headscale_role.py` (root `tests/`, marker-less) → runs under `make test` with no VPN/SSH, unlike `tests/infra/` live tests.
- **Fix #5**: removed the redundant `wait for headscale` handler + its only notify; the always-run inline "Wait for Headscale to be healthy" task remains the single readiness gate.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/networking-dns/lesson-275-headscale-policy-check-is-syntax-only-until-v.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: ADR-041 already decides the model, and this spec implemented it.
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: the permissive-first rollout has only happened once, on one control plane, and lesson-275 records it.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/VPNACL-001-fleet-segmentation/` -> `specs/archive/VPNACL-001-fleet-segmentation/`
- [ ] Backlog entries `VPN-ACL-001/002/003` ticked in vault `11-tasks.md` with PR link
- [ ] Promotions above executed (if any)
