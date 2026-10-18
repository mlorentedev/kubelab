---
id: "TOOL-035-gitea-repository-reconciliation"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-27"
issue: "kubelab#1076"
tags: [spec, proposal, gitea, forge, ci, migration]
template_version: "1.0"
---

# TOOL-035: Gitea repository reconciliation

<!-- from issue #1076: TOOL-035: no declarative path for getting repositories into Gitea -->

## Why

Gitea has run on the Beelink since ADR-061 and holds nothing, because no path exists for getting
repositories in: today "migrate a repo" means a manual `git push` to a remote created by hand in the
web UI — untracked, unrepeatable, invisible to review (#1076). ADR-065 then decided *where inside the
forge* repositories live and *which* ones move, leaving only the mechanism unbuilt.

What makes this urgent rather than tidy is measured, and it is not the forge's emptiness. The pilot
repository `mlorentedev/resume` has had **no working CI since 2026-08-11** — 17 days at the time of
writing. Its own PR #255 documented the cause (the account's pooled GitHub Actions minutes, Free
plan, shared across every private repo) and named the resolution: *"a self-hosted Gitea instance on
kubelab with the repo migrated there."* Verified live on 2026-08-27 against the most recent run
(`32700240170`): every one of the six jobs completed in three seconds with an **empty `steps` array**
— a job rejected before execution, not a test that failed. Every CI run since 2026-08-11 has that
same shape.

So the deliverable is not "repositories exist in Gitea". It is that a push to `resume` in Gitea runs
its checks and they pass — which is what the migration was always for.

## What

1. **Organizations and repositories are declared as SSOT** in `common.yaml`, per ADR-065 D2's
   provenance axis: `teledyne/` (`fae-brain`, `openkm-brain`), `personal/` (`resume`), and `kubelab/`
   declared while holding nothing (D3).
2. **A toolkit reconciler** reads that declaration against Gitea's API: it creates what is declared
   and missing, and **reports** what exists and is undeclared. Deletion is never implicit. Idempotent
   by construction — a second run changes nothing.
3. **Migration carries issues, pull requests, labels, milestones and releases**, not only git
   objects, via Gitea's migration endpoint against GitHub. `resume` carries 28 open issues and 5 open
   pull requests; a migration that dropped them would move the repository and leave the work behind.
4. **A Gitea Actions runner (`act_runner`) on the Beelink**, registered declaratively from Ansible,
   so a push to a migrated repository runs its workflows on hardware whose minutes nobody meters.

## Out of scope

