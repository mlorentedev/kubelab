---
id: lesson-201-homepage-has-no-native-github-cloudflare-dock
type: lesson
status: active
created: "2026-03-23"
owner: manu
tags: [kubelab, lesson]
---

# Homepage has no native GitHub/Cloudflare/DockerHub widgets

**Context**: Trying to add GitHub PRs, Cloudflare analytics, and DockerHub pull counts to Homepage.

**Problem**: These widgets don't exist natively. The `cloudflared` widget is for Cloudflare Tunnels, not analytics.

**Solution**: Use `customapi` widget type with direct API calls.

**Rule**: Verify widget availability in Homepage docs before planning dashboard sections. "80+ widgets" doesn't mean every SaaS has one.
