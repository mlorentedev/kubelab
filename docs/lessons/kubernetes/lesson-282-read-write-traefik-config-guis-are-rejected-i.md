---
id: lesson-282-read-write-traefik-config-guis-are-rejected-i
type: lesson
status: active
created: "2026-06-20"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# Read-write Traefik config GUIs are rejected: IaC/SSOT inversion + K3s CRD-incompatible

**Context:** Evaluating "Traefik Manager" (a Flask service with a web UI that "makes Traefik much easier") for adoption into the cluster, versus relying on the existing Traefik dashboard plus the planned ADR-050 console.

**Problem:** The tool's only net-new capability is point-and-click *mutation*: it owns and writes Traefik dynamic-config YAML via the file provider (and edits static `traefik.yml`). That directly inverts kubelab doctrine — VPS Traefik config is templated from `common.yaml` by the `traefik_vps` Ansible role ("Do NOT edit VPS files manually"), and `traefik_vps/tasks/main.yml` re-templates `middlewares.yml`/`tls.yml`/`errors.yml`/per-route files unconditionally on every `make deploy-vps`. So a GUI edit is either clobbered on the next deploy (templated files) or persists as permanent untracked drift git/SSOT never sees (new files) — two distinct failure modes, both breaking `version-controlled-config > declarative > automated > manual`. Independently, the **K3s** Traefik uses `providers.kubernetesCRD` only (no file provider), so a file-provider GUI literally cannot manage the cluster instance at all. Its read/visualize value is already covered by the native dashboard (`api.dashboard=true`) and the DASH-001 cockpit that ADR-050 absorbs.

**Solution / Rule:** Reject read-write Traefik (or any infra-config) GUIs that own config files — they fight IaC-from-SSOT and create a second source of truth for middlewares already declared in HelmChartConfig/overlays. Evaluate future "make Traefik easier" tools **read-only-only**; the operator surface is the native dashboard plus the ADR-050 console (federate-not-absorb, C4), never a click-to-mutate editor. Corollary: a config GUI is only safe where config is NOT templated from SSOT — which, in kubelab, is nowhere.

**Tags:** `#traefik` `#iac` `#ssot` `#k3s` `#crd` `#adr-050` `#tooling-rejection` `#gotcha`
