export interface Project {
  title: string;
  description: string;
  url?: string;
  github?: string;
  tags: string[];
  featured: boolean;
}

export const projects: Project[] = [
  {
    title: 'KubeLab',
    description:
      'Personal Internal Developer Platform. K3s cluster, Headscale VPN mesh, Traefik, Authelia SSO, observability stack. From bare metal to production.',
    github: 'https://github.com/mlorentedev/kubelab',
    tags: ['Kubernetes', 'Go', 'Python', 'Terraform', 'Ansible'],
    featured: true,
  },
  {
    title: 'Pollex',
    description:
      'MCP server for text polishing via local LLMs. Runs on Jetson Nano and Ollama. Zero cloud dependencies.',
    github: 'https://github.com/mlorentedev/pollex',
    tags: ['Go', 'MCP', 'LLM', 'Ollama'],
    featured: true,
  },
  {
    title: 'ts-bridge',
    description:
      'Tailscale bridge for Windows machines behind corporate firewalls. Ephemeral nodes, auto-reconnect, zero-config RDP access.',
    github: 'https://github.com/mlorentedev/ts-bridge',
    tags: ['Go', 'Tailscale', 'Networking'],
    featured: true,
  },
  {
    title: 'pdf-modifier-mcp',
    description:
      'MCP server for PDF manipulation. Merge, split, extract, watermark — all from your AI assistant.',
    github: 'https://github.com/mlorentedev/pdf-modifier-mcp',
    tags: ['Python', 'MCP', 'PDF'],
    featured: false,
  },
  {
    title: 'youtube-toolkit',
    description:
      'CLI for YouTube channel analytics. Transcript extraction, metadata analysis, content planning.',
    github: 'https://github.com/mlorentedev/youtube-toolkit',
    tags: ['Python', 'CLI', 'YouTube'],
    featured: false,
  },
  {
    title: 'kasa-provisioner',
    description:
      'Bulk provisioner for TP-Link Kasa smart plugs. Network scanning, firmware updates, schedule configuration.',
    github: 'https://github.com/mlorentedev/kasa-provisioner',
    tags: ['Python', 'IoT', 'Networking'],
    featured: false,
  },
  {
    title: 'dotfiles',
    description:
      'Personal development environment. Zsh, Neovim, tmux, Git — scripted and reproducible.',
    github: 'https://github.com/mlorentedev/dotfiles',
    tags: ['Shell', 'Neovim', 'DevEx'],
    featured: false,
  },
];
