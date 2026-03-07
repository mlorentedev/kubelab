import type { Lang } from '../i18n/ui';

export interface Service {
  headline: string;
  problem: string;
  solution: string;
}

const data: Record<Lang, Service[]> = {
  en: [
    {
      headline: 'Your team is fighting infrastructure, not shipping product',
      problem:
        'Deploys take 45 minutes. Rollbacks are manual. Your CI pipeline breaks every other week.',
      solution:
        'I build Internal Developer Platforms on Kubernetes. Your devs deploy with one command, rollback in seconds, and stop paging each other at 2 AM.',
    },
    {
      headline: "Your infra grew organically and now it's a liability",
      problem:
        'Three people understood your infrastructure. Two of them left.',
      solution:
        "I audit everything, document it, and turn it into Infrastructure as Code. When I'm done, your team can maintain it without me.",
    },
    {
      headline: 'You need to keep your data under your control',
      problem:
        "Compliance, regulation, or just common sense — not everything belongs in a public cloud.",
      solution:
        'I design and operate on-prem and hybrid infrastructure. Bare metal, private clusters, VPN meshes — with the same automation and reliability as any cloud provider. Your data stays where you decide.',
    },
    {
      headline: "You built it with AI and now you're stuck",
      problem:
        "You've been shipping features with Cursor and ChatGPT for months. It works on localhost. Now you need auth, CI/CD, monitoring, HTTPS, and a real deployment pipeline.",
      solution:
        "AI can write your app — it can't operate it. I take what you've built, make it production-ready, and set up the infrastructure so you can keep shipping.",
    },
    {
      headline: 'Your engineers know the tools but not the fundamentals',
      problem:
        "They can follow tutorials. They can't debug production under pressure.",
      solution:
        'Hands-on workshops on containers, Kubernetes, and SRE. No slides. Real clusters. Real failures. Your team learns by breaking things safely.',
    },
  ],
  es: [
    {
      headline: 'Tu equipo pelea con la infraestructura en vez de lanzar producto',
      problem:
        'Los despliegues tardan 45 minutos. Los rollbacks son manuales. Tu pipeline de CI se rompe cada dos semanas.',
      solution:
        'Construyo Internal Developer Platforms sobre Kubernetes. Tus devs despliegan con un comando, hacen rollback en segundos y dejan de despertarse a las 2 AM.',
    },
    {
      headline: 'Tu infra creció sin control y ahora es un lastre',
      problem:
        'Tres personas entendían tu infraestructura. Dos se fueron.',
      solution:
        'Audito todo, lo documento y lo convierto en Infrastructure as Code. Cuando termino, tu equipo puede mantenerlo sin mí.',
    },
    {
      headline: 'Necesitas mantener tus datos bajo tu control',
      problem:
        'Compliance, regulación o sentido común — no todo pertenece a una nube pública.',
      solution:
        'Diseño y opero infraestructura on-prem e híbrida. Bare metal, clusters privados, mallas VPN — con la misma automatización y fiabilidad que cualquier proveedor cloud. Tus datos se quedan donde tú decides.',
    },
    {
      headline: 'Lo construiste con IA y ahora estás atascado',
      problem:
        'Llevas meses lanzando funcionalidades con Cursor y ChatGPT. Funciona en localhost. Ahora necesitas auth, CI/CD, monitoring, HTTPS y un pipeline de despliegue real.',
      solution:
        'La IA puede escribir tu app — no puede operarla. Tomo lo que has construido, lo preparo para producción y monto la infraestructura para que sigas lanzando.',
    },
    {
      headline: 'Tus ingenieros conocen las herramientas pero no los fundamentos',
      problem:
        'Pueden seguir tutoriales. No pueden depurar producción bajo presión.',
      solution:
        'Workshops prácticos de contenedores, Kubernetes y SRE. Sin slides. Clusters reales. Fallos reales. Tu equipo aprende rompiendo cosas de forma segura.',
    },
  ],
};

export function getServices(lang: Lang): Service[] {
  return data[lang] ?? data.en;
}
