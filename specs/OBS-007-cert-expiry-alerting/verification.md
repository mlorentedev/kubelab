---
tags: [spec, verification, templates]
created: "2026-08-09"
---

# Verification - OBS-007-cert-expiry-alerting

## Evidence

Mapped 2026-10-10 for DEBT-019 (#2034), against master `cec4f424` plus this branch. The implementation landed in #958 (`d81f4288`); the runbook and the first verification record landed in #976 (`eceb2ce1`).

| AC | Status | Evidence |
|---|---|---|
| AC1: the provisioning API returns the rule and the Apprise contact point in staging and prod, and both survive a `rollout restart` | met | `tests/infra/test_grafana_alerting.py`, 9/9 passed in each env on 2026-10-10 (`make test-infra`). Prod's half was blocked by #951 until it closed; it now reads the API as the declared admin, so the run is a pass, not a skip. Restart survival: staging on 2026-08-10, 5/5 green after `rollout restart`. The rule and contact point come from the hash-suffixed `grafana-alerting` ConfigMap, never from Grafana's database. f1. |
| AC2: an induced ACME failure in staging drives the rule to Alerting and delivers a message within the evaluation interval plus the pending period | met | `make alert-smoke ENV=staging`, exit 0, twice on 2026-10-10 (transcript below). First measured by hand on 2026-08-10: firing at 05:03:00, Apprise `200` at 05:03:34. f2. |
| AC3: the rule does not fire on the `Testing certificate renew...` heartbeat | met by measurement, automation ticketed (#2195) | 2026-08-10: the alert expression was evaluated one minute after a known heartbeat, so the heartbeat was inside the `[10m]` range. Heartbeats in the window: 1. Result: empty. The rule's shape requires an error indicator, so `Starting provider *acme.Provider` is excluded too (`tests/test_alert_smoke.py::TestLogParsing` pins the same shape). No command repeats the measurement: f3 keeps its failing sentinel and is `partial`, and #2195 (OBS-033) builds the check. |
| AC4: the payload names the affected domain and the environment | met | Domain: `make alert-smoke` now requires the firing instance's `domain` label to equal the induced host. Live on 2026-10-10: `firing instance named obs007-induced-failure.kubelab.local: ok`. Environment: `tests/test_grafana_alerting_render.py::TestRenderedPayloadNamesDomainAndEnvironment` asserts that the rendered body prints `{{ .Labels.domain }}` and `{{ .ExternalURL }}`, and that each overlay renders its own `GF_SERVER_ROOT_URL`. Each assertion went red against its mutant (`make mutate`, below). The operator saw the delivered Telegram body on 2026-08-10. The smoke reads Grafana, not Telegram. f4. |
| AC5: teardown returns the rule to Normal and a resolved notification is delivered | met | `make alert-smoke` reports "rule cleared after teardown" and "resolved notification delivered" as separate stages, both `ok` on both 2026-10-10 runs. First measured 2026-08-10: route deleted at 05:04, `inactive` at 05:18:08, resolved delivery at 05:18:30. f5. |
| AC6: the render gives staging the `log` tier and prod the `page` tier | met | `tests/test_grafana_alerting_render.py::TestRenderedAlertTier`, ticked 2026-08-10, under `make test` (f6). Amended during implementation; see `proposal.md`. |

### `make alert-smoke` had been broken since Grafana went OIDC-only

The first run of this audit failed. Grafana has been OIDC-only since 2026-09-24, so the smoke's anonymous read of `/api/prometheus/grafana/api/v1/rules` answered 401. `rule_state` read the HTML as `unreadable`, and the smoke induced the failure anyway, then timed out waiting for a state it could not see. Its teardown still ran: the probe route read NotFound afterwards.

Fixed in `c8a29939`. The read now authenticates inside the pod with the admin the pod already holds (`GF_SECURITY_ADMIN_USER`/`_PASSWORD` from the `grafana-admin` Secret), so no credential crosses kubectl's argv or this process. An unreadable state now aborts before anything is induced. Both behaviors are in `TestRuleStateRead`, red first.

### Transcript: the second run, 2026-10-10, final code

```
[INFO] Baseline: rule=inactive  apprise deliveries=13
[INFO] Inducing an ACME failure: obs007-induced-failure.kubelab.local
[SUCCESS]   rule to fire: observed
[SUCCESS]   the firing notification: observed
[INFO] Removing the induced failure
[SUCCESS]   rule to clear: observed
[SUCCESS]   the resolved notification: observed
[INFO]   rule fired on a real failure: ok
[INFO]   firing instance named obs007-induced-failure.kubelab.local: ok
[INFO]   firing notification delivered: ok
[INFO]   rule cleared after teardown: ok
[INFO]   resolved notification delivered: ok
[SUCCESS] alert-smoke passed — confirm both messages landed in Telegram
exit 0
```

The first run of the day (fix `c8a29939`, before the domain stage) passed the same four stages. Afterwards `obs007-induced-failure` read NotFound.

### Mutations, each from a clean commit with `make mutate`

| File | Mutant | Test | Result |
|---|---|---|---|
| `grafana-alerting/templates.yaml` | `Source: {{ .ExternalURL }}` -> `Source: grafana` | `TestRenderedPayloadNamesDomainAndEnvironment` | RED |
| `grafana-alerting/templates.yaml` | `Domain: {{ .Labels.domain }}` -> `Domain: unknown` | same | RED |
| `overlays/prod/patches.yaml` | prod `GF_SERVER_ROOT_URL` -> the staging URL | same | RED |
| `toolkit/features/alert_smoke.py` | `named = PROBE_HOST in firing_domains(...)` -> `named = True` | `TestTheAlertNamesTheInducedDomain` | RED |

## Test status

- `make test-infra ENV=prod`: 71 passed, 1 skipped, exit 0 (2026-10-10).
- `make test-infra ENV=staging`: 69 passed, 1 skipped, 2 failed, exit 2 (2026-10-10). The alerting module passed 9/9. Both failures are unrelated and ticketed:
  - `test_pods_running_in_namespace`: three Failed `r2-backup-watcher` pods from a stale staging Secret, fixed the same day. The pods stay until three more failures rotate them out, because the CronJob sets no TTL. #2194, lesson-554.
  - `test_every_route_references_rate_limit`: the orphaned staging `gitea` IngressRoute. #2061.
- `make test`: see the run recorded in `features.json` f6.
- `toolkit/features/alert_smoke.py`: `run_alert_smoke` is B (9) and `firing_domains` is B (9) (radon). mypy and ruff are clean.

## Decisions made during implementation

- **AC4 is checked in Grafana, not in Telegram.** The smoke reads the firing instance's labels, which is what the body template prints. Reading Telegram back would need a bot credential in the smoke for no extra coverage of this repo's code. The environment half is static per overlay, so a render test owns it.
- **AC3 archives on its 2026-08-10 measurement**, which was a direct evaluation at an instant with a heartbeat in range, not a wait. The repeatable check is new code outside this spec's shape, so it is #2195 rather than an unreviewed addition here.

## Review dispositions

First archive review (agy/gemini-3.1-pro-high, 2026-10-10, FAIL, `reviewed_sha` 4a7d5e96):

| Finding | Disposition | Evidence |
|---|---|---|
| Blocker, THEORETICAL: the `[10m]` window at a 5m interval lets a single failure line satisfy `for: 5m`, which contradicts the rule's "first blip" comment. Proposed fix: `[5m]`, plus a test that one failure does not page. | **Comment fixed, code fix declined.** The contradiction was real, and the wrong half was the `for:` comment, not the window. The `interval` comment already said a single failure satisfies `for: 5m` by design. The `for:` comment now says the same and gives the measurement. | Traefik writes one line per failed attempt and does not retry within the window. Three induced failures on staging wrote one line each (2026-10-10 12:24, 12:48 and 13:15 UTC, read from Loki), while the route stayed up for more than ten minutes. With `[5m]` a lone line is in one evaluation's window only, so `for: 5m` could never hold: a real failure would never page, and `make alert-smoke` would fail. The proposed test would assert the opposite of what was measured. |

Second archive review (agy/gemini-3.1-pro-high, 2026-10-10, PASS WITH GAPS, `reviewed_sha` 8b62b208):

| Finding | Disposition | Evidence |
|---|---|---|
| Minor, THEORETICAL: `deliveries()` counts over `kubectl logs --tail=300`, a sliding window, so once Apprise has logged more than 300 lines a new delivery can leave the count flat and the smoke fails on a delivered notification. | **Ticketed as #2197 (OBS-034).** Real, latent, and it fails closed: the smoke never passes on a missed delivery. Staging Apprise holds 92 lines and 15 deliveries (2026-10-10), so the tail is not saturated. The code dates from #976, and changing the smoke after this review would need another live run and another review for a failure that cannot occur yet. | `toolkit/features/alert_smoke.py`, `deliveries()`. |

Side effect: `rules.yaml` feeds the hashed `grafana-alerting` ConfigMap, so the comment-only change rolls Grafana in both environments on merge.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons.md`? no: the smoke's 401 is recorded above, and the general rule behind it (a check nobody runs rots silently) is already MON-001's. lesson-554 lands in this PR, but it covers a staging finding from the audit, not this spec.
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: the tier split rests on ADR-044 and ADR-028; this spec adds no decision of its own.
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: the smoke shape (induce, observe, tear down in `finally`) already exists as `notify_smoke.py` in this repo, and no second project needs it.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/OBS-007-cert-expiry-alerting/` -> `specs/archive/OBS-007-cert-expiry-alerting/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
