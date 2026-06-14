export const site = {
  title: 'Manu Lorente — Platform engineering for AI workloads',
  description: 'I build, automate, and operate the infrastructure AI agents run on — Kubernetes, on-prem, reproducible. I run a 40-service homelab and document what breaks.',
  author: 'Manu Lorente',
  domain: 'mlorente.dev',
  url: 'https://mlorente.dev',
  api: {
    baseUrl: import.meta.env.PUBLIC_API_URL || 'https://api.staging.kubelab.live',
  },
} as const;
