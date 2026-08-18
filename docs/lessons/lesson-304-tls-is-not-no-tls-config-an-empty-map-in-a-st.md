---
id: lesson-304-tls-is-not-no-tls-config-an-empty-map-in-a-st
type: lesson
status: active
created: "2026-08-09"
owner: manu
tags: [kubelab, lesson, kustomize, strategic-merge, traefik, acme, letsencrypt, loki, silent-failure, drift-detection, obs-007, gotcha]
---

# `tls: {}` is not "no TLS config" — an empty map in a strategic-merge patch changes nothing

**Context:** While building the cert-expiry alerting for OBS-007, the first Traefik log line Loki returned for prod was a live ACME error, timestamped minutes earlier:

```
ERR Unable to obtain ACME certificate for domains
error="...for the domains [loki.internal.kubelab.local]: acme: error: 400
   POST https://acme-v02.api.letsencrypt.org/acme/new-order"
```

Traefik in production was asking Let's Encrypt for a certificate covering a `.local` domain — something LE can never issue, since it only certifies public TLDs.

**Problem:** The prod overlay already carried what looked like the fix, complete with a comment stating the intent:

```yaml
tls: {}  # No certResolver — .local TLD can't get ACME certs
```

It does nothing. In a strategic-merge patch an empty map means *"change nothing about this field"*, so the base's `certResolver: letsencrypt` merged straight through. The live resource confirmed it, and so did the source: `kubectl kustomize infra/k8s/overlays/prod` emitted `tls: {certResolver: letsencrypt}`. The patch had been asserting a property it never established, and prod had been retrying an impossible order roughly once a day for months.

Two things kept it invisible. Nothing alerts on Traefik's ACME failures — the very gap OBS-007 exists to close, which is why the bug surfaced while building the detector rather than from the failure itself. And `config-check-drift` passes green here: the committed overlay and the generator agree perfectly. Drift detection compares intent against intent; it cannot notice that the intent does not do what its comment claims. That is the same shape as the Pollex dashboard entry found earlier the same day — a green check over a false statement.

The measurement also corrected the alarm. The instinct on seeing a repeated ACME failure in prod is Let's Encrypt rate limits, which would threaten *legitimate* renewals. Counting the occurrences gave one per 24 h — Traefik's retry cadence for a failed order, nowhere near any published limit. A real defect, but not the urgent one it first appeared to be.

**Solution:** `certResolver: null`. An explicit null is what deletes a key; verified by rendering the overlay and reading the emitted `tls:` block, which became `{}` while the other 94 resources were unchanged. The CLAUDE.md gotcha was rewritten from "Patched to `tls: {}`" — which described an intention — to name the null explicitly and warn against the empty-map form.

**Rule:** An empty map is not a deletion. When a patch is meant to *remove* something, verify by rendering the output and reading the field, never by reading the patch — and treat a comment describing what a patch achieves as a claim awaiting evidence, especially when it sits directly beside the code that fails to achieve it. More generally: a config that silently fails open leaves no trace in the thing it configures, so the only place it shows up is the runtime logs of the component downstream. If nothing watches those logs, the config is unfalsifiable.

**Tags:** `#kustomize` `#strategic-merge` `#traefik` `#acme` `#letsencrypt` `#loki` `#silent-failure` `#drift-detection` `#obs-007` `#gotcha`

---
