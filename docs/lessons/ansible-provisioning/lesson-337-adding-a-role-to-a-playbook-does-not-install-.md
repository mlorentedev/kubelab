---
id: lesson-337-adding-a-role-to-a-playbook-does-not-install-
type: lesson
status: active
created: "2026-08-15"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# Adding a role to a playbook does not install it on any path that never runs the playbook

**Context:** ANSIBLE-035 was created because a rebuild of aws1 "wiped the fleet's only maintenance timer with nothing noticing". The fix was to add the `node_maintenance` role to `provision-aws1.yml`, and the spec's verification then concluded that *"a future Spot replacement now reinstalls the timer (with notify wiring) automatically via provisioning, not by hand."*

**The trap:** that conclusion was never traced end to end, and it is false. The replacement path is:

```
make aws1-replace  →  terraform -replace  →  cloud-init  →  "then run: make deploy-argocd"
                                                 │                      │
                                      tailscale + k3s + ns        helm + kubectl only
                                                 └── provision-aws1.yml: never invoked
```

`node_maintenance` lives in `provision-aws1.yml`. Nothing in the chain calls it, so a replaced aws1 comes up with no timer and no notify units — the exact original incident, through a different door. Adding the role was **necessary and not sufficient**, and the gap is invisible in the direction it fails: no timer means no maintenance failures to report, so the missing alert path never announces its own absence either.

Found only because a claim written into a PR body was checked before merging, rather than after.

**Fix:** filed as #1102. The durable shape is Standing Order #1 — the replace target should *run* the provisioning step, not print it as a manual instruction which is also incomplete.

**Rule:**
- **"The role is in the playbook" answers a different question than "the node gets the role".** The second requires naming every path that brings that node up, and cattle nodes usually have a bring-up path — a `-replace` target, cloud-init, an autoscaler — that deliberately bypasses configuration management.
- **A fix that closes an incident deserves a trace of the incident's own path, not of the path you were editing.** ANSIBLE-035 traced the playbook; the incident came through Terraform.
- **Suspect any capability whose failure removes its own alarm.** A missing maintenance timer produces no maintenance failures, so the missing notifier is never exercised. These read as healthy and are indistinguishable from working, which is why they need an external check (#1021) rather than a self-report.

**Tags:** `#ansible` `#terraform` `#cattle` `#observability` `#ansible-035` `#ansible-041` `#gotcha`
