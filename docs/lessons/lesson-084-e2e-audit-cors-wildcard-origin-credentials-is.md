---
id: lesson-084-e2e-audit-cors-wildcard-origin-credentials-is
type: lesson
status: active
created: "2026-02-28"
owner: manu
tags: [kubelab, lesson]
---

# E2E Audit: CORS Wildcard Origin + Credentials Is Invalid

**Context**: E2E test suite examining API middleware. Inspected `middleware.go`.

**Problem**: The CORS middleware sets `Allow-Origin: *` AND `Allow-Credentials: true`. Per RFC 6454 and the Fetch specification, this combination is invalid — browsers will refuse to send cookies with cross-origin requests when the server responds with `*` as the origin. This means any browser-based client using cookies (e.g., authenticated API calls from the web frontend on a different domain) will silently fail.

**Solution**: Either: (a) set `Allow-Origin` to the specific frontend domain(s) instead of `*`, or (b) remove `Allow-Credentials: true` if cookies aren't needed. Option (a) is correct for the web app.

**Rule**: Never combine `Access-Control-Allow-Origin: *` with `Access-Control-Allow-Credentials: true`. If you need credentials, explicitly list allowed origins.

---
