"""Generate Homepage config from common.yaml SSOT + Jinja2 templates.

Reads networking, service definitions, and node topology from common.yaml,
then renders homepage-templates/*.j2 → homepage-config/*.yaml.

Run: `make sync-homepage` or `python toolkit/scripts/sync_homepage_config.py`
"""

from __future__ import annotations

import base64
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import yaml
from jinja2 import Environment, FileSystemLoader

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMON_YAML = PROJECT_ROOT / "infra/config/values/common.yaml"
TEMPLATES_DIR = PROJECT_ROOT / "infra/k8s/base/services/homepage-templates"
OUTPUT_DIR = PROJECT_ROOT / "infra/k8s/base/services/homepage-config"

# Cloudflare zone ID for kubelab.live — used in analytics widget
CLOUDFLARE_ZONE_ID = "a708cb04dd4572e76eb6da42cc09507d"


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
                str(Path.home() / ".kube/kubelab-staging-config"),
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
    """Build ordered node list with metadata for template rendering."""
    nodes = config.get("networking", {}).get("nodes", {})
    vps = config.get("networking", {}).get("vps", {})
    aws = config.get("networking", {}).get("aws", {})
    node_defs = [
        (
            "ace1",
            {
                "ip": nodes.get("ace1", {}).get("tailscale_ip"),
                "icon": "mdi-server",
                "description": "Staging · 12GB",
                "glances": True,
            },
        ),
        (
            "VPS",
            {
                "ip": vps.get("tailscale_ip"),
                "icon": "mdi-cloud",
                "description": "Prod · 8GB",
                "glances": True,
            },
        ),
        (
            "RPi4",
            {
                "ip": nodes.get("rpi4", {}).get("tailscale_ip"),
                "icon": "mdi-raspberry-pi",
                "description": "DNS · 8GB",
                "glances": True,
            },
        ),
        (
            "RPi3",
            {
                "ip": nodes.get("rpi3", {}).get("tailscale_ip"),
                "icon": "mdi-raspberry-pi",
                "description": "Monitor · 1GB",
                "glances": True,
            },
        ),
        (
            "ace2",
            {
                "ip": nodes.get("ace2", {}).get("tailscale_ip"),
                "icon": "mdi-server",
                "description": "Agent · 12GB",
                "glances": True,
            },
        ),
        (
            "aws1",
            {
                "ip": aws.get("tailscale_ip"),
                "icon": "mdi-cloud-outline",
                "description": "Hub · t4g.micro · 1vCPU · 1GB",
                "glances": False,
                "ping_url": f"http://{aws.get('tailscale_ip')}:6443",
            },
        ),
        (
            "Beelink",
            {
                "ip": nodes.get("beelink", {}).get("tailscale_ip"),
                "icon": "mdi-desktop-tower",
                "description": "Ollama · N95 · 8GB (no Glances)",
                "glances": False,
                "ping_url": f"http://{nodes.get('beelink', {}).get('tailscale_ip')}:11434",
            },
        ),
        (
            "Jetson",
            {
                "ip": nodes.get("jetson", {}).get("tailscale_ip"),
                "icon": "mdi-chip",
                "description": "Pollex · ARM · 4GB (no Glances)",
                "glances": False,
                "ping_url": f"http://{nodes.get('jetson', {}).get('tailscale_ip')}:8000",
            },
        ),
    ]
    return node_defs


