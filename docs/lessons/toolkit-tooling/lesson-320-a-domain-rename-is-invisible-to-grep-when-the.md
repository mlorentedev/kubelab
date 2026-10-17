---
id: lesson-320-a-domain-rename-is-invisible-to-grep-when-the
type: lesson
status: active
created: "2026-08-12"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling]
---

# A domain rename is invisible to `grep` when the reference lives in a template string inside a Python generator

**Context:** An independent adversarial review of OPS-022 (#969) — requested from a separate session/subagent specifically because this session implemented the change and self-review is forbidden by the skill's own guardrail — found that the rename shipped without regenerating `infra/k8s/base/services/homepage-config/custom.js`, the committed output of `toolkit/scripts/sync_homepage_config.py`.

**Problem:** The PR's own verification swept `infra/k8s/`, `infra/terraform/`, `tests/`, and `docs/runbooks/` for the old name and found nothing — because the live reference didn't live in any of those. `sync_homepage_config.py`'s Pi-hole entry in its `shared` service list hardcoded `f"https://pihole.staging.{base}"`, inconsistent with every sibling entry in the same list (Argo CD, Headscale, Uptime Kuma all use `{base}` alone, no env prefix) — a manual insertion that predated this session and nobody had reason to touch until now. The generated `custom.js` is a committed artifact, not rebuilt by CI or by `make deploy-k8s`; it only changes when someone remembers to run `make sync-homepage`. Worse than stale text: `custom.js`'s `checkHealth()` does a live client-side `fetch(url, {mode: "no-cors"})` on every dashboard load, and `no-cors` resolves `.then()` (green) for *any* reachable response, including the staging catch-all's 404 that this exact rename intentionally introduced (AC5) — so the dashboard would have shown a false "up" status and a dead link for precisely the service being renamed, recurring the exact "SSOT keeps lying, nothing ever fails to tell us" failure this spec's own "Why" section named as its reason for existing.

**Solution:** Fixed the hardcoded string (now matches its own list's established pattern), the DNS-map table, and the mermaid diagram edge in the same generator function; regenerated `custom.js` via `make sync-homepage`; added 4 named regression tests to `tests/test_sync_homepage_config.py`, each verified to fail against the pre-fix code before being confirmed green.

**Rule:**
- **A rename's blast radius includes every place a name is *generated*, not only every place it's *declared*.** `infra/k8s/`, Terraform, and the test suite were all correctly swept; a Python script whose output is a committed artifact was not, because it doesn't live in any of the directories a routing change "obviously" touches.
- **Grepping the diff finds edited files, not files that should have been edited.** The bug wasn't a wrong string in the changed files — it was a right string that stayed wrong in an unchanged one. A rename's completeness check needs to search the *repository* for the old name, not just review the PR's own diff.
- **A generated file that's committed instead of built-on-demand can silently outlive the source of truth it was generated from.** `custom.js` had no CI regeneration step and no drift check — the same defect shape as this session's other two findings (yamllint's coverage claim, the Argo CD selfHeal drift): a description of intent, once written down, is trusted long after the reality it described has changed.
- **Requesting review from a session that never implemented the change is what caught this.** The implementing session's own verification pass (5/5 stated acceptance criteria, genuinely passing) had no reason to look at a file none of its own acceptance criteria named.

**Tags:** `#homepage` `#generated-config` `#adversarial-review` `#silent-failure` `#dns-rename` `#ops-022` `#gotcha`
