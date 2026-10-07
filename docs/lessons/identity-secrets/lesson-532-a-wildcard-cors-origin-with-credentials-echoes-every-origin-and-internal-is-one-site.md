---
id: lesson-532-a-wildcard-cors-origin-with-credentials-echoes-every-origin-and-internal-is-one-site
type: lesson
status: active
created: "2026-10-07"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, cors, open-webui, tailnet]
---

# A wildcard CORS origin with credentials echoes every origin, and `.internal` is one site

**Context**: AI-009, Open WebUI v0.11.4 on ace2, reached only over the tailnet at
`http://ace2.kubelab.internal:3080`. Its log said at every start that
`CORS_ALLOW_ORIGIN` was `*`, which read as harmless for a service nobody outside
the tailnet can reach.

**Problem**: v0.11.4 passes that `*` to Starlette's `CORSMiddleware` with
`allow_credentials=True`. Browsers refuse a literal `*` on a credentialed
response, so Starlette, to make it work, echoes the request's `Origin` whenever
the request carries a cookie. Measured with `Origin: https://evil.example` and
any cookie: `access-control-allow-origin: https://evil.example`,
`access-control-allow-credentials: true`. socket.io took the websocket upgrade
from that origin too (`101`).

The `SameSite=lax` auth cookie looks like the backstop, and it is not one here.
"Same site" is decided by the public suffix list, and `.internal` is not on it,
so every `*.kubelab.internal` host on the tailnet is the same site as Open WebUI.
A page served by any of them gets the cookie sent, and the echo then lets it
read the answer.

**Solution**: `CORS_ALLOW_ORIGIN` set to the one origin pages are served from,
derived from the same values as `WEBUI_URL` (#2109). Measured afterwards: foreign
origins get no `access-control-allow-origin` and a `403` on the upgrade; the
own origin gets both; the start-up warning is gone.

**Rule**: A tailnet-only address does not make a CORS wildcard safe. With
credentials on, `*` means "echo anyone". And a private TLD is a single site, so
`SameSite` does not separate the services under it. Set the origin list
explicitly, then probe it with a foreign `Origin` and a cookie, because the
config alone does not show the echo.

**Tags**: `#cors` `#samesite` `#open-webui` `#issue-2109`
