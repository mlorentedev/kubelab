---
id: lesson-032-deploy-dns-yml-must-read-from-common-yaml-not
type: lesson
status: active
created: "2026-03-19"
owner: manu
tags: [kubelab, lesson]
---

# deploy-dns.yml must read from common.yaml, not merged config

**Context**: RPi4 CoreDNS serves DNS for ALL environments (staging + prod zones). Running `make deploy TARGET=dns ENV=staging` loaded staging.yaml override which sets `base_domain: staging.kubelab.live`.

**Problem**: The playbook derived `staging_domain = "staging." + base_domain` → `staging.staging.kubelab.live` (double prefix). The prod zone block also got `staging.kubelab.live` instead of `kubelab.live`. Services appeared to work because the wildcard `template` plugin caught queries despite the wrong zone name.

**Solution**: Read `base_domain` and all node IPs from `common` (raw common.yaml vars) instead of `config` (merged env override). RPi4 is env-independent — it serves all zones from a single config.

**Rule**: Multi-env DNS gateways must not depend on `--env` config merging. Use `common.*` for values that are env-independent (base domain, node IPs, service domains).
