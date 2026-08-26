---
id: lesson-391-a-probe-that-sabotages-itself-reports-on-the-probe
type: lesson
status: active
created: "2026-08-24"
owner: manu
category: process-method
tags: [kubelab, process-method, verification, shell, diagnostic-scripts, secrets-show]
---

# Two ways a one-line probe reports on itself, and both look like a fact about the system

**Context**: AUTH-004 task 9 — authenticating against Grafana, MinIO and Authelia as the SSOT-resolved superadmin. Three attempts before one measured anything.

**Problem**: Neither failure was about the services.

1. **A default that only fires on empty.** The username came from `U=$(make -s secrets-show KEY=apps.auth.identities.superadmin ...)`, guarded with `${U:-manu}`. But that key is **plaintext config, not a secret**, so `secrets-show` returned a 74-character *error message* — non-empty, so the guard never fired, and the probe authenticated with 74 characters of prose as a username. Grafana said `401`. The 401 was the probe's.

   The tell was available and ignored: the same command was run against a real secret and returned 9 characters. A length check would have caught it instantly; a `-n` check could not.

2. **A pattern that matches its own shell.** Cleaning up a stale port-forward with `pkill -f "port-forward svc/grafana"` killed the shell running it, because that string was in its own command line. Exit 144, no output, and nothing about Grafana.

**Solution**: The probe became a script rather than a one-liner (the operator has a standing rule to prefer diagnostic scripts over interactive one-liners, and this is what it is for), with credentials in a curl config file instead of argv, an explicit port-forward readiness loop, and **two controls per service** — right user with wrong password, wrong user with right password. Only when both differed from the real attempt was the result trusted. Grafana then answered `401 / 401 / 200` and reported `login='manu' isGrafanaAdmin=True`.

**Rule**: When a probe fails, the first hypothesis is the probe, not the target — and check it by asserting on the *shape* of the inputs, not their presence. `${VAR:-default}` guards emptiness, never wrongness, so a command that prints errors to stdout defeats it silently; assert a plausible length or an expected pattern. For process cleanup, never `pkill -f` a pattern that appears in the invoking command line. And prefer the script: a one-liner has nowhere to put the readiness check and the controls that make its answer mean something. Pairs with [lesson-382](lesson-382-a-control-returning-the-same-code-as-the-real-attempt-measured-nothing.md) — there the control could not discriminate, here it never ran.

**Tags**: `#verification` `#shell` `#diagnostic-scripts` `#secrets-show` `#auth-004`
