---
id: lesson-723-synthetic-fixture-in-a-real-secrets-format-is-an-incident
type: lesson
status: active
created: "2026-11-07"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, gitguardian, secrets-scanning, test-fixtures]
---

# A synthetic fixture in a real secret's format is an incident, and removing it does not clear the check

**Context**: VPN-ACL-016 (#2863) added `tests/test_headscale_authkey.py`, whose fixtures imitated real Headscale
pre-auth keys with high-entropy-looking material (`hskey-auth-SECRETKEYMATERIAL0001`). GitGuardian flagged them and
PR #3192's check went red. The fixtures were reshaped in a later commit (`b00a358c`) to the low-entropy house style
(`hskey-auth-test-0001`, the precedent at `tests/test_headscale_rejoin.py:39`).

**Problem**: two independent halves. First, a fixture that mimics a real credential's format is indistinguishable
from a leak to the scanner — the detector cannot know the material is synthetic, so entropy is the only signal it
has, and the fixture must not spend it. Second, the check stayed red after the fix: GitGuardian scans every commit
of the PR, the incident was already created in its dashboard by the earlier commits, and removing the occurrence
from the tip does not withdraw it — only classifying the incident in dashboard.gitguardian.com does. And even after
classification the displayed check result is cached until a re-scan (a new push, or a dashboard re-scan), so a green
dashboard can coexist with a red check for a while.

**Solution**: synthetic secrets in tests use low-entropy fakes (`hskey-auth-test-0000` style) — the format prefix
is what the code under test needs, not the entropy. For the check: inspect the finding, confirm it is synthetic,
classify it in the dashboard, then let the check refresh; an empty commit is one re-scan path but not the only one.

**Rule**: a fixture imitating a real credential must be as low-entropy as the format allows; and a scanner's verdict
is state in its dashboard, not a property of the current tree — fixing the tree does not retract the incident.

**Tags**: `#gitguardian` `#secrets-scanning` `#test-fixtures` `#pr-3192` `#issue-2863`
