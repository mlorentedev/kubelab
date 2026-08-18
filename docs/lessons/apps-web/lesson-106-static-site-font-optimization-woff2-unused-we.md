---
id: lesson-106-static-site-font-optimization-woff2-unused-we
type: lesson
status: active
created: "2026-03-07"
owner: manu
category: apps-web
tags: [kubelab, apps-web]
---

# Static Site Font Optimization — woff2, Unused Weight Removal, Preloading

**Context**: Full audit of the mlorente.dev portfolio site found 5 Roboto `.woff` font files (468KB total), one of which (Roboto-Light) was loaded by CSS but never used by any Tailwind class.

**Problem**: Three compounding issues: (1) `.woff` format is ~30% larger than `.woff2`; (2) Roboto-Light (93KB) was declared in `@font-face` but no component used `font-light` or `font-thin`; (3) No `<link rel="preload">` for critical fonts caused FOUT (Flash of Unstyled Text) on initial load.

**Solution**: Converted 4 active weights to `.woff2` via fontTools (`TTFont` with `flavor='woff2'`). Deleted all `.woff` files and the unused Light weight entirely. Added `<link rel="preload" href="..." as="font" type="font/woff2" crossorigin>` for Regular and Bold in `<head>`. Result: 468KB → 265KB (-43%), 5 files → 4 files, no FOUT.

**Rule**: For self-hosted fonts on static sites: (1) always use `.woff2` — `.woff` is legacy; (2) audit actual CSS class usage before loading font weights — unused weights are pure waste; (3) preload the 1-2 most critical weights (body + bold) in `<head>` with `crossorigin` attribute (required even for same-origin fonts); (4) `font-display: swap` alone is not enough — preload eliminates the swap flash.

---
