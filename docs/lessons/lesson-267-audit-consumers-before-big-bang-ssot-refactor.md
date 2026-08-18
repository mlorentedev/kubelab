---
id: lesson-267-audit-consumers-before-big-bang-ssot-refactor
type: lesson
status: active
created: "2026-05-23"
owner: manu
tags: [kubelab, lesson, ssot, refactor, process, patterns]
---

# Audit consumers BEFORE big-bang SSOT refactors — "move 3 values" hid 21 references

**Context:** SEC-K8S-001 cleanup surfaced that 3 non-secret values (`email_user`, `email_from`, `beehiiv_pub_id`) live in SOPS but leak into ConfigMaps via the merge. Initial estimate was "5 LOC, move them to common.yaml, done". User asked for a thorough check before changing anything: "hay que chequear también el código de las aplicaciones, manifiestos y helm charts y demás para que nada se rompa."
**Problem:** The audit revealed 21 references across 9 files — not 3. The "5 LOC move" was actually: (1) Go API source code reading the flattened env var (`apps/api/src/pkg/config/env.go`); (2) Docker Compose substitution (`infra/stacks/apps/api/compose.base.yml`); (3) Authelia Jinja template using `APPS_PLATFORM_API_EMAIL_USER` (`configuration.yml.j2:151,153,156` — for SMTP); (4) K8s overlay secrets placeholder (staging + prod); (5) Generated configmaps (staging + prod); (6) Toolkit `SecretSpec` + `SecretMapping` registry (`secrets_manager.py:318/332/346`, `k8s_secrets.py:101-104`). Authelia coupling was the surprise — moving `email_user` without re-sourcing Authelia's template would break OIDC SMTP at next reload.
**Solution:** For any "move this value" or "rename this key" refactor that touches the SSOT layer, **run a read-only consumer audit FIRST**, separate from the change itself. Cast a wide net: source code, templates (Jinja + Helm), generated outputs, Docker Compose substitutions, Ansible vars, tests, toolkit registries. Search for ALL forms of the name simultaneously: dotted path (`apps.platform.api.email_user`), flat snake_case (`email_user`), generator-flattened uppercase (`EMAIL_USER`, `APPS_PLATFORM_API_EMAIL_USER`), and any template `{{ ... }}` variants. Output a table of `file:line → reference form → breakage risk`. Decide PR structure FROM the audit, not the initial estimate. In this case, the audit recommended 3 sequenced PRs (smallest blast radius first: `beehiiv_pub_id` no-coupling → `email_from` no-coupling → `email_user` Authelia-coupled last) rather than one big-bang PR. The audit itself is ~10 minutes of grep; the cost of skipping it is a regression discovered post-merge.
**Tags:** `#ssot` `#refactor` `#process` `#patterns`
