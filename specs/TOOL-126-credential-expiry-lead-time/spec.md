---
id: TOOL-126-credential-expiry-lead-time
type: spec
status: active
created: "2026-10-28"
owner: manu
issue: "kubelab#2744"
---
# TOOL-126: Credential expiry lead time

## Intent

`make secrets-audit` and `toolkit secrets check-expiry` mark a provider-issued or declared credential red when it has fewer than 90 days left. The window is the same for every credential, so one whose whole life is 90 days or less is red from the day it is issued. Measured 2026-10-27, minutes after renewing both: the dev node PAT (60-day life) was red, and the R2 minter (90-day life) turned red the next day. A red line that never needs action trains the operator to skip the column that names a credential about to expire.

## Scope

In:

- `SecretSpec.warn_days`: an optional lead time per catalog entry. Unset, the global window applies (`--warn-days`, 90 by default).
- All three places that judge a remaining life read it: the provider loop of the audit's expiry report, the provider loop of `check-expiry`, and the declared-date lines both share.
- `warn_days=14` on the dev node PAT and the R2 minter, whose stated lives are 60–90 and 90 days.
- A catalog test: an entry whose expiry is reported and whose format hint, rotate note or referenced runbook states a life of 90 days or less declares a lead time shorter than that life.

Out:

- Headscale API keys, which `check-expiry` lists from the server by prefix and cannot tie to a catalog entry; they keep the global window.
- Scheduling `check-expiry` (nothing runs it today).
- Storing a life or a date in the catalog: the life stays where the runbook and hint already state it, and a date would drift on every re-mint.

## Checklist

- [x] Failing tests first: a credential with its own lead time is INFO outside it and ERROR inside it, in the audit report, in `check-expiry` and on a declared date; one without keeps the 90-day default.
- [x] `SecretSpec.warn_days`, validated positive; the three call sites read it.
- [x] `warn_days=14` on `apps.services.automation.dev_node.github_token` and `cloudflare.r2_token_minter`; their format hints state the life.
- [x] Catalog test for stated lives of 90 days or less; mutants on both entries go red.
- [ ] `make secrets-audit` on the live state prints both credentials as INFO.

## Evidence

See the PR body.

## Next

Open the PR, triage, land.

## Promotion candidates

- [ ] Lesson? `no`: the ticket records the measurement; nothing beyond it was learned.
- [ ] ADR? `no`
- [ ] Pattern? `no`
