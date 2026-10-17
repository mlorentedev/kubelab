---
id: lesson-390-a-control-cannot-discriminate-where-both-inputs-are-equal
type: lesson
status: active
created: "2026-08-24"
owner: manu
category: process-method
tags: [kubelab, process-method, verification, staging, negative-control, auth-004]
---

# The environment you can safely test in may be the one where your control cannot tell the two answers apart

**Context**: AUTH-004 AC1 — making every service's admin identity resolve from `apps.auth.identities` instead of from `BASIC_AUTH_USER`, the Traefik basic-auth account. The acceptance criterion says to deploy to staging and authenticate against each service live, and that "a config diff is not evidence".

**Problem**: `make apply-secrets ENV=staging` reported **every** secret `unchanged`, including the two the change was about. That is not evidence the change works; it is evidence it made no difference *there*:

```
staging  basic_auth.user == 'manu'?  SI
common   basic_auth.user == 'manu'?  NO (len=57)
```

**In staging the old alias and the new SSOT resolve to the same value.** The generated secrets are byte-identical either way, so a live staging login passes against the old resolution path exactly as happily as against the new one. Running the criterion as written would have produced a green transcript that demonstrated nothing about the thing under test.

This is a different failure from [lesson-382](lesson-382-a-control-returning-the-same-code-as-the-real-attempt-measured-nothing.md), where the *control* returned the same code as the real attempt. Here the control is fine and the **inputs are identical in this environment** — and the environment was chosen precisely because it is the safe one.

**Solution**: The evidence was split deliberately, and both halves recorded. The **resolution source** is proven by a unit fixture that sets the two values differently and asserts the basic-auth account appears in no generated secret — the only place they can be told apart. **Non-regression** is proven live in staging, which is what staging can honestly say. The verification file states which half is which, so nobody later reads the live transcript as proof of the source.

**Rule**: Before running an acceptance test in a safe environment, check that the two hypotheses actually differ *there*. Ask what value the old path and the new path each produce, and if the answer is the same string, the environment cannot discriminate and the test's result must be labelled accordingly — non-regression, not correctness. Where prod and staging hold different values for one key, that divergence is itself worth reporting: it means the two environments have silently disagreed about something, which is how this was found at all. Pairs with [lesson-306](lesson-306-a-check-never-observed-failing-is-a-claim-in-.md).

**Tags**: `#verification` `#negative-control` `#staging` `#ssot` `#auth-004`
