---
id: lesson-022-silent-success-anti-pattern-in-regex-based-mu
type: lesson
status: active
created: "2026-05-26"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, anti-pattern, tooling, silent-failure, oidc-sync-001]
---

# Silent-success anti-pattern in regex-based mutation tooling

**Context**: `toolkit/scripts/sync_oidc_hashes.py` uses a regex to find/replace `client_secret:` lines in Kubernetes YAML files. When PR #225 moved the OIDC clients block from `patches.yaml` to a new `authelia-config/configuration.yml`, the script's `FILE_PATHS` dict was not updated. The regex now matches **nothing** in the targeted file. But the script's caller compares `if new_content != content:` — when the regex misses entirely, `new_content == content` (the function returns the input unchanged) and the script prints `"OK: gitea hash already current in patches.yaml"`. Indistinguishable from "no change needed".

**Problem**: The "no change needed" path and the "I could not find anything to change" path collapse into the same observable behavior. The operator sees green, assumes sync was successful, and moves on. Drift accumulates invisibly. In this case it caused a multi-hour debug session because the symptom (`invalid_client` from Gitea OIDC) was 3 hops removed from the cause (script silently no-op'd → SOPS plaintext didn't propagate → Gitea stored a stale plaintext → token verification failed). The same shape applies to any mutation tool that uses pattern-matching without explicit assertion of "I found the target".

**Solution**: Tracked as OIDC-SYNC-001 in `11-tasks.md`. Fix has two parts: (a) update `FILE_PATHS` to point to the new authelia-config files, (b) raise `RuntimeError` if `update_client_secret()`'s regex does not match the input — never silently return unchanged content. Also added a regression test that asserts `FILE_PATHS` values exist and contain the expected `client_secret:` pattern, so a future refactor that moves the file will fail fast at test time, not at production debug time.

**Rule**: For any tool that does pattern-based mutation (regex find-replace, AST modification, YAML key edits), the "I could not find the target" path MUST be a hard failure with a distinct exit code, never the same code path as "no change needed". Explicit assertion: `assert match, f"Pattern {pattern} not found in {file_path}"`. The cost is one line; the value is that path drift caused by refactors elsewhere in the codebase cannot silently break the tool. Bonus: when the tool's output is "X updated" vs "FAILED: pattern not found", the operator gets actionable signal immediately instead of false reassurance.

**Tags**: `#anti-pattern` `#tooling` `#silent-failure` `#oidc-sync-001`
