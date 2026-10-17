---
id: lesson-313-a-stage-agnostic-pre-commit-hook-silently-red
type: lesson
status: active
created: "2026-08-12"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation]
---

# A stage-agnostic pre-commit hook silently redundant since hooks went machine-wide

**Context:** Noticed directly in this session's own commit output: the pre-commit hook block (trim-whitespace, gitleaks, the local env-file check, etc.) printed twice per `git commit`, sometimes three times. Traced instead of dismissed as cosmetic.

**Problem:** A pre-commit hook that declares no `stages:` of its own defaults to running at **every** stage. That was harmless while `.git/hooks/` only held what `pre-commit install` wrote per-repo — a stage-agnostic hook still only fired at commit time, because nothing else invoked it. Once hooks are dispatched machine-wide via `core.hooksPath` (shared across every repo/worktree on the machine), every git hook type — `pre-commit`, `prepare-commit-msg`, `commit-msg`, `pre-push` — reaches `pre-commit hook-impl`, and each stage-agnostic hook in `.pre-commit-config.yaml` runs once per hook type that fires: 2-3x per commit, plus once per checkout, plus once per push. Confirmed directly: invoking each dispatcher against a repo whose only hook was `gitleaks` ran `gitleaks` on `pre-commit`, `prepare-commit-msg`, and `commit-msg` alike.

**Solution:** One line, `default_stages: [pre-commit]`, at the top level of `.pre-commit-config.yaml` (DX-001, #895). A hook that genuinely needs another stage still declares its own `stages:`, which overrides the default — nothing else changes. Verified before/after in this repo's own commits: the hook block went from running 2-3 times to once. The one deliberate tradeoff (gitleaks' pre-push re-check, the safety net for a `--no-verify` commit) was confirmed with the maintainer before applying — accepted, since the real gate for that case is CI, not a local hook `--no-verify` already bypasses for everything else.

**Rule:**
- **A shared hook dispatcher (`core.hooksPath` set once, machine-wide) changes what "no `stages:`" means.** It stops being "runs once, whenever commit happens" and starts being "runs at every hook type this machine's git ever fires" — the migration from per-repo to machine-wide hooks silently multiplied every stage-agnostic hook's invocation count.
- **Redundant-but-correct output is easy to stop noticing.** The duplicated block had been printing in commit output for long enough to go unremarked in at least one other repo (`dotfiles`) before this session traced it here — results were never wrong, just repeated, which is exactly the kind of noise that trains a reader to stop reading.
- **Tightening a security-relevant default (dropping the pre-push net) is a decision to surface, not infer.** The technical fix and the security tradeoff were separable; only the tradeoff needed a human call.

**Tags:** `#pre-commit` `#hooks-path` `#dx-001` `#redundant-checks` `#security-tradeoff` `#gotcha`
