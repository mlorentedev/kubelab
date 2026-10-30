---
id: "VPN-ACL-014-tenant-segments"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-10-30"
issue: "mlorentedev/kubelab#2830"
tags: [spec, proposal]
template_version: "1.0"
wip_override: "Operator approved on 2026-10-29: the tenant segment is the critical path for enrolling the office lab, chosen ahead of the Headscale upgrade (13 active, limit 10, 2026-10-30)"
---

# VPN-ACL-014: isolate tenant segments on the shared Headscale

## Why

<!-- from issue #2830: VPN-ACL-014: isolate tenant segments on the shared Headscale -->

Another organisation's lab is to enrol in this Headscale as its own segment, sharing
the control plane but not the private inventory. Rule 1 granted the existing users a
wildcard destination. A tenant node under any identity was then either inside rule 1
or reachable by it, and Headscale makes both peers visible when a grant exists in
either direction. So the tenant would see every private peer. Measured on
2026-10-30 through the read-only audit identity (SEC-037). The live policy equals
the rendered template.

## What

- Rule 1 names its destinations: the existing users, `agents@`, `tag:hermes` and
  `lan-rpi4`, on every port. For every current node and route, that equals the old
  wildcard: each node is owned by one of those users or carries `tag:hermes`, and the
  only advertised subnet is `lan-rpi4`. Headscale v0.29's narrower wildcard needs the
  same change (VPN-ACL-006 G4).
- A tenant segment is data: `{owner, hosts_tag, clients_tag, ports}`, read from
  SOPS (`apps.services.core.headscale.segments`) at deploy time. It grants exactly
  `clients_tag -> hosts_tag:<port>`. Its hosts originate nothing, and nothing reaches
  its clients. The role refuses a malformed segment before rendering.
- Rollback keeps the isolation. The first-activation fallback is the segment-free
  policy instead of an allow-all. While segments are declared, a `.prev` with a
  wildcard grant is not restored.
- `toolkit infra headscale policy-check` also validates a synthetic segment on the
  pinned image.

## Out of scope

- Deploying to production. The segment owner user must exist first, because a policy
  naming an unknown user can be rejected on reload while the deploy reports green
  (VPN-ACL-013, #2190). The morning checklist covers this.
- Tightening rule 1 toward least privilege (VPN-ACL-004), or `tag:hermes`
  (VPN-ACL-012).
- Per-segment DNS. Headscale v0.28 delivers DNS configuration to every node.
  Retiring the extra record is OPS-019 (#964).

## Risks / open questions

- [RESOLVED] Equivalence beyond the measured nodes. Before rendering, the role reads
  the nodes Headscale holds and stops if rule 1 or a segment does not account for
  one, so a node under an unlisted user is a failed deploy, not a lost flow.
- [OPEN, deploy-time] On v0.28, `policy check` is syntax-only. Whether the reload
  accepts the segment owner is proven by the effective policy read through the audit
  identity after the deploy, not by CI.
- [OPEN, operator] The split-zone resolver address still reaches every node. It is
  unreachable under the policy, but visible.
- [ACCEPTED] The segment-free fallback is rendered from the same hosts map as the
  failed policy. If that map caused the failure, the fallback can fail too. The map is
  built from `common.yaml` by the same code that renders today's policy, and the
  `.prev` restore path does not depend on it.

## Acceptance criteria

- [ ] AC1: With no segments, rule 1 reaches every identity the policy knows (users,
  `agents@`, `tag:hermes`) and `lan-rpi4` on every port, and no rule grants a wildcard.
- [ ] AC2: With a segment, no private rule names a segment tag, the segment hosts are
  in no `src`, nothing reaches the segment clients, and the clients reach only the
  declared ports.
- [ ] AC3: The role refuses a segment owned by a private identity, reusing a private
  tag, with a malformed tag or port list, or sharing a tag with another segment, and
  it prints no tenant data.
- [ ] AC4: Neither rollback path can restore a wildcard grant, or a policy this
  template did not render, while segments are declared, and a failed probe still
  leaves every private flow working.
- [ ] AC5: Segments reach the role only from SOPS, and the CI policy check validates
  both the segment-free and a synthetic segment render on the pinned image.
- [ ] AC6: The deploy stops before rendering if a node Headscale holds would not be
  reached by rule 1 or accounted for by a segment.

## References

- Issue: mlorentedev/kubelab#2830
- ADR-041 (agent fleet VPN segmentation); VPN-ACL-006 (#248) for the upgrade
- VPN-ACL-012, VPN-ACL-013 (#2190), OPS-019 (#964)
