---
id: lesson-369-applying-terraform-from-a-feature-branch-destroyed-the-hub
type: lesson
status: active
created: "2026-08-22"
owner: manu
category: process-method
tags: [kubelab, process-method, terraform, gcp, git]
---

# Applying Terraform from a feature branch destroyed the running hub

**Context**: Bringing up the GCP Argo CD hub. Several defects surfaced during the
first applies, each fixed on its own branch to keep PRs atomic:

- `fix/gcp-mig-max-unavailable` — the MIG's `updatePolicy` and the removal of
  `instance_termination_action`
- `fix/cloud-init-kubeconfig` — `export KUBECONFIG`, without which helm never
  installed Argo CD

The hub had been applied successfully from the first branch and was running:
MIG healthy, instance `gcp1-hx0q`, node online in the mesh at `100.64.0.20`.

**Problem**: The second fix was written on a branch cut from `master`, which does
not contain the first. Running `make tf-gcp-apply` there compared the **local
state** — describing the working MIG — against a **configuration missing the
fix**, decided the group needed replacing, destroyed it, and then failed to
create the replacement on the same API refusal the first branch had already
fixed:

```
Error creating RegionInstanceGroupManager: Invalid value for field
'resource.updatePolicy.maxUnavailable.fixed': '1'.
```

Result: `gcloud compute instance-groups managed list` empty,
`gcloud compute instances list` empty. **The hub was gone**, taken down by an
apply intended to fix it.

Terraform state is **per-module and shared across branches** — the state file
lives in the working tree, not in the branch. So the state always describes the
last apply from *any* branch, while the configuration describes only the current
one. Applying from a branch that is behind is therefore a request to revert
infrastructure to that branch's view.

**Solution**: Recovery was an integration branch carrying every fix, then a
normal apply:

```bash
git checkout -B integration/gcp-hub-live fix/gcp-mig-max-unavailable
git merge --no-edit fix/cloud-init-kubeconfig
make tf-gcp-apply     # Apply complete! 2 added, 0 changed, 1 destroyed
```

No data was lost — the hub is stateless by design (ADR-063), which is the only
reason this was an inconvenience rather than an incident. On a data plane the
same mistake destroys a database.

**Rule**: **Never apply infrastructure from a topic branch while other fixes to
the same module are unmerged.** Atomic PRs are right for review and wrong for
apply: review wants the change isolated, apply wants the world complete.

Two workable disciplines, and the choice is a real one:

- **Apply only from `master`.** Merge first, then apply. Slower, and correct by
  construction.
- **Apply from an explicit integration branch** that merges every open fix, as
  the recovery above did. Faster while iterating, and it must be re-made every
  time a fix lands.

What must never happen is applying from whichever branch you happen to be
standing on — which is exactly how this occurred: the branch was the one where
the last edit was made, not the one describing the intended world.

A related tell: `terraform apply` reporting **"creating"** for a resource you
believe exists means state and reality have already diverged. That word was in
the output before the destroy completed, and it is the moment to stop.

**Tags**: `#terraform` `#gcp` `#git` `#adr-063` `#lesson-366`
