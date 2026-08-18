---
id: lesson-340-tailscale-status-says-active-about-a-machine-
type: lesson
status: active
created: "2026-08-16"
owner: manu
tags: [kubelab, lesson, tailscale, aws, spot, diagnostics, gotcha]
---

# `tailscale status` says `active` about a machine that is powered off

**Context:** aws1 was interrupted by a Spot reclaim. Checking whether it had come back, `tailscale status` showed:

```
100.64.0.7   aws1   kubelab   linux   active; relay "fra"; offline, tx 103116 rx 0
```

Read left to right, `active` is the first word and it reads as "the node is up". It is not about the node at all — it describes *this workstation's* connection attempt: a session is open via the Frankfurt DERP relay. The two tokens that carry the answer come after it: `offline`, and `tx 103116 rx 0` — 103 KB sent, **zero bytes back**.

EC2 said `stopped` the whole time, with the persistent Spot request still `open / capacity-not-available`.

**The trap:** the existing entry above (2026-03-28) already records the inverse pair — *"tailscale showing offline while EC2 still reports running / impaired"* — as diagnostic of a wedged Spot. That framing makes Tailscale look like one of two equal witnesses. It is not: **a VPN peer's state is never authoritative about whether the machine exists**, in either direction. Tailscale reports transport, EC2 reports the host.

**Fix:** answer the two questions from their own sources.

```bash
# "Is it powered on?" -> EC2, always
aws ec2 describe-instances --profile kubelab --region eu-central-1 \
  --filters "Name=tag:Project,Values=kubelab" \
  --query 'Reservations[].Instances[].State.Name' --output text

# "Is it reachable?" -> rx, not the status word
tailscale status | grep aws1
```

**Rule:**
- **`rx 0` beats every adjective on the line.** Bytes received is the only field on a `tailscale status` row that cannot be true of a dead peer.
- **Never let a transport report stand in for a liveness report**, especially when the cheap check is one CLI call away and the expensive mistake is a destructive recovery command. This was one step away from `make aws1-replace` against a stopped-but-recoverable instance — see `runbooks/aws1-destroy-replace.md`.

**Tags:** `#tailscale` `#aws` `#spot` `#diagnostics` `#gotcha`