- **Cutover.** The GitHub copy of every migrated repository stays authoritative (ADR-065 D4). What
  must be true before it is retired is explicitly left open by that ADR and stays open here; the
  backup gate (#972 → #1056) binds there, not at pilot start.
- **Teams, webhooks and branch protection as code** — #503. Org membership needed by the reconciler
  is in scope; the general structure is not.
- **Dependency-update automation** for Gitea-hosted repositories — #1384.
- **Anything Argo CD reconciles** stays on GitHub (ADR-061). Nothing here widens what the forge is for.
- **Migrating the remaining repositories.** ADR-065 measured 40 private repositories and moves three;
  `knowledge` and the 36 archived ones stay on GitHub, with reasons recorded there.

## Risks / open questions

1. **[MUST RESOLVE BEFORE CODE] The reconciler creating organizations makes `hefesto` an
   organization owner, which contradicts ADR-065 D1.** D1's whole argument is that the bot *owns
   nothing*, so that its retirement is a membership deletion rather than a data migration. But
   ADR-065's own Consequences section requires widening `hefesto` to `write:organization` — and in
   Gitea the account that creates an organization becomes its owner. Creating orgs as the bot and
   creating them as the superadmin are different systems; decide which, and if it is the bot, decide
   what demotes it afterwards and whether that step is idempotent. Do not write the reconciler
   against a guess. **Settled 2026-08-27 against the live instance** (`verification.md`, *Risk 1*;
   `tasks.md` Setup): the superadmin creates organizations and the bot creates repositories inside
   them, enforced by `actor_for_org_creation() is Actor.SUPERADMIN`.
2. **[MUST RESOLVE BEFORE CODE] The migration endpoint needs a GitHub credential reaching outward
   from the Beelink.** Carrying issues and pull requests means Gitea authenticates *to GitHub* — a
   second forge credential, on an on-demand homelab node, with `repo` scope on private repositories.
   Decide its scope, its expiry, its SOPS path, and whether it is checked by consequence the way
   AUTH-004 required of `hefesto`'s token. An unscoped or unexpiring token here is a worse exposure
   than the one SEC-GITEA-001 just closed.
3. **Open pull requests exist in two live forges at once, and ADR-065 D4 did not anticipate it.**
   D4 keeps the GitHub copy authoritative until cutover, which is a clean rollback plan for code and
   an ambiguous one for five open pull requests: merging in one forge does not close the other.
   Measured 2026-08-27 — all five have `isCrossRepository: false`, so every head branch is fetchable
   and the migration itself is unobstructed. The question is procedural rather than technical:
   which forge accepts a merge during the pilot window. **The operator answered it on 2026-08-28**
   (`tasks.md` Setup, Risk 3): Gitea accepts merges from the migration onward, and GitHub is the
   frozen rollback snapshot. The assumption it rested on, that migrated pull requests arrive
   mergeable, was measured true on 2026-09-02 (5/5 `mergeable=True`).
4. **Three of `resume`'s five workflows cannot run on Gitea, and the split is structural rather than
   a compatibility gap.** Measured 2026-08-27 by reading all five. Marketplace availability is *not*
   the constraint people expect — Gitea resolves `uses:` against github.com by default, so
   `actions/checkout`, `hadolint`, `docker/*`, `astral-sh/setup-uv`, `actions/setup-python` and
   `aquasecurity/trivy-action` are all portable. What does not port is anything speaking the GitHub
   **API as a platform**:

   | workflow | runs on Gitea | why |
   |---|---|---|
   | `ci.yml` (the six dead jobs) | yes | only portable actions |
   | `publish-drive.yml` | yes | Google secrets only |
   | `release.yml` | **no** | `googleapis/release-please-action` creates PRs and releases via `api.github.com` |
   | `add-to-project.yml` | **no** | `actions/add-to-project` + `gh api graphql` against GitHub Projects |
   | `bitacora-status.yml` | **no** | `actions/github-script` + `github.graphql`, same API |

   So the pain *is* addressable — `ci.yml` is exactly the portable one — but migrating `resume` costs
   it release automation and both bitácora integrations. That is a consequence to accept
   deliberately, and it is a second argument for ADR-065 D4's retained GitHub copy that the ADR did
   not consider.

   Three concrete things to verify before claiming AC6, none speculative: (a) `docker/setup-buildx-action`
   and `build-push-action` inside `act_runner`'s Docker mode need the socket mounted — four of the six
   jobs build images, and ADR-030's existing Beelink GitHub runner is the precedent for that shape;
   (b) `actions/upload-artifact@v4` needs Gitea's v4 artifact backend, present since 1.24 and the
   instance runs 1.25.5, but it is the first thing that breaks in practice; (c) `runs-on: ubuntu-latest`
   does not exist by itself and must be mapped to a runner label.
5. **SEC-GITEA-001 (#1389) has no live guard for its own acceptance criterion.** The hardening is in
   `compose.yml.j2` and `tests/test_gitea_anonymous_surface.py` asserts it on the *rendered template*.
   AC1 asks for a refused anonymous request against the running host, and the prod e2e suite probes
   only `/api/healthz`, which is exempt from `REQUIRE_SIGNIN_VIEW` by design (6/6 green on
   2026-08-27, and that greenness says nothing about anonymous exposure). The first push is what
   makes this bite; the guard belongs before it.

## Acceptance criteria

> The seven criteria were drafted from ADR-065 and #1076. AC3's metadata scope and AC6's existence
> were operator decisions. The operator accepted the set by approving the archive on 2026-10-18
> (kubelab#2443). Each criterion is ticked below with a pointer to its evidence in `verification.md`.

- [x] **AC1** — ✓ (`verification.md` *AC1/AC4 measured on prod*) — Declaring an organization and a repository in `common.yaml` and running the reconcile
      command creates them in Gitea; running it a second time reports no change. Verified by a live
      reconcile transcript, not a config diff.
- [x] **AC2** — ✓ (`test_the_plan_has_no_deletion_field`; live stray `personal/zz-stray` reported and kept) — A repository present in Gitea but absent from the declaration is **reported and not
      deleted**. Demonstrated against a repository created for the purpose, then removed by hand.
- [x] **AC3** — ✓ (`verification.md` *AC3 — `resume` migrated*: 165/165 PRs, 5/5 open, 28/28 open issues) — After migrating `resume`, its 28 open issues and 5 open pull requests are present in
      Gitea with their titles and numbers, and every pull request's head branch resolves. Verified by
      counting through Gitea's API against the GitHub counts recorded here, not by opening the UI.
      **The issue figure read `20` until 2026-08-31 and was wrong** — it came from `gh issue list
      --limit 20`, so it measured the flag rather than the repository (lesson-408). Recounted by
      paginating to exhaustion and excluding `pull_request` entries, which the REST issues endpoint
      returns alongside issues.
- [x] **AC4** — ✓ (`verification.md` *AC1/AC4 measured on prod*: `hefesto owns: (none)`) — After a full reconcile, `hefesto` owns no repository and no organization, per ADR-065
      D1. Verified by the API listing what the account owns and finding it empty.
- [x] **AC5** — ✓ (`verification.md` *AC5*: 200 on the grant, 404 and 403 outside it) — The GitHub credential used by the migration is scoped, stored in SOPS, registered in
      `SECRET_CATALOG`, and checked by consequence: an authenticated call returns 200, and a call
      outside its scope is refused. Both halves captured — a token that works proves only half.
- [x] **AC6** — ✓ (#1076 comment 2026-09-04 (run 9, six jobs green); the three non-portable workflows are recorded in `verification.md`) — A push to `resume` in Gitea triggers `ci.yml` on `act_runner` and **all six jobs
      pass** — the same six that have completed in three seconds with an empty `steps` array since
      2026-08-11. The three workflows Risk 4 measured as non-portable are recorded as a named,
      accepted loss with their replacement (or their absence) stated, not quietly dropped.
- [x] **AC7** — ✓ (#1076 comment 2026-09-03: `changed=10` then `changed=0`) — The `act_runner` registration is idempotent from Ansible (`changed=0` on re-run) and
      its resource limits follow ADR-030.

## References

- Bitácora board: mlorentedev/kubelab#1076 (TOOL-035), sequenced by #1077 (IDP-034).
- ADRs: `docs/adr/adr-065-forge-repository-organization.md` (orgs, which repositories, D1 ownership,
  D4 rollback), `adr-061-stateful-service-placement.md` (what the forge is for),
  `adr-062-platform-identity-model.md` (identity tiers), `adr-030-self-hosted-ci-runner.md`
  (runner placement and resource limits).
- Related issues: #1389 (SEC-GITEA-001, hardening — Risk 5), #504 (OPS-D015, Gitea Actions
  evaluation — answered by construction here), #503 (teams/webhooks), #1384 (dependency automation),
  #1075 (ANSIBLE-037, dev-node access), #972 → #1056 (backup gate, binds at cutover).
- Evidence: `mlorentedev/resume` PR #255 (quota exhaustion and the named resolution path); run
  `32700240170` (six jobs, empty `steps`, three seconds).
