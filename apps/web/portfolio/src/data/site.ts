export const site = {
  title: 'Manu Lorente',
  description: 'Engineer. I build infrastructure and products — from hardware to Kubernetes.',
  author: 'Manu Lorente',
  domain: 'mlorente.dev',
  url: 'https://mlorente.dev',
  api: {
    baseUrl: import.meta.env.PUBLIC_API_URL || 'https://api.staging.kubelab.live',
  },
} as const;
