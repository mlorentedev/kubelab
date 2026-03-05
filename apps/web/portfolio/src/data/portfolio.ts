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
      'I wanted to understand how platforms actually work — not just click buttons on managed K8s. So I built one from scratch. 5 physical nodes, K3s, VPN mesh, SSO, full observability. Everything IaC, nothing manual.',
    url: 'https://mlorentedev.github.io/kubelab/',
    github: 'https://github.com/mlorentedev/kubelab',
    tags: ['Kubernetes', 'Go', 'Python', 'Terraform', 'Ansible'],
    featured: true,
  },
  {
    title: 'Hive',
    description:
      'AI assistants waste tokens loading context they don\'t need. Hive queries your Obsidian vault on demand via MCP — only what\'s relevant, when it\'s relevant. 67-82% token reduction.',
    url: 'https://mlorentedev.github.io/hive/',
    github: 'https://github.com/mlorentedev/hive',
    tags: ['Python', 'MCP', 'Obsidian', 'AI'],
    featured: true,
  },
  {
    title: 'Pollex',
    description:
      'Cloud LLM APIs see everything you type. Pollex polishes your English on a $99 Jetson Nano — grammar, coherence, wording. 3-second inference, zero cloud dependencies.',
    url: 'https://mlorentedev.github.io/pollex/',
    github: 'https://github.com/mlorentedev/pollex',
    tags: ['Go', 'MCP', 'LLM', 'Jetson Nano'],
    featured: true,
  },
  {
    title: 'ts-bridge',
    description:
      'Corporate firewalls block VPN clients that need admin rights. ts-bridge tunnels RDP/SSH through Tailscale in userspace — no install, no admin, no traces. One binary.',
    url: 'https://mlorentedev.github.io/ts-bridge/',
    github: 'https://github.com/mlorentedev/ts-bridge',
    tags: ['Go', 'Tailscale', 'Networking'],
    featured: true,
  },
  {
    title: 'pdf-modifier-mcp',
    description:
      'Find-and-replace in PDFs without destroying the formatting. CLI for batch jobs, MCP server for AI agents.',
    url: 'https://mlorentedev.github.io/pdf-modifier-mcp/',
    github: 'https://github.com/mlorentedev/pdf-modifier-mcp',
    tags: ['Python', 'MCP', 'PDF'],
    featured: false,
  },
  {
    title: 'youtube-toolkit',
    description:
      'YouTube Studio analytics are shallow and locked to your own channel. This CLI pulls metrics for any public channel and exports everything.',
    url: 'https://mlorentedev.github.io/youtube-toolkit/',
    github: 'https://github.com/mlorentedev/youtube-toolkit',
    tags: ['Python', 'CLI', 'YouTube'],
    featured: false,
  },
  {
    title: 'kasa-provisioner',
    description:
      'Configuring 20 smart plugs one by one through a phone app is painful. This scans the network, updates firmware, and sets schedules in bulk.',
    github: 'https://github.com/mlorentedev/kasa-provisioner',
    tags: ['Python', 'IoT', 'Networking'],
    featured: false,
  },
  {
    title: 'dotfiles',
    description:
      'Dev environment that rebuilds itself. Zsh, Neovim, tmux, Git — one script on a fresh machine.',
    github: 'https://github.com/mlorentedev/dotfiles',
    tags: ['Shell', 'Neovim', 'DevEx'],
    featured: false,
  },
];
