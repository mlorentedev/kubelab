---
id: lesson-137-k8s-ingressroute-port-must-match-service-port
type: lesson
status: active
created: "2026-03-20"
owner: manu
tags: [kubelab, lesson, k8s, traefik, ingressroute, debugging]
---

# K8s IngressRoute port must match Service port, not container port

**Context:** Prod K3s deployment — web service returning 404 despite pod Running and healthy
**Problem:** Web IngressRoute had port: 8080 (container port) but Service exposed port: 4321. Traefik sends traffic to Service port, not container port. Request never reached the pod.
**Solution:** IngressRoute service port must match the Service spec.ports[].port (4321), not the container's containerPort (8080). Service targetPort handles the translation to container port.
**Tags:** `#k8s` `#traefik` `#ingressroute` `#debugging`
