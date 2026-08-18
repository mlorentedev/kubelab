---
id: lesson-098-coredns-template-overrides-hosts-when-both-ar
type: lesson
status: active
created: "2026-03-01"
owner: manu
tags: [kubelab, lesson]
---

# CoreDNS `template` Overrides `hosts` When Both Are in Same Zone

**Context**: The `kubelab.live` zone had both a `hosts` block (bare-metal services at individual Tailscale IPs) and a `template` wildcard (K3s services at VPS Tailscale IP). Expected hosts to take priority.

**Problem**: CoreDNS `template` plugin overrides `hosts` plugin responses even when the hosts entry explicitly matches. `status.kubelab.live` resolved to `100.64.0.2` (template wildcard) instead of `100.64.0.6` (hosts entry). This is because CoreDNS plugin ordering makes `template` respond after `hosts`, and the template's answer replaces the hosts answer.

**Solution**: Remove the `template` wildcard from `kubelab.live` zone. Use explicit `hosts` entries for ALL prod services (both bare-metal and K3s). This avoids the template-hosts conflict entirely. The staging zone's template wildcard works fine because ALL staging IPs are the same (`100.64.0.4`).

**Rule**: Never mix `hosts` and `template` plugins in the same CoreDNS zone when they resolve to different IPs. Use explicit hosts entries instead. The `template` wildcard is safe ONLY when all entries resolve to the same IP (like staging).

---
