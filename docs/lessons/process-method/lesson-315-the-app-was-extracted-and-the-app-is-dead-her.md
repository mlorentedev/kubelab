---
id: lesson-315-the-app-was-extracted-and-the-app-is-dead-her
type: lesson
status: active
created: "2026-08-12"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# "The app was extracted" and "the app is dead here" are different claims

**Context:** Researching a docs rewrite (`versioning-strategy.md`/`cicd.md`), found `promote-prod.yml`'s `workflow_dispatch` dropdown offered `web`/`api`, and the toolkit's `promote`/`image-tag` CLI help text still said "(api|web)". Read this as leftover debt from `web`'s extraction to its own repo (ADR-053) — about to file a ticket for it.

**Problem:** The premise was half right and half wrong. `web`'s *source* did move to `mlorentedev/web`. Its *deployment* — `apps.platform.web.version` in `common.yaml`/`staging.yaml`/`prod.yaml`, the `PLATFORM_APPS` constant, the `promote` command's `web` branch — never left, because `web-image-receiver.yml` (a `repository_dispatch` cross-repo receiver, ADR-053 §2) is how the other repo's CI hands a built image back to this one for staging/prod promotion. Reading that one workflow file — which the docs rewrite needed anyway — resolved it before any ticket got filed: `web` in those five places is correct, current, load-bearing config, not residue.

**Solution:** No fix needed for `web`. The search that surfaced it also found genuine (much smaller) dead-app residue elsewhere in the same file family — `orchestrator.py` iterating `["api", "web", "blog", "wiki"]` for local dev build/deploy, and hardcoded prod-status URLs for `blog.mlorente.dev`/`wiki.mlorente.dev` (blog killed, wiki retired into a toolkit command, neither resolves to anything this platform serves) — fixed in #1010, after the same one-more-file-read standard applied to confirm those two really were dead (checked `apps/` had no `blog`/`wiki` directories, and DNS had no records for either).

**Rule:**
- **"Extracted to its own repo" describes where the code lives, not whether the artifact is still deployed from here.** A platform/product repo split (ADR-053's own shape) routinely keeps deployment tracking in the platform repo after the source leaves it — the split is about code ownership, not runtime responsibility.
- **Before filing a debt ticket for "dead" references, find the mechanism that would make them live, not just the absence of a local Dockerfile.** A cross-repo `repository_dispatch` receiver is exactly the kind of live wiring that a same-repo grep for `apps/web/` will never surface.
- **The false alarm and the real finding came from the same search.** Casting the net wide enough to catch one meant catching the other too — the discipline was verifying each hit individually rather than accepting the first plausible story for all of them.

**Tags:** `#adr-053` `#platform-product-split` `#false-positive` `#verify-before-ticketing` `#debt-triage` `#gotcha`
