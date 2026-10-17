---
id: lesson-528-a-setting-that-shares-a-name-across-two-systems-does-not-share-its-meaning
type: lesson
status: active
created: "2026-10-07"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, n8n, smtp, import, placeholders]
---

# A setting that shares a name across two systems does not share its meaning

**Context**: APP-CONFIG-018, rendering an n8n `smtp` credential from the `infra.smtp.*` SSOT
that the API and Authelia already read (#2088).

**Problem**: `infra.smtp.secure` is `true` and `infra.smtp.port` is `587`. n8n's credential
has a field called `secure` too, so the obvious render copies one to the other. They do not
mean the same thing: n8n's (nodemailer's) `secure: true` is implicit TLS, which only port 465
speaks, while port 587 is STARTTLS and needs `secure: false`. In the SSOT, `secure: true`
means "require TLS". Copied verbatim, the credential imports without a complaint and the
first email fails to connect, in production, on a workflow that is live from the moment it
is imported. A second thing surfaced in the same pass: the placeholder resolver logged every
value it substituted, which was harmless until a placeholder mapped to a SOPS-resident value
(the digest's recipient) and would have put it on the terminal.

**Solution**: `render_smtp_credential` derives `secure` from the port (`port == 465`) and a
test pins it for 465, 587 and 25. The field names were read from n8n's own
`Smtp.credentials.ts` at the pinned image tag, not recalled. The resolver now logs the token
and the path, never the value, and a test greps the output for sentinel secrets.

**Rule**: when a value crosses a system boundary, map its meaning, not its name, and read the
consumer's definition at the version you run. Pin the mapping with a test whose inputs make
the two readings disagree (587 with `secure: true`). And a log line that prints a substituted
value is a secret leak waiting for the first value that is one.

**Tags**: `#n8n` `#smtp` `#ssot` `#pr-2088`
