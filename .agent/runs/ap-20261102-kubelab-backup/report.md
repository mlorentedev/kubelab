# Run report: ap-20261102-kubelab-backup

Ended: 2026-11-02, before expiry. Reason: queue-exhausted (no remaining item eligible).

| Item | Outcome |
|---|---|
| #2917 | Landed, #2959 |
| #2754 | Landed, #2964 |
| #1042 | Landed, #2973 |
| #1908 | 25 local runs, 0 failures; commented, left open |
| #2955, #1774 | Parked, Blocked on the board (platform.json out of scope; Pollex count decision) |
| #1222 | Not reproduced, left |
| #942 | Open design decisions, not attempted |

Also landed before the run: #2935 (CI SOPS recipient retired).

Disclosures: #2973's last commit (wording) has PR-Agent's review only. A force-push was denied; master was merged instead.

Not authorized and not done: deleting `SOPS_AGE_KEY`, deleting `kubelab-backups`, revoking tokens, #1920 AC3 and archive.
