---
id: lesson-607-two-receivers-on-one-dispatch-event-race-one-branch-so-the-flip-and-the-demotion-ship-together
type: lesson
status: active
created: "2026-10-20"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, repository-dispatch, idp-042]
---

# Two receivers on one dispatch event race one branch, so the flip and the demotion ship together

**Context**: IDP-042 moved web from its own receiver (`web-image-receiver.yml`,
`types: [web-image-published]`) to the generic `product-image-receiver.yml`, which
lists no `types` and lets the product registry decide which events it acts on.

**Problem**: `repository_dispatch` delivers an event to every workflow on the
default branch that matches it, and a workflow with no `types` matches all of them.
Both receivers force-push `deploy/staging-web`, and their `concurrency` groups are
different (`web-image-receiver` against `product-receiver-web`), so nothing
serialises them. Flipping `receiver: generic` in one PR and removing the old
trigger in another leaves a window, however short, where every web image is
promoted twice onto one branch. The reverse order leaves a window where no
receiver acts, and GitHub answers the dispatch 204 either way, so neither window
reports itself.

**Solution**: IDP-042 PR 7 changes `infra/config/products.yaml` and replaces the
old workflow's trigger with `workflow_dispatch` in one commit range, so `git
revert` of the PR restores both at once. `tests/test_product_registry.py::
test_every_staging_event_has_exactly_one_receiver` reads every workflow's
`repository_dispatch.types` and the committed registry: a `legacy` product's event
is listed by exactly one workflow, a `generic` one's by none. Mutating either half
alone turns it red (`make mutate` on the flag and on the trigger).

**Rule**: When an event moves between consumers that write the same thing, the
handover is one change, and a test holds the invariant "exactly one consumer per
event" by reading the routing from where GitHub reads it, not from a list.

**Tags**: `#github-actions` `#idp-042`
