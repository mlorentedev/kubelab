---
tags: [spec, verification]
created: "2026-08-09"
---

# Verification - AI-007-ollama-retirement

## Evidence

All eight criteria map to a probe in `features.json`; all eight are `verified`.

- [x] AC1 (no live wiring in tracked files) -> f1, exit 1 (no matches)
- [x] AC2 (drift gate green, generated artifacts clean) -> f2, `make validate-sync` all-green
- [x] AC3 (key unset in SOPS, not orphaned) -> f3, `sops -d prod.enc.yaml` carries no Ollama
- [x] AC4 (public record destroyed, name does not resolve) -> f4, plan `1 to destroy`, applied, NXDOMAIN at the authoritative NS
- [x] AC5 (out-of-band Middleware gone from the LIVE cluster) -> f5
- [x] AC6 (suites pass, no dangling expectation) -> f6, 393 passed
- [x] AC7 (ADR-028 + ADR-029 amended) -> f7
- [x] AC8 (no operational doc claims it is running; rotation runbook deleted) -> f8

## Test status

- Full non-e2e suite: **393 passed, 98 deselected**. 394 before; the net -1 is two
  ollama-coupled catalog tests replaced by one generic invariant.
- `make type`: clean. `make validate-sync`: all generated files in sync.
- **`yamllint` on `common.yaml` is red, pre-existing, and not caused by this PR.**
  Reproduced against the pristine file at HEAD before attributing it: **21 errors**
  there, **19** with this diff — this change *reduces* them by deleting two offending
  lines. Filed as CI-GATE-007 (#933). The one commit that touches the file skips only
  the `yamllint` hook (`SKIP=yamllint`, so secret detection, ruff and mypy all still
  ran) and says so in its message.

## What the sequence actually proved

The retirement order was derived from **what triggers each surface**, not from runbook
discipline: Argo CD is the only actor that fires by itself (`prune` + `selfHeal`), so it
goes last and the ordering is enforced by merge order. That held. Every operator-triggered
surface was removed while the cluster still served, so no intermediate state was ever
reachable-and-broken:

| Step | Result |
|---|---|
| `tf-dns-apply` | `0 to add, 0 to change, 1 to destroy`; name gone, zone intact (`api.kubelab.live` still resolves) |
| Uptime Kuma monitor | 31 live monitors, 0 duplicates, no Ollama |
| Live `Middleware/api-key-ollama` | deleted; edge smoke after: api 200, auth 200 |
| ace2 teardown | `changed=4`, then `changed=0` on re-run; disk 30G -> 21G |

## Five things the implementation corrected in the spec

1. **AC1 was unsatisfiable, twice over.** `videollamada` in the Calendly URL contains the
   substring `ollama`, so a word-based check matches `common.yaml` and both generated
   ConfigMaps forever. And after a complete sweep every remaining match is either the
   teardown (which must name `/opt/ollama` and `11434` to remove them) or a comment
   explaining why a catalog is empty. Rewritten to assert the **identifiers that make the
   service reachable** rather than the word — a formulation that does not need a growing
   allowlist, because prose about a retirement never matches a live identifier. AC8 got
   the same treatment for the same reason.

2. **There was no backing Secret, and that inverts the significance of AC5.** The API key
   was inline in the Middleware spec (`keys: [${API_KEY}]`). The live object *was* the
   plaintext-at-rest surface, so deleting it is what took the prod key out of etcd — and
   the toolkit has no delete path, so that key survived the decision to retire the service
   until a human ran `kubectl delete`. Filed as TOOL-025 (#926).

3. **`ace2_services` was the Ollama role, not a role containing Ollama.** Every task
   deployed it or cleaned up the MinIO/runner stack it replaced. So the change is a role
   deletion, and — because Ansible is additive — the teardown had to move to whatever now
   owns the node. `dev_node` carries it, mirroring the two precedents already in the repo.

4. **The monitor was in the wrong place on two axes.** Listed after the container, which
   with `interval: 300` / `maxretries: 3` / a notification list lights a fuse to a real
   page; and filed under "requires ace2 powered on" when `monitors.json` deploys to RPi3,
   which is always-on. It was never ace2-gated and could have been done any day since #915.

5. **The first sweep pass missed four homepage references** — topology tables and the DNS
   diagram — which only surfaced because the generated `custom.js` still carried them after
   the source edit. Generated output is a second, independent read of the same sweep.

## Tickets opened during implementation

| Ticket | Why |
|---|---|
| MON-003 (#925) | `monitoring-apply` races its own deletes and reports success anyway; can silently duplicate every monitor |
| TOOL-025 (#926) | middleware secrets have an apply path and no delete path, so a plaintext key outlives the retirement |
| CI-GATE-007 (#933) | `common.yaml` failing yamllint on master, invisibly, because pre-commit only lints changed files |

## Promotion candidates

- [x] **Lesson for `docs/lessons.md`? Yes — and it is not about Ollama.** ✓ 2026-08-09,
      written as *"A check never observed failing is a claim in executable syntax, not a
      check"*. *A completeness check written against a name cannot distinguish a live
      reference from an explanation of its absence.* Both AC1 and AC8 failed this way, and
      the `videollamada` collision shows the failure can also be pure coincidence. The
      entry carries both halves — the name-vs-identifier fix, and the negative-control rule
      that generalises it — plus the four instances of the same shape found in one week
      (`tls: {}`, `hash-password`, CI-GATE-007, AC1/AC8), which is what promoted it from
      anecdote to rule.
- [x] ADR-worthy? **No** — confirmed at archive. ADR-028 and ADR-029 amendments cover it;
      the retirement is an instance of existing decisions, not a new one.
- [x] New pattern for `00_meta/patterns/`? **No new pattern — amended
      [[pattern-feature-list-as-primitive]] instead** ✓ 2026-08-09 (Manu's call). Two
      additions: a third anti-pattern (*a verification with no reachable failing state*,
      completing the set ANSIBLE-033 started) and a **negative-control precondition** — no
      feature may enter `verifying` until its command has been observed exiting non-zero
      once. Kept in the existing pattern rather than split into a verification-methodology
      sibling because the precondition binds to exactly one transition this pattern already
      owns (`in-progress → verifying`). **TOOL-016's amendment stays pending its own
      archive** — it is a different entry under the same question and belongs to that
      spec's closure, not this one.

## Archive checklist

- [x] `proposal.md` frontmatter set to `status: archived` ✓ 2026-08-09. The four
      agent-draft review markers on the narrative sections were cleared at the same time;
      Risks 2, 3 and 9 had been answered by Manu in-session and are recorded in place.
      Written without the literal bracketed token on purpose: the skill's archive lock
      greps for the marker name, and prose *about* a cleared marker is indistinguishable
      from a live one — the same defect as AC1, reproduced inside its own archive
- [x] Folder moved to `specs/archive/AI-007-ollama-retirement/` ✓ 2026-08-09
- [x] #905 closed with the PR link (ADR-018) ✓ 2026-08-09 — closed `completed`; its
      timeline cross-references all three PRs (#915, #919, #935) plus the three tickets
      filed during implementation, so no separate closing comment was needed
- [x] Promotions above executed ✓ 2026-08-09 — lesson written, ADR declined, pattern
      amended instead of duplicated
- [x] **Ping the peer session** — #910's prod half was deliberately blocked on this PR
      merging ✓ 2026-08-09, notified after the merge and the prune verification. That
      session has since closed, so the prod half returns to this track
