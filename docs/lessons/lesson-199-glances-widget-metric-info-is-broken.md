---
id: lesson-199-glances-widget-metric-info-is-broken
type: lesson
status: active
created: "2026-03-23"
owner: manu
tags: [kubelab, lesson]
---

# Glances widget metric: info is broken

**Context**: Homepage Glances widget configuration.

**Problem**: `metric: info` causes a `forEach` JS error in Homepage. The `info` endpoint returns a different data structure than Homepage expects.

**Solution**: Use `cpu` or `memory` metric types instead.

**Rule**: Test each widget metric type individually. Homepage widget docs may list options that don't work with all Glances versions.
