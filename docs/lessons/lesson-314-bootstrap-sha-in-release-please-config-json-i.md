---
id: lesson-314-bootstrap-sha-in-release-please-config-json-i
type: lesson
status: active
created: "2026-08-12"
owner: manu
tags: [kubelab, lesson, release-please, config-schema, ver-009, silent-failure, dry-run, gotcha]
---

# `bootstrap-sha` in `release-please-config.json` is a manifest-level option, not a per-package one

**Context:** Evaluating VER-009 (#989) — adding `infra`/`toolkit` as new release-please packages in a repo with years of pre-existing history under both paths. Set a per-package `bootstrap-sha` on each, expecting it to scope the first release-please pass to commits after that SHA.

**Problem:** It had no effect. A local dry-run (`release-please release-pr --dry-run --local`, against an isolated scratch clone — never the real repo) proposed `toolkit: 1.0.0` with a changelog spanning the entire commit history under `toolkit/`, back through the original K3s migration. `debug-config` showed why: the per-package `ReleaserConfig` object that `extractReleaserConfig` builds from `packages.<path>` has no `bootstrapSha` field at all — it silently accepted and dropped the unrecognized key. Confirmed against the published JSON schema (`raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json`): `bootstrap-sha` is a sibling of `packages` at the top level of the whole config document, described as "For the initial release of a library, only consider as far back as this commit SHA" — global to the run, not scoped per path.

**Solution:** Moved `bootstrap-sha` to the top level. Confirmed dormant for already-released packages (`api`/`errors` — they have real tags, so `latestRelease` lookup succeeds and the SHA is never consulted) and effective for the new ones (re-ran the same dry-run: `infra`/`toolkit` correctly showed 0 commits at the bootstrap point, then correctly picked up exactly one synthetic commit each in a follow-up test, with no cross-contamination between paths). VER-009 itself was later declined on unrelated grounds (SemVer without a consumer is decorative) — the config mechanics stayed correct regardless.

**Rule:**
- **An unrecognized key in a nested config object is not validated — it is dropped.** `release-please`'s config parser (`extractReleaserConfig`) pulls only the fields `ReleaserConfig` defines; anything else nested under `packages.<path>` vanishes with no warning, so a wrong-scope option looks identical to a correctly-scoped one until you read the actual dry-run output.
- **A schema field's own description states its scope — read it before placing the key.** The published schema literally says "for the initial release of *a* library" (singular, global), which was the tell; the assumption that "if it's about one package, it must go inside that package's block" was never verified against the schema before the first (wrong) placement.
- **`debug-config` (or the equivalent introspection command) beats re-reading docs when a config option "has no effect."** Docs describe intent; a dump of the parsed config shows what the tool actually saw.

**Tags:** `#release-please` `#config-schema` `#ver-009` `#silent-failure` `#dry-run` `#gotcha`
