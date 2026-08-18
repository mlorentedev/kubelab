---
id: lesson-027-show-secret-must-bypass-configurationmanager-
type: lesson
status: active
created: "2026-03-22"
owner: manu
tags: [kubelab, lesson]
---

# show_secret must bypass ConfigurationManager for env='common'

**Context**: Building `toolkit secrets show cloudflare.api_token --env common` for the `tf-dns-apply` Makefile target. Cloudflare API token lives in `common.enc.yaml`, not in any env-specific file.

**Problem**: `show_secret` used `ConfigurationManager._decrypt_sops()` which only supports real environments (dev/staging/prod). `env='common'` isn't a valid environment — it's a cross-env secrets file. Additionally, the CLI's `validate_environment()` call rejected "common" before `show_secret` was even reached.

**Solution**: Refactored `show_secret` to use direct `sops -d` subprocess call, building the path explicitly as `secrets_path / f"{env}.enc.yaml"`. The `set` command already used its own validation tuple `("common", "dev", "staging", "prod")` — the `show` command needs the same pattern.

**Rule**: When toolkit commands need to operate on `common.enc.yaml`, bypass `ConfigurationManager` and use direct SOPS CLI. Always include "common" in environment validation for secrets commands. The set command got this right from the start — show was the oversight.
