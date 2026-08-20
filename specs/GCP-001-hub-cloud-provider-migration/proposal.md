---
id: "GCP-001-hub-cloud-provider-migration"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-20"
issue: "mlorentedev/kubelab#1181"
tags: [spec, proposal, infra, cost, gitops]
template_version: "1.0"
---

# GCP-001-hub-cloud-provider-migration

## Why

<!-- from issue #1181 -->

ADR-023 §3.1 put the Argo CD hub on AWS for two reasons: three providers on the
CV, and *"cost is ~$3.60/mo"*. Measured against the AWS API on 2026-08-20 the hub
costs **~$12.75/mo** — 3.5x the recorded figure. The CV reason is
provider-agnostic and survives a swap; the cost reason has inverted.

The interesting part is the failure mode, not the delta. Three inputs moved and
none of them updated the ADR: AWS started billing public IPv4 on 2024-02-01 (now
29% of the hub bill, and the ADR's *"no Elastic IP"* clause was a correct cost
argument that silently became a wrong one), the instance was upsized
`t4g.micro` → `t4g.small`, and the disk grew 8 → 12 GB. **ADR-023 recorded cost
as a scalar rather than as a derivation**, so nothing prompted a re-check.

There is a second reason to do this now, and it is the one that makes the work
worth more than $153/yr. This repo claims cloud-agnosticism in three places —
`provision-aws1.yml:46`, `hub.yaml:4`, `aws1-ebs-resize.md:123` — and has never
executed the claim. A claim never executed is a hypothesis. This migration is its
first experiment, and the spec is designed to **score** it rather than to assume it.

## What

Move the Argo CD hub from AWS EC2 Spot (`t4g.small`, `eu-central-1`) to GCP
Compute Engine Spot (`e2-small`, `europe-west4`), behind a **regional managed
instance group of size 1**, and decommission the AWS side completely.

The node becomes `gcp1` under `networking.gcp`. The role stays where it is
already abstract: `clusters.hub`, `argocd.spokes`, Ansible group `hub`.

Observable outcome: `make deploy-argocd` reconciles both spokes from a GCP hub,
a simulated preemption self-heals without human action, and the AWS account holds
no billable resource.

### The measurement this spec exists to produce

Every touched file is classified into one of three columns. Column 3 is the result.

**Column 1 — reused unchanged (the abstraction held).** Predicted, to be confirmed:

- `infra/config/values/hub.yaml` — every K3s override, verbatim
- Ansible roles `base_system`, `ssh_hardening`, `tailscale`, `k3s_server`, `node_maintenance`
- `infra/ansible/playbooks/{wait-node-ready,maintain}.yml`
- Makefile `deploy-argocd`, `provision`, `wait-node-ready`, `maintain`, `maintain-notify-test`
- `infra/k8s/argocd/**` — Applications, `spoke-rbac.yaml`, `cluster-secret.yaml.tpl`
- `toolkit/features/argo_manager.py`
- The `wait-node-ready` → `provision` → `deploy-argocd` chain built by ANSIBLE-041

**Column 2 — net-new (genuinely provider-specific, expected, not a finding):**

- `infra/terraform/gcp/` — `main.tf`, `variables.tf`, `outputs.tf`, `cloud-init.yml`
- `toolkit infra terraform gcp-tfvars`
- `infra/ansible/playbooks/provision-gcp1.yml` — *predicted verbatim by
  `provision-aws1.yml:46`*, which is itself evidence for column 1's thesis
- Makefile `tf-gcp-*`, `gcp1-replace`, `gcp1-destroy`
- SOPS `gcp.*` keys; budget + kill-switch resources

**Column 3 — touched only because of provider naming (leaked coupling → findings):**

