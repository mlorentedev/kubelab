---
id: lesson-610-an-exemption-keyed-on-which-files-changed-exempts-whatever-those-files-say
type: lesson
status: active
created: "2026-10-21"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, review-attestation, delivery]
---

# An exemption keyed on which files changed exempts whatever those files say

**Context**: DELIVERY-004 (#1619) exempted generated staging deploy PRs from review with a
`review-attestation` signature: the exact changed-file set `values/staging.yaml` plus the
generated staging overlay. Each real deploy PR changes one line in each.

**Problem**: The signature checked which files changed, never what changed in them. Any PR
confined to those two files was exempt, whatever it changed: a resource limit, an env var,
or the image repository. The generated overlay matches the generator by construction, so
the config-drift gate would not catch it either. The class the signature was written for
is "one version moved to a sha tag", and the file set only described what that class
usually looks like. Exact set equality and the negative tests made the comparison strict,
but the input to it was the wrong one.

**Solution**: The exemption now requires the `deploy-shape` predicate
(`toolkit/features/deploy_shape.py`), recomputed from master's code at the head sha the
attestation judges. The predicate allows exactly one values leaf,
`apps.platform.<app>.version` for a registered app, moving to a `sha-` tag. The overlay may
change only in `image` leaves on the same repository, and the tag's commit must be on the
product's default branch. `test_the_staging_files_alone_no_longer_exempt` and
`TestValues.test_a_second_changed_key_ends_it` pin it.

**Rule**: Before a predicate grants anything, ask whether its input can tell the intended
change apart from any other change to the same object. A file list says where a change
happened, not what it did. Where the grant matters, judge the content. The prod signature
has the same shape and is recorded on #1741.

**Tags**: `#review-attestation` `#delivery-004` `#issue-1619`
