---
id: lesson-275-headscale-policy-check-is-syntax-only-until-v
type: lesson
status: active
created: "2026-05-31"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Headscale policy check is syntax-only until v0.29 — don't base ACL rollout safety on the tests block in v0.28

**Context:** Designing ADR-041 (tag-based Headscale ACL for an agent fleet) on a SINGLE production control plane (Headscale v0.28.0, no staging). The rollout-safety argument leaned on the policy `tests` block (reachability assertions evaluated at apply/reload) to de-risk the deny-by-default flip.
**Problem:** The premise was wrong. Verified against the Headscale CHANGELOG: `headscale policy check` exists since v0.26.0 but is SYNTAX-ONLY; evaluation of the policy `tests` block (allow/deny reachability assertions) landed only in v0.29.0. So on v0.28.0 a policy can pass `policy check` while enforcing none of the reachability assertions — leaving the single prod mesh exposed to an untested deny-by-default flip. The error was in freshly-written work believed correct; an adversarial reviewer (Codex P2 on PR #234) caught it.
**Solution:** On v0.28, get rollout safety WITHOUT the tests block: (1) `policy check` as a syntax-only CI gate; (2) permissive-first baseline (replicate current allow-all + agent rules — cannot sever an existing flow by construction); (3) external active connectivity probe after each `systemctl reload` (reload, not restart — non-disruptive and reversible), with auto-revert to the prior known-good policy on failure; (4) upgrade to v0.29.0 BEFORE the deny-by-default tightening to gain in-engine `tests`, and author the external-probe assertions so they migrate into a `tests` block on upgrade. Meta: verify version-gated feature claims against the changelog before designing safety around them; adversarial review is load-bearing even on work you just wrote and believe correct.
**Tags:** `#headscale` `#acl` `#vpn` `#adr-041` `#rollout-safety` `#versioning`
