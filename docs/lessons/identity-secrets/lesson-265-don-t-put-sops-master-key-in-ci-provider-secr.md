---
id: lesson-265-don-t-put-sops-master-key-in-ci-provider-secr
type: lesson
status: active
created: "2026-05-23"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# Don't put SOPS master key in CI provider secrets — use self-hosted-runner-local key

**Context:** CI-GATE-002 Phase 2 needed SOPS decryption in CI to extend the drift gate coverage to all generated paths. Default reflex was "add `SOPS_AGE_KEY` as a GitHub Actions secret". User pushed back: "no me siento cómodo poniendolo en internet".
**Problem:** A SOPS age key in GitHub Actions secrets is broader exposure than it looks: (a) anyone with repo admin can read it decrypted via the API; (b) a workflow with a subtle bug (e.g., `echo $SOPS_AGE_KEY`) leaks despite GH `***` masking only on direct env var references; (c) supply-chain attacks on third-party Actions in the same workflow get the key for free; (d) the key decrypts EVERY secret in the vault including prod credentials, not just the ones the gate needs. Drift validation does not need write authority — but the master key has it.
**Solution:** For projects that already use a self-hosted runner (ADR-030 in this repo), the proper pattern is: the age private key lives on the runner's host filesystem (`~/.config/sops/age/keys.txt`, the same location the user already maintains for local SOPS work). The workflow reads from disk; GitHub never sees the key. Fork PRs continue on `ubuntu-latest` and skip the SOPS-dependent steps — they don't have access to the runner's filesystem. This trades cloud-portability for sharply reduced exposure surface. Long-term alternatives worth considering when adding new infra: GitHub OIDC → cloud KMS for ephemeral key release; Sealed Secrets (Bitnami) for cluster-side-only decrypt with repo-safe CRDs (tracked as SEAL-001..004 + SEC-AGE-001). Don't default to "stuff it in provider secrets" without naming the exposure.
**Tags:** `#security` `#ci` `#sops` `#patterns`
