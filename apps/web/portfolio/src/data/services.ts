export interface Service {
  headline: string;
  problem: string;
  solution: string;
}

export const services: Service[] = [
  {
    headline: 'Your team is fighting infrastructure, not shipping product',
    problem:
      'Deploys take 45 minutes. Rollbacks are manual. Your CI pipeline breaks every other week.',
    solution:
      'I build Internal Developer Platforms on Kubernetes. Your devs deploy with one command, rollback in seconds, and stop paging each other at 2 AM.',
  },
  {
    headline: 'Your infra grew organically and now it\'s a liability',
    problem:
      'Three people understood your infrastructure. Two of them left.',
    solution:
      'I audit everything, document it, and turn it into Infrastructure as Code. When I\'m done, your team can maintain it without me.',
  },
  {
    headline: 'You need to keep your data under your control',
    problem:
      'Compliance, regulation, or just common sense — not everything belongs in a public cloud.',
    solution:
      'I design and operate on-prem and hybrid infrastructure. Bare metal, private clusters, VPN meshes — with the same automation and reliability as any cloud provider. Your data stays where you decide.',
  },
  {
    headline: 'You built it with AI and now you\'re stuck',
    problem:
      'You\'ve been shipping features with Cursor and ChatGPT for months. It works on localhost. Now you need auth, CI/CD, monitoring, HTTPS, and a real deployment pipeline.',
    solution:
      'AI can write your app — it can\'t operate it. I take what you\'ve built, make it production-ready, and set up the infrastructure so you can keep shipping.',
  },
  {
    headline: 'Your engineers know the tools but not the fundamentals',
    problem:
      'They can follow tutorials. They can\'t debug production under pressure.',
    solution:
      'Hands-on workshops on containers, Kubernetes, and SRE. No slides. Real clusters. Real failures. Your team learns by breaking things safely.',
  },
];
