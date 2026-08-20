---
id: lesson-355-rare-and-supervised-hides-what-frequent-and-
type: lesson
status: active
created: "2026-08-20"
owner: manu
category: process-method
tags: [kubelab, process-method, reliability, sre, review, migration]
---

# A recovery path that runs rarely and supervised hides the defects it will have when it runs often and unattended

**Context**: Designing the Argo CD hub's move from an AWS Spot instance with a
persistent Spot request to a GCP Spot VM inside a regional managed instance
group. The MIG was chosen so preemption self-heals instead of leaving the hub
down (as #1066 did).

**Problem**: An adversarial review found three independent defects — and **not
one of them was created by the migration**. All three already existed in the AWS
setup and were invisible there:

1. **Nothing installs Argo CD on a rebuilt hub.** An AWS Spot *stop/restart*
   preserves the EBS volume, so Argo CD survived interruptions untouched; only a
   deliberate `aws1-replace` re-ran `deploy-argocd`. A MIG *recreates* rather than
   restarts, so every preemption becomes a from-scratch build — and the gap that
   the disk had been hiding becomes the normal case.
2. **A stored Headscale preauth key expires.** `aws1` bakes a SOPS-stored key into
   user_data, while every other node mints one just-in-time with `--expiration 1h`.
   On AWS the stored key is only consumed at deliberate replacement, with freshly
   rendered tfvars, so its expiry never bites. Under a MIG, cloud-init fires weeks
   later against a template written long ago.
3. **The Tailscale IP rotates on re-registration.** `common.yaml:90` says to
   prefer `tailscale_dns`, and three consumers read the static `tailscale_ip`
   anyway. `aws1` moved `100.64.0.4` → `100.64.0.7` on the 2026-05-06 replacement,
   which the fleet absorbed because replacements are rare. Under a MIG every
   self-heal re-registers.

The shared structure: each behaviour was **rare and supervised**, and each becomes
**frequent and unattended**. Rarity was doing the work that correctness should
have been doing, and none of the three would have been found by testing the AWS
path, because on the AWS path they do not fire.

**Solution**: Fixed at the design stage rather than discovered in production —
cloud-init completes the whole bring-up with secrets delivered at boot, mints its
own short-lived preauth key through the Headscale API (removing the stored one
entirely), and the ACL render is routed through the existing `resolve_magicdns`
helper. Recorded as F1–F3 in `specs/GCP-001-.../proposal.md`.

**Rule**: When a change makes an existing path run **more often** or **without a
human**, audit that path as if it were new code — even when the diff does not
touch it. Ask of every step: *what was true because this ran rarely?* and *what
did a human silently fix each time?* Frequency is a correctness input, not a
performance one.

The corollary is a reason to take such migrations on rather than defer them: this
one paid for itself in findings before a single resource was created. A path that
has only ever run under supervision has never actually been tested.

**Tags**: `#sre` `#reliability` `#migration` `#review` `#issue-1181`
