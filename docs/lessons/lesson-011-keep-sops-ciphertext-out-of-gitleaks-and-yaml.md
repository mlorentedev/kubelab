---
id: lesson-011-keep-sops-ciphertext-out-of-gitleaks-and-yaml
type: lesson
status: active
created: "2026-06-20"
owner: manu
tags: [kubelab, lesson]
---

# Keep SOPS ciphertext out of gitleaks, and YAML/Markdown out of CRLF, on Windows

**Context**: After wiring pre-commit in this clone (#721), commits touching `infra/config/secrets/*.enc.yaml` were slow enough to be unsustainable, and YAML files kept failing yamllint with `wrong new line character`.

**Problem**: Two independent Windows/tooling frictions. (1) gitleaks (`useDefault`) was scanning SOPS **ciphertext** — SOPS rotates the data key on every edit, so the whole high-entropy file changes each commit; scanning age ciphertext is slow and only yields false positives, because it is not plaintext. (2) `core.autocrlf=true` with no `.gitattributes` override checked YAML out as CRLF; yamllint rejects CRLF, and the toolkit (writing in text mode) re-emitted CRLF — a churn loop.

**Solution**: `.gitleaks.toml` allowlist `infra/config/secrets/.*\.enc\.yaml$` (+ `.*\.pem(\.enc)?$`) — real plaintext leaks are still caught by the toolkit and the `detect-private-key` hook *before* a value ever reaches SOPS. `.gitattributes` pin `*.yaml`/`*.yml` (and now `*.md`) to `eol=lf`.

**Rule**: A secret scanner must never scan SOPS-encrypted stores — allowlist them by path and rely on a pre-SOPS plaintext guard for real leaks. On any repo edited from Windows, pin every text format that tooling parses (YAML, Markdown) to `eol=lf` in `.gitattributes`; autocrlf otherwise produces CRLF that breaks linters and churns diffs.

**Tags**: `#gitleaks` `#sops` `#pre-commit` `#windows` `#crlf` `#gitattributes` `#pr-721`
