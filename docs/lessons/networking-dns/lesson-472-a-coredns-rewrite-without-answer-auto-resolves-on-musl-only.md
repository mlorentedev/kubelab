---
id: lesson-472-a-coredns-rewrite-without-answer-auto-resolves-on-musl-only
type: lesson
status: active
created: "2026-09-27"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, coredns, k3s, glibc]
---

# A CoreDNS regex rewrite without `answer auto` resolves on musl and fails on glibc

**Context**: The prod hairpin (`infra/k8s/base/edge/coredns-custom.yaml`, lesson-141) rewrites `(.*)\.kubelab\.live` to `traefik.kube-system.svc.cluster.local`, so pods reach public hostnames through Traefik's ClusterIP. The PR-Agent server (TOOL-080) received Gitea's webhook and then failed to call back `https://gitea.kubelab.live/api/v1/...`: `NameResolutionError ... Name or service not known`. Grafana, n8n and Authelia in the same namespace resolved the same name without trouble.

**Problem**: The rewrite changes the question but not the answer. CoreDNS returned `traefik.kube-system.svc.cluster.local. A 10.43.254.234` to a query for `gitea.kubelab.live`, which a raw UDP query from the pod showed. musl (Alpine: Grafana, n8n, Authelia) takes the address anyway. glibc (Debian/Ubuntu: the PR-Agent image, `python:*-slim`) drops an answer whose owner is not the name it asked for, and reports the host as unknown. So the hairpin had only ever worked for musl pods, and nothing tested a glibc client.

**Solution**: Add `answer auto` to each regex rewrite (CoreDNS >= 1.10; K3s ships 1.14.1). CoreDNS then rewrites the answer's owner back to the queried name. Reproduced before and after in local CoreDNS 1.14.1 containers: without it, `python:3.12-slim` and the PR-Agent image fail while `alpine` resolves; with it, all three resolve to the Traefik IP. `tests/test_coredns_hairpin_answer.py` requires `answer auto` on every regex rewrite.

**Rule**: A `rewrite name regex` that points a public name at an in-cluster name needs `answer auto`. Test in-cluster DNS from a glibc image, not only from whatever pod has a shell: musl hides this defect. To see the owner name, `dig +noall +answer`; `nslookup` prints it too, but `getent` on musl does not.

**Tags**: `#coredns` `#hairpin` `#glibc` `#tool-080`
