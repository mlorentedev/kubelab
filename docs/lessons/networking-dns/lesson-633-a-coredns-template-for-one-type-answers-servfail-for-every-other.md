---
id: lesson-633-a-coredns-template-for-one-type-answers-servfail-for-every-other
type: lesson
status: active
created: "2026-10-26"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, coredns, musl, staging]
---

# A CoreDNS template for one type answers SERVFAIL for every other type, and musl fails the lookup

**Context**: Staging Vikunja's `wait-for-idp` init container, a busybox image,
waited for `auth.staging.kubelab.live` to resolve and never got there. The pod
stayed in `Init` for eight days. Every glibc client, and `dig A` from any node,
resolved the name.

**Problem**: rpi4's CoreDNS answers the names under `staging.kubelab.live` with
`template IN A` (#2269). A query of any other type falls through that block
with nothing after it to answer, so the chain ends and CoreDNS replies SERVFAIL.
Measured with the pinned `coredns/coredns:1.12.1` and the rendered zone:

| query | before |
|---|---|
| `auth.staging.kubelab.live A` | NOERROR, ace1 |
| `auth.staging.kubelab.live AAAA` | SERVFAIL |
| `auth.staging.kubelab.live HTTPS` | SERVFAIL |
| `staging.kubelab.live AAAA` | NOERROR, empty (from `hosts`) |

glibc sends A and AAAA, takes the A answer and drops the failure. musl (Alpine,
busybox) sends both at once and fails the whole lookup when either one fails.
The apex was never affected, since `hosts` answers NODATA for a name it knows,
which is why a check that read the apex saw nothing wrong. The in-cluster path
logs nothing either: `coredns-custom` forwards the zone to rpi4 without `log` or
`errors`. Lesson-472 is the same split the other way round, a rewrite that
musl accepted and glibc did not.

**Solution**: a second block after the A template answers every other type for
the same names with NODATA, an empty NOERROR carrying the zone's SOA so
resolvers cache it (RFC 2308):

```
template IN ANY staging.kubelab.live {
    match .*\.staging\.kubelab\.live
    rcode NOERROR
    authority "staging.kubelab.live. 60 IN SOA ns.staging.kubelab.live. hostmaster.staging.kubelab.live. 1 7200 1800 1209600 60"
    fallthrough
}
```

Template blocks chain in Corefile order, and a type mismatch with `fallthrough`
moves on to the next block, so A still gets its address from the first one.
The second block's `fallthrough` is what lets the apex, which matches no
pattern, reach `hosts`. `tests/test_coredns_staging_nodata.py` runs the
rendered zone in the pinned image and asks it over UDP. Three mutations (`ANY`
narrowed to `TXT`, the SOA removed, the `fallthrough` removed) each turn it red.

**Rule**: a zone whose names are answered by a `template` for one type needs an
answer for every other type too, or every client that asks for AAAA, HTTPS or
MX gets SERVFAIL. Check a CoreDNS zone with `dig AAAA` and `dig HTTPS` against a
name under it, never with `dig A` against the apex alone. When a name resolves
on one libc and fails on the other, look first at a query type that only one of
them sends or acts on.

**Tags**: `#coredns` `#musl` `#dns-005` `#issue-2711`
