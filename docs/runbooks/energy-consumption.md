---
id: kubelab-energy-consumption
type: infra
status: active
tags: [kubelab, infrastructure, hardware, energy]
created: "2026-02-28"
owner: manu
---

# Homelab Energy Consumption Estimates

> TDP-based estimates from manufacturer specs. Actual consumption measured under real workloads would be lower due to idle states.

## Per-Node Estimates

| Node | Device | TDP (W) | Idle Est. (W) | Load Est. (W) | Role |
|------|--------|---------|---------------|----------------|------|
| Acemagic-1 | Mini PC (12GB) | 15 | 8-10 | 15 | K3s server + agent-1 VMs |
| Acemagic-2 | Mini PC (12GB) | 15 | 8-10 | 15 | K3s agent-2 |
| Beelink | Mini PC (8GB) | 15 | 8-10 | 15 | Ollama bare metal |
| RPi 4 | Raspberry Pi (8GB) | 6.5 | 3-4 | 6 | Network gateway |
| RPi 3 | Raspberry Pi (1GB) | 5 | 2-3 | 4 | Uptime Kuma monitoring |
| Jetson Nano | NVIDIA Jetson | 10 | 5-6 | 10 | Pollex (llama.cpp) |

## Total Estimates

| Scenario | Total Wattage | Monthly kWh | Annual kWh | Annual Cost (EUR) |
|----------|---------------|-------------|------------|-------------------|
| All idle | ~34 W | ~25 kWh | ~298 kWh | ~91 |
| Mixed workload | ~50 W | ~36 kWh | ~438 kWh | ~134 |
| All under load | ~67 W | ~49 kWh | ~587 kWh | ~179 |

**Electricity rate used**: ~0.306 EUR/kWh (Spain average, 2025-2026)

## VPS (Hetzner) — Excluded from Above

| Item | Cost |
|------|------|
| VPS (CX22) | ~4.59 EUR/month = ~55 EUR/year |

## Cloud Equivalent Cost Comparison

Running the same services on cloud (3 small VMs + managed services):

| Cloud Setup | Monthly Cost | Annual Cost |
|-------------|-------------|-------------|
| 3x Hetzner CX22 (4GB) | ~14 EUR | ~168 EUR |
| AWS/GCP equivalent (3x t3.small + managed DB) | ~150-300 EUR | ~1,800-3,600 EUR |

**Conclusion**: Homelab costs ~91-179 EUR/year in electricity + ~55 EUR/year VPS = **~146-234 EUR/year total**, vs ~1,800-3,600 EUR/year cloud equivalent. The hardware CAPEX (~500 EUR total for all devices) pays for itself in 3-6 months.

## Notes

- Jetson Nano and Beelink/Ollama can be powered off when not needed
- RPi3 (Uptime Kuma) should stay 24/7 for external monitoring
- Staging cluster (Acemagic-1 + Acemagic-2) can be powered off between dev sessions
- Current strategy: power off staging when not in use, saving ~16-20W
