---
id: lesson-085-authelia-prod-vpn-network-uses-24-instead-of-
type: lesson
status: active
created: "2026-02-28"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# Authelia Prod VPN Network Uses /24 Instead of /10

**Context**: Auditing hardcoded values in K8s manifests after E2E test expansion.

**Problem**: `infra/k8s/overlays/prod/patches.yaml` defines the Authelia VPN network as `100.64.0.0/24` but Headscale allocates from the `100.64.0.0/10` range. With `/24` Authelia only recognizes IPs 100.64.0.0-255 as VPN traffic. All current nodes fit within `/24` so it works today, but future nodes could get IPs outside this range and bypass VPN-specific access rules.

**Solution**: Changed to `100.64.0.0/10` to match the Headscale allocation range. Added `networking.tailscale_cidr` to common.yaml as the single source of truth.

**Rule**: The Tailscale/Headscale CIDR must be consistent everywhere: Authelia access rules, CrowdSec whitelists, and any IP-based filtering. Reference `networking.tailscale_cidr` from common.yaml; don't hardcode CIDRs in individual K8s manifests.

---
