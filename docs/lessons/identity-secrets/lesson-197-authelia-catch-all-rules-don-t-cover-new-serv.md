---
id: lesson-197-authelia-catch-all-rules-don-t-cover-new-serv
type: lesson
status: active
created: "2026-03-23"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# Authelia catch-all rules don't cover new services automatically

**Context**: Adding `home.staging.kubelab.live` expected it to match the existing `*.staging.kubelab.live` catch-all in Authelia.

**Problem**: The catch-all was restricted to `networks: internal`. New services need explicit `one_factor` rules. (Related: Tailscale CIDR lesson — 2026-03-25.)

**Solution**: Add explicit Authelia `access_control` rule for each new service domain.

**Rule**: Don't assume Authelia wildcard rules cover new services. Always verify the network constraints on catch-all rules and add explicit rules when needed.
