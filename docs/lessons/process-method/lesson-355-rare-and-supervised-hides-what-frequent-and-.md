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
   self-heal re-registers, so the reachability probe starts reporting a
   `required` flow as down when it is not.

The shared structure: each behaviour was **rare and supervised**, and each becomes
**frequent and unattended**. Rarity was doing the work that correctness should
have been doing, and none of the three would have been found by testing the AWS
path, because on the AWS path they do not fire.

**Solution**: Fixed at the design stage rather than discovered in production —
cloud-init completes the whole bring-up with secrets delivered at boot, mints its
own short-lived preauth key through the Headscale API (removing the stored one
entirely), and the probe addresses cloud nodes by MagicDNS name instead of by a
cached literal. Recorded as F1–F3 in `specs/GCP-001-.../proposal.md`.

**A correction that belongs in the lesson, because it is the same discipline.**
The third finding was first written as *"the ACL blocks hub→spoke `:6443`"*. That
was wrong, and the repo's own ACL template disproved it in about thirty seconds:
**no rule references the hub's host alias**, and hub→spoke rides a user-based
rule that no IP can invalidate. The real damage was one rank smaller — a
monitoring false positive — and the ACL exposure is a *future* one, owned by the
ticket that will tighten those rules.

Twice in the same session a confident, specific claim about a failure mode
survived until someone opened the artifact that would have to fail: first the
`$3.60/mo` in ADR-023, then this. Hence the second rule below.

**Rule**: When a change makes an existing path run **more often** or **without a
human**, audit that path as if it were new code — even when the diff does not
touch it. Ask of every step: *what was true because this ran rarely?* and *what
did a human silently fix each time?* Frequency is a correctness input, not a
performance one.

**Second rule, earned the hard way**: before building a fix, open the artifact
that would have to fail and confirm it actually does. A named failure mode is a
hypothesis until the file that would break is read. Getting this wrong costs more
than a wasted fix — it misroutes the work, and it puts a false claim into an ADR,
a spec and a ticket, where it then has to be walked back in public.

The corollary is a reason to take such migrations on rather than defer them: this
one paid for itself in findings before a single resource was created. A path that
has only ever run under supervision has never actually been tested.

**Tags**: `#sre` `#reliability` `#migration` `#review` `#issue-1181`
