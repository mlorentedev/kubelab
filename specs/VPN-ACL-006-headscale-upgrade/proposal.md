---
id: "VPN-ACL-006-headscale-upgrade"
type: spec
status: draft
created: "2026-10-26"
issue: "mlorentedev/kubelab#248"
risk: high
tags: [spec, proposal]
template_version: "1.0"
wip_override: "Operator approved a planning-only exception on 2026-10-26 (12 active, limit 10). Renewed by the operator on 2026-10-29 for this spec only (12 active on master, limit 10): publish it and implement the read-only AC1 preflight. Rollout and production stay unauthorized."
---

# VPN-ACL-006: Headscale upgrade preparation

The operator froze this contract on 2026-10-29 and authorized only the
read-only AC1 preflight. No image change, live backup, restart, enrollment or
deployment is authorized by this document; a production window needs separate
approval.

## Why

<!-- from issue #248: upgrade Headscale v0.28 to v0.29 before deny-by-default tightening -->

The existing single Headscale control plane runs v0.28.0, whose policy check
does not evaluate reachability assertions. ADR-041 requires an upgrade before
least-privilege tightening. Prepare a controlled upgrade to the currently
published stable v0.29.6 with preserved connectivity, tested restoration and
honest policy acceptance checks, rather than changing the image and hoping
the mesh recovers.

## What

The future implementation must provide a repeatable preflight, disposable
upgrade/restoration drill and approved Ansible rollout. Keep Headscale in its
existing Docker Compose deployment outside K3s. Pin the selected image through
`infra/config/values/common.yaml`; verify the Linux ARM64 registry digest before
freezing the pin. A release-asset checksum is not a container-image digest.

Preserve current intended permissions, identities, DNS behavior and approved
routes during the version change. Adapt only configuration and policy semantics
required by the upgrade. In particular, v0.29 changes `*` to overlay ranges:
preserving approved subnet access may require explicit destinations from the
networking SSOT. Do not replace `*` with a broader internet-wide permit.

Native policy tests supplement, rather than replace, external traffic probes,
effective-policy acceptance and client reconnect evidence. They do not prove
peer-map or DNS privacy.

## Out of scope

- Least-privilege redesign, new segment enrollment or migration, retagging
  existing nodes, OIDC onboarding, new endpoints or a second persistent instance.
- Unrelated DNS, firewall, K3s or service hardening; feature adoption such as
  converting ACLs to grants merely because v0.29 supports them.
- Running production operations under this planning approval. Synthetic
  disposable test servers are not a second production control plane.

## Risks / open questions

Tasks are provisional, not frozen. Resolve these gates before implementation
or the later rollout as specified:

| Gate | Risk / required resolution | When |
|---|---|---|
| G1 | Recheck the WIP limit and review this draft. The exception permits planning only. Confirm atomic PR boundaries and dependencies. | Before code |
| G2 | Inventory client compatibility, including embedded Tailscale in bridge binaries. Upstream requires Tailscale >=1.80.0; a bridge release number alone is not evidence. Unknown or incompatible required clients block promotion. | Before rollout |
| G3 | Review the complete v0.29.0-v0.29.6 change set, configuration defaults and ARM64 image manifest. Examine hostname normalization, CLI consumers, node expiry and trusted-proxy behavior. Do not assume unchanged names or headers. | Before code freeze |
| G4 | Define approved subnet and private-flow expectations from the existing SSOT. Required paths cannot disappear behind optional/skip results. | Before code freeze |
| G5 | Minor-version downgrade is blocked. Prove restoration of the old database, keys, configuration and image together; never start v0.28 against the migrated live database. | Before rollout |
| G6 | Reuse #433 for lifecycle/backup work, #2184 for policy restoration evidence and #2190 for rejected-reload detection. Do not duplicate their implementations or treat unresolved acceptance as passed. | Before rollout |
| G7 | The current Windows baseline has two failures in the hosts-owner tests. Track and resolve or explicitly disposition them before claiming a green implementation baseline. No fix is included in planning. | Before code |
| G8 | An approved independent recovery path and maintenance window are not established by an open SSH session. Set measurable outage/recovery bounds and stop triggers with the operator. | Before rollout |

Contract amendments from the 2026-10-29 gate review (evidence in
`verification.md`), accepted by the operator the same day:

- G4: the required private-flow matrix is rule 1's users (`kubelab@`,
  `manu@`, `work@`) to the tailnet plus `lan-rpi4:*` (`networking.lan_cidr`).
  The minimal compatibility edit adds `lan-rpi4:*` to rule 1's destinations;
  `tag:hermes` gains nothing.
- AC1/AC6: preflight reports nodes whose key is expired yet online (v0.29.4
  disconnects them) and given names carrying the old random suffix (v0.29.0
  renames collisions numerically), and refuses to proceed while a required
  node is in either set.
- AC2: rename `ephemeral_node_inactivity_timeout` to
  `node.ephemeral.inactivity_timeout`, set `trusted_proxies` to the K3s
  Traefik hop explicitly (value proven in the disposable drill first), and pin
  the image by OCI index digest in `common.yaml`.

The existing policy fallback can restore broad permissions. This upgrade must
not be represented as making future restricted-segment rollback safe; that
remains a separate blocked contract.

## Acceptance criteria

- [ ] AC1: Preflight refuses unknown/incompatible required client versions,
  unverified ARM64 image pins, unsupported upgrade paths, missing production
  approval, or required nodes the upgrade would disconnect (expired key yet
  online) or rename (pre-v0.29 random given-name suffix), before any
  production mutation.
- [ ] AC2: Rendered v0.29.6 configuration and Compose validate against the
  selected image; removed keys are absent, relevant defaults are explicit and
  CLI/hostname consumers have regression coverage.
- [ ] AC3: The approved private-flow and subnet-route matrix passes on the
  candidate version without widening intended permissions. Required offline,
  skipped or unverified flows block acceptance.
- [ ] AC4: A disposable synthetic v0.28-to-v0.29.6 migration and full restore
  back to v0.28 preserve server identity, nodes and users. Missing/corrupt
  backups fail closed. Production cutover additionally requires a fresh,
  consistent protected backup and independent recovery approval.
- [ ] AC5: Positive and deliberately failing native policy tests execute with
  populated disposable database state. Rejected writes/reloads cannot report
  success, and acceptance checks distinguish effective policy from files on
  disk. The default syntax-only/empty-database path is not sufficient evidence.
- [ ] AC6: Rollout checks version, control-plane responsiveness and client
  reconnects without duplicate enrollment; a second convergence run reports
  `changed=0` without another migration, identity churn or unintended restart.
- [ ] AC7: Runbook and tooling default to non-mutating preparation, require
  explicit production authorization and redact sensitive state. Disposable
  resources are cleaned on success and failure without touching live data.

## References

- [Work gate #248](https://github.com/mlorentedev/kubelab/issues/248)
- [ADR-041](../../docs/adr/adr-041-agent-fleet-vpn-segmentation.md)
- [ADR-015](../../docs/adr/adr-015-vps-k3s-migration-strategy.md)
- [Lifecycle #433](https://github.com/mlorentedev/kubelab/issues/433)
- [Policy restore #2184](https://github.com/mlorentedev/kubelab/issues/2184)
- [Rejected reload #2190](https://github.com/mlorentedev/kubelab/issues/2190)
- [v0.29.0 breaking changes](https://github.com/juanfont/headscale/releases/tag/v0.29.0)
- [v0.29.6 release](https://github.com/juanfont/headscale/releases/tag/v0.29.6)
- [Upgrade procedure](https://headscale.net/stable/setup/upgrade/)
