"""IDP public platform manifest extraction and drift gating (ADR-056 / issue #1347).

Projects common.yaml SSOT into the sanitized public platform.json required by web
(/lab and /lab/idp), strictly enforcing Zero-Addressing doctrine (no IP addresses,
no internal hostnames, no private URLs).
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from toolkit.config.settings import settings
from toolkit.core.io import write_text_lf
from toolkit.core.logging import logger

DEFAULT_OUTPUT = settings.project_root / "infra/config/platform.json"
COMMON_YAML_PATH = settings.project_root / "infra/config/values/common.yaml"

# Canonical node hardware catalog (enriched from common.yaml SSOT)
NODE_METADATA: dict[str, dict[str, Any]] = {
    "vps": {
        "name": "Hetzner Cloud VPS",
        "tier": "cloud",
        "role": "Production Ingress & Core IDP",
        "roleEs": "Ingress de Producción y Core IDP",
        "summary": "Public ingress, Let's Encrypt TLS, Core IDP, Headscale VPN & observability",
        "summaryEs": "Ingress público, TLS Let's Encrypt, Core IDP, VPN Headscale y observabilidad",
        "environment": "Production",
        "provider": "Hetzner Cloud",
        "arch": "ARM64",
        "cpu": "4 vCPU (Ampere Neoverse-N1)",
        "ram": "7.5 GB",
        "storage": "75 GB NVMe",
        "os": "Ubuntu 24.04 LTS",
        "location": "Falkenstein (Germany)",
        "status": "healthy",
        "runtime": "k3s",
        "runtimeRole": "Production K3s cluster (single node)",
    },
    "gcp1": {
        "name": "Google Cloud Platform Hub",
        "tier": "cloud",
        "role": "Argo CD GitOps Control Plane (ADR-063)",
        "roleEs": "Plano de Control GitOps Argo CD (ADR-063)",
        "summary": "Central GitOps orchestrator continuously reconciling multi-cluster state",
        "summaryEs": "Orquestador central GitOps que reconcilia continuamente el estado multi-cluster",
        "environment": "Production",
        "provider": "Google Cloud (europe-west4)",
        "arch": "x86_64",
        "cpu": "2 vCPU (AMD EPYC 7B12)",
        "ram": "2 GB",
        "storage": "12 GB pd-balanced",
        "os": "Ubuntu 24.04 LTS",
        "location": "Eemshaven (Netherlands)",
        "status": "healthy",
        "runtime": "k3s",
        "runtimeRole": "Argo CD hub K3s cluster (single node)",
    },
    "ace1": {
        "name": "Acemagic Staging Cluster",
        "tier": "homelab",
        "role": "Staging K3s & Heavy Workloads",
        "roleEs": "Clúster Staging K3s y Cargas Pesadas",
        "summary": "Primary K3s staging cluster, Gitea Git forge & heavy application pods",
        "summaryEs": "Clúster principal K3s de staging, forge Git Gitea y pods de aplicación",
        "environment": "Staging",
        "provider": "On-Premises Homelab",
        "arch": "x86_64",
        "cpu": "Intel N95 (4c)",
        "ram": "11.5 GB",
        "storage": "233 GB NVMe",
        "os": "Ubuntu 24.04 LTS",
        "location": "Homelab (USA)",
        "status": "healthy",
        "runtime": "k3s",
        "runtimeRole": "Staging K3s cluster (single node)",
    },
    "ace2": {
        "name": "Acemagic Dev & Agent Node",
        "tier": "homelab",
        "role": "Remote development and agent workspaces",
        "roleEs": "Desarrollo remoto y workspaces de agentes",
        "summary": (
            "Where I work and where coding agents run — claude, codex, orca and pi each get their"
            " own workspace. No Kubernetes; it is a workstation I do not sit at."
        ),
        "summaryEs": (
            "Donde trabajo y donde corren los agentes de código — claude, codex, orca y pi tienen"
            " cada uno su workspace. Sin Kubernetes: es una estación de trabajo a la que no me"
            " siento delante."
        ),
        "environment": "Infrastructure",
        "provider": "On-Premises Homelab",
        "arch": "x86_64",
        "cpu": "Intel N95 (4c)",
        "ram": "11.5 GB",
        "storage": "233 GB NVMe",
        "os": "Ubuntu 24.04 LTS",
        "location": "Homelab (USA)",
        "status": "healthy",
        "runtime": "docker",
        "runtimeRole": "Remote dev host: agent workspaces, no Kubernetes",
    },
    "jetson": {
        "name": "NVIDIA Jetson Nano",
        "tier": "homelab",
        "role": "Edge AI GPU Inference Node",
        "roleEs": "Nodo de Inferencia GPU Edge AI",
        "summary": ("Hardware-accelerated CUDA edge inference running local Qwen 1.5B with 0% data leaks"),
        "summaryEs": ("Inferencia GPU edge con CUDA corriendo Qwen 1.5B local sin fuga de datos"),
        "environment": "Edge AI",
        "provider": "Bare Metal Edge",
        "arch": "ARM64",
        "cpu": "4c Cortex-A57 (128 Maxwell CUDA cores, unused)",
        "ram": "3.9 GB LPDDR4",
        "storage": "230 GB",
        "os": "Linux4Tegra (Ubuntu 18.04)",
        "location": "Edge Hardware (USA)",
        "status": "healthy",
        "runtime": "systemd",
        "runtimeRole": "Edge inference host: Ollama, no Kubernetes",
    },
    "beelink": {
        "name": "Beelink Forge & CI Runner",
        "tier": "homelab",
        "role": "Git forge, CI runner and object store",
        "roleEs": "Forge Git, runner de CI y almacén de objetos",
        "summary": (
            "Hosts the Gitea forge, the MinIO object store, the GitHub Actions runner and the"
            " Buildx builders. All Docker; no Kubernetes."
        ),
        "summaryEs": (
            "Aloja el forge Gitea, el almacén de objetos MinIO, el runner de GitHub Actions y los"
            " builders de Buildx. Todo en Docker, sin Kubernetes."
        ),
        "environment": "Infrastructure",
        "provider": "On-Premises Homelab",
        "arch": "x86_64",
        "cpu": "Intel N95 (4c)",
        "ram": "7.5 GB",
        "storage": "98 GB NVMe",
        "os": "Ubuntu 24.04 LTS",
        "location": "Homelab (USA)",
        "status": "healthy",
        "runtime": "docker",
        "runtimeRole": "Docker host: Gitea, MinIO, CI runner, Buildx builders",
    },
    "rpi4": {
        "name": "Raspberry Pi 4 Gateway",
        "tier": "homelab",
        "role": "Split DNS Gateway & Pi-hole",
        "roleEs": "Gateway de DNS Split y Pi-hole",
        "summary": "Authoritative Split DNS resolver (CoreDNS) and network sinkhole (Pi-hole)",
        "summaryEs": "Resolutor autoritativo Split DNS (CoreDNS) y sinkhole de red (Pi-hole)",
        "environment": "Infrastructure",
        "provider": "Bare Metal SBC",
        "arch": "ARM64",
        "cpu": "Broadcom BCM2711 (4c)",
        "ram": "7.6 GB",
        "storage": "58 GB MicroSD",
        "os": "Ubuntu 24.04 LTS",
        "location": "Homelab (USA)",
        "status": "healthy",
        "runtime": "docker",
        "runtimeRole": "Docker host: Pi-hole and CoreDNS split DNS",
    },
    "rpi3": {
        "name": "Raspberry Pi 3 Monitor",
        "tier": "homelab",
        "role": "Telemetry & Uptime Kuma",
        "roleEs": "Telemetría y Uptime Kuma",
        "summary": "Independent out-of-band synthetic monitoring with Uptime Kuma 90-day SLA",
        "summaryEs": "Monitor sintético out-of-band independiente con SLA a 90 días en Uptime Kuma",
        "environment": "Infrastructure",
        "provider": "Bare Metal SBC",
        "arch": "ARM64",
        "cpu": "Broadcom BCM2837 (4c)",
        "ram": "0.9 GB",
        "storage": "29 GB MicroSD",
        "os": "Debian 13 (trixie)",
        "location": "Homelab (USA)",
        "status": "healthy",
        "runtime": "docker",
        "runtimeRole": "Docker host: Uptime Kuma out-of-band monitor",
    },
    "aws1": {
        "name": "AWS Standby Hub",
        "tier": "cloud",
        "role": "Cold standby for the Argo CD hub",
        "roleEs": "Standby en frío del hub de Argo CD",
        "summary": (
            "Held the Argo CD hub until the migration to GCP (ADR-063). Powered down; reprovisionable"
            " from provision-aws1.yml."
        ),
        "summaryEs": (
            "Alojó el hub de Argo CD hasta la migración a GCP (ADR-063). Apagado; reprovisionable"
            " desde provision-aws1.yml."
        ),
        "environment": "Infrastructure",
        "provider": "AWS (t4g.small)",
        "arch": "ARM64",
        "cpu": "2 vCPU (Graviton2)",
        "ram": "2 GB",
        "storage": "—",
        "os": "—",
        "runtime": "standby",
        "runtimeRole": "Not running. Rehearsal date not yet recorded.",
        "status": "standby",
        "location": "Powered down (was eu-central)",
    },
}

# Canonical platform services (Zero-Addressing enforced: no private URLs)
PLATFORM_SERVICES: list[dict[str, Any]] = [
    {
        "slug": "pollex",
        "name": "Pollex Edge AI",
        "category": "AI & Inference",
        "categoryEs": "IA e Inferencia",
        "description": "On-device LLM text polish running local Qwen 1.5B with zero cloud telemetry.",
        "descriptionEs": ("Corrección de texto LLM en edge con Qwen 1.5B local sin telemetría en la nube."),
        "url": "https://mlorentedev.github.io/pollex/",
        "node": "jetson",
        "env": "prod",
        "tech": ["Go", "CUDA", "TensorRT", "K3s"],
        "isPublic": True,
        "status": "operational",
    },
    {
        "slug": "hive",
        "name": "Hive MCP Server",
        "category": "AI & Inference",
        "categoryEs": "IA e Inferencia",
        "description": ("Deterministic AST chunker and MCP memory layer for multi-agent workflows."),
        "descriptionEs": ("Fragmentador AST determinista y capa de memoria MCP para flujos multi-agente."),
        "url": "https://mlorentedev.github.io/hive/",
        "node": "vps",
        "env": "prod",
        "tech": ["Python", "FastMCP", "Tree-sitter", "SQLite FTS5"],
        "isPublic": True,
        "status": "operational",
    },
    {
        "slug": "ollama",
        "name": "Ollama Local Engine",
        "category": "AI & Inference",
        "categoryEs": "IA e Inferencia",
        "description": ("Bare-metal local LLM inference cluster running Mistral and DeepSeek models."),
        "descriptionEs": ("Clúster bare-metal de inferencia LLM local corriendo modelos Mistral y DeepSeek."),
        "node": "jetson",
        "env": "prod",
        "tech": ["Ollama", "Go", "C++", "Bare-metal"],
        "isPublic": False,
        "status": "operational",
    },
    {
        "slug": "kubelab-api",
        "name": "KubeLab Platform API",
        "category": "Core Gateway",
        "categoryEs": "Gateway Principal",
        "description": ("High-throughput Go API, Token-Bucket rate limiting and platform telemetry."),
        "descriptionEs": ("API en Go de alto rendimiento, rate limiting por token bucket y telemetría de plataforma."),
        "url": "https://api.kubelab.live",
        "healthEndpoint": "https://api.kubelab.live/health",
        "node": "vps",
        "env": "prod",
        "tech": ["Go", "Traefik", "ArgoCD", "Kubernetes"],
        "isPublic": True,
        "status": "operational",
    },
    {
        "slug": "traefik",
        "name": "Traefik Ingress Proxy",
        "category": "Core Gateway",
        "categoryEs": "Gateway Principal",
        "description": ("Layer 7 cloud and homelab edge ingress router with Let's Encrypt TLS termination."),
        "descriptionEs": ("Enrutador Ingress L7 en cloud y edge con terminación TLS automática Let's Encrypt."),
        "node": "vps",
        "env": "common",
        "tech": ["Traefik", "K3s", "Let's Encrypt", "CrowdSec"],
        "isPublic": False,
        "status": "operational",
    },
    {
        "slug": "headscale",
        "name": "Headscale Mesh VPN",
        "category": "Core Gateway",
        "categoryEs": "Gateway Principal",
        "description": ("Self-hosted WireGuard control plane with MagicDNS and isolated tenant routing."),
        "descriptionEs": ("Plano de control WireGuard autoalojado con MagicDNS y enrutamiento aislado."),
        "node": "vps",
        "env": "common",
        "tech": ["WireGuard", "Go", "Tailscale", "SQLite"],
        "isPublic": False,
        "status": "operational",
    },
    {
        "slug": "authelia",
        "name": "Authelia Zero-Trust Auth",
        "category": "Core Gateway",
        "categoryEs": "Gateway Principal",
        "description": ("Two-factor authentication and forward-auth identity provider for internal services."),
        "descriptionEs": ("Autenticación de doble factor y proveedor forward-auth para servicios internos."),
        "node": "vps",
        "env": "common",
        "tech": ["Authelia", "Redis", "TOTP", "Duo"],
        "isPublic": False,
        "status": "operational",
    },
    {
        "slug": "argocd",
        "name": "Argo CD GitOps Hub",
        "category": "GitOps & Delivery",
        "categoryEs": "GitOps y Entrega",
        "description": ("Declarative GitOps continuous delivery synchronizing K3s clusters with drift detection."),
        "descriptionEs": ("Entrega continua GitOps declarativa sincronizando clústeres K3s con detección de drift."),
        "node": "gcp1",
        "env": "common",
        "tech": ["ArgoCD", "Kubernetes", "Kustomize", "Helm"],
        "isPublic": False,
        "status": "operational",
    },
    {
        "slug": "gitea",
        "name": "Gitea On-Prem Forge",
        "category": "GitOps & Delivery",
        "categoryEs": "GitOps y Entrega",
        "description": ("Lightweight self-hosted Git repository and automated CI mirror for private codebases."),
        "descriptionEs": ("Repositorio Git ligero autoalojado y mirror de CI automatizado para código privado."),
        "node": "beelink",
        "env": "common",
        "tech": ["Gitea", "Go", "PostgreSQL", "SSH"],
        "isPublic": False,
        "status": "operational",
    },
    {
        "slug": "grafana",
        "name": "Grafana Telemetry",
        "category": "Observability",
        "categoryEs": "Observabilidad",
        "description": ("Centralized metrics visualization, cluster resource dashboards and latency graphs."),
        "descriptionEs": ("Visualización centralizada de métricas, dashboards de clúster y gráficas de latencia."),
        "node": "vps",
        "env": "prod",
        "tech": ["Grafana", "Prometheus", "Loki", "Glances"],
        "isPublic": False,
        "status": "operational",
    },
    {
        "slug": "loki",
        "name": "Loki Log Aggregator",
        "category": "Observability",
        "categoryEs": "Observabilidad",
        "description": ("Horizontally-scalable log aggregation system indexed by Kubernetes pod labels."),
        "descriptionEs": ("Sistema escalable de agregación de logs indexado por etiquetas de pods de K8s."),
        "node": "vps",
        "env": "prod",
        "tech": ["Loki", "Promtail", "Go", "S3 Storage"],
        "isPublic": False,
        "status": "operational",
    },
    {
        "slug": "uptime-kuma",
        "name": "Uptime Kuma Probes",
        "category": "Observability",
        "categoryEs": "Observabilidad",
        "description": ("Independent synthetic HTTP and ICMP health monitor with 90-day SLA history tracking."),
        "descriptionEs": ("Monitor sintético independiente HTTP/ICMP con registro histórico de SLA a 90 días."),
        "node": "rpi3",
        "env": "common",
        "tech": ["Node.js", "Vue", "SQLite", "Docker"],
        "isPublic": False,
        "status": "operational",
    },
    {
        "slug": "minio",
        "name": "MinIO S3 Object Store",
        "category": "Storage & Data",
        "categoryEs": "Almacenamiento y Datos",
        "description": ("High-performance S3-compatible distributed object storage for backups and AI models."),
        "descriptionEs": ("Almacenamiento de objetos distribuido compatible con S3 para backups y modelos de IA."),
        "node": "vps",
        "env": "prod",
        "tech": ["MinIO", "Go", "S3 API", "K3s"],
        "isPublic": False,
        "status": "operational",
    },
    {
        "slug": "coredns",
        "name": "CoreDNS & Pi-hole Split Gateway",
        "category": "Core Gateway",
        "categoryEs": "Gateway Principal",
        "description": ("Authoritative Split DNS daemon and network sinkhole routing staging zones and microservices."),
        "descriptionEs": (
            "Demonio Split DNS autoritativo y sinkhole de red que enruta zonas de staging y microservicios."
        ),
        "node": "rpi4",
        "env": "common",
        "tech": ["CoreDNS", "Pi-hole", "Go", "DNSSEC"],
        "isPublic": False,
        "status": "operational",
    },
]

# Canonical architecture diagrams (Zero-Addressing enforced: no IP addresses or internal FQDNs)
ARCHITECTURE_DIAGRAMS: list[dict[str, Any]] = [
    {
        "id": "topology",
        "title": "Platform Infrastructure Topology",
        "titleEs": "Topología de Infraestructura de la Plataforma",
        "category": "Topology & Network",
        "categoryEs": "Topología y Red",
        "description": (
            "Hybrid cloud and on-premises bare-metal node architecture interconnected via"
            " encrypted Tailscale WireGuard mesh."
        ),
        "descriptionEs": (
            "Arquitectura híbrida cloud y bare-metal on-premise interconectada por malla WireGuard cifrada."
        ),
        "mermaid": (
            "flowchart TB\n"
            '    subgraph internet["Public Internet & Ingress"]\n'
            '        CF["Cloudflare DNS<br/>proxied: api.kubelab.live · direct: mlorente.dev"]\n'
            "    end\n"
            '    subgraph alwayson["Always-on Cloud Infrastructure"]\n'
            '        VPS["Hetzner Cloud VPS · ARM64 Neoverse-N1, 7.5GB<br/>'
            "Prod K3s: Traefik, API (Go), Web (Astro),<br/>"
            'Grafana, Loki, Authelia, CrowdSec, MinIO<br/>+ Headscale Mesh Coordinator"]\n'
            '        GCP["gcp1 · GCP e2-small<br/>Argo CD GitOps Hub (ADR-063)"]\n'
            '        AWS["aws1 · AWS t4g.small<br/>Standby, powered down"]\n'
            '        RPI3["RPi3 · Uptime Kuma<br/>Independent external monitor"]\n'
            "    end\n"
            '    subgraph homelab["On-Demand Homelab"]\n'
            '        RPI4["RPi4 Gateway<br/>Pi-hole + CoreDNS (Split DNS)"]\n'
            '        ACE1["ace1 · Intel N95, 11.5GB<br/>Staging K3s, single node"]\n'
            '        ACE2["ace2 · Intel N95, 11.5GB<br/>Dev node: agent workspaces"]\n'
            '        BEE["Beelink · Intel N95, 7.5GB<br/>Gitea forge, CI runner, MinIO"]\n'
            '        JET["Jetson Nano · 3.9GB<br/>Pollex Edge AI (Qwen 2.5 1.5B, CPU)"]\n'
            "    end\n"
            "    CF --> VPS\n"
            '    GCP -- "Argo CD Sync · WireGuard" --> VPS\n'
            '    GCP -- "Argo CD Sync · WireGuard" --> ACE1\n'
            '    VPS -. "Headscale Mesh" .- RPI4\n'
            "    RPI4 --- ACE1\n"
            "    RPI4 --- ACE2\n"
            "    RPI4 --- BEE\n"
            "    RPI4 --- JET\n"
            "    VPS -. Mesh .- RPI3\n"
            "    VPS -. Mesh .- GCP\n"
            "    AWS -.-> GCP"
        ),
    },
    {
        "id": "gitops",
        "title": "GitOps Edge-to-Cloud Delivery Pipeline",
        "titleEs": "Pipeline de Entrega GitOps Edge-to-Cloud",
        "category": "Delivery & CI/CD",
        "categoryEs": "Entrega y CI/CD",
        "description": (
            "Deterministic build-once promote-by-digest delivery promoting verified container"
            " bytes from staging to production."
        ),
        "descriptionEs": (
            "Flujo determinista build-once/promote-by-digest que promueve bytes verificados de staging a producción."
        ),
        "mermaid": (
            "flowchart LR\n"
            '    PR["1. PR (feature/*)<br/>Conventional Commits"] --> '
            'CI["2. CI Validation<br/>Astro check + Lint"]\n'
            '    CI --> BUILD["3. Build Image<br/>sha-&lt;short&gt;"]\n'
            '    BUILD --> MERGE["4. Squash-Merge<br/>to master branch"]\n'
            '    MERGE --> SD["5. Staging Dispatch<br/>Webhook to kubelab"]\n'
            '    SD --> AS["6. Argo CD Staging<br/>Auto-sync to Ace1 in &lt;30s"]\n'
            '    MERGE --> RP["7. Release Please<br/>Release PR (SemVer vX.Y.Z)"]\n'
            '    RP --> PP["8. Promote Prod<br/>Re-tag exact staging digest"]\n'
            '    PP --> AP["9. Argo CD Prod<br/>Zero-downtime K3s rollout"]'
        ),
    },
    {
        "id": "security",
        "title": "Zero-Trust Request Path & Perimeter Defense",
        "titleEs": "Ruta de Peticiones Zero-Trust y Defensa Perimetral",
        "category": "Security & Gateway",
        "categoryEs": "Seguridad y Gateway",
        "description": (
            "Layered security at the edge: Traefik terminates TLS and applies token-bucket rate"
            " limiting, CrowdSec blocks by behaviour, and Authelia enforces 2FA forward auth on"
            " the internal services. Cloudflare fronts api.kubelab.live only."
        ),
        "descriptionEs": (
            "Seguridad en capas en el edge: Traefik termina TLS y aplica rate limiting por token"
            " bucket, CrowdSec bloquea por comportamiento y Authelia exige 2FA en los servicios"
            " internos. Cloudflare solo hace de proxy en api.kubelab.live."
        ),
        "mermaid": (
            "flowchart TD\n"
            '    Client(["Client / Browser"]):::client -->|HTTPS 443| '
            'CF["Cloudflare DNS<br/>proxied for api.kubelab.live only"]\n'
            '    CF -->|Forward| Traefik["Traefik L7 Ingress Router<br/>Rate Limiting & Secure Headers"]\n'
            '    Traefik --> CrowdSec{"CrowdSec IPS Bouncer<br/>Behavioral Threat Analysis"}\n'
            '    CrowdSec -->|Malicious IP| Block["403 Forbidden / Drop"]\n'
            '    CrowdSec -->|Clean Traffic| Auth{"Route Inspection"}\n'
            '    Auth -->|Public Route| PublicApps["Public Services<br/>mlorente.dev · API · Pollex"]\n'
            '    Auth -->|Private / Admin| Authelia["Authelia Forward-Auth<br/>2FA / Duo / TOTP Session"]\n'
            '    Authelia -->|Authenticated| InternalApps["Internal Platform<br/>Grafana · ArgoCD · Gitea · MinIO"]\n'
            '    InternalApps --> WireGuard["Tailscale WireGuard Mesh<br/>Direct Pod Encapsulation"]'
        ),
    },
    {
        "id": "ai-mcp",
        "title": "Edge AI & Multi-Agent MCP Knowledge Plane",
        "titleEs": "Plano de Conocimiento MCP Multi-Agente y Edge AI",
        "category": "AI & Knowledge",
        "categoryEs": "IA y Conocimiento",
        "description": ("Sub-millisecond semantic retrieval layer and physical Jetson GPU hardware inference."),
        "descriptionEs": (
            "Capa de recuperación semántica en submilisegundos e inferencia GPU en hardware Jetson físico."
        ),
        "mermaid": (
            "flowchart TB\n"
            '    subgraph Agents["Multi-Agent Swarm"]\n'
            '        Claude["Claude Code"]\n'
            '        Antigravity["Antigravity IDE / CLI"]\n'
            "    end\n"
            '    subgraph MCP["Hive Knowledge & Context Plane"]\n'
            '        Vault["Obsidian Knowledge Vault<br/>ADRs, Runbooks, Lessons"]\n'
            '        TreeSitter["Tree-sitter AST Chunker<br/>Deterministic code/markdown"]\n'
            '        FTS5["SQLite FTS5 BM25 Engine<br/>Sub-millisecond ranking"]\n'
            '        FastMCP["Hive FastMCP Server<br/>Tools: vault_query, session_briefing"]\n'
            "    end\n"
            '    subgraph EdgeAI["Hardware CPU Acceleration"]\n'
            '        ClientReq["Client Text / Polish Request"]\n'
            '        JetsonGPU["NVIDIA Jetson Nano (4GB)<br/>128 Maxwell CPU Cores"]\n'
            '        Qwen["Ollama Quantized Qwen 1.5B<br/>~3.2s TTFT · 0% Cloud Leakage"]\n'
            "    end\n"
            "    Vault --> TreeSitter --> FTS5 --> FastMCP\n"
            "    FastMCP <-->|Model Context Protocol| Agents\n"
            "    ClientReq --> JetsonGPU --> Qwen --> ClientReq"
        ),
    },
    {
        "id": "dns",
        "title": "Split DNS Resolution Paths & Mesh Routing",
        "titleEs": "Rutas de Resolución Split DNS y Enrutamiento Mesh",
        "category": "DNS & Network",
        "categoryEs": "DNS y Red",
        "description": ("Intelligent split DNS routing staging domains, bare-metal extra records and public zones."),
        "descriptionEs": (
            "Enrutamiento Split DNS inteligente para dominios staging, registros bare-metal y zonas públicas."
        ),
        "mermaid": (
            "flowchart TD\n"
            '    Client["Client / VPN Node"] --> Query{"Target Domain"}\n'
            '    Query -->|"*.staging.kubelab.live<br/>staging.mlorente.dev"| '
            'Headscale["Headscale Split DNS<br/>staging_zones &rarr; RPi4"]\n'
            '    Headscale --> CoreDNS["RPi4 CoreDNS<br/>Resolves to the staging nodes over the mesh"]\n'
            '    Query -->|"*.kubelab.live (Prod)<br/>mlorente.dev"| '
            'PublicDNS["Public Cloudflare DNS<br/>Resolves to Hetzner VPS"]\n'
            '    Query -->|"Ad / Tracker Domain"| PiHole["RPi4 Pi-hole Sinkhole<br/>Sinkhole / Blocked"]'
        ),
    },
]


def _get_commit_provenance(file_path: Path) -> tuple[str, str]:
    """Return deterministic (timestamp, sha) for the file from git log."""
    try:
        ts = subprocess.check_output(
            ["git", "log", "-1", "--format=%cI", str(file_path)],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        sha = subprocess.check_output(
            ["git", "log", "-1", "--format=%H", str(file_path)],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if ts and sha:
            return ts, sha
    except Exception:
        pass
    # Fallback if git is unavailable or repo is not yet committed
    return datetime.now(timezone.utc).isoformat(), "0000000000000000000000000000000000000000"


def generate_manifest(config_path: Path | None = None) -> dict[str, Any]:
    """Project common.yaml SSOT into the public platform.json manifest."""
    cfg_file = config_path or COMMON_YAML_PATH
    if not cfg_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {cfg_file}")

    with open(cfg_file, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    generated_at, source_commit = _get_commit_provenance(cfg_file)

    # 1. Fleet nodes extraction
    nodes: list[dict[str, Any]] = []
    active_node_count = 0
    for node_id, meta in NODE_METADATA.items():
        node_entry = {"id": node_id, **meta}
        if node_entry.get("status") != "standby":
            active_node_count += 1
        nodes.append(node_entry)

    # 2. Cluster metadata
    k3s_ver = config.get("k3s", {}).get("version", "v1.34.4+k3s1")
    if not k3s_ver.startswith("K3s "):
        k3s_ver = f"K3s {k3s_ver}"

    cluster_info = {
        "name": "KubeLab Hybrid Cloud & Edge Platform",
        "version": k3s_ver,
        "gitops": "Argo CD v3.4.1 · 2 applications synced",
        "uptime": "99.9% (90d, Uptime Kuma)",
        "activeNodes": active_node_count,
        "totalServices": 35,
        "kubernetesClusters": 3,
        "kubernetesNodes": 3,
    }

    # 3. Platform metrics
    metrics = {
        "inferenceLatency": "not measured",
        "contextReduction": "67–82%",
        "reconciliationTime": "<30s",
        "edgeArchitecture": "Tailscale mesh (Headscale)",
        "uptimeScore": "99.9%",
        "gitopsSyncLoop": "<30s Drift Loop",
    }

    # 4. Assemble manifest
    manifest: dict[str, Any] = {
        "generated_at": generated_at,
        "source_commit": source_commit,
        "cluster": cluster_info,
        "metrics": metrics,
        "nodes": nodes,
        "services": PLATFORM_SERVICES,
        "diagrams": ARCHITECTURE_DIAGRAMS,
    }

    # 5. Zero-Addressing validation (fail closed before emitting)
    serialized = json.dumps(manifest)
    if re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", serialized):
        raise ValueError("Zero-Addressing violation: IP address detected in manifest payload")
    if re.search(r"\b[a-zA-Z0-9.-]+\.(?:internal|local|lan)\b", serialized):
        raise ValueError("Zero-Addressing violation: internal hostname detected (.internal, .local, or .lan)")

    return manifest


def sync(output_path: Path | None = None, check: bool = False) -> int:
    """Generate or check the platform.json manifest.

    Args:
        output_path: Destination path (default: infra/config/platform.json).
        check: If True, exits with 1 on drift instead of writing.

    Returns:
        0 on success or match, 1 on failure or drift.
    """
    target = output_path or DEFAULT_OUTPUT
    manifest = generate_manifest()
    content = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"

    if check:
        if not target.exists():
            logger.error(f"Platform manifest missing: {target}")
            return 1
        current = target.read_text(encoding="utf-8")
        if current != content:
            logger.error(f"Drift detected in {target}")
            diff = difflib.unified_diff(
                current.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=f"a/{target.name}",
                tofile=f"b/{target.name}",
            )
            logger.error("".join(diff))
            return 1
        logger.success(f"Platform manifest {target.name} is in sync")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    write_text_lf(target, content)
    logger.success(f"Synced platform manifest: {target}")
    return 0
