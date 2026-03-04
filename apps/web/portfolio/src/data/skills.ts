export interface SkillGroup {
  category: string;
  skills: string[];
}

export const skillGroups: SkillGroup[] = [
  {
    category: 'Languages',
    skills: ['Go', 'Python', 'TypeScript', 'Matlab'],
  },
  {
    category: 'Infrastructure',
    skills: ['Kubernetes', 'Docker', 'Terraform', 'Ansible'],
  },
  {
    category: 'Cloud',
    skills: ['AWS', 'Hetzner', 'Cloudflare'],
  },
  {
    category: 'Observability',
    skills: ['Grafana', 'Loki', 'Prometheus', 'Uptime Kuma'],
  },
  {
    category: 'Networking',
    skills: ['Tailscale', 'Headscale', 'CoreDNS', 'Traefik'],
  },
];
