---
id: lesson-456-a-parent-domain-cookie-shadows-a-same-named-cookie-in-a-child-environment
type: lesson
status: active
created: "2026-09-24"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, authelia, cookies]
---

# A session cookie on a parent domain shadows a same-named cookie in a child environment, so login succeeds and access is anonymous

**Context**: The operator logged into staging Authelia as `manu` to reach
Grafana. It was the first staging login in a browser that already held a prod
session.

**Problem**: Authelia logged `Successful 1FA authentication attempt made by
user 'manu'`. In the same second, the redirect to Grafana arrived at ForwardAuth
as `<anonymous>` and bounced back to the portal, three times in a row. From the
browser it looked like a wrong password or a broken redirect. Both environments
named their cookie `authelia_session`. Prod's is scoped to `kubelab.live`, which
browsers also send to every `*.staging.kubelab.live` host, so staging received
two cookies with one name. It read prod's, found no such session in its own
Redis, and treated the user as anonymous. Nothing errors anywhere.

**Solution**: #1805. Staging's cookie is `authelia_session_staging`.
`tests/test_authelia_session_cookies.py` reads every environment's Authelia
config and fails when two of them share a name on domains where one covers the
other. Proved with a session carrying both cookies: before, a 302 back to the
portal; after, a 200.

**Rule**: Any cookie scoped to a parent domain reaches every environment nested
under it. Environments that nest by domain need distinct cookie names, not only
distinct domains. When Loki shows a successful login immediately followed by an
anonymous request, look at which cookies the browser sends before looking at
the password.

**Tags**: `#authelia` `#cookies` `#session` `#issue-1805` `#auth-004`
