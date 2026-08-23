"""Generate Homepage config from common.yaml SSOT + Jinja2 templates.

Reads networking, service definitions, and node topology from common.yaml,
then renders homepage-templates/*.j2 → homepage-config/*.yaml.

Run: `make sync-homepage` or `python toolkit/scripts/sync_homepage_config.py`
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import yaml
from jinja2 import Environment, FileSystemLoader

from toolkit.core.io import write_text_lf
from toolkit.features.k8s_kubeconfig import output_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMON_YAML = PROJECT_ROOT / "infra/config/values/common.yaml"
TEMPLATES_DIR = PROJECT_ROOT / "infra/k8s/base/services/homepage-templates"
OUTPUT_DIR = PROJECT_ROOT / "infra/k8s/base/services/homepage-config"

# Cloudflare zone ID for kubelab.live — used in analytics widget
CLOUDFLARE_ZONE_ID = "a708cb04dd4572e76eb6da42cc09507d"


def hub_node(config: dict[str, Any]) -> tuple[str, str]:
    """The hub's name and the address to show for it, from the SSOT.

    `clusters.hub.node` is what says which machine is the Argo CD hub, and it is
    the single value the AWS->GCP cutover flips. Before this, four places in this
    file spelled "aws1" as a literal -- a topology diagram, a flow diagram, an
    ASCII table and a service row -- so the cutover was four edits nobody would
    connect to each other, in a file whose whole job is to describe the fleet
    accurately.

    Address prefers the recorded IP and falls back to MagicDNS, which is the
    opposite of `generator_ansible` and deliberately so: these tables are read by
    a human looking for an address, and one of them is literally titled "IP
    reference". aws1 therefore renders exactly as it did before this change.

    gcp1 has NO recorded IP at all -- a MIG rotates it on every preemption, so
    `networking.gcp` declines to cache one -- and falls back to
    `gcp1.kubelab.internal`, which is its stable identity.
    """
    name = config.get("clusters", {}).get("hub", {}).get("node", "")
    networking = config.get("networking", {})
    block = networking.get(name)
    if not isinstance(block, dict):
        block = networking.get("nodes", {}).get(name, {})
        # Cloud nodes sit at the top level keyed by provider, not by hostname.
        if not block:
            for candidate in networking.values():
                if isinstance(candidate, dict) and candidate.get("hostname") == name:
                    block = candidate
                    break
    addr = block.get("tailscale_ip") or block.get("tailscale_dns") or "?"
    return name or "?", str(addr)


def resolve_path(data: dict[str, Any], path: str) -> Any:
    """Resolve dotted path in nested dict."""
    current: Any = data
    for key in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def get_traefik_cluster_ip() -> str:
    """Get Traefik ClusterIP from K8s — dynamic, not in SSOT."""
    try:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "svc",
                "traefik",
                "-n",
                "kube-system",
                "-o",
                "jsonpath={.spec.clusterIP}",
                "--kubeconfig",
                str(output_path("staging")),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    # Fallback — last known ClusterIP
    return "10.43.86.38"


def build_node_list(config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Build ordered node list from common.yaml SSOT (SSOT-005).

    Reads `networking.{nodes.*, vps, aws}` and renders one cockpit tile for
    every entry that defines a `dashboard:` sub-block. Sorted by
    `dashboard.order`. Display name comes from `dashboard.display_name`
    (falls back to the key). Widget shape from `dashboard.widget`:
    - `glances`: emits `glances=True` + optional `glances_version`.
    - `ping`:    emits `glances=False` + `ping_url`. Source of the URL
                 (mutually exclusive — exactly one required):
                 * `ping_target: <dotted-path>` — references
                   `apps.services.<path>` and builds
                   `http://<node.tailscale_ip>:<svc.default_port>`. Keeps
                   the host single-sourced from the node entry.
                 * `ping_url: <full URL>` — used verbatim. Use only when
                   the target is NOT the node's own IP (e.g. aws1 pings
                   the public Argo CD domain).
    - `none`:    emits `glances=False` only (tile with description, no widget).
    """
    networking = config.get("networking") or {}
    apps_services = (config.get("apps") or {}).get("services") or {}

    def _ip_for(entry: dict[str, Any]) -> str | None:
        # aws prefers MagicDNS over IP (ADR-025); other entries use tailscale_ip.
        return entry.get("tailscale_dns") or entry.get("tailscale_ip")

    def _resolve_ping_url(dashboard: dict[str, Any], ip: str | None, key: str) -> str:
        target = dashboard.get("ping_target")
        explicit = dashboard.get("ping_url")
        if target and explicit:
            raise ValueError(f"dashboard for {key!r}: ping_target and ping_url are mutually exclusive")
        if target:
            svc = resolve_path(apps_services, target)
            if not isinstance(svc, dict):
                raise ValueError(f"dashboard for {key!r}: ping_target {target!r} not found under apps.services")
            port = svc.get("default_port")
            if not port:
                raise ValueError(f"dashboard for {key!r}: apps.services.{target} has no default_port")
            if not ip:
                raise ValueError(f"dashboard for {key!r}: ping_target requires the node to have an IP")
            return f"http://{ip}:{port}"
        if explicit:
            return explicit
        raise ValueError(f"dashboard for {key!r}: widget=ping requires ping_target or ping_url")

    candidates: list[tuple[str, dict[str, Any], str | None]] = []
    for name, node in (networking.get("nodes") or {}).items():
        if node.get("dashboard"):
            candidates.append((name, node["dashboard"], _ip_for(node)))
    for singleton_key in ("vps", "gcp", "aws"):
        entry = networking.get(singleton_key) or {}
        if entry.get("dashboard"):
            candidates.append((singleton_key, entry["dashboard"], _ip_for(entry)))

    candidates.sort(key=lambda c: c[1].get("order", 999))

    out: list[tuple[str, dict[str, Any]]] = []
    for key, dashboard, ip in candidates:
        display_name = dashboard.get("display_name", key)
        widget = dashboard.get("widget", "none")
        tile: dict[str, Any] = {
            "ip": ip,
            "icon": dashboard["icon"],
            "description": dashboard["description"],
        }
        if widget == "glances":
            tile["glances"] = True
            if "glances_version" in dashboard:
                tile["glances_version"] = dashboard["glances_version"]
        elif widget == "ping":
            tile["glances"] = False
            tile["ping_url"] = _resolve_ping_url(dashboard, ip, key)
        else:
            tile["glances"] = False
        out.append((display_name, tile))
    return out


