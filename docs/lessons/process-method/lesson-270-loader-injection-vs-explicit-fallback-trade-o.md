---
id: lesson-270-loader-injection-vs-explicit-fallback-trade-o
type: lesson
status: active
created: "2026-05-25"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# Loader-injection vs explicit-fallback: trade-off SSOT cleanliness vs grep-ability

**Context:** SSOT-014c had to derive 3 fields (`edge.traefik.acme_email`, `uptime_kuma.admin_email`, Authelia admin user email) from one SSOT (`apps.contact.email`). Two implementation approaches considered: (a) explicit fallback at each consumer site (`config.X | default(config.apps.contact.email, true)` in Jinja + `field or contact_email` in Python — repeated at ~6 call sites across Ansible playbooks and toolkit code); (b) loader injection — the config loader (`configuration.py:get_merged_config`) post-processes the merged config to fill empty fields from the SSOT. Consumer code unchanged.
**Problem:** Both achieve the SSOT goal (single declaration). Approach (a) is grep-friendly — reading the consumer code, you SEE the fallback. Approach (b) is consumer-friendly — adding a new derivation later (e.g., `notifier.from_email`) is one helper edit, not 6 consumer-site touches. But (b) introduces "magic" — a reader of `common.yaml` may not see why `edge.traefik.acme_email` is non-empty at runtime when removed from the file. Risk: future debugging confusion ("where does this value come from?").
**Solution:** Chose (b) loader injection because: (1) the project pattern (ADR-036 `infra.<service>.*` namespace) already establishes "config loader is allowed to derive cross-section values"; (2) consumer paths (`config.edge.traefik.acme_email` etc.) are spec interfaces consumed by Ansible/generators/K8s manifests — changing them is a much bigger blast than tucking the derivation in the loader; (3) **explicit documentation at TWO points neutralizes the "magic" risk** — inline comment in common.yaml at `apps.contact.email` listing the derived paths, and a docstring on `_inject_contact_email_derivations` mirroring the same list. Plus: 4 new regression tests that assert each derivation works (prevent silent loss of the helper in future refactors). Lesson generalizes: loader-injection patterns are professional iff (a) the injected fields are well-documented in BOTH the SSOT declaration site and the helper, and (b) regression tests enforce the derivation. Without those, prefer explicit fallback — debug cost dominates. Shipped in PR #220.
**Tags:** `#ssot` `#config` `#patterns` `#ssot-014c`