def build_mermaid_topology(config: dict[str, Any]) -> str:
    """Generate Mermaid topology diagram from common.yaml."""
    n = config.get("networking", {}).get("nodes", {})
    vps = config.get("networking", {}).get("vps", {})
    aws = config.get("networking", {}).get("aws", {})
    return f"""graph TB
  subgraph Internet
    CF[Cloudflare DNS+CDN]
    Users[Users]
  end
  subgraph Cloud
    VPS["VPS {vps.get("public_ip")} / {vps.get("tailscale_ip")}<br/>K3s Prod 8GB"]
    AWS1["aws1 {aws.get("tailscale_ip")}<br/>Argo CD Hub 1GB"]
  end
  subgraph HomeLab["Home Lab 172.16.1.0/24"]
    ACE1["ace1 {n["ace1"]["lan_ip"]} / {n["ace1"]["tailscale_ip"]}<br/>K3s Staging 12GB"]
    ACE2["ace2 {n["ace2"]["lan_ip"]} / {n["ace2"]["tailscale_ip"]}<br/>K3s Agent 12GB"]
    RPI4["RPi4 {n["rpi4"]["lan_ip"]} / {n["rpi4"]["tailscale_ip"]}<br/>DNS Gateway 8GB"]
    BEE["Beelink {n["beelink"]["lan_ip"]} / {n["beelink"]["tailscale_ip"]}<br/>Ollama 8GB"]
    JET["Jetson {n["jetson"]["lan_ip"]} / {n["jetson"]["tailscale_ip"]}<br/>Pollex 4GB"]
  end
  subgraph Standalone
    RPI3["RPi3 {n["rpi3"]["tailscale_ip"]}<br/>Uptime Kuma 1GB"]
  end
  Users --> CF --> VPS
  AWS1 -. Tailscale .-> VPS
  AWS1 -. Tailscale .-> ACE1
  VPS -. Tailscale .-> ACE1
  VPS -. Tailscale .-> RPI3
  ACE1 --- ACE2
  ACE1 --- RPI4
  ACE1 --- BEE
  ACE1 --- JET
  RPI4 -. Tailscale .-> VPS
  classDef cloud fill:#dbeafe,stroke:#3b82f6,stroke-width:2px
  classDef lan fill:#dcfce7,stroke:#22c55e,stroke-width:2px
  classDef standalone fill:#fef3c7,stroke:#f59e0b,stroke-width:2px
  classDef ext fill:#f3f4f6,stroke:#9ca3af
  class VPS,AWS1 cloud
  class ACE1,ACE2,RPI4,BEE,JET lan
  class RPI3 standalone
  class CF,Users ext"""


MERMAID_GITOPS = """graph LR
  DEV[Developer] -->|push| GH[GitHub]
  GH -->|webhook| ARGO[Argo CD<br/>aws1 Hub]
  ARGO -->|sync| STG[K3s Staging<br/>ace1]
  ARGO -->|sync| PRD[K3s Prod<br/>VPS]
  GH -->|CI| GHA[GitHub Actions]
  GHA -->|push| DH[Docker Hub]
  DH -.-> STG
  DH -.-> PRD
  classDef hub fill:#fce7f3,stroke:#ec4899,stroke-width:2px
  classDef spoke fill:#dbeafe,stroke:#3b82f6,stroke-width:2px
  classDef ci fill:#f3f4f6,stroke:#9ca3af
  class ARGO hub
  class STG,PRD spoke
  class GH,GHA,DH ci"""


def build_mermaid_dns(config: dict[str, Any]) -> str:
    """Generate Mermaid DNS diagram from common.yaml."""
    vps = config.get("networking", {}).get("vps", {})
    n = config.get("networking", {}).get("nodes", {})
    return f"""graph TB
  C[Client] -->|*.kubelab.live| CFDNS[Cloudflare]
  CFDNS --> VPS["VPS Traefik {vps.get("public_ip")}"]
  C -->|VPN| HS[Headscale]
  HS -->|split DNS| PH["Pi-hole RPi4"]
  PH -->|staging| CD["CoreDNS RPi4"]
  CD --> ACE1["ace1 Traefik {n["ace1"]["tailscale_ip"]}"]
  PH -->|other| UP[1.1.1.1 / 8.8.8.8]
  classDef dns fill:#ede9fe,stroke:#8b5cf6,stroke-width:2px
  classDef proxy fill:#dbeafe,stroke:#3b82f6,stroke-width:2px
  classDef ext fill:#f3f4f6,stroke:#9ca3af
  class PH,CD,CFDNS dns
  class VPS,ACE1 proxy
  class C,HS,UP ext"""


