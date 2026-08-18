---
id: lesson-274-codex-adversarial-pr-review-caught-4-real-def
type: lesson
status: active
created: "2026-05-30"
owner: manu
tags: [kubelab, lesson, code-review, codex, verification, process]
---

# Codex adversarial PR review caught 4 real defects across the OIDC sprint — bias toward verification over self-trust

**Context:** Five-PR OIDC session (#229 SYNC-001, #230 SYNC-001b, #231 DRIFT-001, #232/#233 ADR-040). Codex (chatgpt-codex-connector bot) reviews every PR on this repo.
**Problem:** Codex flagged 4 distinct P2 issues, 3 of them in code/docs I had just written and believed correct: (1) #229 fixed path-drift in only one of two duplicated path constants — _get_oidc_output_files in cli/sync.py still pointed at the old files, so --check compared/restored the wrong files (#230 fixed). (2) #231 classify_token_response returned PASS for any JSON lacking invalid_client — an ingress/proxy JSON 404/403/502 would falsely report the secret matches; needed a 3rd INCONCLUSIVE verdict (fixed in #231). (3) #232 ADR over-claimed consumer verification as covering all consumers when DRIFT-001 only covers Gitea (#233 fixed). Each was a real latent bug invisible to my own tests as written — my tests covered what I designed them to cover, not the gap.
**Solution:** Treat adversarial machine review as a first-class part of the loop, not a formality: every Codex P2 this session was legitimate and worth a fix or follow-up PR. Reinforces the recurring KubeLab pattern (SSOT-019, OIDC auth_method, 22 orphan CMs): tests/claims cover what you design to cover; latent bugs hide where no test or no reviewer reaches. Concrete reinforcement for OIDC-E2E-001 (programmatic OIDC flow tests in CI) — it is the standing verifier that would catch this class before a human/bot has to. Practice: after writing a fix, ask "what second copy / what unhandled response / what unverified consumer did I just NOT cover?" before claiming done.
**Tags:** `#code-review` `#codex` `#verification` `#process` `#kubelab`
