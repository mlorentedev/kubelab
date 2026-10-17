---
id: lesson-307-a-perfect-evidence-chain-measured-against-a-s
type: lesson
status: active
created: "2026-08-09"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# A perfect evidence chain measured against a stale baseline (SEC-001)

**Context:** Two agent sessions worked this repo in parallel for an afternoon, merging roughly every twenty minutes. Picking up the remaining third of #910 — an orphaned `users_admin_password_hash` in `prod.enc.yaml` — I did what the previous session's lessons prescribe: took a positive control *before* mutating anything.

```
$ make secrets-show KEY=...users_admin_password_hash SECRETS_ENV=prod
$argon2id$v=19$m=65536,t=3,p=4$GCgsohmhQlm9Mi/...
```

The key was there. I removed it with `toolkit secrets unset`, then verified without trusting the tool's `[SUCCESS]`: the key gone, the operator hash byte-identical, `testuser` intact, audit unchanged at 43/43, and an encrypted diff of exactly one content line plus SOPS metadata. Six independent checks, all green, all genuinely run.

**Problem:** The work was already done. #936 had removed that key and merged at `23:54:56Z` — which is what closed #910 one second later. My PR was a duplicate of a fix that had landed hours before I looked.

I had run `git fetch` once, at session start, when `origin/master` was `d31c506`. #936 merged twelve minutes after that. I created the branch from my **stale local ref**, and every subsequent measurement read a working tree that predated the fix. The hash was real. The file was real. Both belonged to a commit that was no longer master.

What makes this worth recording is that *the evidence chain cannot detect it*. Every check was internally consistent, because they were all consistent with the same wrong baseline. Not one line of that output names the commit it is reading — `secrets-show` prints a hash, `secrets audit` prints a ratio, `git diff` prints a diff against whatever `origin/master` happens to point at locally. A positive control proves a key exists *somewhere*; it says nothing about whether that somewhere is current. The discipline that was supposed to protect me produced six pieces of corroborating evidence for a false conclusion, and the corroboration is what made it convincing.

The parallel session hit the sibling failure the same afternoon: a loop testing whether three branches still merged cleanly, where one branch's `git rev-parse` failed, so `git merge-tree` never ran, so the grep found no conflict markers in the error text — and the branch was reported **clean**. A check that passed because it could not run. The two hazards compound: a stale ref gives you the wrong answer, and a silently-skipping check stops you noticing.

**Solution:** `git fetch` immediately before branching, and take the baseline *after* the fetch. #939 closed as a duplicate; the incorrect comment on #910 corrected in place.

**Rule:** **A session-start fetch expires the moment anyone else merges.** In any multi-agent or multi-session day, treat your local `origin/*` refs as a cache with a lifetime of minutes, and re-validate immediately before every branch, baseline reading, or "is this still needed?" judgement.

Two corollaries that generalise past git:

- **A positive control establishes that a state exists, not that it is current.** Where the answer depends on a baseline, the baseline is part of what must be verified — say which commit, revision or generation the reading came from, or the reading is unfalsifiable.
- **Distinguish a check that ran and passed from a check that never ran.** Any composite command where an early step can fail must report `CANNOT CHECK` distinctly from `OK`; a grep over an error message finds no matches and looks exactly like success.

**Tags:** `#git` `#stale-ref` `#parallel-sessions` `#verification` `#positive-control` `#silent-failure` `#false-positive` `#sops` `#sec-001` `#gotcha`

---