MERMAID_REQUEST = """graph LR
  U[User] --> T[Traefik]
  T --> CS[CrowdSec]
  CS --> A{Authelia}
  A -->|ok| APP[App]
  A -->|no| LOGIN[Login]
  A -.-> R[(Redis)]
  APP -.-> V[Vector]
  V --> L[(Loki)]
  L --> G[Grafana]
  classDef sec fill:#fef3c7,stroke:#f59e0b,stroke-width:2px
  classDef app fill:#dcfce7,stroke:#22c55e,stroke-width:2px
  classDef obs fill:#ede9fe,stroke:#8b5cf6,stroke-width:2px
  classDef proxy fill:#dbeafe,stroke:#3b82f6,stroke-width:2px
  class CS,A,LOGIN,R sec
  class APP app
  class V,L,G obs
  class T,U proxy"""


def build_ascii_topology(config: dict[str, Any]) -> str:  # noqa: E501
    """Generate ASCII topology diagram from common.yaml."""
    n = config.get("networking", {}).get("nodes", {})
    vps = config.get("networking", {}).get("vps", {})
    aws = config.get("networking", {}).get("aws", {})

    vps_pub = vps.get("public_ip", "?")
    vps_ts = vps.get("tailscale_ip", "?")
    aws_ts = aws.get("tailscale_ip", "?")

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
        "CLOUD (Tailscale mesh)",
        f"  VPS        {vps_pub} / {vps_ts}  K3s Prod 8GB",
        f"  aws1       {aws_ts}              Argo CD Hub 1GB",
        "",
        "HOME LAB (172.16.1.0/24)",
        f"  ace1       {a1l} / {a1t}   K3s Staging 12GB",
        f"  ace2       {a2l} / {a2t}     K3s Agent 12GB",
        f"  RPi4       {r4l} / {r4t}    DNS Gateway 8GB",
        f"  Beelink    {bel} / {bet}     Ollama 8GB",
        f"  Jetson     {jel} / {jet}     Pollex 4GB",
        "",
        "STANDALONE",
        f"  RPi3       {r3t}              Uptime Kuma 1GB",
        "",
        "CONNECTIONS",
        "  VPS <--> ace1      Tailscale",
        "  VPS <--> aws1      Tailscale",
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
    n = config.get("networking", {}).get("nodes", {})
    vps = config.get("networking", {}).get("vps", {})
    aws = config.get("networking", {}).get("aws", {})

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
        _row("aws1", "—", aws.get("tailscale_ip", "?"), "Argo CD Hub · 1GB"),
        _row("ace1", a1l, a1t, "K3s Staging · 12GB"),
        _row("ace2", a2l, a2t, "K3s Agent · 12GB"),
        _row("RPi4", r4l, r4t, "DNS Gateway · 8GB"),
        _row("RPi3", "—", r3t, "Uptime Kuma · 1GB"),
        _row("Beelink", bel, bet, "Ollama · 8GB"),
        _row("Jetson", jel, jet, "Pollex · 4GB"),
    ]
    return "\n".join(rows)


def build_dns_map(config: dict[str, Any]) -> str:
    """Generate DNS zone map from common.yaml."""
    vps = config.get("networking", {}).get("vps", {})
    n = config.get("networking", {}).get("nodes", {})
    vps_pub = vps.get("public_ip", "?")
    ace1_ts = n.get("ace1", {}).get("tailscale_ip", "?")
    rpi4_lan = n.get("rpi4", {}).get("lan_ip", "?")

    rows = [
        f"{'DOMAIN':<36} {'RESOLVES TO'}",
        f"{'─' * 36} {'─' * 40}",
        "",
        "PROD (public DNS via Cloudflare)",
        f"  {'*.kubelab.live':<34} VPS Traefik ({vps_pub})",
        f"  {'mlorente.dev':<34} VPS Traefik ({vps_pub})",
        f"  {'vpn.kubelab.live':<34} {vps_pub} (public, never Tailscale)",
        "",
        "STAGING (VPN-only via split DNS)",
        f"  {'*.staging.kubelab.live':<34} Headscale → Pi-hole → CoreDNS → ace1 ({ace1_ts})",
        f"  {'pihole.staging.kubelab.live':<34} LAN EndpointSlice → RPi4 ({rpi4_lan})",
        "",
        "VPN-ONLY (Headscale extra_records)",
        f"  {'pihole.kubelab.live':<34} RPi4 ({rpi4_lan})",
        f"  {'ollama.kubelab.live':<34} Beelink ({n.get('beelink', {}).get('lan_ip', '?')})",
    ]
    return "\n".join(rows)


