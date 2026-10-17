---
id: "lesson-566-terraform-does-not-keep-a-states-lineage-across-a-migration"
type: lesson
status: active
title: "Terraform does not keep a state's lineage across a migration"
created: "2026-10-13"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, terraform, r2, state, tf-007]
---

# Terraform does not keep a state's lineage across a migration

**Context**: TF-007 moved the `dns`, `r2` and `aws` states from msi's local files
to R2 (ADR-069). The runner's `migrate` pushed each file without `-force`, read
the remote back, and accepted it only if the lineage matched, the resource
addresses matched, and the serial was not lower. The premise was that `state push`
writes the file as it is.

**Problem**: It does not, the first time. Measured on msi on 2026-10-13 with
Terraform 1.16.4: against an S3 key that holds nothing, `state pull` answers an
empty state with no lineage at serial 0. `state push` into that empty state
imports the resources under a lineage minted for that write, at serial 1. The `dns` push
landed all 14 resources, and the gate refused it because the lineage was not the
local one. A retry would have been worse: Terraform refuses a push across
lineages without `-force`, so the gate had turned a migration that worked into one
that could not be finished. The before-write history copy also filed that empty
serial-0 state under the bucket lock, as `history/dns//0.tfstate` (an empty
lineage, hence the double slash): a locked object that holds nothing.

**Solution**: The gate compares what the state holds, not its identifiers. Each
resource, keyed by its address, and the outputs are rendered canonically and
compared. A mismatch is reported by address only, never by value, since a state
holds secrets. Before pushing, the runner checks whether R2 already holds that
content. If it does, the run is a migration whose rename never happened, and it
finishes with the rename and no second push. Serial 0 is never copied to history,
because nothing wrote it. Mutation-tested: an always-push, a gate that ignores
attributes or outputs, and a serial-0 copy each turn
`tests/test_terraform_runner.py` red.

The content check had a hole of its own, found on the next root. `aws` holds no
resources and no outputs, so its content equals the empty state an untouched key
answers. The runner took it as already in R2, pushed nothing, and renamed the
local file. Equality of content proves arrival only against a state that was
written, so the gate also requires a remote serial of at least 1. A pre-remote
copy whose root has no written state in R2 is now pushed from where it is, so a
rename with no write behind it is finished by the next run, not by hand.

**Rule**: Verify a move by the content that arrived, not by the identifiers the
source carried. The destination can re-key what it receives, and a gate keyed on
the source's identity refuses a correct result, then blocks its own retry.
Identifiers are the tool's business; equality of content is what the move promised.
