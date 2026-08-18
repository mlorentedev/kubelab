---
id: lesson-293-kubectl-create-secret-leaks-every-value-into-
type: lesson
status: active
created: "2026-07-09"
owner: manu
tags: [kubelab, lesson, secrets, kubernetes, kubectl, argv, proc, yaml-injection, safe-dump, sec-secrets-001, gotcha]
---

# `kubectl create secret` leaks every value into `/proc/<pid>/cmdline` — render the manifest in-process and apply over stdin (SEC-SECRETS-001)

**Context:** SEC-SECRETS-001 (#831), the capstone of the secret-delivery hardening cluster. `_apply_single_secret` in `k8s_secrets.py` shipped Secrets with `kubectl create secret generic … --from-literal=k=v … --dry-run=client -o yaml | kubectl apply -f -`.

**Problem:** Two distinct exposures. (1) `--from-literal=key=value` puts **every plaintext secret in the child process's argv**, world-readable in `/proc/<pid>/cmdline` for the life of the call and visible to any `ps` on the box — a local-user disclosure that no amount of SOPS-at-rest encryption prevents. (2) The dynamic builders (`_build_users_database`, `_build_apprise_config`) assembled their YAML by **f-string interpolation**, so a value containing a `:`, a leading `%`, or a newline (an argon2 hash, a bot token, a display name) could produce malformed or reinterpreted YAML — an injection seam in the config a service then parses as truth.

**Solution:** One delivery primitive, `_render_secret_manifest(name, namespace, data)`: build the Secret as a **dict** with base64-encoded `data`, `yaml.safe_dump` it, and hand it to `kubectl apply -f -` via **stdin** (`input=manifest`). No value ever becomes a subprocess argument. `data` + base64 is byte-equivalent to what `kubectl create secret -o yaml` emitted, so the applied object is unchanged — a pure delivery-path swap, not a semantic one. The two builders became `yaml.safe_dump(dict)` as well, so the serializer owns escaping instead of the caller. TOOL-018's fail-closed-on-partial-resolve behaviour is preserved on top.

**Rule:** Secrets belong on **stdin, never in argv** — the process table is a disclosure channel, and `--from-literal` is the idiom that walks straight into it. Equally: never build YAML that will carry a secret by string interpolation; hand a dict to `safe_dump` and let it own the escaping. Both are the same discipline — stop treating a structured, sensitive payload as text you concatenate.

**Tags:** `#secrets` `#kubernetes` `#kubectl` `#argv` `#proc` `#yaml-injection` `#safe-dump` `#sec-secrets-001` `#gotcha`
