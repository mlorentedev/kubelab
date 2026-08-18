---
id: lesson-063-k3s-tls-san-must-be-set-before-first-start
type: lesson
status: active
created: "2026-02-22"
owner: manu
tags: [kubelab, lesson]
---

# K3s TLS SAN Must Be Set Before First Start

**Context**: kubectl from workstation via Tailscale required `insecure-skip-tls-verify: true`.

**Problem**: K3s generates the API server cert on first start. By default it only includes LAN IP + localhost. The Tailscale IP (100.64.0.4) was not in the SAN → TLS validation fails → insecure workaround needed.

**Solution**: Create `/etc/rancher/k3s/config.yaml` with `tls-san: ["100.64.0.4"]` and restart K3s. Then update kubeconfig: replace `insecure-skip-tls-verify` with `certificate-authority-data` using the server CA cert.

**Rule**: Always configure `tls-san` with ALL access IPs (LAN, Tailscale, public) BEFORE the first `curl | sh` of K3s. If already running, requires restart (regenerates certs). Document in k3s-setup runbook.

---
