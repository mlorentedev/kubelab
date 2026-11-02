# Run report: ap-20261102-kubelab-delivery

- Armed: 2026-11-02T05:55Z, envelope `f58c2cbe`. Window until 17:55Z.
- Ended: 2026-11-02T11:30Z. Reason: `queue-empty` (all 5 items worked or parked).
- Merges under the standing grant: #2974, #2978, #2982 (tests/specs only, each with CI green, `## Review triage`
  posted and `dotf pr triage-queue --pr N` exit 0). Nothing under `.github/`, `harness/` or `infra/` was written.

## Items

| # | Item | Outcome |
|---|---|---|
| 1 | #1619 DELIVERY-004 | Adversarial review done by a non-implementer (`specs/.../review.md`, PASS-WITH-GAPS). Major 1 and two untested guards fixed in #2982 (merged). Major 2 filed as #2983, setup-python pin as #2984. Evidence 2/3 logged on #1619. |
| 2 | #1694 CI-004 | parked: the publish step is inline in `review-attestation.yml` (frozen). Options on the issue. Board: Blocked. |
| 3 | #1691 CI-003 | #2974 merged, closes it. |
| 4 | #837 CI-GATE-004 | #2978 merged, closes it. |
| 5 | #1737 DELIVERY-008 | parked: services `init()` panics without SITE_TITLE in CI. Options on the issue. Board: Blocked. |

## For the operator

1. Third evidence case: deploy-merge still judges #2966, #2967 and #2968 `merge` at their heads (run 41434622397).
   Merge one by hand (#2967 web, or #2968 api), then check its deploy-verify. #2966 and #2968 both bump api from
   sha-80171ff, so merging one makes the other conflict, and the judge should then skip it: a free negative case.
2. Answer on #1619: is #2983 (`unstable` stops enforcing Drift; no image-to-app binding) accepted debt under option B,
   or a blocker for PR 4?
3. #2984 touches `.github/`; it is yours.
4. Parked #1694 and #1737 each carry two options on the issue.

## Not covered

- CodeRabbit and Codex were out of quota all night; pr-agent was the only reviewer (queued ~45 min per PR).
