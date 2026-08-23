// Architecture diagrams + endpoints — Generated from common.yaml SSOT
// Run `make sync-homepage` to regenerate. Do NOT edit custom.js directly.

var KUBELAB_DIAGRAMS = {
  topology: `graph TB
  subgraph Internet
    CF[Cloudflare DNS+CDN]
    Users[Users]
  end
  subgraph AlwaysOn["Always-On (24/7) — ADR-028"]
    VPS["VPS 162.55.57.175 / 100.64.0.2<br/>K3s Prod 8GB"]
    HUB["gcp1 gcp1.kubelab.internal<br/>Argo CD Hub 2GB"]
    RPI3["RPi3 100.64.0.6<br/>Uptime Kuma 1GB"]
  end
  subgraph OnDemand["On-Demand homelab 172.16.1.0/24 — ADR-028"]
    ACE1["ace1 172.16.1.2 / 100.64.0.11<br/>K3s Staging 12GB"]
    ACE2["ace2 172.16.1.5 / 100.64.0.5<br/>Dev node / CDE 12GB"]
    BEE["Beelink 172.16.1.3 / 100.64.0.3<br/>Platform Node 8GB"]
    RPI4["RPi4 172.16.1.1 / 100.64.0.10<br/>DNS Gateway 8GB"]
    JET["Jetson 172.16.1.4 / 100.64.0.8<br/>Pollex 4GB"]
  end
  Users --> CF --> VPS
  HUB -. Tailscale .-> VPS
  HUB -. Tailscale .-> ACE1
  VPS -. Tailscale .-> ACE1
  VPS -. Tailscale .-> RPI3
  ACE1 --- ACE2
  ACE1 --- RPI4
  ACE1 --- BEE
  ACE1 --- JET
  RPI4 -. Tailscale .-> VPS
  classDef alwayson fill:#dbeafe,stroke:#3b82f6,stroke-width:2px
  classDef ondemand fill:#fef3c7,stroke:#f59e0b,stroke-width:2px
  classDef ext fill:#f3f4f6,stroke:#9ca3af
  class VPS,HUB,RPI3 alwayson
  class ACE1,ACE2,BEE,RPI4,JET ondemand
  class CF,Users ext`,
  gitops: `graph LR
  DEV[Developer] -->|push| GH[GitHub]
  GH -->|webhook| ARGO[Argo CD<br/>gcp1 Hub]
  ARGO -->|"Tailscale sync"| STG[K3s Staging<br/>ace1]
  ARGO -->|"Tailscale sync"| PRD[K3s Prod<br/>VPS]
  GH -->|CI| GHA[GitHub Actions]
  GHA -->|push| DH[Docker Hub]
  DH -.-> STG
  DH -.-> PRD
  classDef hub fill:#fce7f3,stroke:#ec4899,stroke-width:2px
  classDef spoke fill:#dbeafe,stroke:#3b82f6,stroke-width:2px
  classDef ci fill:#f3f4f6,stroke:#9ca3af
  class ARGO hub
  class STG,PRD spoke
  class GH,GHA,DH,DEV ci`,
  dns: `graph TB
  C[Client] -->|*.kubelab.live| CFDNS[Cloudflare]
  CFDNS --> VPS["VPS Traefik 162.55.57.175"]
  CFDNS -->|"pihole.kubelab.live<br/>(OPS-022)"| ACE1["ace1 Traefik 100.64.0.11"]
  C -->|VPN| HS[Headscale]
  HS -->|"split DNS<br/>*.staging.kubelab.live ONLY"| PH["Pi-hole RPi4"]
  PH -->|forward staging| CD["CoreDNS RPi4"]
  CD --> ACE1["ace1 Traefik 100.64.0.11"]
  PH -->|non-staging| UP[1.1.1.1 / 8.8.8.8]
  classDef dns fill:#ede9fe,stroke:#8b5cf6,stroke-width:2px
  classDef proxy fill:#dbeafe,stroke:#3b82f6,stroke-width:2px
  classDef ext fill:#f3f4f6,stroke:#9ca3af
  classDef vpn fill:#dcfce7,stroke:#22c55e,stroke-width:2px
  class PH,CD,CFDNS dns
  class VPS,ACE1 proxy
  class C,HS,UP ext`,
  request: `graph LR
  U[User] --> T["Traefik<br/>(+ CrowdSec plugin)"]
  T -->|IP allowed| A{Authelia}
  T -->|IP blocked| BLOCK[403 Forbidden]
  A -->|ok| APP[Apps / API / Web / n8n]
  A -->|no| LOGIN[Login]
  A -.-> R[(Redis)]
  APP -.-> DB[(PostgreSQL)]
  T -.->|stream mode 60s| LAPI[CrowdSec LAPI]
  APP -.-> V[Vector]
  V --> L[(Loki)]
  L --> G[Grafana]
  G -->|Alerts| N8N[n8n Router]
  N8N -->|Slack| SLACK[#alerts / #ops-log]
  classDef sec fill:#fef3c7,stroke:#f59e0b,stroke-width:2px
  classDef app fill:#dcfce7,stroke:#22c55e,stroke-width:2px
  classDef obs fill:#ede9fe,stroke:#8b5cf6,stroke-width:2px
  classDef proxy fill:#dbeafe,stroke:#3b82f6,stroke-width:2px
  classDef block fill:#fee2e2,stroke:#ef4444,stroke-width:2px
  class A,LOGIN,R,LAPI sec
  class APP,DB app
  class V,L,G,N8N,SLACK obs
  class T,U proxy
  class BLOCK block`,
  secret_flow: `graph LR
  SOPS["SOPS<br/>staging.enc.yaml<br/>prod.enc.yaml"] -->|decrypt| TK[toolkit secrets]
  TK -->|hash argon2| AUTH["Authelia<br/>K8s Secret"]
  TK -->|hash bcrypt| ARGO["Argo CD<br/>K8s Secret"]
  TK -->|webhook URLs| APPRISE["Apprise / n8n<br/>K8s Secret"]
  TK -->|plaintext| GENERIC["App Secrets<br/>K8s Secret"]
  TK -->|file mount| CS["CrowdSec<br/>kube-system Secret"]
  SOPS -.->|git| GIT[(Git Repo)]
  AUTH --> POD1[Authelia Pod]
  ARGO --> POD2[Argo CD Pod]
  APPRISE --> POD5[Apprise / n8n Pods]
  GENERIC --> POD3[App Pods]
  CS --> POD4[Traefik Pod]
  classDef sops fill:#fef3c7,stroke:#f59e0b,stroke-width:2px
  classDef toolkit fill:#dbeafe,stroke:#3b82f6,stroke-width:2px
  classDef secret fill:#dcfce7,stroke:#22c55e,stroke-width:2px
  classDef pod fill:#f3f4f6,stroke:#9ca3af
  class SOPS,GIT sops
  class TK toolkit
  class AUTH,ARGO,APPRISE,GENERIC,CS secret
  class POD1,POD2,POD3,POD4,POD5 pod`,
  deploy_pipeline: `graph LR
  DEV[Developer] -->|git push| GH[GitHub]
  GH -->|PR merge| GHA[GitHub Actions]
  GHA -->|build + test| IMG[Docker Image]
  IMG -->|push| DH[Docker Hub / GHCR]
  GHA -->|release-please| TAG[SemVer Tag]
  TAG -.-> DH
  DH -->|image ready| ARGO[Argo CD<br/>gcp1 Hub]
  ARGO -->|Kustomize overlay| STG[K3s Staging<br/>ace1]
  ARGO -->|Kustomize overlay| PRD[K3s Prod<br/>VPS]
  STG -.->|HelmChartConfig| HELM1[Traefik Helm]
  PRD -.->|HelmChartConfig| HELM2[Traefik Helm]
  DEV -->|make provision| ANS[Ansible]
  ANS -->|K3s + config| STG
  ANS -->|K3s + config| PRD
  DEV -->|make deploy-dns| TF[Terraform]
  TF -->|records| CF[Cloudflare]
  TF -->|MIG Spot VM| GCP[GCP Hub]
  classDef ci fill:#f3f4f6,stroke:#9ca3af
  classDef hub fill:#fce7f3,stroke:#ec4899,stroke-width:2px
  classDef spoke fill:#dbeafe,stroke:#3b82f6,stroke-width:2px
  classDef iac fill:#fef3c7,stroke:#f59e0b,stroke-width:2px
  classDef helm fill:#ede9fe,stroke:#8b5cf6,stroke-width:2px
  class GH,GHA,IMG,DH,TAG ci
  class ARGO,GCP hub
  class STG,PRD spoke
  class DEV,ANS,TF,CF iac
  class HELM1,HELM2 helm`,
  ip_reference: `NODE         LAN              TAILSCALE        ROLE
──────────── ──────────────── ──────────────── ────────────────────
VPS          162.55.57.175    100.64.0.2       K3s Prod · 8GB
gcp1         —                gcp1.kubelab.internal Argo CD Hub · 2GB
ace1         172.16.1.2       100.64.0.11      K3s Staging · 12GB
ace2         172.16.1.5       100.64.0.5       Dev node / CDE · 12GB
RPi4         172.16.1.1       100.64.0.10      DNS Gateway · 8GB
RPi3         —                100.64.0.6       Uptime Kuma · 1GB
Beelink      172.16.1.3       100.64.0.3       Platform Node · 8GB
Jetson       172.16.1.4       100.64.0.8       Pollex · 4GB`,
  dns_map: `DOMAIN                               RESOLVES TO
──────────────────────────────────── ────────────────────────────────────────

PROD (public DNS via Cloudflare)
  *.kubelab.live                     VPS Traefik (162.55.57.175)
  mlorente.dev                       VPS Traefik (162.55.57.175)
  vpn.kubelab.live                   162.55.57.175 (public, never Tailscale)
  pihole.kubelab.live                100.64.0.11 (public record, VPN-reachable only — OPS-022)

STAGING (VPN-only via split DNS)
  *.staging.kubelab.live             Headscale → Pi-hole → CoreDNS → ace1 (100.64.0.11)`,
  tech_stack: `TECHNOLOGY           PURPOSE                      WHERE                    MANAGED BY
──────────────────── ──────────────────────────── ──────────────────────── ────────────────────

ORCHESTRATION
  K3s                Container orchestration      ace1, VPS                Ansible
  Kustomize          K8s manifest overlays        ace1, VPS                toolkit / make
  Helm               Third-party charts           ace1, VPS                HelmChartConfig

INFRASTRUCTURE
  Terraform          DNS records                  Cloudflare               make deploy-dns
  Ansible            Node provisioning            All nodes                make provision
  Docker Compose     VPS services                 VPS                      make deploy-vps

NETWORKING
  Traefik            Reverse proxy + TLS          ace1, VPS (K3s)          HelmChartConfig
  Headscale          VPN mesh (WireGuard)         VPS (Docker)             Ansible
  CoreDNS            Staging DNS resolution       RPi4 (Docker)            make deploy-dns
  Pi-hole            DNS filtering + cache        RPi4 (Docker)            make deploy-dns
  Cloudflare         Prod DNS + CDN               External                 Terraform

SECURITY
  Authelia           SSO / OIDC / 2FA             ace1, VPS (K3s)          Kustomize
  CrowdSec           WAF / IP reputation          ace1, VPS (K3s)          Kustomize + plugin
  SOPS               Secret encryption            Git repo                 toolkit secrets

OBSERVABILITY
  Grafana            Dashboards                   ace1, VPS (K3s)          Kustomize
  Loki               Log aggregation              ace1, VPS (K3s)          Kustomize
  Vector             Log shipping                 ace1, VPS (K3s)          Kustomize
  Glances            Node metrics                 All nodes                Ansible
  Uptime Kuma        External monitoring          RPi3 (Docker)            Docker Compose

GITOPS
  Argo CD            Hub-and-spoke GitOps         gcp1 (K3s)               Helm
  GitHub Actions     CI/CD pipelines              GitHub                   .github/workflows/
  release-please     Automated releases           GitHub                   .github/workflows/

TOOLING
  toolkit (Python)   CLI: secrets, sync, deploy   Local                    Poetry
  Makefile           Task runner                  Local                    make help
  Homepage           Dashboard (this page)        ace1, VPS (K3s)          Kustomize

K3s v1.34.4+k3s1`,
};

