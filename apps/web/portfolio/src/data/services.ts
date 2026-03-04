export interface Service {
  headline: string;
  problem: string;
  solution: string;
}

export const services: Service[] = [
  {
    headline: 'Platform Engineering',
    problem: 'Your developers waste hours fighting infrastructure instead of shipping features.',
    solution:
      'I design Internal Developer Platforms on Kubernetes — CI/CD, observability, SSO, and developer tooling — so your team can deploy with confidence.',
  },
  {
    headline: 'Cloud Architecture',
    problem: 'Your infrastructure grew organically and now nobody understands it.',
    solution:
      'I audit, simplify, and document your cloud setup. Whether it\'s AWS, Hetzner, or hybrid — I turn chaos into Infrastructure as Code.',
  },
  {
    headline: 'Technical Mentoring',
    problem: 'Your team knows how to use the tools but not why they work.',
    solution:
      'Hands-on workshops on containers, Kubernetes, and SRE practices. I help engineers understand the stack from the metal up.',
  },
];
