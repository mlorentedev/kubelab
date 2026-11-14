---
id: lesson-753-an-on-demand-liveness-watchdog-must-be-local-but-independent-of-the-agent-kill-switch
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: observability
tags: [kubelab, observability, systemd, hermes]
---

# An on-demand liveness watchdog must be local but independent of the agent kill switch

**Context**: hermes-kubelab runs on on-demand ace2 behind an API bind that the external monitor cannot reach. AI-013 adds a local Docker healthcheck and a systemd timer that pages through the existing fleet notification fabric. Power-off is normal and must stay silent, while gateway failure on a running node must page.

**Problem**: An external Kuma monitor tagged `on-demand` would be muted both for normal power-off and for the agent failure, so it cannot implement the distinction. A persistent local timer would catch up at boot and could page for time when the node was intentionally off. Binding the watcher to `agent-stack-egress.service` looks like a convenient planned-stop suppression, but that unit also gates the agent's user manager and has no failure notification of its own: an unexpected egress/daemon failure would disable the watcher along with the agent.

**Solution**: Keep detection on ace2, with no external monitor, no `Persistent`/`OnCalendar` catch-up and a ten-minute boot grace period. Keep the watcher independent of the egress kill switch so loss of the rootless daemon fails closed and pages. For an intentional silent stop, stop the watcher timer before stopping egress; provisioning enables it again. Use the simple `/health` route for process liveness, not authenticated detailed readiness that can conflate a Slack or provider outage with a dead gateway. Reuse `kubelab-notify@` and its recovery hook for deduplication, spooling and incident closure.

**Rule**: On-demand silence must come from the absence of work while the node is off, not from muting the failure being detected. A watchdog must not share a failure domain with the component it watches unless another independent alert covers that domain. Make planned suppression an explicit operator action and test both sides of the distinction.

**Tags**: `#systemd` `#notify` `#ai-013`
