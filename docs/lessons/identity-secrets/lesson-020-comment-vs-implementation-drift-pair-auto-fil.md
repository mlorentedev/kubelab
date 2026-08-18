---
id: lesson-020-comment-vs-implementation-drift-pair-auto-fil
type: lesson
status: active
created: "2026-05-26"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, patterns, testing, documentation, drift, ssot-019, oidc-sync-001]
---

# Comment-vs-implementation drift — pair "auto-filled" comments with executable tests

**Context**: This session surfaced the same pattern twice. (1) `infra/config/values/common.yaml:477` had the comment `# admin_email auto-filled from apps.contact.email by the config loader (SSOT-014c)`, but `toolkit/features/configuration.py:_inject_contact_email_derivations` only filled 3 consumers (acme_email, uptime_kuma, Authelia admin) — Gitea was missing. Result: `make apply-secrets ENV=prod` warned `Missing values: ADMIN_EMAIL`, and the prod gitea pod entered `CreateContainerConfigError` for 76 minutes after the first restart that touched the new SECRET_CATALOG entry. (2) `toolkit/scripts/sync_oidc_hashes.py` docstring promises "Sync OIDC client_secret hashes from SOPS into Authelia K8s ConfigMap YAMLs", but its `FILE_PATHS` dict still points to `infra/k8s/overlays/prod/patches.yaml` after PR #225 moved the OIDC clients block to `infra/k8s/overlays/prod/authelia-config/configuration.yml`. The regex misses, the script reports `"OK: gitea hash already current in patches.yaml"` and exits 0 — false success.

**Problem**: Documentation comments are written at the moment a behavior is intended; implementation can drift around them and the comment becomes a false promise. There is no mechanism (linter, test, ADR review) that forces comment-vs-code alignment. The "auto-filled", "synced", "validated" verbs in particular are dangerous because they invite the reader to trust an invariant that is not enforced anywhere. Both bugs above had **zero CI signal** until manual smoke caught them.

**Solution**: For SSOT-019 (PR #226) added explicit parametrized tests in `tests/test_credentials_reconcile.py::TestSSOTContactEmail` that assert each derivation (`acme_email`, `uptime_kuma.admin_email`, `gitea.admin_email`, Authelia admin user) literally equals `apps.contact.email`. The test is the executable form of the comment — if someone removes the derivation later, the test fails before the comment lies. For OIDC-SYNC-001 (tracked) the corresponding fix is `RuntimeError` when the script's regex misses entirely, plus a regression test that `FILE_PATHS` points to a file containing the expected pattern.

**Rule**: Every comment that asserts a behavior ("X is auto-filled from Y", "Z is synced via this script", "field W is validated at load") MUST have a sibling test that asserts that exact behavior. Treat the comment as a hypothesis and the test as its proof. The cost is one test per assertion; the value is that the comment becomes self-verifying — future contributors who break the invariant will see a failing test before they see a misleading comment. Anti-pattern: writing the comment alone and trusting future readers to enforce it.

**Tags**: `#patterns` `#testing` `#documentation` `#drift` `#ssot-019` `#oidc-sync-001`
