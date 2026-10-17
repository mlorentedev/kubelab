---
id: "lesson-561-a-retired-service-lives-on-in-every-doc-that-names-its-host"
type: lesson
status: active
title: "A retired service lives on in every doc that names its host, and a pasted config copy rots twice"
created: "2026-10-11"
owner: manu
category: process-method
tags: [kubelab, process-method, docs, dns]
---

# A retired service lives on in every doc that names its host, and a pasted config copy rots twice

**Context**: The blog was killed on 2026-03-15. `common.yaml` records it, #1010 removed it from the toolkit and #1530 from the health checks. Checking a runbook during the #2212 DNS work on 2026-10-11 turned up `curl -f https://blog.kubelab.live` as a verification step.

**Problem**: Every retirement had cleaned the code and the config, and none had cleaned the prose. One sweep found the blog in seven runbooks, `web.staging.kubelab.live` (staging web has been `staging.mlorente.dev` since WEB-001) in six steps, an Argo CD hub "on aws1" two months after aws1 was destroyed, and whole troubleshooting sections for Portainer, Vaultwarden and Headplane, none of which is deployed anywhere. The worst was the runbook's Corefile reference: a pasted copy of `edge/dns-gateway/Corefile`, a file that no longer exists. Its content had drifted from the template that replaced it, so it was wrong twice, once in where it pointed and once in what it said. Staging hides all of this from a smoke test: its wildcard resolves any name, so a stale step fails at Traefik, not at DNS, and reads like the service being down.

**Solution**: The dead names were fixed or removed, and the Corefile copy became a pointer to `infra/ansible/roles/coredns/templates/Corefile.j2`. `tests/test_runbook_hostnames_are_published.py` now holds the line. Every prod name in runbooks, troubleshooting and architecture docs must be in `infra/terraform/dns/services.json`, and every staging name must appear in a manifest under `infra/k8s/base` or the staging overlay. Exceptions are a shrink-only list, each tied to its ticket.

**Rule**:
- A retirement is finished when the prose is clean, not the code: grep `docs/` for the host as part of removing the service, and let a test hold the line.
- For a staging name, the check is what the manifests route, never what DNS answers. A wildcard zone resolves every name it is asked.
- Point at a generated or templated file; never paste it into a doc. A copy drifts both in path and in content, and nothing compares it with the source.

**Tags**: `#docs-drift` `#retirement` `#wildcard-dns` `#issue-825`
