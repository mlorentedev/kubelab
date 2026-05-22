---
id: "TOOL-001-secret-drift"
type: spec
status: draft
created: "2026-05-13"
tags: [spec, proposal, toolkit, secrets, sops]
template_version: "1.0"
---

# TOOL-001: Secret drift detection CLI subcommand

## Why

When adding a new secret to staging, it's currently easy to forget to add the same key to prod. Drift is only detected when the prod deployment fails to find the secret at runtime. A drift-detection subcommand lets us catch this before deploy.

This unblocks the related TOOL-002 (secret sync) by providing the report-only step first.

## What

New subcommand: `toolkit secrets diff [--env A --env B] [--format plain|json]`.

- Reads two SOPS-encrypted files (default: `apps.staging.enc.yaml` vs `apps.prod.enc.yaml`).
- Decrypts both in memory (via existing toolkit SOPS integration).
- Compares **keys only** — values are never logged, only key presence and type shape.
- Outputs:
  - Keys present in A but missing in B
  - Keys present in B but missing in A
  - Common keys with mismatched value SHAPES (string vs map vs list) — not values
- Exit code: 0 if identical, 1 if drift detected, 2 if execution error.

## Out of scope

- TOOL-002 (sync drift forward) — separate spec.
- Comparing secret VALUES (security: never).
- Cross-cluster drift (multi-K8s) — only SOPS files for v1.
- UI / web dashboard.

## Risks / open questions

1. **Output format.** Plain text, JSON, or both (`--format`)? Lean: both, plain default for humans, `--format json` for CI gates. RESOLVED in spec.
2. **What "shape mismatch" means.** Just primitive type difference (string/int/list/map) or deeper (nested map keys also diffed)? Lean: type-level only for v1; defer deeper to TOOL-002.
3. **Empty files / decryption failure.** Error and exit 2 vs treat as no drift? Lean: error and exit 2 — silent ambiguity is dangerous for secrets.
4. **Authorization.** Both files must be decryptable by current SOPS keys. If user lacks one key, fail clean with "missing key for env X". No partial diff.

## Acceptance criteria

- [ ] `toolkit secrets diff --env staging --env prod` runs and exits 0 if identical.
- [ ] If staging has key `apps.services.x.foo` and prod does not, output lists it under "staging only" and exits 1.
- [ ] Output never contains a secret VALUE (verified via test with negative assertion on known fixture values).
- [ ] Decryption failure produces clear error and exit 2.
- [ ] `--format json` emits parseable JSON for CI consumption.
- [ ] Type-shape mismatch (e.g. string vs list under same key) is flagged and exits 1.

## References

- `kubelab/11-tasks.md` — TOOL-001 / TOOL-002
- Existing SOPS integration: `toolkit/secrets/` (assumed module path — verify)
- Possible ADR: secret management policy — TBD if this work surfaces one
