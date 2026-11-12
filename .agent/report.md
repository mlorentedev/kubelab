# Unattended run report: 2026-11-12

- **Armed:** 2026-11-12T06:59:46Z, envelope `785275e2`. **Expires:** 18:59:46Z (the owner asked for 16h; the cap is 12h).
- **Objective:** carry IDP-053 forward (land what the agent may merge, leave owner-merge slices triaged and ready), and work the resume follow-ups of the daily command.
- **Status:** ended at 17:40Z, with the owner back. The resume line is drained: RES-113 is archived (#798) and #777 is closed. Four kubelab PRs wait for the owner's merge.

## Landed

| Repo | PR | What | Closes |
|---|---|---|---|
| kubelab | #3305 (`db6672c3`) | `pull_secret_mappings` refuses an uncatalogued pull secret | #3297 |
| kubelab | #3335 (`1a4eaca`) | ADR-073 D13 decided (B); one condition left before acceptance | |
| kubelab | #3356 (`c34c3c4`) | The pull credential is exchanged once per release proof | #3287 |
| kubelab | #3370 (`df6bddd`) | `verify-product` refuses a lane the contract does not declare | #3251 |
| kubelab | #3363 (`b5cf887`) | A catalog secret is read from its flattened environment variable first, and the source is logged by name | part of #3286 |
| resume | #779 | `resume daily` | |
| resume | #786 (`4d97dfa9`) | `scan` exits non-zero when no board was read | #778 |
| resume | #784 (`aa815ea7`) | A pre-filtered day is not a failed run; a step exception is reported by type only | #783 |
| resume | #792 (`bcc83dde`) | scan and evaluate redact the text of exceptions they handle; secret-shaped fixtures built at runtime, two exact `.gitleaksignore` fingerprints | #789 |
| resume | #787 (`ed2e1c58`) | `daily` logs the attempt's start, so a retried Job's digest can be recovered by hand | #782 |
| resume | #791 (`b3476552`) | A posting that fails to fetch no longer turns every run red; `stalled` means the evaluator failed and nothing was scored | #788 |
| resume | #796 (`fb83749d`) | One posting whose evaluation always fails no longer turns every run red (owner's rule) | #794 |
| resume | #797 (`5dbb898a`) | The `daily: started` line no longer wraps | #795 |
| resume | #798 (`ba2c3d1a`) | Archive RES-113 with its closing review (third independent round: PASS-WITH-GAPS) | #777 |

## Ready PRs (owner merges)

| PR | Slice | Head | Notes |
|---|---|---|---|
| #3368 | S5c: read-only Gitea repo token | `49d14dac` | Green, triaged. After merge: mint `repo_reader`, set the GitHub Actions secret. |
| #3372 | S2b: `imagePullSecrets` for a private Deployment | `ce3b1062` | Green, triaged. No existing Deployment changes. |
| #3373 | S2c: Gitea registry pull token and `registry-check` | `8e0e2d0b` | Green, triaged (pr-agent and CodeRabbit: 5 applied, 2 declined). After merge: mint, then run `registry-check` deployed. |
| #3339 | #3288: one verdict for a Gitea outage | `153cf6c0` | Triaged. |

#3368 and #3373 conflict additively; the second to land keeps both entries and runs `make sync-platform-json`.

## Owner actions

1. Merge #3368, #3372, #3373 (and #3339) after reading them.
2. After S2c and S5c: mint both tokens; set the two GitHub Actions secrets.
3. #3286's workflow part is blocked on S2c: the variable to export is the Gitea registry pull token's, not `GHCR_PULL_TOKEN` (no private product is on GHCR, and no such SOPS key exists). An attempt to set `GHCR_PULL_TOKEN` created an empty repo secret, deleted at once; no value existed to expose.
4. #3289 waits on S5c's mint.
5. RES-113: the owner set the stall rule on 2026-11-12 (#794): a provider failure, or answer failures on 2 or more postings, with nothing scored. The accepted gap is that poisoned postings can accumulate until #790 lands, so #790 should be next on resume.

## Tickets filed

- resume #785: the redacting filter misses tracebacks and query-string keys.
- resume #788: a posting that fails to fetch every day turned every run red (closed by #791).
- resume #789: scan and evaluate print the text of exceptions they handle.
- resume #790: a posting that can never be fetched is retried forever.
- resume #793: CI's gitleaks scans every ref, so one branch's leak fails every PR.
- resume #794: one posting whose evaluation always fails turns every run red (RES-113 re-review, FAIL; rule decided by the owner).
- resume #795: the `daily: started` line wraps at a narrow terminal.

## Out of the envelope

- S6b (receiver workflow) is in a workflow file the envelope does not list.
- The staging load test owned by another session runs until about 18:00Z; no staging deploy was made.

## Noted

- The CI watcher counted superseded cancelled runs as failures, which led to unneeded reruns. Fixed in the watcher (latest run per check name).
- A builder twice reverted uncommitted work with `git checkout --` while reverting a mutation. Nothing was lost. It now checks for a clean tree before each mutation batch.
