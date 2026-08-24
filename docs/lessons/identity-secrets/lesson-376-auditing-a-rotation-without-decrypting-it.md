---
id: lesson-376-auditing-a-rotation-without-decrypting-it
type: lesson
status: active
created: "2026-08-23"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, sops, audit, verification]
---

# A SOPS diff answers "did this key change" without decrypting anything — until the file is rewritten whole

**Context**: Four secrets were printed in plaintext during a study session on
2026-08-20. The spec recorded "the operator reports them rotated; this task is
the audit that confirms it". The audit had never run, and running it could not
mean decrypting the vault to compare values — the transcript doctrine forbids
exactly that.

**Problem**: Verifying a rotation appears to require reading the secret. It does
not. SOPS encrypts values individually and **preserves the ciphertext of values
it does not edit**, so `git diff --numstat` over the encrypted file answers the
question without any value reaching stdout:

```
$ git diff --numstat df9e1e1 origin/master -- infra/config/secrets/common.enc.yaml
10  2   infra/config/secrets/common.enc.yaml
```

Ten additions, two removals. The additions were two new `gcp.*` keys and four
`push_tokens.*`; the removals were `lastmodified` and `mac`. **Zero existing
keys rewritten** — so nothing had been rotated, contradicting the record.

The additions are what make that a result rather than a silence: they prove the
diff can see a change at all. Without a positive control, "no lines changed" is
indistinguishable from "I looked in the wrong place".

**The limit, found the same day.** Hours later the same method was applied after
`credentials-generate` and reported that all four *immutable* secrets had
changed — which would have meant a destroyed Authelia database. They had not.
That command **rewrites the whole file**, so SOPS re-encrypts every value with a
fresh nonce and every ciphertext changes regardless of content. The method is
valid for incremental writes (`sops set`) and worthless after a full
regeneration.

**Solution**: Audit by ciphertext, always with a positive control, and first
establish which kind of write produced the diff. `toolkit secrets set` and the
new `secrets rotate` use `sops set` and stay auditable; `credentials generate`
does not. Where ciphertext cannot answer, ask the issuer instead — `toolkit
secrets check-expiry` reads key prefixes and expiry dates off Headscale over
SSH, which identified two API keys unambiguously by their expiry dates without
decrypting either.

**Rule**: To verify a secret changed, compare its ciphertext across commits —
never its value. Include a key you know changed as a positive control, or a
negative result is an unanswered question. And check how the file was written
before trusting the diff: a whole-file re-encryption makes every ciphertext
change and tells you nothing.

**Tags**: `#sops` `#audit` `#verification` `#pr-1335` `#pr-1349`
