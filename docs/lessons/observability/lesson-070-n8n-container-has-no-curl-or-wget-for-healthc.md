---
id: lesson-070-n8n-container-has-no-curl-or-wget-for-healthc
type: lesson
status: active
created: "2026-02-25"
owner: manu
category: observability
tags: [kubelab, observability]
---

# n8n Container Has No curl or wget for Healthchecks

**Context**: Adding a healthcheck to the n8n service in Docker Compose.

**Problem**: The `n8nio/n8n` image does not include `curl`, `wget`, or any HTTP client. Standard Docker healthcheck patterns (`CMD curl -f http://localhost:5678`) fail immediately with `exec: "curl": executable file not found`.

**Solution**: Use the Node.js runtime that is already present in the image:
```yaml
healthcheck:
  test: ["CMD-SHELL", "node -e \"require('http').get('http://localhost:5678/healthz', (r) => { process.exit(r.statusCode === 200 ? 0 : 1) })\""]
  interval: 30s
  timeout: 10s
  retries: 3
```

**Rule**: Before writing a healthcheck, verify which HTTP clients are available in the image (`docker run --entrypoint sh image which curl wget node`). For Node.js-based images without curl, use the built-in `require('http').get(...)` pattern.

---
