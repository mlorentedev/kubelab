---
id: lesson-458-a-second-login-door-that-answers-first-replaces-the-one-you-configured
type: lesson
status: active
created: "2026-09-24"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, grafana, authelia, auth-proxy, oidc]
---

# A second login door that answers first replaces the one you configured, and yours never runs

**Context**: #1818 fixed Grafana's OAuth role path so that Authelia's `admins`
group maps to Admin. The review was re-run after the deploy, and `operator`, in
`admins`, was still Viewer. Its Grafana profile said "Synced via Auth Proxy".

**Problem**: Grafana had two login mechanisms enabled at once:

- The **auth proxy** (`GF_AUTH_PROXY_ENABLED=true`) trusted the `Remote-User`
  header that Authelia's ForwardAuth adds to every request on the route.
- **Generic OAuth**, which carried the role mapping.

The proxy authenticates on the header before Grafana renders its login page. So
every browser session through the route was a proxy login, and the OAuth button,
with the role mapping behind it, was unreachable. The proxy maps no role: every
account got the default, Viewer. `manu` looked right only because it is the local
admin account. All six accounts in both environments carried only the "Auth
Proxy" label, so no OAuth login had ever succeeded.

Each mechanism was correct on its own, and each had its own tests. The defect was
that both existed, and nothing asked which one a real login actually went through.

**Solution**: One door. `GF_AUTH_PROXY_ENABLED=false` and
`GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN=true`: `/login` goes straight to Authelia, and
the role is synced from `groups` on every login. The ForwardAuth middleware stays
on the route as a perimeter, but Grafana trusts no header. The break-glass path
opens `/login?disableAutoLogin=true` over the port-forward, because the root now
redirects to the IdP, the one thing that is down when break-glass is in use.
`tests/test_grafana_login_door.py` pins all three. Moving the existing accounts
across is lesson-459.

**Rule**: When an app can authenticate in more than one way, the mapping you
configured only matters for logins that go through it. Verify a tier with a real
login through the real route, then read which mechanism the app says it used.
Reading the mapping's config tells you nothing about which door the login took.
Retire the doors you do not mean to keep. See also lesson-447: a trusted header is
as wide as whatever can reach the port.

**Tags**: `#grafana` `#auth-proxy` `#oidc` `#single-door` `#auth-004`
