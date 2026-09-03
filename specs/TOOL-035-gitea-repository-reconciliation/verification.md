---
tags: [spec, verification, templates]
created: "2026-08-27"
---

# Verification - TOOL-035

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] AC1 (declare + reconcile is idempotent) -> `890f6f56` / `tests/test_gitea_repo_reconcile.py` / live transcript under *AC1/AC4 measured on prod*
- [x] AC2 (undeclared is reported, never deleted) -> `890f6f56` / `test_the_plan_has_no_deletion_field` (structural, over `dataclasses.fields`)
- [x] AC3 (issues and pull requests carry over) -> `personal/resume`, counts under *AC3 — `resume` migrated*
- [x] AC4 (`hefesto` owns nothing) -> live listing under *AC1/AC4 measured on prod*, printed by the reconcile itself
- [ ] AC5 (migration credential scoped and checked both ways) -> both transcripts
- [ ] AC6 (`ci.yml`'s six jobs green on `act_runner`) -> run URL
- [ ] AC7 (`act_runner` registration idempotent) -> `changed=0` transcript

## Baselines measured before any change (2026-08-27)

Recorded now so AC3 and AC6 are checked against a number rather than a memory.

**`mlorentedev/resume` on GitHub** — private, 2.97 MB, default branch `main`:

| | count |
|---|---|
| issues, open | **28** |
| issues, all states | **93** |
| pull requests, open | **5** |
| pull requests, all states | **165** |
| open PRs with `isCrossRepository: true` | 0 — every head branch is in-repo and therefore fetchable |

**This table was wrong on its first writing and the error is instructive.** It read
"20 open issues", which was the value of `gh issue list --limit 20` — the page size, not the count.
A baseline that is silently the page size is worse than no baseline, because AC3 would have
"verified" the migration against it and passed. Recounted 2026-08-28 by paginating the REST API to
exhaustion. Note also that `/issues` counts pull requests as issues, so the open figure is
`33 - 5`; taking the endpoint's number at face value would have overstated it by exactly the PR
count. The migration is 258 numbered objects, not the ~25 first sketched.

**CI is dead, and its signature is not a test failure.** Most recent run `32700240170`, 2026-08-24T07:09Z:

```
job "lint"
  started   2026-08-24T07:09:10Z
  completed 2026-08-24T07:09:13Z
  conclusion failure
  steps     []
```

Three seconds, zero steps, and the same for all six jobs (`lint`, `test`, `audit`, `type`,
`gitleaks`, `build-pdf`). A job rejected before execution, not one that ran and failed. Every CI run
since 2026-08-11 has this shape — the condition PR #255 documented that day, still in force 17 days
later.

**Workflow portability**, read from all five workflow files rather than assumed:

| workflow | portable | blocking dependency |
|---|---|---|
| `ci.yml` | yes | none — `checkout`, `hadolint`, `docker/*`, `setup-uv`, `setup-python`, `trivy`, `upload-artifact` |
| `publish-drive.yml` | yes | Google secrets only |
| `release.yml` | no | `googleapis/release-please-action` → `api.github.com` |
| `add-to-project.yml` | no | `actions/add-to-project` + `gh api graphql` → GitHub Projects |
| `bitacora-status.yml` | no | `actions/github-script` + `github.graphql` → GitHub Projects |

**Gitea prod e2e, 2026-08-27**: `make test-e2e ENV=prod -k gitea` → 6 passed. Recorded with its
limitation stated: the suite probes `/api/healthz`, which `REQUIRE_SIGNIN_VIEW` exempts by design, so
this is evidence the forge is reachable and healthy and is **not** evidence for #1389 AC1. That gap
is PR0.

**Fleet state**: beelink, ace2 and ace1 all reachable over the tailnet; both Argo CD spokes answer
HTTP 200 (`toolkit infra argo check-spokes`).

## PR0 — the anonymous surface, measured (2026-08-27)

Evidence for #1389 AC1/AC2. Recorded here because PR0 is this spec's precondition; the ticket it
closes is #1389, and the same transcripts are posted there.

**Anonymous.** `tests/infra/test_gitea_anonymous_surface_live.py`, 5 passed against prod, and the
raw probe behind it:

```
path                 status  verdict                      kind
/explore/repos          303  REFUSED (redirect to login)  closed
/explore/users          303  REFUSED (redirect to login)  closed
/api/swagger            303  REFUSED (redirect to login)  closed
/api/v1/version         403  REFUSED                      closed
/api/healthz            200  OPEN                         CONTROL — must be reachable

version string '1.25.5' present in /api/v1/version body: False
```

All four were **200** on 2026-08-24. The control is the part that makes this more than a green tick:
`/api/healthz` answers 200 and the guard's own assertion classifies it `OPEN`, so putting it in
`CLOSED_PATHS` would fail the suite. The guard discriminates between "closed" and "merely
unreachable" rather than passing vacuously — which matters because Traefik answers 502 through
error-pages when the Beelink is off, and a bare `!= 200` assertion would go green against a forge
that is not running at all. That is why the suite carries a liveness precondition and skips instead.

**Authenticated.** Same endpoints with the machine identity's token (read in process from SOPS,
never printed):

