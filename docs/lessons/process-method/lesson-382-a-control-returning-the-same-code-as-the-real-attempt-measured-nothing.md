---
id: lesson-382-a-control-returning-the-same-code-as-the-real-attempt-measured-nothing
type: lesson
status: active
created: "2026-08-23"
owner: manu
category: process-method
tags: [kubelab, process-method, verification, negative-control, minio, grafana, authelia]
---

# Discriminate the error code, and check that your control can even distinguish the answer

**Context**: Verifying which services had actually survived the 2026-08-23 prod credential rotation (#1355). Three consumers were in question — Gitea, MinIO and Grafana — and each was probed with the rotated credential.

**Problem**: Two separate ways a probe reports a result that is not about the thing being probed.

1. **Undiscriminated failure codes collapse distinct faults.** MinIO answering `InvalidAccessKeyId` and MinIO answering `SignatureDoesNotMatch` are both "auth failed" to a probe that only checks for success, but they demand opposite repairs: the first says *the identity no longer exists* (the access key was replaced, so the account must be recreated or the key re-pointed), the second says *the identity is right and the password diverged* (re-deliver the secret). Reading only "it failed" turns a two-minute fix into a search.
2. **A control that cannot return a different answer measures nothing.** The Grafana probe returned `302` and was read as Grafana rejecting the credential. It was Authelia's ForwardAuth redirect to the login page — every request to that host returns `302` regardless of the credential, including one with a deliberately wrong password, and including one with no credential at all. The negative control returned the same code as the real attempt, which is the definition of an experiment with no signal. Grafana's own verdict was never obtained, and Grafana's status stayed genuinely unknown while being reported as known-bad.

**Solution**: Report the exact code, not the boolean. For MinIO, `InvalidAccessKeyId` vs `SignatureDoesNotMatch` selected the repair. For Grafana, the finding was recorded as *unverified* rather than *broken* — the probe has to bypass or authenticate through the ForwardAuth layer before it can say anything about the backend, since `302` is the edge's answer and never the application's.

**Rule**: Before trusting a probe, run the control and require it to differ. If a deliberately-wrong input produces the same response as the real one, the probe is measuring a layer in front of the target and its result must be discarded, not interpreted. And when a service distinguishes its failure modes, propagate the distinction to the report: "auth failed" is a category, while `InvalidAccessKeyId` is a diagnosis. Pairs with [lesson-306](lesson-306-a-check-never-observed-failing-is-a-claim-in-.md) — a check never observed failing is a claim, not a control.

**Tags**: `#verification` `#negative-control` `#minio` `#grafana` `#authelia` `#issue-1355`