var KUBELAB_SERVICES_STAGING = [
  {
    "name": "API",
    "url": "https://api.staging.kubelab.live",
    "health": "https://api.staging.kubelab.live/health",
    "auth": "Public",
    "category": "Platform",
    "node": "ace1",
    "version": "dev",
    "notes": "REST API"
  },
  {
    "name": "Web",
    "url": "https://staging.mlorente.dev",
    "health": "https://staging.mlorente.dev",
    "auth": "Public",
    "category": "Platform",
    "node": "ace1",
    "version": "dev",
    "notes": "Frontend"
  },
  {
    "name": "Authelia",
    "url": "https://auth.staging.kubelab.live",
    "health": "https://auth.staging.kubelab.live/api/health",
    "auth": "Public (IdP)",
    "category": "Security",
    "node": "ace1",
    "version": "4.39.15",
    "notes": "SSO / Login"
  },
  {
    "name": "CrowdSec",
    "url": "https://crowdsec.staging.kubelab.live",
    "health": "https://crowdsec.staging.kubelab.live/health",
    "auth": "Authelia",
    "category": "Security",
    "node": "ace1",
    "version": "1.7.6",
    "notes": "WAF / LAPI"
  },
  {
    "name": "Traefik",
    "url": "https://traefik.staging.kubelab.live/dashboard/",
    "health": "https://traefik.staging.kubelab.live/dashboard/",
    "auth": "Authelia",
    "category": "Core",
    "node": "ace1",
    "version": "3.x",
    "notes": "Dashboard"
  },
  {
    "name": "n8n",
    "url": "https://n8n.staging.kubelab.live",
    "health": "https://n8n.staging.kubelab.live/healthz",
    "auth": "Built-in",
    "category": "Core",
    "node": "ace1",
    "version": "2.12.3",
    "notes": "Automation"
  },
  {
    "name": "MinIO API",
    "url": "https://minio.staging.kubelab.live",
    "health": "https://minio.staging.kubelab.live/minio/health/live",
    "auth": "Built-in",
    "category": "Data",
    "node": "ace1",
    "version": "2025-09-07",
    "notes": "S3 API"
  },
  {
    "name": "MinIO Console",
    "url": "https://console.minio.staging.kubelab.live",
    "health": "https://console.minio.staging.kubelab.live",
    "auth": "Built-in (OIDC)",
    "category": "Data",
    "node": "ace1",
    "version": "2025-09-07",
    "notes": "Console UI"
  },
  {
    "name": "Grafana",
    "url": "https://grafana.staging.kubelab.live",
    "health": "https://grafana.staging.kubelab.live/api/health",
    "auth": "Authelia",
    "category": "Observability",
    "node": "ace1",
    "version": "latest",
    "notes": "Dashboards"
  },
  {
    "name": "Loki",
    "url": "https://loki.staging.kubelab.live",
    "health": "https://loki.staging.kubelab.live/ready",
    "auth": "Authelia",
    "category": "Observability",
    "node": "ace1",
    "version": "3.6.4",
    "notes": "Log aggregation"
  },
  {
    "name": "Apprise",
    "url": "http://apprise.kubelab.svc:8000",
    "health": "http://apprise.kubelab.svc:8000/health",
    "auth": "Internal",
    "category": "Core",
    "node": "ace1",
    "version": "1.5.0",
    "notes": "Notification gateway"
  },
  {
    "name": "PostgreSQL",
    "url": "postgres.kubelab.svc:5432",
    "health": "postgres.kubelab.svc:5432",
    "auth": "Internal",
    "category": "Data",
    "node": "ace1",
    "version": "17-alpine",
    "notes": "Platform DB"
  },
  {
    "name": "Redis",
    "url": "redis.kubelab.svc:6379",
    "health": "redis.kubelab.svc:6379",
    "auth": "Internal",
    "category": "Data",
    "node": "ace1",
    "version": "7-alpine",
    "notes": "Session cache"
  },
  {
    "name": "Vector",
    "url": "vector.kubelab.svc:8686",
    "health": "vector.kubelab.svc:8686",
    "auth": "Internal",
    "category": "Observability",
    "node": "ace1",
    "version": "DaemonSet",
    "notes": "Log pipeline agent"
  },
  {
    "name": "SRE Watchers",
    "url": "-",
    "health": "-",
    "auth": "Internal",
    "category": "Observability",
    "node": "ace1",
    "version": "CronJobs",
    "notes": "Quota / R2 / Disk"
  },
  {
    "name": "Homepage",
    "url": "https://home.staging.kubelab.live",
    "health": "https://home.staging.kubelab.live",
    "auth": "Public",
    "category": "Core",
    "node": "ace1",
    "version": "latest",
    "notes": "This dashboard"
  }
];
var KUBELAB_SERVICES_PROD = [
  {
    "name": "API",
    "url": "https://api.kubelab.live",
    "health": "https://api.kubelab.live/health",
    "auth": "Public",
    "category": "Platform",
    "node": "VPS",
    "version": "dev",
    "notes": "REST API"
  },
  {
    "name": "Web",
    "url": "https://mlorente.dev",
    "health": "https://mlorente.dev",
    "auth": "Public",
    "category": "Platform",
    "node": "VPS",
    "version": "dev",
    "notes": "Frontend"
  },
  {
    "name": "Authelia",
    "url": "https://auth.kubelab.live",
    "health": "https://auth.kubelab.live/api/health",
    "auth": "Public (IdP)",
    "category": "Security",
    "node": "VPS",
    "version": "4.39.15",
    "notes": "SSO / Login"
  },
  {
    "name": "CrowdSec",
    "url": "https://crowdsec.kubelab.live",
    "health": "https://crowdsec.kubelab.live/health",
    "auth": "Authelia",
    "category": "Security",
    "node": "VPS",
    "version": "1.7.6",
    "notes": "WAF / LAPI"
  },
  {
    "name": "Traefik",
    "url": "https://traefik.kubelab.live/dashboard/",
    "health": "https://traefik.kubelab.live/dashboard/",
    "auth": "Authelia",
    "category": "Core",
    "node": "VPS",
    "version": "3.x",
    "notes": "Dashboard"
  },
  {
    "name": "n8n",
    "url": "https://n8n.kubelab.live",
    "health": "https://n8n.kubelab.live/healthz",
    "auth": "Authelia",
    "category": "Core",
    "node": "VPS",
    "version": "2.12.3",
    "notes": "Automation"
  },
  {
    "name": "MinIO API",
    "url": "https://minio.kubelab.live",
    "health": "https://minio.kubelab.live/minio/health/live",
    "auth": "Built-in",
    "category": "Data",
    "node": "VPS",
    "version": "2025-09-07",
    "notes": "S3 API"
  },
  {
    "name": "MinIO Console",
    "url": "https://console.minio.kubelab.live",
    "health": "https://console.minio.kubelab.live",
    "auth": "Built-in (OIDC)",
    "category": "Data",
    "node": "VPS",
    "version": "2025-09-07",
    "notes": "Console UI"
  },
  {
    "name": "Grafana",
    "url": "https://grafana.kubelab.live",
    "health": "https://grafana.kubelab.live/api/health",
    "auth": "Authelia",
    "category": "Observability",
    "node": "VPS",
    "version": "latest",
    "notes": "Dashboards"
  },
  {
    "name": "Loki",
    "url": "https://loki.kubelab.live",
    "health": "https://loki.kubelab.live/ready",
    "auth": "Authelia",
    "category": "Observability",
    "node": "VPS",
    "version": "3.6.4",
    "notes": "Log aggregation"
  },
  {
    "name": "Apprise",
    "url": "http://apprise.kubelab.svc:8000",
    "health": "http://apprise.kubelab.svc:8000/health",
    "auth": "Internal",
    "category": "Core",
    "node": "VPS",
    "version": "1.5.0",
    "notes": "Notification gateway"
  },
  {
    "name": "PostgreSQL",
    "url": "postgres.kubelab.svc:5432",
    "health": "postgres.kubelab.svc:5432",
    "auth": "Internal",
    "category": "Data",
    "node": "VPS",
    "version": "17-alpine",
    "notes": "Platform DB"
  },
  {
    "name": "Redis",
    "url": "redis.kubelab.svc:6379",
    "health": "redis.kubelab.svc:6379",
    "auth": "Internal",
    "category": "Data",
    "node": "VPS",
    "version": "7-alpine",
    "notes": "Session cache"
  },
  {
    "name": "Vector",
    "url": "vector.kubelab.svc:8686",
    "health": "vector.kubelab.svc:8686",
    "auth": "Internal",
    "category": "Observability",
    "node": "VPS",
    "version": "DaemonSet",
    "notes": "Log pipeline agent"
  },
  {
    "name": "SRE Watchers",
    "url": "-",
    "health": "-",
    "auth": "Internal",
    "category": "Observability",
    "node": "VPS",
    "version": "CronJobs",
    "notes": "Quota / R2 / Disk"
  },
  {
    "name": "Homepage",
    "url": "https://home.kubelab.live",
    "health": "https://home.kubelab.live",
    "auth": "Public",
    "category": "Core",
    "node": "VPS",
    "version": "latest",
    "notes": "This dashboard"
  },
  {
    "name": "kubelab.live",
    "url": "https://kubelab.live",
    "health": "https://kubelab.live",
    "auth": "-",
    "category": "Core",
    "node": "VPS",
    "version": "",
    "notes": "301 \u2192 mlorente.dev"
  }
];
var KUBELAB_SERVICES_SHARED = [
  {
    "name": "Gitea",
    "url": "https://gitea.kubelab.live",
    "health": "https://gitea.kubelab.live/api/healthz",
    "auth": "Built-in (OIDC)",
    "category": "Core",
    "node": "Beelink",
    "version": "1.25.5",
    "notes": "Git hosting \u00b7 on-demand"
  },
  {
    "name": "Argo CD",
    "url": "https://argo.kubelab.live",
    "health": "https://argo.kubelab.live",
    "auth": "Authelia",
    "category": "Core",
    "node": "gcp1",
    "version": "2.14",
    "notes": "GitOps hub"
  },
  {
    "name": "Headscale",
    "url": "https://vpn.kubelab.live",
    "health": "https://vpn.kubelab.live/health",
    "auth": "Built-in",
    "category": "Network",
    "node": "VPS",
    "version": "0.28.0",
    "notes": "VPN mesh"
  },
  {
    "name": "Uptime Kuma",
    "url": "https://status.kubelab.live",
    "health": "https://status.kubelab.live",
    "auth": "Public",
    "category": "Observability",
    "node": "RPi3",
    "version": "2.2.1",
    "notes": "Status page"
  },
  {
    "name": "Pi-hole",
    "url": "https://pihole.kubelab.live",
    "health": "https://pihole.kubelab.live/admin/",
    "auth": "Built-in (v6)",
    "category": "Network",
    "node": "RPi4",
    "version": "v6",
    "notes": "DNS filtering"
  },
  {
    "name": "Pollex",
    "url": "http://100.64.0.8:8000",
    "health": "http://100.64.0.8:8000",
    "auth": "Tailscale",
    "category": "AI",
    "node": "Jetson",
    "version": "",
    "notes": "Edge AI \u00b7 on-demand"
  }
];


