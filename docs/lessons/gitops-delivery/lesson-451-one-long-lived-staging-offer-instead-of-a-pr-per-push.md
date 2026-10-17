---
id: lesson-451-one-long-lived-staging-offer-instead-of-a-pr-per-push
type: lesson
status: active
created: "2026-09-05"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, staging, receiver, force-push, adr-046, pr-1671]
---

# One long-lived staging offer instead of a pull request per push

**Context**: `web-image-receiver.yml` turns every image dispatched from the
`web` repo into a `chore(staging): deploy` pull request that a human merges
to move staging. #1671, closes #1645.

**Problem**: Measured over the workflow's life: 104 such PRs opened, 35
merged, 68 closed, and of those 68, 67 were superseded by a newer offer and
exactly one was declined on its merits. The human gate had been exercised as
a genuine "hold staging" once in 104; the rest of the closes carried no
decision at all. The cause was one line, `BRANCH="deploy/staging-web-${TAG}"`,
so every dispatch minted a branch and every branch minted a PR, plus a
coalescing loop to close the ones it had just overtaken.

**Solution**: A stable `deploy/staging-web` branch, always exactly one commit
ahead of master, force-updated to the newest sha. Its pull request is created
once and patched thereafter, so the queue is a single long-lived offer.
The gate is untouched: merging still moves staging, and declining is now
simply not merging, which is strictly better than closing a PR a newer one
replaces anyway. `allow_auto_merge` stays false, and the "diff nobody wrote"
exception is deliberately not invoked: once the noise is gone the exception
is unnecessary. ADR-046 is not reopened; it chose CI-driven, PR-gated
promotion, not a branch naming scheme.

Three decisions worth keeping. The PR lookup runs before the push, so an API
failure leaves the remote untouched and offer and description still agree,
instead of new content under an old title that invites a merge by a stale
description. Plain `--force`, not `--force-with-lease`: `actions/checkout`
fetches only the ref it checks out, so the lease has nothing to compare
against and refuses with `stale info`, and fetching first would make it
vacuous (lesson-430); what protects the ref is that nothing else writes it.
#1651's rollback is retired, because on a stable branch the ref is meant to
persist and there is nothing to reconcile. Tests execute the shipped step
against a real bare remote with `gh` stubbed and assert on what the remote
holds; six of seven fail against the old step, and moving the lookup after
the push fails exactly the ordering test.

Scope: AC3 ("web and api do not collide") was deferred, because the api lane
in `staging-deploy.yml` had 16 `startup_failure` triggers in ten weeks and
had never run (#1666); a collision between two lanes cannot be verified when
one does not exist.

**Rule**: Count what a human gate actually decided before defending it. When
almost every close is a supersession, the PR-per-push shape is generating
work, not review; keep the gate and collapse the queue to one offer that is
patched in place. Do the read that names the offer before the write that
changes it, and choose a force mode by measuring what the runner can see
rather than by which flag sounds safer.

**Tags**: `#staging` `#receiver` `#force-push` `#adr-046` `#pr-1671`
