# Ledger, run 2026-10-16-ai012 (armed 08:15Z, expires 18:15Z)

| time (UTC) | item | state | evidence |
|---|---|---|---|
| 08:15 | tickets #2338-#2342 created | done | gh issue list |
| 08:22 | #2340 AC9 managed skills | draft PR #2347, live on ace2 (changed=6, then 0) | verification.md; AC10 docs mirror still open |
| 08:35 | #2339 Grafana token route | parked(scope-violation) | needs infra/k8s/overlays/prod/patches.yaml, frozen; ticket commented (no `blocked` label exists in the repo) |
| 09:05 | #2341 persona | draft PR #2350, no live provision (held for operator); dry-run failed=0 | vault profile added 540990c3 |
| 10:05 | #2347 triage | PR-Agent 2 findings applied; live changed=2 then 0; waiting CI on new head | triage comment posted |
| 10:15 | #2342 curator 6a | draft PR #2352 (analyzer + weekly host unit); live waits for #2347 merge (branch does not carry skills) | fetch finding: category folders |
| 10:30 | Slack read probe | bot token reads all 4 alert channels from the gateway (allow-list does not govern a script read) | verification.md in PR #2354 |
| 10:50 | #2347 conflict | master moved (lesson-579 collision, platform.json): merged master, renumbered mine to 580, 157 tests pass, pushed ed2c9dc4; CI rerunning | |
| 11:00 | #2338 8a | draft PR #2354 (channels SSOT, alert-activity.py, catalog entry); never merged unattended (prod.enc.yaml, secrets_manager.py) | 19 tests |
| 11:35 | #2347 merged | `07f1ed3b` squash, --match-head-commit ed2c9dc4; Tests, review, attestation, drift green; triage addendum posted; #2340 stays open for AC10 | |
| 11:50 | #2342 6a live | master merged into #2352, provision changed=4 then 0; unit Result=success; candidates.json 1962 files / 8 candidates; lesson-581; PR ready | verification.md |
| 11:55 | #2350 | master merged (conflicts: runbook, defaults; kept both), 121 tests pass, still draft, no live provision | |
| 12:20 | #2342 6a review rounds | PR-Agent found 8 over 3 heads (partial fetch, dead guard, provenance, stale read-back applied; 4 declined with evidence); live re-provision changed=1 then 0 | PR #2352 triage comments |
| 12:40 | #2342 6b | judge input + emitter + 2 jobs written on feat/hermes-curator-judge (stacked on 6a; rebase after 6a merges); 42 tests, 3 mutations red; no provision yet | decisions: emitter is a gateway script job (data/ is 0700 to a subuid), evidence from candidates.json not the record |
| 12:55 | #2342 6b live | judge run ok, emitter wrote 4 drafts in `proposals/`, vault sync committed them (`a07a75db`); second emitter run silent | verification.md in PR #2355 |
| 13:10 | #2352 CI fix | Tests failed on the import ordering (curator before the bridge); fixed, and the dropped-repository cache finding applied with a mutation-proved test; triage comment 4th pass | 21 curator tests; full suite 5444 passed |
| 13:35 | #2352 merged | `1d5b2e43` squash, --match-head-commit b0622b98; all checks green, CLEAN, no peer on agent_stack | |
| 13:55 | #2355 opened | 6b rebased on master (duplicate curator import from the merge removed), lesson-582, runbook, verification; provision changed=1, 0, 0; PR ready, CI and review pending | size over max_loc 400 with tests, disclosed in the PR |
