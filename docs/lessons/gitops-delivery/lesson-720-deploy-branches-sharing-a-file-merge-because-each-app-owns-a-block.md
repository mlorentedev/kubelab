---
id: lesson-720-deploy-branches-sharing-a-file-merge-because-each-app-owns-a-block
type: lesson
status: active
created: "2026-11-06"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, deploy-merge, promotion]
---

# Deploy branches that rewrite the same files merge in either order, because each app's writes stay inside its own block

**Context**: every product promoted to staging keeps a long-lived `deploy/staging-<app>` branch, cut
from master's tip and force-pushed on each image. Every one of those branches rewrites
`values/staging.yaml` and `overlays/staging/generated/deployments.yaml`. The IDP-042 closeout review
asked whether a second generic product would make the second PR conflict, or carry a stale copy of the
first product's pin (#2611).

**Problem**: the risk is real only if two branches change lines that git cannot separate. Git's
three-way merge conflicts when both sides change the same line or consecutive lines. Shared files with
one writer per app are safe exactly when no writer reaches outside its app's lines.

**Solution**: measured, not argued. `tests/test_two_generic_products_merge.py` runs `git merge-file` on
branches produced by the real writers: `promotion.promote` for the pin and `product_render.write` for a
contract change. Two generic products sit in the tightest layout the writers produce, where only the
`third:` key separates web's last line from third's first. The test also covers the committed staging
values and overlay. Every order merges cleanly and keeps both pins. A control case shows that two pins
on consecutive lines do conflict, so the clean result is a finding. Since a merged PR's diff is its own
lines, the other product's pin is never stale.

**Rule**: a file that several generated PRs rewrite stays mergeable while each writer edits only its
own block, and the block's own key line separates it from the next. A writer that rewrites a line
shared by all apps breaks that property. Examples: a list of every image on one line, a checksum of
the whole file, a sorted index. Such a writer needs a test like this one before it ships.

**Tags**: `#deploy-merge` `#issue-2611` `#idp-042`