| # | Site | Nature |
|---|---|---|
| 1 | `toolkit/features/k8s_connect.py:114` | `for key in ("vps", "aws")` — a hardcoded provider list inside a *generic* node resolver |
| 2 | `toolkit/features/generator_ansible.py:157-163` | `networking.get("aws", {})`, `"aws1"` default |
| 3 | `toolkit/scripts/render_headscale_policy.py:38` | `hosts["aws1"] = net["aws"]["tailscale_ip"]` |
| 4 | `toolkit/scripts/headscale_probe.py:53,57,69,70` | flow definitions and `if node in ("vps", "aws1", "aws")` |
| 5 | `infra/ansible/playbooks/deploy-vps.yml:63` | `'aws1': config.networking.aws.tailscale_ip` |
| 6 | `Makefile:504` | `--render RESOLVE_AWS1_TAILSCALE_IP=aws1.kubelab.internal` |
| 7 | `infra/k8s/overlays/prod/argocd-endpointslice.yaml` | carries the `RESOLVE_AWS1_TAILSCALE_IP` placeholder |
| 8 | `infra/config/values/common.yaml` | `networking.aws`, `clusters.hub.*`, dashboard tile — **the only legitimate edit in this column** |
| 9 | `infra/ansible/inventories/homelab.yml` | generated; `kubelab-aws1` |
| 10 | `tests/` — `test_k8s_connect`, `test_k8s_render`, `test_headscale_role`, `test_node_location_axis`, `test_backup_sources`, `test_aws1_replace_chain`, `test_orphan_manifests` | assert provider names |

### The finding beneath the findings

Rows 1-4 share one root cause, and it is architectural rather than cosmetic.

`networking` has an **asymmetric shape**: homelab nodes live under
`networking.nodes.*` and are iterated generically, while cloud nodes are
*top-level sibling keys* (`networking.vps`, `networking.aws`). Every consumer
that wants "all nodes" must therefore hardcode the set of cloud provider
keys — which is literally what `k8s_connect.py:114` and
`test_node_location_axis.py:94` and `test_backup_sources.py:46` each do, three
times, independently.

Consequence: **adding a cloud provider is O(number of consumers), not O(1)** —
the opposite of what an SSOT is for. Had cloud nodes lived under
`networking.nodes.*` carrying a `provider:` attribute (they already carry
`location:` for ADR-028), column 3 would contain row 8 alone.

