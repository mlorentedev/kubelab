---
id: "kubelab-runbook-acme-alerting"
type: runbook
status: active
tags: [runbook, kubelab, acme, certificates, alerting, traefik, grafana]
created: "2026-08-10"
last_tested: "2026-08-10"
owner: manu
---
# ACME certificate failure — what the alert means and what to do

> Triage for the **ACME certificate failure** alert (OBS-007, #799). It fires
> when Traefik reports that it could not obtain a certificate. Left alone, the
> affected certificate expires and the service starts serving a browser error.

> **Tested 2026-08-10.** The failure was induced deliberately in staging rather
> than waited for, using the procedure in "Testing this alert" at the end. The
> alert fired, the notification arrived, and it cleared on teardown.

## Why this alert exists

Traefik renews certificates on its own at 30 days remaining, and for years that
worked well enough that nobody watched it. Then in June 2026 staging's renewals
failed for roughly five weeks behind a stale Cloudflare API token, and the
failure was found by a browser error rather than by any alert.

The gap was never the renewal. It was that a renewal which stops working leaves
no signal anywhere a human looks. While writing the spec for this alert, the
first Traefik log line Loki returned for **prod** was a live ACME error that had
been repeating roughly once a day for months, entirely unobserved (#927).

So: **this alert firing is good news.** It means the thing that used to fail
silently now announces itself.

## What you will receive

A Telegram message, routed by environment — prod goes to the push channel
(`page`), staging to the archive channel (`log`):

```
kubelab · page · firing: ACME certificate failure
Traefik reported an ACME failure. Certificates are not renewing, and they
will expire silently unless this is fixed.
Domain: loki.internal.kubelab.local
Started: 2026-08-09 17:04:00 +0000 UTC
Source: https://grafana.kubelab.live/
```

`Domain` comes from the log line's `domains=` field. **It can be empty** — that
is not a bug. The rule deliberately still fires on ACME errors whose shape does
not carry that field, because the alternative would be dropping a failure mode
nobody has observed yet. An empty domain means "go read the logs", not "no
domain affected".

`Source` identifies the environment via Grafana's own external URL, so staging
and prod are distinguishable without a per-environment label.

## Triage

### 1. Read the actual error

The alert tells you a failure happened; the log line tells you why.

```bash
kubectl --kubeconfig ~/.kube/kubelab-<env>-config \
  logs -n kube-system -l app.kubernetes.io/name=traefik --tail=400 \
  | sed 's/\x1b\[[0-9;]*m//g' | grep -iE 'acme.*(err|unable|fail)'
```

The `sed` is not optional. Traefik colours its output, and the escape codes make
the lines painful to read and break naive `grep` patterns that span a field
boundary — the same property that made the alert's own regexp non-obvious.

### 2. Match it against the known causes

| What the error says | Cause | Fix |
|---|---|---|
| `rejectedIdentifier … does not end with a valid public suffix` | A router requests a certificate for a non-public TLD (`.local`, `.internal`) that Let's Encrypt can never issue | Remove `certResolver` from that IngressRoute. Use an explicit `certResolver: null` in the overlay patch — **not** `tls: {}`, which means "change nothing" and silently keeps the resolver (this exact bug ran for months, #927) |
| `unauthorized` / `403` from the DNS provider | The Cloudflare API token is stale or lost its permissions | Rotate it in SOPS, then `make apply-secrets ENV=<env>` and restart Traefik. This was the June 2026 five-week outage |
| `too many certificates already issued` | Let's Encrypt rate limit: 5 certificates per identical domain set per 168h | Wait it out. Then check ACME persistence — if `/data/acme.json` is on an `emptyDir`, every pod restart discards certificates and requests new ones, which is how the limit gets hit at all |
| `timeout` during DNS-01 propagation | The challenge TXT record is not visible to the resolver in time | Usually transient; Traefik retries. If persistent, check the `dnschallenge.resolvers` argument on the Traefik pod |

### 3. Confirm the fix

The rule clears on its own once the failures stop appearing in the 10-minute
window, and a `resolved` message is delivered. Do not assume — wait for it. A
rule that fires and never clears is a rule people learn to ignore, so the
recovery path is part of what is being verified here.

```bash
# Should return nothing once healthy.
kubectl --kubeconfig ~/.kube/kubelab-<env>-config \
  logs -n kube-system -l app.kubernetes.io/name=traefik --tail=200 \
  | sed 's/\x1b\[[0-9;]*m//g' | grep -iE 'acme.*(err|unable|fail)'
```

## What this alert does NOT cover

It watches for **failures Traefik reports**. It does not watch time-to-expiry, so
it will not catch a certificate quietly ageing out because nothing ever tried to
renew it — for example if a router was removed from Traefik's configuration while
the certificate stayed in `acme.json`.

That lagging net is deliberately out of scope for OBS-007 and is tracked
separately: Uptime Kuma's built-in certificate-expiry notification on the RPi3,
plus a scheduled run of `tests/e2e/test_tls_routing.py` for staging.

## Testing this alert

Waiting for a real failure is not a test. Induce one:

```bash
# 1. Apply a router asking for a certificate Let's Encrypt cannot issue.
#    A `.local` host is rejected at the new-order step, BEFORE any DNS-01
#    challenge — so nothing is written to Cloudflare and no failed-validation
#    rate limit is consumed. It also reproduces the exact shape of the real
#    prod failure rather than a different one that happens to be convenient.
kubectl --kubeconfig ~/.kube/kubelab-staging-config apply -f - <<'EOF'
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: obs007-induced-failure
  namespace: kubelab
spec:
  entryPoints: [websecure]
  routes:
    - match: Host(`obs007-induced-failure.kubelab.local`)
      kind: Rule
      services:
        - name: grafana
          port: 3000
  tls:
    certResolver: letsencrypt
EOF

# 2. Traefik attempts the order within seconds. The rule evaluates every 5m and
#    holds for 5m, so expect Alerting within roughly 10-11 minutes.

# 3. Tear down, and confirm the rule returns to Normal with a resolved message.
kubectl --kubeconfig ~/.kube/kubelab-staging-config \
  delete ingressroute obs007-induced-failure -n kubelab
```

**Do this in staging.** Staging routes to the archive tier, so it does not
interrupt anyone; prod routes to the push tier and would.

## Related

- Spec: `specs/OBS-007-cert-expiry-alerting/`
- `docs/lessons.md` — MON-001 (automation without observation), and the
  2026-08-10 entry on provisioning success not being delivery success
- **ADR-044** — Apprise owns the tag→URL map, which is why the contact point
  carries no credential
- **#927** — the live prod ACME failure this alert would have caught
