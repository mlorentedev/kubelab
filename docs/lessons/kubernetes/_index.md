# Cluster, workloads and manifests

51 lessons, newest first. Back to [all categories](../_index.md).

| # | Lesson | Date |
|---|---|---|
| 387 | [A shell program embedded in a manifest is a second language, and nothing in the delivery path reads it as one](lesson-387-a-shell-program-inside-a-manifest-is-a-second-language-nothing-validates.md) | 2026-08-25 |
| 351 | [A manual `kubectl apply` annexes the fields it touches, and the bill arrives months later](lesson-351-a-manual-kubectl-apply-annexes-the-fields-it-touches.md) | 2026-08-19 |
| 003 | [`Burstable` QoS proved the wrong container had a request (IDP-031)](lesson-003-burstable-qos-proved-the-wrong-container-had-.md) | 2026-08-17 |
| 328 | [`kubectl apply` cannot convert a Service with a selector into a selector-less one — omitting a field is not deleting it](lesson-328-kubectl-apply-cannot-convert-a-service-with-a.md) | 2026-08-14 |
| 327 | [K3s's built-in ServiceLB masks every client's real IP — `externalTrafficPolicy: Local` cannot fix it](lesson-327-k3s-s-built-in-servicelb-masks-every-client-s.md) | 2026-08-14 |
| 318 | [`kubectl describe pod`'s "Reason" field distinguishes OOM from a probe-triggered kill — a bare exit 137 does not](lesson-318-kubectl-describe-pod-s-reason-field-distingui.md) | 2026-08-12 |
| 317 | [`kubectl exec` with a CLI that boots a full runtime shares the pod's own cgroup](lesson-317-kubectl-exec-with-a-cli-that-boots-a-full-run.md) | 2026-08-12 |
| 343 | [Elapsed time inside a long session is not a measurement — pull the authoritative clock](lesson-343-elapsed-time-inside-a-long-session-is-not-a-m.md) | 2026-08-09 |
| 305 | [A LimitRange can *reject* pods — the guardrail has the same failure mode as the thing it guards (IDP-031)](lesson-305-a-limitrange-can-reject-pods-the-guardrail-ha.md) | 2026-08-09 |
| 293 | [`kubectl create secret` leaks every value into `/proc/<pid>/cmdline` — render the manifest in-process and apply over stdin (SEC-SECRETS-001)](lesson-293-kubectl-create-secret-leaks-every-value-into-.md) | 2026-07-09 |
| 291 | [`kubectl create secret \| kubectl apply -f -` REPLACES the whole Secret — a partial render silently deletes keys (TOOL-018)](lesson-291-kubectl-create-secret-kubectl-apply-f-replace.md) | 2026-07-08 |
| 282 | [Read-write Traefik config GUIs are rejected: IaC/SSOT inversion + K3s CRD-incompatible](lesson-282-read-write-traefik-config-guis-are-rejected-i.md) | 2026-06-20 |
| 019 | [caronc/apprise OOMKilled on k8s — cap APPRISE_WORKER_COUNT, don't inherit the host-core default](lesson-019-caronc-apprise-oomkilled-on-k8s-cap-apprise-w.md) | 2026-06-14 |
| 276 | [Apprise tags only resolve in stateful mode — Option B needs `simple` mode + a mounted config, not stateless](lesson-276-apprise-tags-only-resolve-in-stateful-mode-op.md) | 2026-06-14 |
| 272 | [Kubernetes `subPath` mounts freeze content — silently breaks app-level watch and live Secret updates](lesson-272-kubernetes-subpath-mounts-freeze-content-sile.md) | 2026-05-25 |
| 249 | [Helm upgrade on disk-constrained node creates pull-evict-prune-pull death loop](lesson-249-helm-upgrade-on-disk-constrained-node-creates.md) | 2026-05-10 |
| 248 | [Activating aggressive GC threshold on a backlog cluster needs manual pre-cleanup](lesson-248-activating-aggressive-gc-threshold-on-a-backl.md) | 2026-05-10 |
| 247 | [K3s server can deadlock on futex after bulk-delete; restart releases the lock](lesson-247-k3s-server-can-deadlock-on-futex-after-bulk-d.md) | 2026-05-10 |
| 237 | [2026-03-29: ArgoCD staging sync error after Helm upgrade — stale repo-server connection](lesson-237-2026-03-29-argocd-staging-sync-error-after-he.md) | 2026-05-01 |
| 123 | [2026-03-16: Helm Migration Strategy (ADR-021)](lesson-123-2026-03-16-helm-migration-strategy-adr-021.md) | 2026-05-01 |
| 230 | [2026-03-28: aws1 t4g.micro Helm upgrade always causes swap thrashing — mitigate before deploy](lesson-230-2026-03-28-aws1-t4g-micro-helm-upgrade-always.md) | 2026-05-01 |
| 232 | [2026-03-28: t4g.micro cannot survive repeated Helm upgrade retries — stop after first failure](lesson-232-2026-03-28-t4g-micro-cannot-survive-repeated-.md) | 2026-05-01 |
| 234 | [2026-03-28: ArgoCD Helm chart RBAC key is `configs.rbac`, NOT `configs.rbacConfig`](lesson-234-2026-03-28-argocd-helm-chart-rbac-key-is-conf.md) | 2026-05-01 |
| 233 | [2026-03-28: aws1 upgraded t4g.micro → t4g.small (+$3.14/mo) — eliminates all OOM issues](lesson-233-2026-03-28-aws1-upgraded-t4g-micro-t4g-small-.md) | 2026-05-01 |
| 125 | [2026-03-16: Helm + Docker Image Gotchas](lesson-125-2026-03-16-helm-docker-image-gotchas.md) | 2026-05-01 |
| 235 | [2026-03-28: Only Spot instances need dynamic IP resolve — physical nodes keep hardcoded IPs](lesson-235-2026-03-28-only-spot-instances-need-dynamic-i.md) | 2026-05-01 |
| 229 | [2026-03-28: Never kubectl patch — always IaC (deploy-argocd, deploy-k8s, deploy TARGET=vps)](lesson-229-2026-03-28-never-kubectl-patch-always-iac-dep.md) | 2026-05-01 |
| 228 | [Homepage ConfigMap is ad-hoc — not in Kustomize, needs manual apply](lesson-228-homepage-configmap-is-ad-hoc-not-in-kustomize.md) | 2026-03-27 |
| 221 | [Helm pending-install state blocks all future upgrades](lesson-221-helm-pending-install-state-blocks-all-future-.md) | 2026-03-27 |
| 214 | [Homepage Services Tab — SSOT-Driven Dashboard Tables](lesson-214-homepage-services-tab-ssot-driven-dashboard-t.md) | 2026-03-26 |
| 184 | [t4g.micro Spot sizing: fits Argo CD, not Helm upgrades](lesson-184-t4g-micro-spot-sizing-fits-argo-cd-not-helm-u.md) | 2026-03-23 |
| 195 | [ConfigMap mount must use subPath for Homepage](lesson-195-configmap-mount-must-use-subpath-for-homepage.md) | 2026-03-23 |
| 200 | [Cross-namespace DNS fails from certain pods](lesson-200-cross-namespace-dns-fails-from-certain-pods.md) | 2026-03-23 |
| 208 | [K3s bundled Traefik API is port 9000](lesson-208-k3s-bundled-traefik-api-is-port-9000.md) | 2026-03-23 |
| 207 | [rollout restart is destructive for stateful services](lesson-207-rollout-restart-is-destructive-for-stateful-s.md) | 2026-03-23 |
| 206 | [subPath ConfigMap mounts don't auto-update](lesson-206-subpath-configmap-mounts-don-t-auto-update.md) | 2026-03-23 |
| 182 | [K8s 1.24+ ServiceAccount tokens require explicit Secret](lesson-182-k8s-1-24-serviceaccount-tokens-require-explic.md) | 2026-03-23 |
| 173 | [K3s IngressRoute needed for vpn.kubelab.live after cutover](lesson-173-k3s-ingressroute-needed-for-vpn-kubelab-live-.md) | 2026-03-22 |
| 157 | [Traefik Helm chart api.dashboard values don't work in K3s HelmChartConfig](lesson-157-traefik-helm-chart-api-dashboard-values-don-t.md) | 2026-03-22 |
| 155 | [enableServiceLinks: false required for n8n on K8s](lesson-155-enableservicelinks-false-required-for-n8n-on-.md) | 2026-03-22 |
| 177 | [AWS Spot t4g.micro: 1GB RAM is NOT enough for K3s + Argo CD without swap](lesson-177-aws-spot-t4g-micro-1gb-ram-is-not-enough-for-.md) | 2026-03-22 |
| 175 | [Kustomize images section doesn't cover custom apps automatically](lesson-175-kustomize-images-section-doesn-t-cover-custom.md) | 2026-03-22 |
| 178 | [Cross-cluster K3s proxy: ClusterIP is NOT reachable from outside — use NodePort](lesson-178-cross-cluster-k3s-proxy-clusterip-is-not-reac.md) | 2026-03-22 |
| 146 | [Service mesh assessment: overkill for single-node K3s](lesson-146-service-mesh-assessment-overkill-for-single-n.md) | 2026-03-21 |
| 152 | [Authelia ConfigMap changes require pod restart](lesson-152-authelia-configmap-changes-require-pod-restar.md) | 2026-03-21 |
| 142 | [Kustomize images: transformer is SSOT for image versions](lesson-142-kustomize-images-transformer-is-ssot-for-imag.md) | 2026-03-21 |
| 121 | [K3s tests should use local kubeconfig not SSH+sudo](lesson-121-k3s-tests-should-use-local-kubeconfig-not-ssh.md) | 2026-03-15 |
| 090 | [K3s Traefik HTTP→HTTPS Redirect: CLI Args, Not Helm Values](lesson-090-k3s-traefik-http-https-redirect-cli-args-not-.md) | 2026-03-01 |
| 080 | [Secrets leaked in K8s ConfigMaps — blocklist approach is fragile](lesson-080-secrets-leaked-in-k8s-configmaps-blocklist-ap.md) | 2026-02-28 |
| 066 | [Kustomize configMapGenerator for Binary Assets](lesson-066-kustomize-configmapgenerator-for-binary-asset.md) | 2026-02-24 |
| 063 | [K3s TLS SAN Must Be Set Before First Start](lesson-063-k3s-tls-san-must-be-set-before-first-start.md) | 2026-02-22 |
