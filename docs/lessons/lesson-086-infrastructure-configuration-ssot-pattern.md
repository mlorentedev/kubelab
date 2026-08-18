---
id: lesson-086-infrastructure-configuration-ssot-pattern
type: lesson
status: active
created: "2026-02-28"
owner: manu
tags: [kubelab, lesson]
---

# Infrastructure Configuration SSOT Pattern

**Context**: Audited all hardcoded values in the repo during E2E test expansion. Found 16 critical hardcoded IPs, ports, and image versions across K8s manifests, Ansible inventory, Corefile, tests, and toolkit code.

**Problem**: The toolkit generates Docker Compose and Traefik configs from `common.yaml`, but K8s manifests, Ansible inventory, CoreDNS Corefile, and toolkit monitoring code hardcode the same values independently. When an IP or port changes, it must be updated in 3-7 places manually. The DNS Corefile wildcard (`*.staging.kubelab.live → 100.64.0.4`) points domains to K3s even for services not deployed there, causing self-signed cert errors.

**Solution applied**:
1. Added `networking` section to common.yaml with all node Tailscale IPs, VPS IPs, and the Tailscale CIDR
2. Updated tests to read from common.yaml instead of hardcoding IPs/domains
3. Added CrowdSec whitelist ConfigMap referencing the common.yaml CIDR
4. Fixed Authelia prod overlay VPN CIDR (`/24` → `/10`)

**Remaining gaps** (tracked as future tasks):
- Ansible inventory IPs still hardcoded (needs inventory generation from config)
- CoreDNS Corefile IPs hardcoded (needs Corefile generation from config)
- K8s image versions diverge from common.yaml (needs image pinning review)
- `toolkit/cli/monitoring.py` Uptime Kuma IP hardcoded

**Rule**: Follow the SSOT → Generator → Consumer pattern. Every IP, port, domain, and image version should have exactly ONE canonical location in `infra/config/values/common.yaml`. K8s manifests, Ansible, Terraform, and Corefile should either be generated from common.yaml or have a comment noting which common.yaml key they mirror. When adding a new hardcoded value, ask: "Can I read this from config instead?"

---
