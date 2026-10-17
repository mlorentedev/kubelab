---
id: lesson-297-two-merge-implementations-over-the-same-files
type: lesson
status: active
created: "2026-08-08"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# Two merge implementations over the same files meant `common.enc.yaml` had two different meanings (ANSIBLE-033)

**Context:** The ace2 dev-node PAT lives in `common.enc.yaml`. Ansible provisioned it correctly; `toolkit secrets audit` reported it missing.

**Problem:** `ConfigurationManager._deep_update` guarded its recursive branch with `isinstance(value, dict) and value`. An empty mapping is **falsy**, so it fell to the assignment branch and *replaced* the base subtree instead of recursing into it. Moving the token to `common` had left a `dev_node: {}` behind in `staging.enc.yaml`, and that empty mapping erased the common subtree — but only on the toolkit side. The playbooks merge the same two files with `combine(recursive=True)`, which treats an empty mapping as a Mapping and recurses, preserving it. The same two files therefore meant different things depending on which tool read them.

The dangerous half was not the read. `credentials.py` `_promote_shared_secrets` runs the same merge into the decrypted `common.enc.yaml` and **re-encrypts the result to disk**, and `_partition_secrets` copies subtrees verbatim from a `SHARED_NESTED` path — `apps.services.automation`, exactly where the token lives. One `credentials generate` run would have silently and permanently destroyed the credential. A broken read is recoverable by re-running the tool; that write is not.

**Solution:** Recurse whenever the override is a mapping, into the base only when that is a mapping too — matching Ansible's `merge_hash` on all four edge cases (empty mapping, mapping-over-scalar, scalar-over-mapping, explicit null). The same guard also fixed a latent `TypeError` where a mapping override onto a scalar base recursed *into the scalar*. Blast radius was enumerated rather than assumed: a redacted path→hash image of the merged config for all three environments showed exactly two deltas, and the generated staging manifests were byte-identical before and after.

**Rule:** When two tools consume the same configuration files, their merge semantics are a **contract**, and an untested contract drifts. Pin it with tests that assert parity against the reference implementation, not just against your own intent. And when auditing a merge bug, find every call site before judging severity — a merge that only ever fed reads is an inconvenience; the one that feeds an encrypt-and-write is data loss.

**Tags:** `#sops` `#config-merge` `#ansible` `#toolkit` `#data-loss` `#ansible-033` `#gotcha`
