---
tags: [spec, tasks, infra]
created: "2026-08-20"
---

# Tasks - GCP-001-hub-cloud-provider-migration

> TDD order. One task = one focused commit. `[P]` = no dependency on another
> unchecked task. `[AC<n>]` = satisfies acceptance criterion `<n>` in `proposal.md`.
>
> **Two PRs.** PR 1 is substrate that stands on its own merits and does not
> mention GCP; PR 2 is the migration. Split per AGENTS.md's ~300-line cap and
> because F3's probe defect is live today and should not wait on a migration.

## Design decisions this breakdown resolves

**1. Additive-then-subtractive, never a swap.** `gcp1` is built and proven while
`aws1` still runs. `Makefile:504` renders prod's Argo CD EndpointSlice from
`aws1.kubelab.internal`, so a simultaneous swap points prod's IngressRoute at a
host that is about to stop existing. Two hubs coexist briefly; one is referenced.

**2. Terraform state is per-module and local.** `infra/terraform/gcp/` gets its
own `backend "local"`, as `infra/terraform/aws/` has. No `state mv` — the AWS
module is destroyed intact at the end. One module holding both providers would
couple the destroy to the create.

**3. Cloud-init is now load-bearing code, not a convenience.** Per F1/F2, a MIG
recreate is a from-scratch build that runs unattended, possibly months after the
template was written. Every failure inside it is a silent hub outage. It is
therefore tested (static assertions in PR 2, live in Phase 4) before the MIG is
trusted, not after.

