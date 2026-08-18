---
id: lesson-104-astro-i18n-type-safety-es-only-keys-need-en-s
type: lesson
status: active
created: "2026-03-06"
owner: manu
tags: [kubelab, lesson]
---

# Astro i18n Type Safety — ES-Only Keys Need EN Stubs

**Context**: Rewrote portfolio landing page with newsletter CTA only on Spanish pages. Added `newsletter.*` keys only to the `es` object in `ui.ts`.

**Problem**: The `t()` function is typed against `defaultLang` (EN) keys: `keyof (typeof ui)[typeof defaultLang]`. ES-only keys like `newsletter.placeholder` cause TypeScript error TS2345 — the key doesn't exist in the EN type.

**Solution**: Add the keys to EN as well with English translations. They won't be displayed on EN pages, but the type system needs them present in the default locale.

**Rule**: In Astro i18n with `defaultLang` as the type source, ALL keys must exist in the default locale object. Language-specific display logic belongs in components, not in the type system.
