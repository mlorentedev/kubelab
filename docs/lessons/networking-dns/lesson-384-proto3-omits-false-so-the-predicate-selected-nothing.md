---
id: lesson-384-proto3-omits-false-so-the-predicate-selected-nothing
type: lesson
status: active
created: "2026-08-24"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, headscale, json, incident]
---

# A predicate testing `== false` against proto3 JSON selects nothing, not "the false ones"

**Context**: the GCP hub's `cloud-init.yml` deletes its predecessor's Headscale
record before registering, because Headscale allocates by *given name* and a name
still held by an old record lands the newcomer as `gcp1-<random>`. The query was:

```bash
jq '.nodes[] | select(.givenName==$n and .online==false) | .id'
```

**Problem**: on 2026-08-24 a real Spot preemption rebuilt the hub in 18 seconds,
and the replacement registered as `gcp1-mj5bsge9`. `gcp1.kubelab.internal` kept
resolving to the dead node, the prod Argo CD EndpointSlice followed it there, and
`argo.kubelab.live` was down for 35 minutes.

The predicate had never worked. **proto3 JSON omits fields at their default
value**, so an offline node carries no `online` key at all:

```
id 39  given gcp1           has online key: False   <- the predecessor
id 40  given gcp1-mj5bsge9  has online key: True
```

`.online == false` therefore evaluates `null == false` → false. It does not
select offline nodes; it selects **none**, on every invocation since it shipped.
The node's own boot log had been saying so all along — `no stale Headscale node
to recycle`, printed while the record sat in the response it had just parsed.

A second hazard rode along: the CLI emits `given_name`, the REST gateway is
documented as camelCase, and nothing had verified which spelling that path
returns. A wrong guess there fails identically and silently.

**Solution**: drop the liveness test rather than repair it. At that point in boot
the node has not registered, so anything holding its hostname is by definition a
predecessor — its liveness was never information the query needed. Both field
spellings are accepted rather than picked:

```bash
jq '.nodes[] | select((.givenName // .given_name) == $n) | .id'
```

Verified against a preemption-equivalent drill: `deleted stale Headscale node 41
(gcp1)`, and the replacement reclaimed the canonical name with no human step.

**Rule**: in proto3-derived JSON, absence and false are the same thing on the
wire, so `== false` is never the test you want — check truthiness, or drop the
condition. More generally: a filter that silently matches nothing is
indistinguishable from a filter that correctly found nothing, and the difference
is only visible if something asserts the *positive* case at least once.

**Tags**: `#headscale` `#json` `#proto3` `#jq` `#incident` `#issue-1369`