def render_mermaid_svg(mermaid_def: str) -> str:
    """Render Mermaid to SVG via mermaid.ink. Returns SVG string or empty on failure."""
    try:
        encoded = base64.urlsafe_b64encode(mermaid_def.encode()).decode()
        url = f"https://mermaid.ink/svg/{encoded}"
        req = Request(url, headers={"User-Agent": "kubelab-sync/1.0"})
        with urlopen(req, timeout=20) as resp:
            return resp.read().decode()
    except Exception as e:
        print(f"  WARNING: mermaid.ink render failed: {e}", file=sys.stderr)
        return ""


def generate_diagrams(config: dict[str, Any]) -> None:
    """Generate architecture diagrams: Kroki SVG + ASCII art."""
    diagrams = {
        "topology": build_mermaid_topology(config),
        "gitops": MERMAID_GITOPS,
        "dns": build_mermaid_dns(config),
        "request": MERMAID_REQUEST,
    }

    # Generate Kroki SVGs
    svgs = {}
    for name, mermaid_def in diagrams.items():
        svg = render_mermaid_svg(mermaid_def)
        if svg:
            svgs[name] = svg
            print(f"  Kroki SVG: {name} ({len(svg)} bytes)")
        else:
            print(f"  Kroki SVG: {name} FAILED")

    # Write custom.js with embedded SVGs + ASCII
    ascii_sections = {
        "ip_reference": build_ip_reference(config),
        "dns_map": build_dns_map(config),
    }

    js_parts = [
        "// Architecture diagrams — Generated from common.yaml SSOT",
        "// Run `make sync-homepage` to regenerate. Do NOT edit custom.js directly.",
        "",
        "var KUBELAB_DIAGRAMS = {",
    ]
    for name, svg in svgs.items():
        b64 = base64.b64encode(svg.encode()).decode()
        js_parts.append(f'  {name}: "data:image/svg+xml;base64,{b64}",')
    # Escape ASCII for JS
    for name, ascii_text in ascii_sections.items():
        escaped = ascii_text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
        js_parts.append(f"  {name}: `{escaped}`,")
    js_parts.append("};")
    js_parts.append("")
    js_parts.append("""
(function() {
  var injected = {};

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
        var img = document.createElement("img");
        img.src = data;
        img.style.cssText = "max-width:100%;height:auto";
        img.alt = dataKey + " diagram";
        container.appendChild(img);
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

  function tryInject() {
    var hash = (window.location.hash || "").toLowerCase();
    if (hash === "#diagrams") {
      injectDiagram("IP Reference", "ip_reference", true);
      injectDiagram("Topology", "topology", false);
      injectDiagram("DNS Map", "dns_map", true);
      injectDiagram("DNS Resolution", "dns", false);
      injectDiagram("GitOps", "gitops", false);
      injectDiagram("Request Path", "request", false);
    }
  }

  // Click-to-zoom on diagram images
  document.addEventListener("click", function(e) {
    var img = e.target.closest("img[alt*='diagram']");
    if (img && !e.target.closest(".diagram-overlay")) {
      var overlay = document.createElement("div");
      overlay.className = "diagram-overlay";
      var clone = img.cloneNode(true);
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

    # Embed build metadata in footer
    git_short = "unknown"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            git_short = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    footer_text = f"KubeLab IDP \u00b7 config synced {date.today().isoformat()} \u00b7 {git_short}"
    js_content = js_content.replace("KUBELAB_FOOTER_PLACEHOLDER", footer_text)

    (OUTPUT_DIR / "custom.js").write_text(js_content)
    print(f"  Generated custom.js ({len(js_content)} bytes)")


def main() -> int:
    with open(COMMON_YAML) as f:
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
        output_path.write_text(rendered)
        synced += 1
        print(f"  {template_path.name} → {output_name}")

    # Generate architecture diagrams (Kroki SVG + ASCII)
    generate_diagrams(config)
    synced += 1

    print(f"Synced {synced} homepage config(s) from common.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