This spec does **not** fix that. Fixing it during a migration would make the
measurement unreadable — the whole point is to observe the coupling as it
actually is. Filed as
[SSOT-015 / #1182](https://github.com/mlorentedev/kubelab/issues/1182); this
spec's job is to *produce the evidence* that justifies it.

## Out of scope

- **Flattening `networking` to remove the cloud/homelab asymmetry.** The finding
  above, filed as SSOT-015 (#1182). Deliberately not fixed here so the
  measurement stays honest.
- **Renaming to a provider-neutral `hub1`.** Better end state, rejected for this
  change (ADR-063 D3): a rename inside a migration contaminates the diff with
  churn indistinguishable from genuine coupling.
- **`e2-medium` / 4 GB.** A capacity decision (RELIAB-009 / #368), not a provider
  decision. `e2-small` keeps 2 GB and `hub.yaml`'s low-RAM mitigations stay.
- **Retiring the AWS account.** Only its billable resources go.
- **Anything outside the hub.** VPS and homelab untouched.

## Risks / open questions

- **RESOLVED — the $10/mo credit exists.** Confirmed by the operator 2026-08-20.
  The cost case does not depend on it: raw prices are $9.57 vs $12.75. The credit
  makes it free rather than cheaper.
- **RESOLVED — Spot VMs have no maximum runtime.** The 24-hour cap belongs to
  *legacy preemptible* VMs; Spot VMs have no minimum or maximum runtime (Google
  Compute Engine docs). This was the single fact that could have made the
  migration non-viable, so it was checked before anything else.
- **RESOLVED — no disk regression.** `pd-balanced` carries a 3,000 IOPS per-instance
  floor independent of size, so 12 GB yields 3,072 IOPS against gp3's flat 3,000.
- **RESOLVED — zone choice is not a price lever on GCP.** Spot pricing is
  per-region and uniform across zones, unlike AWS where it is per-AZ (this hub
  pays 20% more in `eu-central-1a` than `1b`/`1c` for exactly that reason). Zone
  affects capacity only, which the regional MIG follows rather than guesses.
- **OPEN, does not block — GCP Spot preemption frequency is unmeasurable in
  advance.** AWS reclaimed `aws1` at least twice. No published rate exists for
  `e2-small` in `europe-west4`, and vendor generalities ("up to 91% off") say
  nothing about frequency. D2's MIG exists so the answer stops being
  load-bearing; the rate is recorded post-cutover as an observation, not
  predicted here.
- **OPEN, blocks AC4's evidence tier — Google publishes no per-VM disk
  performance ceiling below 4 vCPU.** The 3,072 IOPS figure is the *disk's*
  capability. The shared-core VM's own ceiling is undocumented and must be
  measured on the live node (`fio` or equivalent), not asserted from the disk spec.
- **OPEN — the MagicDNS given-name property transfers but is not automatic.**
  ANSIBLE-041 established that `aws1.kubelab.internal` resolving is *a fact about
  the current registration*, not a property of replacement: Headscale names nodes
  by given-name, and re-registration without stale-node cleanup yields
  `<name>-<random>`. The AWS cloud-init handles this via the Headscale API.
  **The GCP cloud-init must carry the same cleanup, and a MIG makes it fire more
  often**, since every self-heal is a re-registration. Task breakdown must assert
  the resolved name after a MIG recreate, not after first boot.
- **OPEN — cutover ordering is not free.** `Makefile:504` renders the prod
  EndpointSlice from `aws1.kubelab.internal`. Until it is re-rendered against
  `gcp1`, prod's Argo CD IngressRoute points at a host that is about to stop
  existing. Sequence must be: GCP hub reconciling → re-render EndpointSlice →
  only then `aws1-destroy`.

## Review findings (2026-08-20, SRE pass against official docs)

An adversarial review of the draft found **AC4 unreachable as originally
specified**. Recorded here before the design changes, so the reasoning survives.

**F1 — a MIG recreate produces a fresh boot disk, and nothing installs Argo CD on
it. (BLOCKER)** Compute Engine docs, verbatim: *"If Compute Engine stops a
preemptible instance in a managed instance group, the group repeatedly tries to
**recreate** that instance using the specified instance template."* Recreate, not
restart — new disk, cloud-init re-runs from scratch.

This exposes that **AWS parity was subtler than ADR-063 first stated**. A Spot
*stop/restart* on AWS preserves the EBS volume, so Argo CD survives an
interruption untouched; only a deliberate `aws1-replace` re-runs
`deploy-argocd`. A MIG turns *every* preemption into a replacement. Cloud-init
installs K3s and creates the `argocd` namespace, then stops — so the recovered
hub has K3s, no Argo CD, no spoke cluster secrets. "Returns to Synced without
human action" cannot happen.

Stateful MIG is not the escape: Google recommends against stateful boot disks
("cannot be updated to new images or repaired from corruption"), autoscaling is
disallowed, and **a stateful regional MIG requires disabling proactive
redistribution and "does not automatically orchestrate cross-zone failover"** —
which cancels the exact property regional MIG was chosen for (#1066).

**F2 — the preauth key model does not survive a MIG. (BLOCKER)** `aws1`'s
Headscale preauth key is stored in SOPS and baked into user_data via tfvars.
Every *other* node mints one just-in-time with `--expiration 1h`, delegated
through the VPS (`provision-ace1.yml:105-110`). On AWS the stored key is only
consumed at deliberate replacement, when tfvars is freshly rendered. **A MIG
fires cloud-init at arbitrary future times** — weeks after the template was
written — so a stored key that has expired means the recreated VM never joins the
mesh, and the hub dies silently. Same invisible-failure shape as #1102.

Confirmed available fix: Headscale exposes `POST /api/v1/preauthkey`
(`user`, `reusable`, `ephemeral`, `expiration`; default single-use, 1 h).
Cloud-init **already holds the Headscale API key** for stale-node cleanup, so it
can mint its own fresh key at boot and the stored preauth key disappears
entirely — one long-lived credential instead of two.

**F3 — the Tailscale IP rotates on re-registration, and this repo has already
observed it. (MAJOR)** `aws1` moved `100.64.0.4` → `100.64.0.7` on the
2026-05-06 Spot replacement. `common.yaml:90` says to prefer `tailscale_dns`,
and yet three consumers read the static IP: `render_headscale_policy.py:38`,
`headscale_probe.py:70`, `deploy-vps.yml:63`. The helper that would fix them,
`resolve_magicdns` (`k8s_render.py:72`), already exists and is used **only** by
the render path.

Under a MIG every self-heal is a re-registration, so a latent bug becomes a
frequent one: after the first IP-rotating preemption the Headscale ACL still
names the old address and hub→spoke `:6443` is blocked until a human edits
`common.yaml` and redeploys the VPS. **This makes the ACL render load-bearing for
AC4 and therefore in scope here**, not deferrable to #1182 — it is recorded in
column 3 as *"renamed + behavioural fix"*, with the reason.

**F4 — a default budget measures spend NET of credits. (MAJOR)**
`credit_types_treatment` defaults to `INCLUDE_ALL_CREDITS`, so a $10 budget fires
at $10 of *real money* — $20 of gross usage — which is not "the credit is
exhausted". Both thresholds must use `EXCLUDE_ALL_CREDITS` so $10 and $15 mean
gross usage and keep their meaning if the credit ever lapses.

**Confirmed sound, do not re-verify:** Spot VMs have no maximum runtime (the
24 h cap is legacy preemptible); `pd-balanced` carries a 3,000 IOPS per-instance
floor; GCP Spot pricing is per-region, uniform across zones; the scratch-project
kill-switch test design; ephemeral-only external IP (which also closes the
likeliest overrun path — a *reserved but unattached* IP costs $0.010/hr, **4x**
the attached Spot rate).

## Acceptance criteria

Mirrors #1181. Evidence tiers named deliberately: AC4 and AC8 require live
observation and cannot be satisfied by configuration review.

- [ ] **AC1 — the billing account holding the credit is recorded**, and the project
      is attached to it. Recorded so it can be re-checked, not re-discovered.
- [ ] **AC2 — spend alerted at $10, hard-capped at $15.** Budget with 50/90/100%
      alerts, plus Pub/Sub → function detaching billing at $15. Runbook states
      that budgets notify but do not cap, and that detaching takes the hub down.
- [ ] **AC2b — the cap is proven, not configured.** The kill-switch function is
      invoked once directly and shown to detach billing. A rule that never fired
      is not evidence.
- [ ] **AC3 — the hub reconciles from GCP.** Both Applications Synced/Healthy
      against staging (`ace1`) and prod (`vps`) over Tailscale, from `gcp1`.
- [ ] **AC4 — preemption self-heals, demonstrated live.** VM deleted or
      maintenance simulated; the regional MIG recreates it; the node re-registers
      under the *same* MagicDNS given-name; Argo CD returns to Synced with no
      human action. Assert the resolved name explicitly — the OPEN risk above is
      exactly that this is not automatic.
- [ ] **AC5 — the portability claim is scored.** `verification.md` carries the
      final three-column inventory with actual counts, and every column-3 entry
      is fixed or ticketed. **A short column 3 confirms the claim; a long one
      falsifies it — and the spec must report whichever occurred**, not reframe a
      long column as expected churn.
- [ ] **AC6 — AWS holds no billable resource.** Instance terminated, Spot request
      cancelled, EBS volume deleted, IAM access keys revoked — each verified by an
      API call whose output is pasted, not by the console.
- [ ] **AC7 — the stale-cost failure mode is closed at the source.** ADR-063
      supersedes ADR-023 §3.1 and states cost as a derivation (D4). No new doc in
      this change states an infrastructure cost as a bare scalar.
- [ ] **AC8 — the undocumented ceilings are measured, not assumed.** Disk IOPS on
      the live shared-core VM, and one `make deploy-argocd` completing under the
      best-effort burst model. Numbers recorded in `verification.md`; a
      regression against AWS is a finding, not a silent acceptance.

## References

- Bitácora: `mlorentedev/kubelab#1181` (GCP-001)
- Decision: `docs/adr/adr-063-hub-cloud-provider-migration.md`
- Runbook: `docs/runbooks/gcp-hub-bootstrap.md`
- Superseded: `docs/adr/adr-023-hub-spoke-multicloud-gitops.md` §3.1
- Prior art reused wholesale: `specs/ANSIBLE-041-aws1-replacement-provisioning/`
  (the readiness → provision → deploy chain; its deferred AC5 is satisfiable here)
- Coupled: #1066 (mooted), #1106 (resolved by ADR-063 D2), #1102, #368
- Produced by this spec's measurement: #1182 (SSOT-015)