**4. F3's ACL scope was retracted after checking the policy template.** An earlier
draft put "route the Headscale ACL render through `resolve_magicdns`" in PR 1,
justified as load-bearing for AC4. **The template falsified it**: no ACL rule
references the `aws1` alias, and hub→spoke rides rule 1, which is user-based and
IP-independent. PR 1 therefore shrinks to the one consumer that genuinely breaks
— the reachability probe — plus a dated warning on VPN-ACL-004 (#586), which is
the change that would *make* the alias load-bearing. `deploy-vps.yml:63` and
`render_headscale_policy.py:38` keep writing the SSOT literal, which is correct.

---

# PR 1 — substrate (no GCP; stands alone)

Merges and is valuable even if the migration is never done.

- [ ] Branch: `fix/GCP-001-probe-hub-address`
- [ ] [P] Failing test: `_ssh_target` addresses a cloud node by its
      `tailscale_dns` name, not its `tailscale_ip` literal. Evidence for the bug
      is in-repo — `aws1` moved `100.64.0.4` → `100.64.0.7` on the 2026-05-06
      replacement while `common.yaml:90` already said to prefer the DNS name.
- [ ] Fix `toolkit/scripts/headscale_probe.py`'s `_ssh_target` to prefer
      `tailscale_dns`, mirroring `generator_ansible.py:162` exactly. SSH resolves
      the name itself, so this needs no `dig` and adds no new dependency.
- [ ] Update `test_required_source_down_fails`, which asserts against the literal
      IP and must now assert against the name — the test changing is the
      behaviour change being visible.
- [ ] [P] Regression guard: a test asserting `_ssh_target` never returns a bare
      IPv4 for a node that declares a `tailscale_dns`, so the literal cannot
      quietly come back.
- [ ] Comment on **#586 (VPN-ACL-004)**: when rule 1 is tightened from user-based
      to host-based, the hub alias must be tag-or-resolved and never the
      `common.yaml` literal, because the IP rotates on every preemption after
      GCP-001. Dated, with the reason.
- [ ] `make check-headscale-policy` green — it must be *unaffected*, which is the
      point: the ACL render is deliberately not touched.
- [ ] `make test` green; `make secrets-audit` clean.

> **Secret-delivery groundwork deliberately excluded from PR 1.** An earlier
> draft put a store-agnostic `secrets sync` here. It was cut: there is exactly
> one store ever planned, so "parameterised by store" is speculative generality,
> and a push path with zero consumers is dead code until PR 2 lands — which
> contradicts PR 1's own justification of standing alone. It ships in PR 2,
> Secret-Manager-specific, next to its only consumer. Parameterise when a second
> store exists.

# PR 2 — the migration

## Phase 0 — account, billing, guardrails (human-driven, before any resource)

> **Which Terraform root.** Phase 0 requires guardrails as code *before* the
> compute module exists, which reads circular. It is not: **billing budgets
> attach to the billing account, not to project compute**, so they live in their
> own tiny root at `infra/terraform/gcp-billing/` with its own local state, and
> apply independently of `infra/terraform/gcp/`. Build that root first; it has no
> dependency on Phase 1.

- [ ] [AC1] Runbook §1–§3: project created and linked to the billing account that
      **holds the credit**. Record the account ID in `verification.md`.
      `gcloud billing projects describe` output pasted — the create command's exit
      code proves nothing about which account it landed on.
- [ ] [AC2] Runbook §4.1: $10 budget, alerts at 50/90/100%,
      **`credit_types_treatment = EXCLUDE_ALL_CREDITS`** (F4 — the default
      subtracts credits and would fire at $20 of usage).
- [ ] [AC2] Runbook §4.2: $15 budget → Pub/Sub → Cloud Function detaching billing.
      Terraform, not console. Target project as an env var, not a constant.
- [ ] [AC2b] Runbook §4.3: prove the switch on a **scratch project** with a
      synthetic Pub/Sub message. Never against the hub project — it would work.

## Phase 1 — Terraform module (no apply)

- [ ] [P] [AC5] Failing test `tests/test_gcp_hub_module.py`, static parse of
      `infra/terraform/gcp/*.tf`, asserting:
      (a) `provisioning_model = "SPOT"`;
      (b) `instance_termination_action = "DELETE"` — **not** the `STOP` default,
      so no `TERMINATED` shell is left behind;
      (c) the MIG is **regional**, `target_size = 1`;
      (d) **no `google_compute_address` resource exists** — ephemeral IP only, per
      the $0.010/hr unattached trap;
      (e) boot disk `pd-balanced`, size from `common.yaml`;
      (f) no credential literal in any `.tf`.
      Runs in `make test-fast`, needs no GCP.
- [ ] [AC5] Write `infra/terraform/gcp/{main,variables,outputs}.tf`: firewall
      (SSH bootstrap + Tailscale UDP 41641 + egress all), service account with
      `secretmanager.secretAccessor` on **named secrets only**, instance template,
      regional MIG size 1. **No autohealing in v1** (ADR-063 D2): with DELETE
      termination the MIG already restores target size, and a probe firing before
      cloud-init finishes would produce a recreate loop on a Spot hub.
- [ ] [AC5] `budget.tf` + kill-switch resources from Phase 0, as code.
- [ ] [AC4] Write `cloud-init.yml`. It must complete the **whole** bring-up, per
      F1 — a MIG recreate is a from-scratch build:
      1. fetch the Headscale API key from Secret Manager;
      2. delete the stale Headscale node (given-name cleanup);
      3. **mint a fresh single-use preauth key** via `POST /api/v1/preauthkey`
         (F2 — no stored key that can expire between template-write and preemption);
      4. `tailscale up`;
      5. K3s with the same flags as the AWS module, plus 2 GB swap and `UseDNS no`;
      6. install Argo CD and the spoke cluster secrets from Secret Manager.
      Log every stage to `/var/log/kubelab-bootstrap.log` — §7 of the runbook
      depends on it being readable after an unattended failure.
- [ ] [AC5] `toolkit infra terraform gcp-tfvars`, mirroring `aws-tfvars`; the
      Makefile deletes the rendered file after every use.
- [ ] [P] Register `gcp.headscale_api_key` in `SECRET_CATALOG` with
      `envs=("prod",)` — **not `("common",)`**, which matches no real env and
      makes the secret vanish from every audit silently (ANSIBLE-033).
- [ ] `make secrets-audit` clean.

## Phase 2 — SSOT and the naming blast radius

- [ ] [AC5] Add `networking.gcp` to `common.yaml`; point `clusters.hub.*` at it.
- [ ] [AC5] Walk column 3 of `proposal.md` **one row per commit**, so the diff
      shows exactly what a provider change costs. Do **not** refactor into a
      generic lookup — that is #1182 and it would destroy the measurement.
- [ ] [AC5] Regenerate the Ansible inventory; confirm `gcp1` is in group `hub`
      with `ansible_user: deployer`. SSOT-014a infers the SSH-user category from
      **YAML position**, so verify it did not silently fall through to the
      homelab user.
- [ ] `infra/ansible/playbooks/provision-gcp1.yml` — from `provision-aws1.yml`,
      hardware assertions retargeted. **Do not copy its header's stale claims**
      (it documents a `terminate`+ASG contract never applied, and 8 GB where the
      volume is 12). Write what is true of GCP.
- [ ] Makefile: `tf-gcp-{plan,apply,destroy}`, `gcp1-{status,start,stop,replace,destroy}`.
      Reuse the ANSIBLE-041 chain verbatim.

## Phase 3 — bring-up (both hubs alive)

- [ ] [AC3] `make tf-gcp-apply`; capture output.
- [ ] [AC3] `make wait-node-ready NODE=gcp1 ENV=hub`.
- [ ] [AC3] `dig +short gcp1.kubelab.internal` on **first** registration.
- [ ] [AC3] `make provision NODE=gcp1 ENV=hub` twice — second pass `changed=0`.
- [ ] [AC3] `make maintain-notify-test NODE=gcp1 ENV=hub` → `Result=success`.
      This is the check ANSIBLE-035/041 exist to protect and that a rebuild has
      historically dropped.
- [ ] [AC3] Both Argo CD Applications Synced/Healthy against `ace1` and `vps`.
- [ ] [AC8] Measure the undocumented ceilings on the live node: disk IOPS (`fio`)
      and wall time of one `make deploy-argocd` under the best-effort burst model.
      **A regression against the AWS baseline is a finding to report.**

## Phase 4 — preemption evidence (the design's load-bearing claim)

- [ ] [AC4] Delete the MIG's instance. Observe end to end: MIG recreates →
      cloud-init → stale node cleaned → fresh preauth minted → mesh joined →
      K3s → **Argo CD installed** → Synced.
- [ ] [AC4] `dig +short gcp1.kubelab.internal` post-recreate. The load-bearing
      assertion: a re-registration without cleanup lands as `gcp1-<random>` and
      breaks the inventory, the kubeconfig and the prod EndpointSlice at once,
      silently.
- [ ] [AC4] Confirm **zero** human steps between delete and Synced. If any were
      needed, the MIG has not replaced the AWS persistent Spot request and AC4 fails.
- [ ] [AC4] Repeat once. IP rotation may only appear on a second re-registration;
      a single pass does not exercise it. Record whether the address actually
      changed — that observation is what tells #586 how urgent its own fix is.

## Phase 5 — cutover and decommission (strictly ordered)

- [ ] [AC3] Re-render the prod EndpointSlice against `gcp1` **before** any AWS
      teardown — until this runs, prod's Argo CD route points at `aws1`.
- [ ] [AC3] Verify `https://argo.kubelab.live` serves from the GCP hub.
- [ ] [AC6] `make aws1-destroy`.
- [ ] [AC6] Verify by API, output pasted: `describe-instances` empty,
      `describe-spot-instance-requests` cancelled, `describe-volumes` empty.
- [ ] [AC6] **Credential rotation — the full exposure set.** Four secrets were
      printed in plaintext during the 2026-08-20 study session (a `sops -d | grep`
      wider than it needed to be). All four must be rotated; two of them are
      *not* retired by this migration and therefore should not wait for cutover:

      | Secret | Retired by migration? | When |
      |---|---|---|
      | `aws.access_key_id` / `secret_access_key` | yes | at cutover (AC6) |
      | `aws.headscale_preauth_key` | yes — D7 deletes it | **now** — live in SOPS until PR 2 lands, which has no start date |
      | `aws.headscale_api_key` | **no** — survives as `gcp.headscale_api_key` | **now** |
      | `argocd.admin_password` (+ `admin_password_hash`) | **no** — hub credential, unrelated to provider | **now** |

      The two AWS-scoped keys retire with the account. The other two are live
      credentials for an unbounded window if their rotation is deferred to a PR
      with no scheduled start. `make credentials-generate` regenerates the Argo CD
      hub secrets — note it also rotates OIDC client secrets and the HMAC, so
      re-run `make deploy-argocd` after.
- [ ] Remove `infra/terraform/aws/`, `provision-aws1.yml`, `aws1-*` targets and
      `networking.aws`. Separate commit from the destroy, so the teardown is
      revertable independently of the code removal.

## Closing

- [ ] [AC5] `verification.md` carries the **final** three-column inventory with
      real counts. Report whichever result occurred.
- [ ] [AC7] ADR-063 `proposed` → `accepted`; ADR-023 §3.1 annotated superseded.
- [ ] Close #1066 (mooted). Comment on #1106 (resolved by ADR-063 D2) and #1102
      (deferred AC5 now satisfied).
- [ ] `CLAUDE.md` topology + gotchas updated: aws1 → gcp1, `t4g.small` →
      `e2-small`, and the GCP-specific gotchas (per-region Spot pricing;
      unattached IP at 4x; budgets notify but do not cap).
- [ ] Retire `docs/runbooks/aws1-{destroy-replace,ebs-resize}.md`.
- [ ] `make test` green; lint and type checks pass.
- [ ] Lessons 354 and 355 already written (2026-08-20). Add a third only if
      implementation produces something neither covers.
