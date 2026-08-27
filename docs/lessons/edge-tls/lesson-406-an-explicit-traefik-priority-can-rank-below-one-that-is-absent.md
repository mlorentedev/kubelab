---
id: lesson-406-an-explicit-traefik-priority-can-rank-below-one-that-is-absent
type: lesson
status: active
created: "2026-08-27"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls, traefik, ingress, routing]
---

# An explicit Traefik priority can rank below one that is absent

**Context**: TOOLKIT-010 (#774) added a same-origin `/api` route on the web host,
so the frontend's relative `POST /api/subscribe` would reach the API instead of
the static site. The generator emitted a second rule on the same host,
`Host(...) && PathPrefix(`/api`)`, ahead of the existing host catch-all. The
issue advised setting `priority` explicitly "to be safe", and the
implementation used `priority: 10`.

**Problem**: The route generated correctly, drift was clean, 1578 tests passed,
Argo applied it — and it never matched. Measured on staging after the merge:

```
POST https://staging.mlorente.dev/api/subscribe  -> 404, server: nginx
GET  https://api.staging.kubelab.live/health     -> 200
```

The request still died in the web pod, which returned the static site's own 404.

Traefik gives a router **without** an explicit priority *the length of its rule*:

> "If a priority is not explicitly set, the system defaults to the length of the
> rule, where longer rules receive higher priority."
> "The smaller the number, the lower the priority. Every other router will be
> evaluated before this one."

So `` Host(`staging.mlorente.dev`) `` — 28 characters, no priority — sat at ~28,
and the new, longer, more specific rule sat at 10. The catch-all won. Setting
the priority is what demoted it: left unset, rule-length ordering would have
favoured the longer rule on its own.

**Solution**: default priority `10` -> `100`, comfortably above any realistic
rule length. The regression test asserts the relationship rather than the
literal, so it still fails if someone retunes the value downward:

```python
assert routes[0]["priority"] > len("Host(`staging.mlorente.dev`)")
```

**Rule**: A Traefik priority is only meaningful against the *computed* priorities
of its neighbours, and a neighbour with no `priority` field is not at zero — it
is at the length of its rule. Either set priorities on **every** router in the
same host group, or set none and let rule length rank them. A single explicit
number among implicit ones is the one combination that silently inverts the
order you intended.

And the wider one: this shipped with green CI, a correct manifest and a clean
drift gate. Only `curl` against the environment found it. A routing change is
not verified by the manifest that declares it.

**Tags**: `#traefik` `#ingress` `#routing` `#pr-1465` `#pr-1457`