def build_service_tables(
    config: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """Build staging, prod, and shared service lists from common.yaml SSOT."""
    hub_name, _hub_addr = hub_node(config)
    base = config.get("global", {}).get("base_domain", "kubelab.live")
    apps = config.get("apps", {})
    services = apps.get("services", {})
    platform = apps.get("platform", {})

    def _auth(svc: dict[str, Any], override: str = "") -> str:
        if override:
            return override
        return "Authelia" if svc.get("auth_level") == "one_factor" else "Public"

    def _ver(image_str: str) -> str:
        """Extract version tag from image string like 'authelia/authelia:4.39.15'."""
        if ":" in image_str:
            tag = image_str.rsplit(":", 1)[1]
            # Clean up common prefixes/suffixes
            tag = tag.lstrip("v")
            if tag.startswith("RELEASE."):
                tag = tag[8:18]  # YYYY-MM-DD
            if tag.endswith("-alpine"):
                tag = tag[:-7]
            return tag
        return ""

    def _svc(
        name: str,
        url: str,
        health: str,
        auth: str,
        cat: str,
        node: str,
        notes: str = "",
        version: str = "",
    ) -> dict[str, str]:
        return {
            "name": name,
            "url": url,
            "health": health,
            "auth": auth,
            "category": cat,
            "node": node,
            "version": version,
            "notes": notes,
        }

    def _env_services(env: str) -> list[dict[str, str]]:
        prefix = f"staging.{base}" if env == "staging" else base
        ml = "staging.mlorente.dev" if env == "staging" else "mlorente.dev"
        nd = "ace1" if env == "staging" else "VPS"

        api = platform.get("api", {})
        authelia = services.get("security", {}).get("authelia", {})
        crowdsec = services.get("security", {}).get("crowdsec", {})
        traefik = services.get("core", {}).get("traefik", {})
        n8n = services.get("automation", {}).get("n8n", {})
        minio = services.get("data", {}).get("minio", {})
        grafana = services.get("observability", {}).get("grafana", {})
        loki = services.get("observability", {}).get("loki", {})

        return [
            _svc(
                "API",
                f"https://api.{prefix}",
                f"https://api.{prefix}" + api.get("health_path", "/health"),
                _auth(api),
                "Platform",
                nd,
                "REST API",
                version=api.get("version", ""),
            ),
            _svc(
                "Web",
                f"https://{ml}",
                f"https://{ml}",
                "Public",
                "Platform",
                nd,
                "Frontend",
                version=platform.get("web", {}).get("version", ""),
            ),
            _svc(
                "Authelia",
                f"https://auth.{prefix}",
                f"https://auth.{prefix}" + authelia.get("health_path", "/api/health"),
                "Public (IdP)",
                "Security",
                nd,
                "SSO / Login",
                version=_ver(authelia.get("image", "")),
            ),
            _svc(
                "CrowdSec",
                f"https://crowdsec.{prefix}",
                f"https://crowdsec.{prefix}" + crowdsec.get("health_path", "/health"),
                _auth(crowdsec),
                "Security",
                nd,
                "WAF / LAPI",
                version=_ver(crowdsec.get("image", "")),
            ),
            _svc(
                "Traefik",
                f"https://traefik.{prefix}/dashboard/",
                f"https://traefik.{prefix}/dashboard/",
                _auth(traefik),
                "Core",
                nd,
                "Dashboard",
                version=config.get("k3s", {}).get("traefik_version", "3.x"),
            ),
            _svc(
                "n8n",
                f"https://n8n.{prefix}",
                f"https://n8n.{prefix}" + n8n.get("health_path", "/healthz"),
                "Authelia" if env == "prod" else "Built-in",
                "Core",
                nd,
                "Automation",
                version=_ver(n8n.get("image", "")),
            ),
            _svc(
                "MinIO API",
                f"https://minio.{prefix}",
                f"https://minio.{prefix}" + minio.get("health_path", "/minio/health/live"),
                "Built-in",
                "Data",
                nd,
                "S3 API",
                version=_ver(minio.get("image", "")),
            ),
            _svc(
                "MinIO Console",
                f"https://console.minio.{prefix}",
                f"https://console.minio.{prefix}",
                "Built-in (OIDC)",
                "Data",
                nd,
                "Console UI",
                version=_ver(minio.get("image", "")),
            ),
            _svc(
                "Grafana",
                f"https://grafana.{prefix}",
                f"https://grafana.{prefix}" + grafana.get("health_path", "/api/health"),
                _auth(grafana),
                "Observability",
                nd,
                "Dashboards",
                version=_ver(grafana.get("image", "")) or "latest",
            ),
            _svc(
                "Loki",
                f"https://loki.{prefix}",
                f"https://loki.{prefix}" + loki.get("health_path", "/ready"),
                _auth(loki),
                "Observability",
                nd,
                "Log aggregation",
                version=_ver(loki.get("image", "")),
            ),
            _svc(
                "Apprise",
                "http://apprise.kubelab.svc:8000",
                "http://apprise.kubelab.svc:8000/health",
                "Internal",
                "Core",
                nd,
                "Notification gateway",
                version="1.5.0",
            ),
            _svc(
                "PostgreSQL",
                "postgres.kubelab.svc:5432",
                "postgres.kubelab.svc:5432",
                "Internal",
                "Data",
                nd,
                "Platform DB",
                version="17-alpine",
            ),
            _svc(
                "Redis",
                "redis.kubelab.svc:6379",
                "redis.kubelab.svc:6379",
                "Internal",
                "Data",
                nd,
                "Session cache",
                version="7-alpine",
            ),
            _svc(
                "Vector",
                "vector.kubelab.svc:8686",
                "vector.kubelab.svc:8686",
                "Internal",
                "Observability",
                nd,
                "Log pipeline agent",
                version="DaemonSet",
            ),
            _svc(
                "SRE Watchers",
                "-",
                "-",
                "Internal",
                "Observability",
                nd,
                "Quota / R2 / Disk",
                version="CronJobs",
            ),
            _svc(
                "Homepage",
                f"https://home.{prefix}",
                f"https://home.{prefix}",
                "Public",
                "Core",
                nd,
                "This dashboard",
                version="latest",
            ),
        ]

    staging = _env_services("staging")
    prod = _env_services("prod")
    prod.append(_svc("kubelab.live", f"https://{base}", f"https://{base}", "-", "Core", "VPS", "301 → mlorente.dev"))

    headscale = services.get("core", {}).get("headscale", {})
    uptime_kuma = services.get("observability", {}).get("uptime_kuma", {})
    gitea = services.get("core", {}).get("gitea", {})

    shared = [
        # Gitea moved out of the per-environment list when ADR-061 classified it
        # `singleton`: there is exactly one instance, on one apex name, so a
        # `gitea.staging.*` tile would advertise a host that no longer resolves —
        # the same failure #1027 fixed for Pi-hole after its apex rename.
        _svc(
            "Gitea",
            f"https://gitea.{base}",
            f"https://gitea.{base}" + gitea.get("health_path", "/api/healthz"),
            "Built-in (OIDC)",
            "Core",
            "Beelink",
            "Git hosting · on-demand",
            version=_ver(gitea.get("image", "")),
        ),
        _svc(
            "Argo CD",
            f"https://argo.{base}",
            f"https://argo.{base}",
            "Authelia",
            "Core",
            hub_name,
            "GitOps hub",
            version="2.14",
        ),
        _svc(
            "Headscale",
            f"https://vpn.{base}",
            f"https://vpn.{base}/health",
            "Built-in",
            "Network",
            "VPS",
            "VPN mesh",
            version=_ver(headscale.get("image", "")),
        ),
        _svc(
            "Uptime Kuma",
            f"https://status.{base}",
            f"https://status.{base}",
            "Public",
            "Observability",
            "RPi3",
            "Status page",
            version=_ver(uptime_kuma.get("image", "")),
        ),
        _svc(
            "Pi-hole",
            f"https://pihole.{base}",
            f"https://pihole.{base}/admin/",
            "Built-in (v6)",
            "Network",
            "RPi4",
            "DNS filtering",
            version="v6",
        ),
        _svc(
            "Pollex",
            "http://100.64.0.8:8000",
            "http://100.64.0.8:8000",
            "Tailscale",
            "AI",
            "Jetson",
            "Edge AI · on-demand",
        ),
    ]

    return staging, prod, shared


def build_mermaid_topology(config: dict[str, Any]) -> str:
    """Generate Mermaid topology diagram from common.yaml."""
    hub_name, hub_addr = hub_node(config)
    networking = config.get("networking", {})
    n = networking.get("nodes", {})
    vps = networking.get("vps", {})
    lan_cidr = networking.get("lan_cidr", "?")
    return f"""graph TB
  subgraph Internet
    CF[Cloudflare DNS+CDN]
    Users[Users]
  end
  subgraph AlwaysOn["Always-On (24/7) — ADR-028"]
    VPS["VPS {vps.get("public_ip")} / {vps.get("tailscale_ip")}<br/>K3s Prod 8GB"]
    HUB["{hub_name} {hub_addr}<br/>Argo CD Hub 2GB"]
    RPI3["RPi3 {n["rpi3"]["tailscale_ip"]}<br/>Uptime Kuma 1GB"]
  end
  subgraph OnDemand["On-Demand homelab {lan_cidr} — ADR-028"]
    ACE1["ace1 {n["ace1"]["lan_ip"]} / {n["ace1"]["tailscale_ip"]}<br/>K3s Staging 12GB"]
    ACE2["ace2 {n["ace2"]["lan_ip"]} / {n["ace2"]["tailscale_ip"]}<br/>Dev node / CDE 12GB"]
    BEE["Beelink {n["beelink"]["lan_ip"]} / {n["beelink"]["tailscale_ip"]}<br/>Platform Node 8GB"]
    RPI4["RPi4 {n["rpi4"]["lan_ip"]} / {n["rpi4"]["tailscale_ip"]}<br/>DNS Gateway 8GB"]
    JET["Jetson {n["jetson"]["lan_ip"]} / {n["jetson"]["tailscale_ip"]}<br/>Pollex 4GB"]
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
  class CF,Users ext"""


MERMAID_GITOPS = """graph LR
  DEV[Developer] -->|push| GH[GitHub]
  GH -->|webhook| ARGO[Argo CD<br/>{hub_name} Hub]
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
  class GH,GHA,DH,DEV ci"""


def build_mermaid_dns(config: dict[str, Any]) -> str:
    """Generate Mermaid DNS diagram from common.yaml."""
    vps = config.get("networking", {}).get("vps", {})
    n = config.get("networking", {}).get("nodes", {})
    return f"""graph TB
  C[Client] -->|*.kubelab.live| CFDNS[Cloudflare]
  CFDNS --> VPS["VPS Traefik {vps.get("public_ip")}"]
  CFDNS -->|"pihole.kubelab.live<br/>(OPS-022)"| ACE1["ace1 Traefik {n["ace1"]["tailscale_ip"]}"]
  C -->|VPN| HS[Headscale]
  HS -->|"split DNS<br/>*.staging.kubelab.live ONLY"| PH["Pi-hole RPi4"]
  PH -->|forward staging| CD["CoreDNS RPi4"]
  CD --> ACE1["ace1 Traefik {n["ace1"]["tailscale_ip"]}"]
  PH -->|non-staging| UP[1.1.1.1 / 8.8.8.8]
  classDef dns fill:#ede9fe,stroke:#8b5cf6,stroke-width:2px
  classDef proxy fill:#dbeafe,stroke:#3b82f6,stroke-width:2px
  classDef ext fill:#f3f4f6,stroke:#9ca3af
  classDef vpn fill:#dcfce7,stroke:#22c55e,stroke-width:2px
  class PH,CD,CFDNS dns
  class VPS,ACE1 proxy
  class C,HS,UP ext"""


MERMAID_REQUEST = """graph LR
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
  class BLOCK block"""


def build_ascii_topology(config: dict[str, Any]) -> str:  # noqa: E501
    """Generate ASCII topology diagram from common.yaml."""
    hub_name, hub_addr = hub_node(config)
    networking = config.get("networking", {})
    n = networking.get("nodes", {})
    vps = networking.get("vps", {})
    lan_cidr = networking.get("lan_cidr", "?")

    vps_pub = vps.get("public_ip", "?")
    vps_ts = vps.get("tailscale_ip", "?")

    def node(name: str) -> tuple[str, str]:
        nd = n.get(name, {})
        return nd.get("lan_ip", "?"), nd.get("tailscale_ip", "?")

    a1l, a1t = node("ace1")
    a2l, a2t = node("ace2")
    r4l, r4t = node("rpi4")
    bel, bet = node("beelink")
    jel, jet = node("jetson")
    _, r3t = node("rpi3")

    lines = [
        "INTERNET",
        f"  Cloudflare DNS --> VPS ({vps_pub})",
        "",
        "ALWAYS-ON 24/7 (ADR-028)",
        f"  VPS        {vps_pub} / {vps_ts}  K3s Prod 8GB",
        f"  {hub_name:<10} {hub_addr:<21} Argo CD Hub 2GB",
        f"  RPi3       {r3t}                 Uptime Kuma 1GB",
        "",
        f"ON-DEMAND homelab {lan_cidr} (ADR-028)",
        f"  ace1       {a1l} / {a1t}   K3s Staging 12GB",
        f"  ace2       {a2l} / {a2t}     Dev node / CDE 12GB",
        f"  Beelink    {bel} / {bet}     Platform Node 8GB",
        f"  RPi4       {r4l} / {r4t}    DNS Gateway 8GB",
        f"  Jetson     {jel} / {jet}     Pollex 4GB",
        "",
        "CONNECTIONS",
        "  VPS <--> ace1      Tailscale",
        f"  VPS <--> {hub_name:<10}Tailscale",
        "  VPS <--> RPi3      Tailscale",
        "  RPi4 <-> VPS       Tailscale",
        "  ace1 --- ace2      LAN",
        "  ace1 --- RPi4      LAN",
        "  ace1 --- Beelink   LAN",
        "  ace1 --- Jetson    LAN",
    ]
    return "\n".join(lines)


def build_ip_reference(config: dict[str, Any]) -> str:  # noqa: E501
    """Generate IP reference table from common.yaml."""
    hub_name, hub_addr = hub_node(config)
    n = config.get("networking", {}).get("nodes", {})
    vps = config.get("networking", {}).get("vps", {})

    def _node(name: str) -> tuple[str, str]:
        nd = n.get(name, {})
        return nd.get("lan_ip", "?"), nd.get("tailscale_ip", "?")

    def _row(name: str, lan: str, ts: str, role: str) -> str:
        return f"{name:<12} {lan:<16} {ts:<16} {role}"

    a1l, a1t = _node("ace1")
    a2l, a2t = _node("ace2")
    r4l, r4t = _node("rpi4")
    _, r3t = _node("rpi3")
    bel, bet = _node("beelink")
    jel, jet = _node("jetson")

    rows = [
        _row("NODE", "LAN", "TAILSCALE", "ROLE"),
        f"{'─' * 12} {'─' * 16} {'─' * 16} {'─' * 20}",
        _row("VPS", vps.get("public_ip", "?"), vps.get("tailscale_ip", "?"), "K3s Prod · 8GB"),
        _row(hub_name, "—", hub_addr, "Argo CD Hub · 2GB"),
        _row("ace1", a1l, a1t, "K3s Staging · 12GB"),
        _row("ace2", a2l, a2t, "Dev node / CDE · 12GB"),
        _row("RPi4", r4l, r4t, "DNS Gateway · 8GB"),
        _row("RPi3", "—", r3t, "Uptime Kuma · 1GB"),
        _row("Beelink", bel, bet, "Platform Node · 8GB"),
        _row("Jetson", jel, jet, "Pollex · 4GB"),
    ]
    return "\n".join(rows)


def build_dns_map(config: dict[str, Any]) -> str:
    """Generate DNS zone map from common.yaml."""
    vps = config.get("networking", {}).get("vps", {})
    n = config.get("networking", {}).get("nodes", {})
    vps_pub = vps.get("public_ip", "?")
    ace1_ts = n.get("ace1", {}).get("tailscale_ip", "?")

    rows = [
        f"{'DOMAIN':<36} {'RESOLVES TO'}",
        f"{'─' * 36} {'─' * 40}",
        "",
        "PROD (public DNS via Cloudflare)",
        f"  {'*.kubelab.live':<34} VPS Traefik ({vps_pub})",
        f"  {'mlorente.dev':<34} VPS Traefik ({vps_pub})",
        f"  {'vpn.kubelab.live':<34} {vps_pub} (public, never Tailscale)",
        f"  {'pihole.kubelab.live':<34} {ace1_ts} (public record, VPN-reachable only — OPS-022)",
        "",
        "STAGING (VPN-only via split DNS)",
        f"  {'*.staging.kubelab.live':<34} Headscale → Pi-hole → CoreDNS → ace1 ({ace1_ts})",
    ]
    # The old pihole.staging.* row (LAN EndpointSlice → RPi4) and the "Headscale extra_records"
    # section were both removed with OPS-022 — extra_records has never resolved for anything
    # (see CLAUDE.md gotcha, #964), and pihole no longer uses either path.
    return "\n".join(rows)


def build_tech_stack(config: dict[str, Any]) -> str:
    """Generate tech stack reference table from common.yaml."""
    hub_name, hub_addr = hub_node(config)
    k3s_ver = config.get("k3s", {}).get("version", "?")
    rows = [
        f"{'TECHNOLOGY':<20} {'PURPOSE':<28} {'WHERE':<24} {'MANAGED BY'}",
        f"{'─' * 20} {'─' * 28} {'─' * 24} {'─' * 20}",
        "",
        "ORCHESTRATION",
        f"  {'K3s':<18} {'Container orchestration':<28} {'ace1, VPS':<24} Ansible",
        f"  {'Kustomize':<18} {'K8s manifest overlays':<28} {'ace1, VPS':<24} toolkit / make",
        f"  {'Helm':<18} {'Third-party charts':<28} {'ace1, VPS':<24} HelmChartConfig",
        "",
        "INFRASTRUCTURE",
        f"  {'Terraform':<18} {'DNS records':<28} {'Cloudflare':<24} make deploy-dns",
        f"  {'Ansible':<18} {'Node provisioning':<28} {'All nodes':<24} make provision",
        f"  {'Docker Compose':<18} {'VPS services':<28} {'VPS':<24} make deploy-vps",
        "",
        "NETWORKING",
        f"  {'Traefik':<18} {'Reverse proxy + TLS':<28} {'ace1, VPS (K3s)':<24} HelmChartConfig",
        f"  {'Headscale':<18} {'VPN mesh (WireGuard)':<28} {'VPS (Docker)':<24} Ansible",
        f"  {'CoreDNS':<18} {'Staging DNS resolution':<28} {'RPi4 (Docker)':<24} make deploy-dns",
        f"  {'Pi-hole':<18} {'DNS filtering + cache':<28} {'RPi4 (Docker)':<24} make deploy-dns",
        f"  {'Cloudflare':<18} {'Prod DNS + CDN':<28} {'External':<24} Terraform",
        "",
        "SECURITY",
        f"  {'Authelia':<18} {'SSO / OIDC / 2FA':<28} {'ace1, VPS (K3s)':<24} Kustomize",
        f"  {'CrowdSec':<18} {'WAF / IP reputation':<28} {'ace1, VPS (K3s)':<24} Kustomize + plugin",
        f"  {'SOPS':<18} {'Secret encryption':<28} {'Git repo':<24} toolkit secrets",
        "",
        "OBSERVABILITY",
        f"  {'Grafana':<18} {'Dashboards':<28} {'ace1, VPS (K3s)':<24} Kustomize",
        f"  {'Loki':<18} {'Log aggregation':<28} {'ace1, VPS (K3s)':<24} Kustomize",
        f"  {'Vector':<18} {'Log shipping':<28} {'ace1, VPS (K3s)':<24} Kustomize",
        f"  {'Glances':<18} {'Node metrics':<28} {'All nodes':<24} Ansible",
        f"  {'Uptime Kuma':<18} {'External monitoring':<28} {'RPi3 (Docker)':<24} Docker Compose",
        "",
        "GITOPS",
        f"  {'Argo CD':<18} {'Hub-and-spoke GitOps':<28} {hub_name + ' (K3s)':<24} Helm",
        f"  {'GitHub Actions':<18} {'CI/CD pipelines':<28} {'GitHub':<24} .github/workflows/",
        f"  {'release-please':<18} {'Automated releases':<28} {'GitHub':<24} .github/workflows/",
        "",
        "TOOLING",
        f"  {'toolkit (Python)':<18} {'CLI: secrets, sync, deploy':<28} {'Local':<24} Poetry",
        f"  {'Makefile':<18} {'Task runner':<28} {'Local':<24} make help",
        f"  {'Homepage':<18} {'Dashboard (this page)':<28} {'ace1, VPS (K3s)':<24} Kustomize",
        "",
        f"K3s {k3s_ver}",
    ]
    return "\n".join(rows)


MERMAID_SECRET_FLOW = """graph LR
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
  class POD1,POD2,POD3,POD4,POD5 pod"""

MERMAID_DEPLOY_PIPELINE = """graph LR
  DEV[Developer] -->|git push| GH[GitHub]
  GH -->|PR merge| GHA[GitHub Actions]
  GHA -->|build + test| IMG[Docker Image]
  IMG -->|push| DH[Docker Hub / GHCR]
  GHA -->|release-please| TAG[SemVer Tag]
  TAG -.-> DH
  DH -->|image ready| ARGO[Argo CD<br/>{hub_name} Hub]
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
  class HELM1,HELM2 helm"""


def render_mermaid_svg(mermaid_def: str, retries: int = 2, backoff_seconds: float = 1.0) -> str:
    """Render Mermaid to SVG via mermaid.ink. Returns SVG string or empty on failure.

    Retries transient failures (network blip, rate limit) — this call is now
    exercised by CI (TOOL-020), not just local runs, so a single flaky
    request must not fail the whole sync. Still degrades gracefully to an
    empty string after exhausting retries; the caller treats that the same
    as any other fetch failure.
    """
    encoded = base64.urlsafe_b64encode(mermaid_def.encode()).decode()
    url = f"https://mermaid.ink/svg/{encoded}"
    req = Request(url, headers={"User-Agent": "kubelab-sync/1.0"})

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urlopen(req, timeout=20) as resp:
                return resp.read().decode()
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(backoff_seconds * (attempt + 1))

    print(f"  WARNING: mermaid.ink render failed after {retries + 1} attempts: {last_error}", file=sys.stderr)
    return ""


def generate_diagrams(config: dict[str, Any]) -> None:  # noqa: C901
    """Generate architecture diagrams + endpoint tables: Dynamic Mermaid + ASCII art + JSON."""
    diagrams = {
        "topology": build_mermaid_topology(config),
        # `.format()` rather than an f-string: these are module constants, so the
        # hub's name has to be substituted where they are USED. Left as a plain
        # string they would render the literal "{hub_name}" into a diagram that
        # nobody re-reads once it looks like a picture.
        "gitops": MERMAID_GITOPS.format(hub_name=hub_node(config)[0]),
        "dns": build_mermaid_dns(config),
        "request": MERMAID_REQUEST,
        "secret_flow": MERMAID_SECRET_FLOW,
        "deploy_pipeline": MERMAID_DEPLOY_PIPELINE.format(hub_name=hub_node(config)[0]),
    }

    # Write custom.js with embedded Mermaid definitions + ASCII
    ascii_sections = {
        "ip_reference": build_ip_reference(config),
        "dns_map": build_dns_map(config),
        "tech_stack": build_tech_stack(config),
    }

    staging_services, prod_services, shared_services = build_service_tables(config)
    print(f"  Services: staging={len(staging_services)}, prod={len(prod_services)}, shared={len(shared_services)}")

    js_parts = [
        "// Architecture diagrams + endpoints — Generated from common.yaml SSOT",
        "// Run `make sync-homepage` to regenerate. Do NOT edit custom.js directly.",
        "",
        "var KUBELAB_DIAGRAMS = {",
    ]
    for name, mermaid_def in diagrams.items():
        escaped = mermaid_def.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
        js_parts.append(f"  {name}: `{escaped}`,")
    # Escape ASCII for JS
    for name, ascii_text in ascii_sections.items():
        escaped = ascii_text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
        js_parts.append(f"  {name}: `{escaped}`,")
    js_parts.append("};")
    js_parts.append("")
    # Service JSON data
    js_parts.append(f"var KUBELAB_SERVICES_STAGING = {json.dumps(staging_services, indent=2)};")
    js_parts.append(f"var KUBELAB_SERVICES_PROD = {json.dumps(prod_services, indent=2)};")
    js_parts.append(f"var KUBELAB_SERVICES_SHARED = {json.dumps(shared_services, indent=2)};")
    js_parts.append("")
    js_parts.append("""
(function() {
  var injected = {};
  var mermaidPromise = null;

  function getMermaid() {
    if (!mermaidPromise) {
      mermaidPromise = import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs")
        .then(function(m) {
          m.default.initialize({
            startOnLoad: false,
            theme: "neutral",
            securityLevel: "loose"
          });
          return m.default;
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
        btnUrl.textContent = "\u2398";
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
          btnHealth.textContent = "\u2398";
          tdHealth.appendChild(btnHealth);
        } else {
          tdHealth.textContent = "\u2014";
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
        tdVer.textContent = svc.version || "\u2014";
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
    var dots = container.querySelectorAll(".ep-status[data-health-url]");
    dots.forEach(function(dot) {
      var url = dot.getAttribute("data-health-url");
      if (!url || url === "-" || url.indexOf("http") !== 0) {
        dot.className = "ep-status ep-status-internal";
        dot.title = "Cluster-internal component";
        return;
      }
      fetch(url, {signal: AbortSignal.timeout(8000)})
        .then(function(res) {
          if (res.ok || res.type === "opaque") {
            dot.className = "ep-status ep-status-up";
            dot.title = "Online (HTTP " + (res.status || "OK") + ")";
          } else {
            dot.className = "ep-status ep-status-down";
            dot.title = "Degraded (HTTP " + res.status + ")";
          }
        })
        .catch(function() {
          fetch(url, {mode: "no-cors", signal: AbortSignal.timeout(4000)})
            .then(function() {
              dot.className = "ep-status ep-status-unknown";
              dot.title = "Reachable (CORS protected)";
            })
            .catch(function() {
              dot.className = "ep-status ep-status-down";
              dot.title = "Unreachable";
            });
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
          btn.textContent = "\u2713";
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
    footer.textContent = "KUBELAB_FOOTER_PLACEHOLDER";
    main.appendChild(footer);
  }
  setTimeout(addFooter, 2000);
  window.addEventListener("hashchange", function() { setTimeout(addFooter, 500); });
})();
""")

    js_content = "\n".join(js_parts)

    # Footer build metadata \u2014 a pure function of the generated content.
    #
    # This previously embedded `date.today()` and `git rev-parse --short HEAD`.
    # Both are ambient state, and because custom.js is a GENERATED FILE THAT IS
    # COMMITTED, that made it change on every commit and every new calendar day
    # even when nothing about the dashboard had changed. Each such change is a
    # new configMapGenerator hash, so a new ConfigMap name, so a fresh apply of
    # a ~260 KB object \u2014 which is how #938 stayed lit and how a Deployment ended
    # up referencing `homepage-config-t4chht7t47`, a name present in no commit.
    #
    # The two ambient values were also misleading on their own terms: the date
    # recorded when someone last ran this script, not when anything deployed, so
    # a months-stale generation displayed as if it were current.
    #
    # A digest of the content answers the question the footer is actually for \u2014
    # "which configuration is live?" \u2014 and by construction only changes when the
    # configuration does. Computed over the pre-substitution text, so it is
    # well-defined and independent of itself.
    config_digest = hashlib.sha256(js_content.encode("utf-8")).hexdigest()[:8]
    footer_text = f"KubeLab IDP \u00b7 config {config_digest}"
    js_content = js_content.replace("KUBELAB_FOOTER_PLACEHOLDER", footer_text)

    write_text_lf(OUTPUT_DIR / "custom.js", js_content)
    print(f"  Generated custom.js ({len(js_content)} bytes)")


def main() -> int:
    with open(COMMON_YAML, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    apps = config.get("apps", {})
    services = apps.get("services", {})
    platform = apps.get("platform", {})
    networking = config.get("networking", {})
    nodes = networking.get("nodes", {})
    vps = networking.get("vps", {})
    argocd = config.get("argocd", {})

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    context = {
        "global": config.get("global", {}),
        "services": services,
        "platform": platform,
        "nodes": nodes,
        "vps": vps,
        "aws": networking.get("aws", {}),
        "argocd": argocd,
        "k3s": config.get("k3s", {}),
        "node_list": build_node_list(config),
        "traefik_cluster_ip": get_traefik_cluster_ip(),
        "cloudflare_zone_id": CLOUDFLARE_ZONE_ID,
        "today": date.today().isoformat(),
    }

    synced = 0
    for template_path in sorted(TEMPLATES_DIR.glob("*.j2")):
        # Skip custom.js.j2 — now generated by generate_diagrams()
        if template_path.name == "custom.js.j2":
            continue
        template = env.get_template(template_path.name)
        output_name = template_path.stem  # e.g. services.yaml.j2 → services.yaml
        output_path = OUTPUT_DIR / output_name

        rendered = template.render(**context)
        write_text_lf(output_path, rendered)
        synced += 1
        print(f"  {template_path.name} → {output_name}")

    # Generate architecture diagrams (Kroki SVG + ASCII)
    generate_diagrams(config)
    synced += 1

    print(f"Synced {synced} homepage config(s) from common.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