```
path                  anon  auth   reading
/api/v1/version        403   200   API alive for authenticated callers, closed to anonymous
/api/v1/user           403   200   the token authenticates as an account

authenticated as: 'hefesto'  (admin=False)
repositories owned by the bot: 0  (ADR-065 D1 requires 0)
```

The 403/200 contrast on one endpoint is the actual claim: the refusal is about **authentication**,
not about the API having been switched off. A hardening that disabled the API outright would look
identical from the anonymous side and would silently break the migration.

Two findings that are not #1389's and belong to this spec:

- **`hefesto` owns 0 repositories today** — ADR-065 D1's baseline, and what AC4 must still be true
  after PR1 runs.
- **`GET /api/v1/user/orgs` did not answer 200**, consistent with the token holding
  `write:repository,write:user` and no organization scope. This is ADR-065's "the token must widen"
  observed rather than read, and it is an input to Risk 1.

An authenticated `git clone` — #1389 AC2's literal wording — **could not be demonstrated**: the forge
holds no repository to clone. The API contrast above is the available half; the clone gets its
evidence in PR2, when `resume` lands. Recorded as a stated gap rather than ticked.

**Idempotence (#1389 AC4).** `make provision NODE=bee ENV=prod`, two consecutive runs:

| run | result |
|---|---|
| 1 | `ok=128 changed=7` |
| 2 | `ok=127 changed=0` |

The role is idempotent. The seven changes on the first run were **accumulated drift on the node** —
the Beelink had not been provisioned since some template changes landed, and one of them restarted
the services. The anonymous guard was re-run after that restart: still 5/5.

That drift is the whole argument for PR0 existing. The template in git was correct for days and the
running container was not, and no static test could tell them apart. It is also a caution for PR3:
`act_runner` will be added to this same role, so the first run after it lands will report changes and
the *second* is the one that proves anything.

## AC1/AC4 measured on prod (2026-09-02)

**The first-run half of AC1 is a stated gap.** The organizations and repositories were created on
2026-09-01 and that transcript was not written down before the session ended — evidence produced and
not made durable, which is the same failure this file exists to prevent, one level up from the code.
What is recorded below is the convergence half, measured on 2026-09-02. First-run evidence returns for real
in PR2: the migration path creates `personal/resume`, so its first `--apply` is a first run.

**AC1 — a second run changes nothing.** `make gitea-reconcile ENV=prod`:

```text
Gitea reconcile — https://gitea.kubelab.live (prod)

  (nothing to do — forge matches the declaration)

AC4 ok — hefesto owns: (none)
[SUCCESS] forge matches the declaration — nothing to create
```

**AC4 — the machine identity owns nothing.** Printed by the reconcile itself rather than by a
separate command, so the run that proves AC1 produces AC4's evidence as a side effect. It is on the
CLI path rather than in a pytest because the property is about the LIVE forge and this repo's live
suites cannot decrypt SOPS (`tests/infra/fixtures.py` reads `common.yaml` only) — a credentialed test
would be new machinery, not evidence.

**AC4 could not be read at all until today, and every signal said otherwise.** The client carried
`whoami` and `list_owned_repos` specifically "to assert AC4 by consequence"; both call `/users/...`;
the admin grant did not include `read:user`. Measured before the fix:

```text
GET /users/hefesto        -> 403 required=[read:user], token scope=read:admin,write:organization,read:repository
GET /users/hefesto/repos  -> 403 required=[read:user], token scope=read:admin,write:organization,read:repository
GET /user                 -> 403 required=[read:user], token scope=read:admin,write:organization,read:repository
```

`tests/test_gitea_token_scopes.py` was green throughout, because it compared a hand-written
`REQUIRED_ADMIN_SCOPES` against a grant that matched it — two declarations agreeing about the wrong
set. **Lesson 413 one layer up**: last time a credential was present and powerless, this time a
METHOD was, and presence passed for capability both times. The cure is derivation, not another
literal: `REQUIRED_ADMIN_SCOPES` is now a union over `SCOPE_BY_METHOD`, and a test introspects
`GiteaClient` so a method cannot enter the class without its scope entering the requirement.

Guards verified by mutation, all four red with the intended diagnostic:

| mutation | fails |
|---|---|
| drop `read:user` from the declared grant | `test_admin_grant_covers_what_the_reconciler_reads` |
| add a public client method with no map entry | `test_every_client_method_declares_the_scope_it_needs` |
| restate `REQUIRED_ADMIN_SCOPES` as a literal | `test_the_admin_requirement_is_derived_from_the_methods_it_performs` |
| drop a method from the map while `ADMIN_METHODS` names it | `RuntimeError` at import, naming the method |

**The rotation that closed it.** Gitea cannot edit a minted token's scopes, so widening
`token_scopes.admin` alone changes nothing on an instance that already holds a token:

```text
make gitea-rotate-token TOKEN=admin ENV=prod APPLY=1
  [SUCCESS] revoked kubelab-reconciler on manu — the outage window is now OPEN
  [SUCCESS] cleared apps.services.core.gitea.admin_token — the mint gate is open

make provision NODE=bee ENV=prod TAGS=gitea
  run 1: ok=44 changed=2   (mint the superadmin's scoped token; record it in SOPS)
  run 2: ok=42 changed=0
```

Idempotent, and the re-mint is gated on the SOPS key being absent — so the rotation is what opens the
gate, and a provision with the key present does nothing.

**AC2 — observed as well as structural (2026-09-02).** The forge held no stray, so one was made:
`personal/zz-stray`, created by the bot, empty, undeclared. Both paths that could have removed it were
then run against it:

```
$ make gitea-reconcile ENV=prod
  ? repo personal/zz-stray   undeclared — reported, not removed
  AC4 ok — hefesto owns: (none)
  [SUCCESS] forge matches the declaration — nothing to create

$ make gitea-drop-empty REPO=personal/zz-stray ENV=prod
  [ERROR] personal/zz-stray is not declared in `apps.services.core.gitea.organizations`.
          Undeclared repositories are reported and never removed (#1076, ADR-065 D3) —
          being empty does not change that.

  survived: True | empty= True        <- read back afterwards
```

The second run is the one worth noticing: `zz-stray` **is** empty, so the only thing standing between
it and deletion was the declaration check. Emptiness does not make someone else's repository ours.
Removed afterwards through the same basic-auth path the command uses, so the forge is back to
declared state.

The structural claim still carries the weight for every future caller:
`test_the_plan_has_no_deletion_field` asserts over `dataclasses.fields(ReconcilePlan)` that no field
a deletion could travel in exists at all — stronger than a fixture that happened not to delete
anything.

## AC3 — `resume` migrated (2026-09-02)

**Counts against the GitHub baseline, once the import settled:**

| | Gitea | GitHub baseline |
|---|---|---|
| pull requests (all states) | **165** | 165 |
| open pull requests | **5** | 5 |
| open issues | **28** | 28 |

Nothing is recorded as missing. `owner=personal` — the organization, not a person — so ADR-065 D1
holds by consequence and not by assertion, and the reconcile's own AC4 line still reads
`hefesto owns: (none)`.

**Risk 3's standing assumption is now measured rather than assumed.** It rested on migrated pull
requests arriving mergeable, because the plan is to drain them in Gitea:

```
#259  mergeable=True  head='chore/align-agents-cascade'                   -> 'main'
#258  mergeable=True  head='feat/docs-005-modular-lessons'                -> 'main'
#256  mergeable=True  head='feat/res-065-scan-format-json'                -> 'main'
#255  mergeable=True  head='docs/ci-blocked-actions-quota'                -> 'main'
#253  mergeable=True  head='release-please--branches--main--components--resume' -> 'main'
```

All five same-repository heads resolved. The fallback documented in Risk 3 — draining on GitHub with
`resume`'s local `make check` path — is not needed.

### Three things this migration taught, none of which were in the plan

**1. NO TOKEN MAY MIGRATE INTO AN ORGANIZATION.** The spec assigned migration to the bot, by analogy
with repository creation. Gitea disagrees. Discriminated cleanly by asking each credential to migrate
an already-existing repository — 409 means *may*, 403 means *may not*:

```
bot token             -> 403 "Given user is not owner of organization."
admin token           -> 403 required=[write:repository], token scope=read:admin,write:organization,read:repository,read:user
superadmin basic auth -> 409 "The repository with the same name already exists."
```

Two different walls, and neither is worth demolishing. The bot is stopped by **organization
ownership**, which ADR-065 D1 requires it never to have — so it cannot be fixed by widening a scope,
only by violating D1. The admin token is stopped by **scope**, and granting it `write:repository`
would hand the reconciler a standing `DELETE /repos/...` capability. So migration goes through the
basic-auth session, exactly as `drop-empty` does. `execute` now takes an explicit `migrator` and
refuses rather than silently falling back to a token that Gitea will reject.

**2. THE IMPORT OUTLIVES THE RESPONSE, so an early count measures the clock.** Counted at three
moments on the same repository: **98** pull requests, then **147**, then **165**. Had the first
number been written into this file it would have been recorded as evidence of a partial migration —
lesson-408's mistake wearing a new disguise, since the API answers 200 throughout and never says
"still importing". The reconcile now prints that the import continues, and says the counts must stop
moving before AC3 is checked.

A related false alarm worth recording because it nearly became a finding: an early reading showed
`open PRs = 0` against a baseline of 5, which read as "pull requests did not carry over". They had
simply not arrived yet.

**3. `POST /repos/migrate` outlives the client's timeout too.** The 15s default raised `ReadTimeout`
while the server was succeeding — an error meaning "it may or may not have worked", which is worse
than a slow call. `MIGRATION_TIMEOUT = 600` now applies to that call alone.

### Two latent defects found on the way, both fixed here

- **`_paginate` built an invalid URL for any endpoint carrying a query string**, appending `?page=1`
  unconditionally: `/repos/x/y/issues?state=open&type=issues?page=1&limit=50`. Gitea reads the second
  `?` as part of the previous value, so the filter silently becomes `type=issues?page=1` and the
  endpoint answers with the wrong set rather than an error. Latent because no existing caller passed
  a filter; AC3's issue count was the first. Guarded by `tests/test_gitea_client_pagination.py`.
- **`drop-empty` built its own declared-repository set** and drifted the moment `RepoSpec` landed,
  producing strings like `"personal/RepoSpec(name='resume', ...)"` — so a declared repository read as
  undeclared and the command refused it. It failed *safe*, because that membership test guards a
  deletion, but that was the bug's direction rather than the design's doing. One producer now:
  `declared_full_names`.

## Risk 1 — settled 2026-08-27, against the live instance

The apparent contradiction in ADR-065 (D1 "the bot owns nothing" vs Consequences "the token must
widen to `write:organization`") dissolves, because **token scope and organization ownership are
different layers and the scope gates first**. Measured with a throwaway organization, created and
deleted in the same run:

```
Q1  bot POST /orgs                  -> 403
    {"message":"token does not have at least one of required scope(s),
     required=[write:organization], token scope=write:repo…"}

Q2  admin POST /orgs                -> 201
    teams in the new org: [('Owners', 'owner')]
    members: ['manu']

Q3  admin create team 'reconcilers' -> 201
    add 'hefesto' to the team       -> 204
    bot GET /user/orgs              -> 403   (required=[write:organization])
    bot POST /orgs/…/repos          -> 403   (required=[write:organization])
    team 'Owners' (owner):       ['manu']
    team 'reconcilers' (none):   ['hefesto']

cleanup: DELETE /orgs/zz-probe-risk1 -> 204 ; GET -> 404 (clean)
```

**Answer: the superadmin creates organizations, the bot creates repositories inside them.** The
creator becomes the sole member of `Owners` (Q2), so a bot that creates an organization owns it and
D1 is violated at the moment of creation — but `write:organization` on the token is *permission to
act on* organizations, not ownership of them. Widening the token and keeping the bot ownerless are
therefore compatible, which is what ADR-065 asserts without demonstrating.

**Two things this did NOT settle, and neither should be assumed:**

- **The team-permission half is unproven.** Both bot calls in Q3 were refused at the *scope* layer,
  so the team's permission was never exercised. That the bot can create a repository in an
  organization it does not own, once its token carries the scope, still has to be measured — re-run
  this probe after widening. A 403 from a missing scope and a 403 from a missing permission are the
  same status code, which is the trap AUTH-004 AC5 already recorded once.
- **`permission: "write"` came back as `permission: none`.** The team was created with an explicit
  `units` list, and the response reports `none`. Passing `units` appears to override the coarse
  `permission` field rather than combine with it. PR1 must read the created team back and assert its
  effective permission rather than trusting the request body — otherwise the reconciler ships a team
  that grants nothing and nothing looks wrong.

## AC5 — the migration credential, checked by consequence (2026-08-28)

```
ALLOWED
  /repos/mlorentedev/resume                    200
  /repos/mlorentedev/resume/issues?state=open  200   33 items  = 28 issues + 5 PRs
  /repos/mlorentedev/resume/pulls?state=open   200    5 items
  /repos/mlorentedev/resume/contents/README.md 200
  /repos/mlorentedev/fae-brain                 200   second granted repo

REFUSED
  /repos/mlorentedev/knowledge                 404   private, outside the grant
  PATCH /repos/mlorentedev/resume              403   write on a GRANTED repo

  /user/repos  ->  64 visible, of which private: ['fae-brain', 'resume']
  anonymous /users/mlorentedev/repos -> 22 public

token expiration header: 2026-10-27 03:01:11 UTC  (59 days)
```

**The refusal is a 404, not a 403.** A fine-grained PAT does not confirm the existence of a
repository outside its grant, so `knowledge` is indistinguishable from a repository that is not
there. Reading that 404 as "absent" rather than "refused" would be the wrong lesson, and it is the
same trap as AUTH-004 AC5's — where an account-level rejection and a scope-level one shared a status
code and voided a whole verification run.

**`/user/repos` returning 64 was a misread probe, not a broad grant.** Only **2** of them are
private and they are exactly the two granted; the other 62 are public, which need no grant at all.
The control that settles it is the direct read: `knowledge` (private, ungranted) → 404, `iris`
(public) → 200, which is what ADR-065 says each should be.

## A defect found in the credential-expiry control itself

Registering the token surfaced a real bug in `toolkit secrets`, fixed on this branch with
`tests/test_secret_expiry_lookup.py`. Both expiry reports resolved values from
`ConfigurationManager("common")` alone, so any PROVIDER credential stored per environment was
invisible to them:

```
before:  apps.services.core.gitea.github_migration_token  declared PROVIDER but absent from SOPS
after:   apps.services.core.gitea.github_migration_token  expires 2026-10-27  (59d)
```

The two callers failed differently and both were wrong — `audit` skipped it with no output at all,
`check-expiry` announced it absent — about a credential that authenticated against GitHub in the
same session. A false negative on a credential control is precisely what `secret_expiry`'s own
docstring is written against: a key nobody is warned about is indistinguishable from one that cannot
expire.

The fix searches every SOPS file rather than threading an env through, because `SecretSpec.envs` is
the audit dimension and not the storage location (ANSIBLE-033) — the catalog cannot be asked which
file holds a value — and because `check-expiry` takes no `--env` and must be correct without one.

**Incidental finding, filed rather than fixed:** the same report shows an orphaned Headscale API key
that expired 2026-08-23. The key this repository stores is the healthy one (verified by comparing
prefixes, never values), so nothing is broken — but it reddens `check-expiry` permanently, and a
control that always fails stops being read. Filed as #1485 (VPN-014).

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- **2026-08-27 — the migration carries metadata, not only git objects.** Operator decision. `resume`'s
  20 open issues and 5 open pull requests are the reason the repository is worth moving; a
  git-objects-only push would have moved the code and left the work.
- **2026-08-27 — the Gitea Actions runner is inside this spec rather than a separate one under #504.**
  Operator decision, and it follows from the Why: migrating a repository whose CI is dead into a forge
  with no CI does not close the pain. #504's evaluation is answered by construction here.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons/`? Likely yes — the portability line for Gitea Actions is
      "does the action talk to the GitHub API as a platform, or only to the runner", which predicts
      the outcome better than any compatibility list.
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? Possibly — ADR-065 left "what must be
      true before the GitHub copy is retired" open, and Risk 3 (which forge accepts a merge during the
      pilot) is the first half of that answer.
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. Probably no.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/TOOL-035-gitea-repository-reconciliation/` -> `specs/archive/`
- [ ] Bitácora board tickets moved to Done / closed with PR links (ADR-018): #1076, #1389, #504
- [ ] Promotions above executed (if any)
