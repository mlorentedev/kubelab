---
id: lesson-473-the-argo-cd-ui-asks-for-confirmation-before-the-server-authorizes
type: lesson
status: active
created: "2026-09-26"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, argocd, rbac, verification]
---

# The Argo CD UI asks for confirmation before the server authorizes, so the modal is not a permission

**Context**: AUTH-011 gave the `users` group `role:operator` in Argo CD:
read, sync and resource actions on applications, nothing else. Its prod
check (AC5) needed `operator` to be refused a delete of an application.

**Problem**: Signed in as `operator`, *Delete* on an application opened the
confirmation dialog, name field and all, exactly as it does for `manu`. The
UI does not ask the server whether the caller may delete before it asks the
caller whether they mean it. The refusal only comes back after the dialog is
confirmed, so the one way to see it in the browser is to confirm a delete in
prod and trust the policy to stop it. If the policy were wrong, the evidence
would be a deleted application.

**Solution**: Denials were judged by Argo CD's own evaluator against the
policy the hub actually serves, never by confirming the dialog. The live
`policy.csv` came from `argocd-rbac-cm` through the hub kubeconfig, and the
pinned image evaluated it with
`argocd admin settings rbac can <subject> <action> <resource> <object> --policy-file policy.csv --default-role role:readonly`
(exit 0 means allowed). `users` was denied `delete` and `update` on
`applications` and `update` on `repositories`, and allowed `sync`. The same
matrix runs in CI over the shipped file
(`test_argo_cd_rbac_lets_users_operate_and_never_administer`). The browser
was used only for what is safe to confirm: a Sync, which `operator` may do.

**Rule**: A confirmation dialog proves the UI understood the request, not
that the server will refuse it. Never confirm a destructive action to test a
denial. Evaluate the live policy with the product's own evaluator, and use the
browser only for the allowed half of the check.

**Tags**: `#argocd` `#rbac` `#issue-1862` `#pr-1870`
