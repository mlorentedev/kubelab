# Ledger: ap-20261018-kubelab-specs

| time (UTC) | item | event |
|---|---|---|
| 08:35 | run | armed, envelope 4a4f8d30, wake-lock caffeinate -i -t 30000 |
| 08:40 | peers | fix-tasks-vikunja-30, fix-sso-signout-1813-fb, kubelab-c1: none own the 8 specs |
| 08:55 | TOOL-035 | evidence recorded, draft tags resolved, lesson-598 (597 taken on fix/1957), commit aba5d89c |
| 09:05 | TOOL-035 | follow-up #2485 (ts-bridge cutover). Self-correction: first titled TOOL-089, which collides with #1940; renamed without an id |
| 09:05 | TOOL-035 | `dotf spec review` launched (pool, foreground, 30m) |
| 09:20 | TOOL-035 | review PASS-WITH-GAPS (nan/glm5.3-flash); finding 3 ticketed #2488; dispositions in verification.md; archived; PR #2489 opened and marked ready |
| 09:30 | APP-CONFIG-016 | 96 tests passed; `make n8n-probe ENV=prod` exit 0, merge probe ok (log n8n-probe-prod.log, scanned: 0 secret-like lines); features.json passing; review launched |
| 09:35 | DT-004 | abandoned (obsolete): verification note, ADR-035 row, CLAUDE.md anchor; review launched |
| 10:40 | CONSOLE-002 | AC4 residue ticketed #2494; Abandoned section + ADR-050 status note (fbb35c75); review launched |
| 10:48 | TOOL-035 | #2489 was DIRTY (lessons index counts); rebased, recounted, force-pushed e6e227ae |
| 10:50 | DT-004 | review PASS-WITH-GAPS (nan/deepseek-v4-flash): 5 applied, 1 declined; ADR-034 row marked; archived --abandoned; PR #2496 |
| 10:52 | APP-CONFIG-016 | review PASS (nan/glm5.3-flash, 3 mutations red); dispositions; archived; PR #2497 |
| 10:55 | TOOL-001 | audit exits 0 on a missing key and on a decrypt failure (read in code): ticket #2499; verification written; review launched |
| 10:57 | OPS-016 | live `make monitoring-apply CHECK=1`: 0/0/0 over 36 (monitoring-check.log); rpi3 boot unit lacks --force-recreate: ticket #2500; ACs amended; review launched |
| 10:58 | CONSOLE-002 | review FAIL (features f4 still said Ollama default; tasks.md read as live): fixed; go-selector guard blind spot #2501; prod `secrets audit` 121/121 (secrets-audit-prod.log, key paths only); re-review launched |
| 10:59 | finding | prod audit exits 1 on orphan `apps.services.core.vikunja.reconciler_api_token`; peer PR #2464 registers it (on master as 99c65d6b). Expiries: github_migration_token 10-27, r2_token_minter 11-03, dev_node.github_token 11-06, n8n analytics_token |
| 11:00 | TOOL-009 | AC5 amended to iris#30 ownership; 34 tests passed; review launched |
| 11:03 | AUTH-004 | `make auth-review ENV=prod` all OK (auth-review-prod.log); tickets #2503 (AC7 drill), #2504 (AC5 Authelia refusal), #2505 (AC2 operator refusal); ACs amended; review launched. break-glass.md untouched (peer #2491 holds it) |
| 11:05 | OPS-016 | review FAIL (no features.json; delete guard untested by mutation): features.json added, #2506 filed, #2501 extended; re-review launched |
| 11:07 | TOOL-001 | review PASS (nan/deepseek-v4-flash): 5 applied, 1 no-action; lesson-163 update; archived; PR #2507 |
| 11:08 | CI | GitHub-hosted runners queued across all PRs; PR-Agent pending; CodeRabbit and Codex rate limited |
| 11:11 | AUTH-004 | review PASS WITH GAPS (agy/gemini-3.8-flash-high): 3 Majors carried by #2503-#2505, 2 Minors declined (closing checklist; mypy gate covers toolkit/ only), 1 applied by archive; archived; PR #2509 (pushed fast-forward after a force push was refused) |
| 11:15 | CONSOLE-002 | re-review PASS-WITH-GAPS: launcher base -> dotfiles#1727, #2501 corrected by comment, item 2 reworded, route boxes ticked by hand, live Vikunja claim passed to #2443; archived --abandoned; PR #2510 |
| 11:35 | TOOL-009 | review PASS-WITH-GAPS: attribution corrected in verification.md, T9 kept blocked on iris#30, knowledge#118 already closed (checklist -> comment); archived; spec-gate test hardcodes TOOL-009 as the cross-repo spec, tests/ frozen -> parked, draft PR #2515 with options A (expect set()) / B (keep active) |
