---
id: lesson-403-known-hosts-has-two-ways-to-make-a-purge-a-silent-no-op
type: lesson
status: active
created: "2026-08-26"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, ssh, known-hosts, gcp, cattle]
---

# `known_hosts` has two independent ways to make a host-key purge a silent no-op

**Context**: Building the fix for [#1380](https://github.com/mlorentedev/kubelab/issues/1380) — `make fetch-kubeconfig ENV=hub` dies whenever the hub's SSH host key rotates, which under a Spot VM in a MIG is a routine unattended event (18 seconds, measured in #1369). The fix purges the stale entry for nodes the SSOT marks ephemeral.

**Problem**: The obvious implementation — remove the entry for the SSH alias, or find and strip the line from the file — fails in two different ways, and both fail *quietly*, returning success while removing nothing.

1. **`known_hosts` is keyed by the hostname ssh resolves, not by the alias you type.** Measured: `ssh -G gcp1 | grep '^hostname '` → `gcp1.kubelab.internal`. Purging `gcp1` finds no entry and exits 0.

2. **`HashKnownHosts` is on by default**, so hostnames are stored as salted hashes:

   ```
   $ grep -c gcp1 ~/.ssh/known_hosts
   0          # while the entry is definitely there
   ```

   Any implementation that searches the file as text is a no-op on a real workstation, and would have passed a unit test written against an unhashed fixture.

The two compound: the first makes you purge the wrong name, the second stops you from noticing.

**Solution**: Ask ssh what host it will contact (`ssh -G <alias>`, which follows any `ssh_config` indirection) and hand that name to `ssh-keygen -R`, which hashes the candidate and compares rather than searching. Both are in `toolkit/features/k8s_kubeconfig.py`; verified live — the command that had been failing now succeeds and is idempotent across runs.

A third failure was found by review on the same PR and is the same species: `forget_host_key` returned whether the purge succeeded and the caller discarded it, so a purge blocked by a read-only file left the error hint asserting *"this node is NOT marked as recreated-in-place in the SSOT"* — false for that node, printed during a post-preemption recovery. Fixed in #1460.

**Rule**: `ssh-keygen -R` is not a convenience wrapper around editing the file; on a default configuration it is the **only** thing that can find the entry. And before removing an identity record keyed by a name, establish which name the tool that wrote it used — an alias, a resolved hostname and a mesh IP are three different keys, and only one of them is in the file.

More generally: when a removal reports success, that is not evidence something was removed. Absence-of-error and absence-of-entry look identical from the outside, which is why the honest check is the consequence — try the operation the stale entry was blocking — rather than the exit code.

**Tags**: `#ssh` `#known-hosts` `#cattle` `#pr-1455` `#pr-1460` `#issue-1380`
