---
id: lesson-447-a-trusted-identity-header-is-as-wide-as-whatever-can-reach-the-port
type: lesson
status: active
created: "2026-08-26"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, grafana, auth-proxy, networkpolicy, forwardauth, pr-1424]
---

# A trusted identity header is as wide as whatever can reach the port

**Context**: Grafana sits behind Authelia's ForwardAuth middleware and runs
with `GF_AUTH_PROXY_ENABLED`, trusting the `Remote-User` header Traefik sets
after Authelia has authenticated the browser. Reviewed in #1424 (refs #1409).

**Problem**: The header is trusted unconditionally, and the Service is a plain
`ClusterIP` with nothing restricting who can talk to it. So the identity gate
lived in Traefik, but the port answered to everyone:

```
$ kubectl -n kubelab port-forward svc/grafana 18300:3000
$ curl -o /dev/null -w '%{http_code}' localhost:18300/api/user
401
$ curl -o /dev/null -w '%{http_code}' -H 'Remote-User: operator' localhost:18300/api/user
200
```

Any pod in the cluster, or anyone holding `services/proxy` or
`pods/portforward` RBAC, could become any Grafana user by naming one.
`GF_AUTH_PROXY_AUTO_SIGN_UP: "true"` widened it further: the user did not even
have to exist, so the header was an account creator as well.

**Solution**: A `NetworkPolicy` (`grafana-ingress-from-traefik-only`) that
admits ingress to the Grafana pod only from the Traefik pod, selected by
namespace and label. Not `GF_AUTH_PROXY_WHITELIST`: that wants an IP or CIDR,
Traefik's pod IP is not stable across a rebuild, and a hardcoded CIDR breaks
the SSOT rule. Auto sign-up switched off; both known identities already had
accounts. A static test pins the policy's selector and the flag so a later
edit that loosens either fails without a cluster.

Verified in staging: curl with the header from a throwaway pod went from
`200` to connection refused. `port-forward` still answers, and that is not a
gap: it is node-originated traffic most CNIs exempt from pod-selector
policies, and the RBAC that allows it already allows `exec` into the pod and
reading the admin Secret directly.

The AC4 audit found this was the only instance: Loki carries the same
middleware but consumes no identity header, and n8n and Homepage do not carry
the middleware at all.

**Rule**: A proxy-set identity header is an authentication decision made
upstream, and it is only as strong as the guarantee that nothing but that
upstream can reach the listener. Whenever a service trusts a header, ask what
else can open a connection to its port; if the answer is "any pod", the
header is a self-service login. Close it by selector on the caller, not by
address, and turn off any auto-provisioning that turns a spoofed name into a
real account.

**Tags**: `#auth-proxy` `#networkpolicy` `#forwardauth` `#grafana` `#pr-1424`
