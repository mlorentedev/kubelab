---
id: lesson-543-a-cloudflare-create-that-times-out-can-land-and-leave-the-record-tainted
type: lesson
status: active
created: "2026-10-08"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, terraform, cloudflare]
---

# A Cloudflare create that times out can still land, and Terraform then plans to replace it

**Context**: After #2142 merged, `make tf-dns-apply` from the main checkout
created `cloudflare_record.kubelab_svc["chat"]`, the only change the plan
showed. Authelia already held the OIDC redirect on that name.

**Problem**: The apply failed with `timeout while waiting for state to become
'success' (timeout: 30s)`. The record existed anyway: `dig chat.kubelab.live
@1.1.1.1` answered the VPS address. Terraform had recorded the resource as
*tainted*, so the next plan read `1 to add, 0 to change, 1 to destroy`
(`is tainted, so must be replaced`). Re-running `tf-dns-apply`, which carries
`-auto-approve`, would have deleted the name that SSO was already redirecting
to and created it again, risking the same timeout halfway through.

**Solution**: Check the record by its consequence (it resolves), then clear the
taint, which touches only the state:
`terraform untaint 'cloudflare_record.kubelab_svc["chat"]'` in
`infra/terraform/dns`. The next `make tf-dns-plan` read `No changes`. Since TF-013
(#2147) that is `make tf-untaint ROOT=dns RES=<address>`, and `tf-dns-apply`
refuses a replace unless `ALLOW_DESTROY=1`.

**Rule**: When a provider create fails on a timeout, do not re-apply. Check
whether the object exists first. If it exists and matches the config, untaint
it. A re-apply of a tainted resource is a destroy and a create, and an
`-auto-approve` target shows you neither before it runs.

**Tags**: `#terraform` `#cloudflare` `#pr-2142`
