---
id: lesson-417-an-unapplied-iac-module-is-read-as-a-control
type: lesson
status: active
created: "2026-09-02"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, terraform, security, disaster-recovery, sec-005, sec-006]
---

# An IaC module that was never applied is read as a control, and the header saying otherwise does not stop it

**Context**: SEC-005 (#1538) found `http://<vps>:9000/api/overview` answering the
public internet — Traefik's dashboard and API, unauthenticated. Three controls
should each have stopped it. Two failed legibly. The third was
`hcloud_firewall.vps` in `infra/terraform/compute/`, which declares only
22/80/443/3478/41641 open and attaches itself to the server at line 105.

**Problem**: That module has never been applied. It has `.terraform/` from a
`terraform init` on 2026-03-15 and no `terraform.tfstate` in the six months
since. **Production has no cloud firewall at all** — and the repo reads as
though it does.

The module says so about itself, in its first four lines:

```terraform
# Hetzner VPS provisioning — recreate-only DR module
#
# This module is NOT imported against the current VPS.
# It defines "how to create a VPS from scratch" for disaster recovery.
```

It is not even an undocumented decision: **ADR-020** makes this module Layer 0
of the disaster-recovery bootstrap. The design is correct and deliberate.

**And it was still misread twice, by the same person, within a day.** Once
writing #1538's analysis ("`hcloud_firewall.vps` declares 9000 closed"), and
again writing #1557's AC1 ("decide whether this module is meant to manage this
VPS at all") — an acceptance criterion for a question the file had already
answered on line 3. Both times from lines 50 and 105 without line 3.

## Why the comment fails

A grep lands you in the middle of a file. `grep -rn hcloud_firewall` returns
line 50; the reader sees a firewall resource, sees it attached at line 105, and
has their answer before scrolling up. The header is above the region anyone
searching for the mechanism ever visits.

This is not carelessness that better attention fixes. It is the ordinary way
people read a repository, and any control that depends on them reading
differently will keep failing.

## Root cause

**A declaration and a deployment are indistinguishable in source.** Nothing in
the text of a Terraform resource says whether it has ever run — state is
machine-local, gitignored, and absent from every checkout. So the repository
cannot answer "is this live?" and will always appear to say yes.

That makes the unapplied module strictly worse than no module. No firewall in
the repo prompts "we should add one". A firewall in the repo ends the enquiry —
**and silently weakens every later decision that assumes a second layer is
there.** Port 9000 was reachable partly *because* this looked handled.

## Fix

**Verify by consequence, never by declaration.** The only check that can tell
the two apart asks the provider what is actually attached (`GET /firewalls`),
not what the config says. Static tests cannot substitute: a "does every module
have state" test cannot run in CI, because no machine but the one that applied
has state — and it would have marked this *correct* module as defective while
saying nothing about prod.

**Separate the two module kinds by name, not by comment.** SEC-006 (#1557) put
the live firewall in `infra/terraform/vps-firewall/` and left `compute/`
untouched. The directory name appears in every `ls`, every grep hit and every
error path — it is where the eye lands first, which the header was not.

**Never import a running server into a DR module to fix this.** It contradicts
the ADR, requires importing the SSH key too, and leaves `user_data` from
`templatefile()` permanently mismatched against the real cloud-init — so the
plan proposes replacing production, or `ignore_changes` covers so much that it
is management in name only. Attach instead: `hcloud_firewall_attachment` binds a
firewall to server IDs the module does not own, so the server never enters
state and a replacement is impossible by construction rather than by care.

## Generalisation

Applies to any IaC root whose state is local and gitignored — every Terraform
module in this repo. Ask of each: **if this had never been applied, what in the
repository would look different?** Where the answer is "nothing", the module is
a claim about the world that the world has not been consulted about.

The tell that you are in this failure mode: a control that reads as protection,
that nobody has ever seen refuse anything.

## Related

- [[lesson-413-a-credential-can-exist-authenticate-and-not-work]] — the same
  verify-by-consequence rule for credentials rather than infrastructure.
- `#1538` / `#1541` — SEC-005, the exposure. `#1548` — its live guard, and the
  origin of "a merged template is not a deployed one".
- `#1557` — SEC-006. `#959` — why ufw could never have covered the port either.
- ADR-020 — IaC Lifecycle Strategy, which makes `compute/` DR Layer 0.
