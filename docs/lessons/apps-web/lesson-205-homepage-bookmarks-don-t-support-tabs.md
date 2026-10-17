---
id: lesson-205-homepage-bookmarks-don-t-support-tabs
type: lesson
status: active
created: "2026-03-23"
owner: manu
category: apps-web
tags: [kubelab, apps-web]
---

# Homepage bookmarks don't support tabs

**Context**: Wanted to organize bookmarks into tabbed sections in Homepage.

**Problem**: Bookmarks section has no tab support. Only services support tab-based layout.

**Solution**: Move bookmark content to `services.yaml` to get tab layout support.

**Rule**: Read Homepage layout docs carefully. Features available for services may not exist for bookmarks/widgets. When layout matters, model everything as services.
