---
id: lesson-292-a-sops-subprocess-with-a-bare-os-environ-pass
type: lesson
status: active
created: "2026-07-08"
owner: manu
tags: [kubelab, lesson, secrets, sops, age, subprocess, ci, ast-guard, tool-017, gotcha]
---

# A `sops` subprocess with a bare `os.environ` passes in your shell and returns empty in CI (TOOL-017)

**Context:** TOOL-017 (#828) — wrapping every `sops` subprocess in the toolkit with `age_key_env()`, a helper that injects `SOPS_AGE_KEY_FILE` into the child process env.

**Problem:** A `sops` call launched with a **bare `os.environ`** (no explicit age key) works fine in an interactive shell that already `export`ed `SOPS_AGE_KEY_FILE` — so the unit suite and every local run go green. But in a **fresh shell or a CI runner** without that ambient export, `sops` can't locate the key and, depending on the code path, either errors or hands back an **empty decrypt** — silently yielding empty secret values. The bug is invisible precisely in the environment a developer would test in, and only bites in automation.

**Solution:** Route *every* sops invocation through `age_key_env()` (five call sites: `secrets_manager` show/set/unset, `configuration` batch-decrypt, `credentials` read-existing) so the key file is injected regardless of the ambient shell. Then add an **AST-based regression guard** that scans `toolkit/` for any `subprocess` call to `sops` using a bare `os.environ` and fails the suite — the invariant is enforced structurally, not by reviewer memory.

**Rule:** A subprocess that depends on an env var you *happen* to have exported is a latent bug — the passing local test proves nothing about a clean shell. Inject the dependency explicitly at every call site and enforce it with an AST scan (not a convention the next call site can quietly skip). "Works in my shell" ≠ "works in CI" — same failure class as the TOOL-020 encoding lesson above.

**Tags:** `#secrets` `#sops` `#age` `#subprocess` `#ci` `#ast-guard` `#tool-017` `#gotcha`