(function() {
  var injected = {};
  var mermaidPromise = null;

  function getMermaid() {
    if (!mermaidPromise) {
      mermaidPromise = import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs")
        .then(function(m) {
          var instance = m.default || m;
          instance.initialize({
            startOnLoad: false,
            theme: "neutral",
            securityLevel: "loose"
          });
          return instance;
        })
        .catch(function(err) {
          console.error("Mermaid ESM load error:", err);
          return null;
        });
    }
    return mermaidPromise;
  }

  function injectDiagram(groupTitle, dataKey, isAscii) {
    if (injected[dataKey]) return;
    var data = KUBELAB_DIAGRAMS[dataKey];
    if (!data) return;

    // Homepage v15.5 DOM: H2.service-group-name inside BUTTON inside DIV.services-group
    var h2s = document.querySelectorAll("h2.service-group-name, h2");
    for (var i = 0; i < h2s.length; i++) {
      var text = (h2s[i].textContent || "").trim();
      if (text !== groupTitle) continue;
      // Navigate up to the services-group container
      var group = h2s[i].closest(".services-group") || h2s[i].closest("[class*='services-group']");
      if (!group) continue;

      var container = document.createElement("div");
      container.style.cssText = "width:100%;display:flex;justify-content:center;padding:0.5rem;overflow-x:auto";

      if (isAscii) {
        var pre = document.createElement("pre");
        pre.style.cssText = "font-size:0.6rem;line-height:1.2;"
          + "font-family:monospace;background:var(--bg-card,#f9fafb);"
          + "padding:1rem;border-radius:0.5rem;overflow-x:auto";
        pre.textContent = data;
        container.appendChild(pre);
      } else {
        var diagramBox = document.createElement("div");
        diagramBox.className = "diagram-svg-box";
        diagramBox.style.cssText = "width:100%;display:flex;justify-content:center;align-items:center;min-height:180px";
        diagramBox.textContent = "Rendering architecture diagram...";
        container.appendChild(diagramBox);

        getMermaid().then(function(m) {
          if (!m) {
            diagramBox.textContent = "Diagram rendering unavailable.";
            return;
          }
          var renderId = "mermaid_" + dataKey + "_" + Math.floor(Math.random() * 100000);
          m.render(renderId, data).then(function(res) {
            diagramBox.innerHTML = res.svg;
            var svgEl = diagramBox.querySelector("svg");
            if (svgEl) {
              svgEl.style.maxWidth = "100%";
              svgEl.style.height = "auto";
              svgEl.style.cursor = "zoom-in";
              svgEl.setAttribute("alt", dataKey + " diagram");
            }
          }).catch(function(e) {
            diagramBox.textContent = "Diagram render error: " + e.message;
          });
        });
      }

      // Insert after the header button and hide placeholder service cards
      var btn = group.querySelector("button");
      if (btn && btn.nextElementSibling) {
        group.insertBefore(container, btn.nextElementSibling);
      } else {
        group.appendChild(container);
      }
      // Hide only the placeholder list items (not structural elements)
      var lis = group.querySelectorAll("li");
      for (var j = 0; j < lis.length; j++) {
        lis[j].style.display = "none";
      }
      injected[dataKey] = true;
      return;
    }
  }

  function injectServices(groupTitle, services) {
    if (injected["svc_" + groupTitle]) return;
    if (!services || !services.length) return;

    var h2s = document.querySelectorAll("h2.service-group-name, h2");
    for (var i = 0; i < h2s.length; i++) {
      var text = (h2s[i].textContent || "").trim();
      if (text !== groupTitle) continue;
      var group = h2s[i].closest(".services-group") || h2s[i].closest("[class*='services-group']");
      if (!group) continue;

      var wrap = document.createElement("div");
      wrap.style.cssText = "width:100%;padding:0.5rem;overflow-x:auto";

      var table = document.createElement("table");
      table.className = "ep-table";

      // Header
      var thead = document.createElement("thead");
      var hr = document.createElement("tr");
      ["", "Service", "URL", "Health", "Auth", "Category", "Node", "Version"].forEach(function(col) {
        var th = document.createElement("th");
        th.textContent = col;
        hr.appendChild(th);
      });
      thead.appendChild(hr);
      table.appendChild(thead);

      // Body
      var tbody = document.createElement("tbody");
      services.forEach(function(svc) {
        var tr = document.createElement("tr");

        // Status dot
        var tdStatus = document.createElement("td");
        var dot = document.createElement("span");
        dot.className = "ep-status ep-status-unknown";
        dot.setAttribute("data-health-url", svc.health);
        tdStatus.appendChild(dot);
        tr.appendChild(tdStatus);

        // Service name
        var tdName = document.createElement("td");
        tdName.className = "ep-name";
        tdName.textContent = svc.name;
        tr.appendChild(tdName);

        // URL with copy button
        var tdUrl = document.createElement("td");
        var aUrl = document.createElement("a");
        aUrl.href = svc.url;
        aUrl.target = "_blank";
        aUrl.rel = "noopener";
        aUrl.textContent = svc.url.replace("https://", "");
        tdUrl.appendChild(aUrl);
        var btnUrl = document.createElement("button");
        btnUrl.className = "ep-copy";
        btnUrl.setAttribute("data-url", svc.url);
        btnUrl.title = "Copy URL";
        btnUrl.textContent = "⎘";
        tdUrl.appendChild(btnUrl);
        tr.appendChild(tdUrl);

        // Health with copy button
        var tdHealth = document.createElement("td");
        if (svc.health && svc.health !== svc.url) {
          var aHealth = document.createElement("a");
          aHealth.href = svc.health;
          aHealth.target = "_blank";
          aHealth.rel = "noopener";
          var healthPath = svc.health.replace(svc.url, "") || "/";
          aHealth.textContent = healthPath;
          tdHealth.appendChild(aHealth);
          var btnHealth = document.createElement("button");
          btnHealth.className = "ep-copy";
          btnHealth.setAttribute("data-url", svc.health);
          btnHealth.title = "Copy health URL";
          btnHealth.textContent = "⎘";
          tdHealth.appendChild(btnHealth);
        } else {
          tdHealth.textContent = "—";
        }
        tr.appendChild(tdHealth);

        // Auth
        var tdAuth = document.createElement("td");
        tdAuth.textContent = svc.auth;
        if (svc.auth === "Public" || svc.auth === "Public (IdP)") {
          tdAuth.className = "ep-auth-public";
        } else if (svc.auth === "Authelia") {
          tdAuth.className = "ep-auth-authelia";
        } else if (svc.auth.indexOf("Built-in") === 0) {
          tdAuth.className = "ep-auth-builtin";
        }
        tr.appendChild(tdAuth);

        // Category (clickable tag)
        var tdCat = document.createElement("td");
        var tag = document.createElement("span");
        tag.className = "ep-tag ep-tag-" + svc.category.toLowerCase().replace(/[^a-z]/g, "");
        tag.textContent = svc.category;
        tag.setAttribute("data-filter", svc.category);
        tag.style.cursor = "pointer";
        tdCat.appendChild(tag);
        tr.appendChild(tdCat);

        // Node
        var tdNode = document.createElement("td");
        tdNode.textContent = svc.node;
        tr.appendChild(tdNode);

        // Version
        var tdVer = document.createElement("td");
        tdVer.className = "ep-version";
        tdVer.textContent = svc.version || "—";
        tr.appendChild(tdVer);

        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      wrap.appendChild(table);

      var btn = group.querySelector("button");
      if (btn && btn.nextElementSibling) {
        group.insertBefore(wrap, btn.nextElementSibling);
      } else {
        group.appendChild(wrap);
      }
      var lis = group.querySelectorAll("li");
      for (var j = 0; j < lis.length; j++) {
        lis[j].style.display = "none";
      }
      injected["svc_" + groupTitle] = true;

      // Run health checks for this table
      checkHealth(wrap);
      return;
    }
  }

  function checkHealth(container) {
    var isHttps = (window.location.protocol === "https:");
    var dots = container.querySelectorAll(".ep-status[data-health-url]");
    dots.forEach(function(dot) {
      var url = dot.getAttribute("data-health-url");
      if (!url || url === "-" || url.indexOf("http") !== 0) {
        dot.className = "ep-status ep-status-internal";
        dot.title = "Cluster-internal component";
        return;
      }
      if (isHttps && url.indexOf("http://") === 0) {
        dot.className = "ep-status ep-status-internal";
        dot.title = "Internal service (Tailscale / LAN)";
        return;
      }
      fetch(url, {mode: "no-cors", signal: AbortSignal.timeout(6000)})
        .then(function() {
          dot.className = "ep-status ep-status-up";
          dot.title = "Online (Reachable)";
        })
        .catch(function() {
          if (url.indexOf(".staging.") !== -1) {
            dot.className = "ep-status ep-status-internal";
            dot.title = "Staging (On-demand cluster)";
          } else {
            dot.className = "ep-status ep-status-down";
            dot.title = "Unreachable";
          }
        });
    });
  }

  function tryInject() {
    var hash = (window.location.hash || "").toLowerCase();
    if (hash === "#topology") {
      injectDiagram("IP Reference", "ip_reference", true);
      injectDiagram("Topology", "topology", false);
      injectDiagram("DNS Map", "dns_map", true);
      injectDiagram("DNS Resolution", "dns", false);
    }
    if (hash === "#flows") {
      injectDiagram("GitOps", "gitops", false);
      injectDiagram("Request Path", "request", false);
      injectDiagram("Secret Flow", "secret_flow", false);
      injectDiagram("Deploy Pipeline", "deploy_pipeline", false);
      injectDiagram("Tech Stack", "tech_stack", true);
    }
    if (hash === "#services") {
      injectServices("Shared", KUBELAB_SERVICES_SHARED);
      injectServices("Staging", KUBELAB_SERVICES_STAGING);
      injectServices("Prod", KUBELAB_SERVICES_PROD);
    }
  }

  // Copy-to-clipboard for endpoint URLs
  document.addEventListener("click", function(e) {
    var btn = e.target.closest(".ep-copy");
    if (btn) {
      var url = btn.getAttribute("data-url");
      if (url && navigator.clipboard) {
        navigator.clipboard.writeText(url).then(function() {
          var orig = btn.textContent;
          btn.textContent = "✓";
          setTimeout(function() { btn.textContent = orig; }, 1200);
        });
      }
      e.preventDefault();
      return;
    }

    // Category filter toggle
    var tag = e.target.closest(".ep-tag[data-filter]");
    if (tag) {
      var filter = tag.getAttribute("data-filter");
      var table = tag.closest(".ep-table");
      if (!table) return;
      var rows = table.querySelectorAll("tbody tr");
      var isFiltered = table.getAttribute("data-filter") === filter;
      if (isFiltered) {
        // Clear filter — show all
        rows.forEach(function(r) { r.style.display = ""; });
        table.removeAttribute("data-filter");
        table.querySelectorAll(".ep-tag").forEach(function(t) { t.style.opacity = ""; });
      } else {
        // Apply filter
        rows.forEach(function(r) {
          var rowTag = r.querySelector(".ep-tag");
          r.style.display = (rowTag && rowTag.getAttribute("data-filter") === filter) ? "" : "none";
        });
        table.setAttribute("data-filter", filter);
        table.querySelectorAll(".ep-tag").forEach(function(t) {
          t.style.opacity = t.getAttribute("data-filter") === filter ? "" : "0.3";
        });
      }
      e.preventDefault();
      return;
    }
  });

  // Resizable columns — drag syncs across all service tables
  (function() {
    var dragging = null;
    var colIndex = -1;
    var startX = 0;
    var startW = 0;

    document.addEventListener("mousedown", function(e) {
      var th = e.target.closest(".ep-table th");
      if (!th) return;
      var rect = th.getBoundingClientRect();
      if (e.clientX < rect.right - 6) return;
      dragging = th;
      colIndex = Array.from(th.parentNode.children).indexOf(th);
      startX = e.clientX;
      startW = th.offsetWidth;
      e.preventDefault();
    });

    document.addEventListener("mousemove", function(e) {
      if (!dragging) return;
      var w = Math.max(30, startW + (e.clientX - startX));
      var colCount = dragging.parentNode.children.length;
      var tables = document.querySelectorAll(".ep-table");
      tables.forEach(function(t) {
        var ths = t.querySelectorAll("thead th");
        if (ths.length !== colCount) return;
        // Switch to fixed layout so widths stick
        t.style.tableLayout = "fixed";
        // On first resize, capture current auto widths for all columns
        if (!t.getAttribute("data-sized")) {
          for (var c = 0; c < ths.length; c++) {
            ths[c].style.width = ths[c].offsetWidth + "px";
          }
          t.setAttribute("data-sized", "1");
        }
        ths[colIndex].style.width = w + "px";
      });
    });

    document.addEventListener("mouseup", function() {
      dragging = null;
      colIndex = -1;
    });

    document.addEventListener("mousemove", function(e) {
      if (dragging) return;
      var th = e.target.closest(".ep-table th");
      if (!th) return;
      var rect = th.getBoundingClientRect();
      th.style.cursor = (e.clientX > rect.right - 6) ? "col-resize" : "";
    });
  })();

  // Click-to-zoom on diagram SVG and images
  document.addEventListener("click", function(e) {
    var target = e.target.closest(".diagram-svg-box svg, img[alt*='diagram']");
    if (target && !e.target.closest(".diagram-overlay")) {
      var overlay = document.createElement("div");
      overlay.className = "diagram-overlay";
      var clone = target.cloneNode(true);
      clone.style.cssText = "max-width:95vw;max-height:95vh;object-fit:contain;min-width:auto;cursor:zoom-out";
      overlay.appendChild(clone);
      overlay.addEventListener("click", function() { overlay.remove(); });
      document.body.appendChild(overlay);
    }
  });

  // Run on tab changes
  window.addEventListener("hashchange", function() { injected = {}; setTimeout(tryInject, 300); });
  setTimeout(function() { if (window.location.hash) tryInject(); }, 1000);
})();

// Footer
(function() {
  function addFooter() {
    if (document.getElementById("kubelab-footer")) return;
    var main = document.querySelector("main") || document.querySelector("#page_container") || document.body;
    var footer = document.createElement("div");
    footer.id = "kubelab-footer";
    footer.textContent = "KubeLab IDP · config ef7040ce";
    main.appendChild(footer);
  }
  setTimeout(addFooter, 2000);
  window.addEventListener("hashchange", function() { setTimeout(addFooter, 500); });
})();
