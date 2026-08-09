---
id: dev-node-token-rotation
type: runbook
status: active
created: "2026-08-08"
updated: "2026-08-08"
owner: manu
---

# Dev node token rotation (ace2)

> Rotate the fine-grained GitHub PAT that gives the ace2 dev node its machine
> identity. **Next due: 2026-11-05** (90 days from 2026-08-07).

The token is the node's only credential: it serves both `gh` and git-over-HTTPS,
so one rotation covers both. See ADR-058 (D1/D3) and the archived
`specs/ANSIBLE-033-dev-node-credentials/` for why it exists and why it expires.

## What breaks on expiry day, and how you find out

There is **no alert**. The token stops working on a date GitHub enforces, and
the failure shows up as work not happening:

| Symptom | Where |
|---|---|
| `gh auth status` reports the token is invalid | ace2, interactively |
| `git push` fails **401** / `Authentication failed` | any agent workspace on ace2 |
| `gh pr create` fails 401 | agent sessions in tmux |
| Agents appear to "hang" or silently stop opening PRs | whatever is driving them |

The last row is the dangerous one — an agent that cannot push may look busy
rather than broken. **If an agent stops producing PRs, check the token first.**

Nothing else on ace2 is affected: the toolchain and the dev sessions do
not use this credential.

## Who is notified

Nobody, automatically. This is a **calendar-driven** task, which is precisely why
the expiry date is recorded here, in the token's name (`ace2-dev-node-2026-08`),
and in `SECRET_CATALOG`. The 90-day life is deliberate — see the spec's Risks
section — and short enough that this runbook gets exercised four times a year.

## Rotation

Steps 1-4 replace the credential; **step 5 is the one people skip.**

### 1. Mint the replacement

GitHub → Settings → Developer settings → Personal access tokens → Fine-grained.

- **Name:** `ace2-dev-node-<YYYY-MM>` (e.g. `ace2-dev-node-2026-11`). The host
  leads so that during an incident you can answer "which machine loses access if
  I revoke this?". The month distinguishes the new token from the old during the
  overlap, when both are live.
- **Expiry:** 90 days.
- **Repository access:** see *Reconsider the scope* below before choosing.
- **Permissions:** Contents `RW`, Pull requests `RW`, Metadata `R` (forced),
  Checks `R`, Commit statuses `R`. **No** Workflows, **no** Issues, **no**
  Actions. A token that can write workflows can run arbitrary code on the
  self-hosted runner with its secrets.

### 2. Reconsider the scope (do this now, not "later")

The token is currently scoped to **All repositories** — a deliberate decision,
recorded in the spec, which leaves the repository axis open and pre-authorises
repositories created after the token was minted. Narrowing needs **no re-mint**,
so rotation is the natural moment to revisit it.

> **Ask:** which repositories has the dev node actually needed this quarter?
> If the answer is a short list, enumerate it instead of granting All.

**If you narrow it, keep the acceptance fixture in scope.** The ANSIBLE-033 f2
probe clones and pushes to `mlorentedev/kubelab-devnode-fixture` — a private repo
that exists for no other reason. If narrowing drops it, the probe fails at the
clone with a generic auth error that reads like a broken credential rather than a
moved goalpost. Whatever list you enumerate, that repo is on it.

### 3. Store it

```bash
toolkit secrets set apps.services.automation.dev_node.github_token --env common
```

It lives in `common.enc.yaml`, **not** per-env: this is machine identity, not
environment configuration. Confirm the audit still sees it:

```bash
make secrets-audit          # staging must stay at 100%
```

### 4. Re-provision the node

```bash
make provision NODE=ace2 ENV=staging TAGS=dev_node
```

`TAGS=`, not `--tags` — make rejects the latter. The controller decrypts SOPS and
passes the token in; **ace2 never holds a decryption key**, and must not be given
one (SEC-SOPS-001 / #889: every SOPS file is encrypted to the same recipients, so
any age key on that node would also open prod).

Verify — in two steps, because the first one is weaker than it looks:

```bash
ssh -o ForwardAgent=no ace2 'gh auth status'
```

That proves the node *stored* a credential. It does not prove the credential can
do the job: a token minted with the wrong permissions, or scoped to a repository
list that omits the fixture, passes this check and still cannot push. Run the
acceptance probe for the write path:

```bash
scp specs/archive/ANSIBLE-033-dev-node-credentials/probes/f2-private-repo-flow.sh \
    ace2:/tmp/ansible-033-f2.sh
ssh -o ForwardAgent=no ace2 'tmux kill-session -t ansible033f2 2>/dev/null; \
    tmux new-session -d -s ansible033f2 "bash /tmp/ansible-033-f2.sh"'
ssh -o ForwardAgent=no ace2 'cat /tmp/ansible-033-f2.result'   # want: F2_OK
```

It clones, commits, pushes and opens a draft PR against the fixture, then removes
both. `F2_FIXTURE_ARCHIVED` means the fixture, not the token, is the problem.

The `specs/archive/` path is correct as written: the spec was archived on
2026-08-08, and the runbook outlives it by design.

### 5. Revoke the old token

**This is the step that gets skipped**, because everything already works after
step 4 — which is exactly why the old credential quietly stays valid.

GitHub → the previous token (`ace2-dev-node-<previous-month>`) → **Delete**.

Until you do this, there are two live credentials for one machine, and the
compensating control that the whole interim rests on — a short, enforced
lifetime — is not actually in force.

### 6. Update the record

- Bump **Next due** at the top of this file (+90 days).
- Note the new token name in the archived spec's `verification.md` if the
  repository scope changed.

## Recovery: expired with no replacement ready

Nothing is broken on the node — it simply has no identity. Run steps 1, 3, 4.
No cleanup is needed first: `gh auth login --with-token` overwrites the stored
credential, and the role's guard compares the stored token with the desired one,
so the change is applied on the next provision.

## Exit criteria for this runbook

This procedure exists because the credential is at rest on the node — a
deliberate deviation from ADR-058 D3, taken because Bitwarden-over-API
(`mlorentedev/dotfiles#585`) does not exist. When that lands, or a GitHub App
replaces the PAT (deferred to its own ADR), this runbook retires with it.

## Related

- `specs/archive/ANSIBLE-033-dev-node-credentials/` — the decision record
- `docs/adr/adr-058-ace2-dev-node.md` — D1/D3
- [SEC-SOPS-001 (#889)](https://github.com/mlorentedev/kubelab/issues/889) — why ace2 holds no age key
