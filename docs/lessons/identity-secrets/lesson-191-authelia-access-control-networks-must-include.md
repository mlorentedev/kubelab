---
id: lesson-191-authelia-access-control-networks-must-include
type: lesson
status: active
created: "2026-03-25"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# Authelia access_control networks must include Tailscale CIDR

**Context**: Authelia `access_control` had hardcoded RFC1918 ranges as "internal" networks. VPN clients use Tailscale IPs (100.64.0.0/10) which are not in RFC1918.

**Problem**: The catch-all rule `*.staging.kubelab.live` with `policy: one_factor` only applied to `internal` networks. Tailscale clients got `default_policy: deny` → Forbidden on all staging services.

**Solution**: Created `networking.trusted_cidrs` SSOT list in common.yaml (RFC1918 + Tailscale CIDR). Authelia template reads from context variable `trusted_cidrs` via a Jinja2 loop. Single source, N consumers.

**Rule**: Network CIDR lists must be SSOT-driven from common.yaml, not hardcoded in templates. Any service that makes network-based access decisions (Authelia, CrowdSec whitelist, firewall rules) must consume from the same `trusted_cidrs` list.
