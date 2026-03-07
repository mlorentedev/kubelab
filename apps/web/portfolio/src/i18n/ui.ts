export const languages = {
  en: 'English',
  es: 'Español',
} as const;

export const defaultLang = 'en';

export type Lang = keyof typeof languages;

export const ui = {
  en: {
    // Nav
    'nav.notes': 'Notes',
    'nav.contact': 'Work with me',
    'nav.toggle': 'Toggle menu',

    // Hero
    'hero.tagline': 'Seville \u2192 Grenoble \u2192 Shenzhen \u2192 Denver \u00b7 10+ years \u00b7 From cleanrooms to Kubernetes',
    'hero.title': 'I kept watching the same infrastructure fail in every country I worked in.',
    'hero.subtitle1': 'Three people understood the system. Two left. Deploys were manual. Documentation was tribal knowledge. Every time I moved to a new team \u2014 Spain, France, China, the US \u2014 the problems were identical.',
    'hero.subtitle2': "So I stopped just fixing things and started building platforms that work after I leave. Cloud, on-prem, or hybrid \u2014 your data stays where you decide.",
    'hero.cta': "Tell me what's broken",

    // Services
    'services.heading': 'I solve five problems',

    // ContactCTA
    'cta.heading': 'What working with me looks like',
    'cta.step1.title': 'Infrastructure audit',
    'cta.step1.desc': "I map what you have, what's broken, and what's missing. One week.",
    'cta.step2.title': 'Architecture proposal',
    'cta.step2.desc': 'IaC, diagrams, and a clear migration path. No vendor lock-in.',
    'cta.step3.title': 'Implementation + knowledge transfer',
    'cta.step3.desc': 'I build it with your team, not for them. They own it when I leave.',
    'cta.step4.title': 'Documentation',
    'cta.step4.desc': 'Runbooks, architecture diagrams, and decision records your team can actually use.',
    'cta.step5.title': '30 days of async support',
    'cta.step5.desc': 'after handoff. Because the first month is when questions come up.',
    'cta.guarantee.title': 'My guarantee',
    'cta.guarantee.text': "I work with a few clients at a time so every project gets my full attention. Before any engagement, I'll review your setup and tell you honestly if I can help. If I take the project, the first week is an infrastructure audit \u2014 if it doesn't surface at least 3 improvements that pay for themselves, you don't pay for the audit.",
    'cta.final.title': 'Ready for infrastructure that just works?',
    'cta.final.text': "I take on 2\u20133 clients at a time. Tell me what you're building and what's broken.",

    // Contact page
    'contact.title': 'Work with me',
    'contact.description': 'Work with me on your infrastructure challenges.',
    'contact.heading': "Skip the pitch. Tell me what's broken.",
    'contact.p1': "I work with 2\u20133 clients at a time. No account managers, no handoffs \u2014 you work with me directly.",
    'contact.p2': "Tell me what you're building, what's broken, and what you've tried. If I can help, I'll reply within 48 hours with a concrete proposal. If I can't, I'll tell you that too.",

    // Notes page
    'notes.title': 'Notes',
    'notes.description': 'Platform engineering notes — from hardware to Kubernetes.',
    'notes.intro1': 'Most platform engineers learned Kubernetes from tutorials. I learned engineering from the metal up — hardware, firmware, backend, then cloud.',
    'notes.intro2': "That's why my platforms don't break.",
    'notes.projects': 'What I ship',
    'notes.articles': 'What I think',
    'notes.empty': 'Coming soon.',
    'notes.all': 'All notes',

    // Note detail
    'note.prev': 'Previous',
    'note.next': 'Next',

    // Tags
    'tags.projects': 'Projects',
    'tags.notes': 'Notes',
    'tags.all': 'All notes',

    // Footer
    'footer.blog': 'Blog en español',

    // 404
    '404.title': 'Not Found',
    '404.text': "This page doesn't exist.",
    '404.cta': 'Go home',

    // Meta
    'meta.description': 'Engineer. I build infrastructure and products — from hardware to Kubernetes.',
    'meta.ghchart.alt': "Manu's GitHub contribution chart",
  },
  es: {
    // Nav
    'nav.notes': 'Notas',
    'nav.contact': 'Trabajar conmigo',
    'nav.toggle': 'Abrir menú',

    // Hero
    'hero.tagline': 'Sevilla \u2192 Grenoble \u2192 Shenzhen \u2192 Denver \u00b7 10+ a\u00f1os \u00b7 De la sala limpia a Kubernetes',
    'hero.title': 'Vi la misma infraestructura romperse en cada pa\u00eds donde trabaj\u00e9.',
    'hero.subtitle1': 'Tres personas entend\u00edan el sistema. Dos se fueron. Los despliegues eran manuales. La documentaci\u00f3n era conocimiento tribal. Cada vez que cambiaba de equipo \u2014 Espa\u00f1a, Francia, China, EE.UU. \u2014 los problemas eran id\u00e9nticos.',
    'hero.subtitle2': 'As\u00ed que dej\u00e9 de solo arreglar cosas y empec\u00e9 a construir plataformas que funcionan despu\u00e9s de que me voy. Cloud, on-prem o h\u00edbrido \u2014 tus datos se quedan donde t\u00fa decides.',
    'hero.cta': 'Cu\u00e9ntame qu\u00e9 est\u00e1 roto',

    // Services
    'services.heading': 'Resuelvo cinco problemas',

    // ContactCTA
    'cta.heading': 'Así es trabajar conmigo',
    'cta.step1.title': 'Auditoría de infraestructura',
    'cta.step1.desc': 'Mapeo lo que tienes, lo que falla y lo que falta. Una semana.',
    'cta.step2.title': 'Propuesta de arquitectura',
    'cta.step2.desc': 'IaC, diagramas y un plan de migración claro. Sin vendor lock-in.',
    'cta.step3.title': 'Implementación + transferencia de conocimiento',
    'cta.step3.desc': 'Lo construyo con tu equipo, no para ellos. Cuando me voy, es suyo.',
    'cta.step4.title': 'Documentación',
    'cta.step4.desc': 'Runbooks, diagramas de arquitectura y registros de decisiones que tu equipo puede usar de verdad.',
    'cta.step5.title': '30 días de soporte asíncrono',
    'cta.step5.desc': 'después de la entrega. Porque el primer mes es cuando surgen las preguntas.',
    'cta.guarantee.title': 'Mi garantía',
    'cta.guarantee.text': 'Trabajo con pocos clientes a la vez para dar a cada proyecto toda mi atenci\u00f3n. Antes de cualquier proyecto, reviso tu setup y te digo honestamente si puedo ayudar. Si acepto, la primera semana es una auditor\u00eda de infraestructura \u2014 si no encuentra al menos 3 mejoras que se paguen solas, la auditor\u00eda no te cuesta nada.',
    'cta.final.title': '\u00bfListo para una infraestructura que simplemente funcione?',
    'cta.final.text': 'Acepto 2\u20133 clientes a la vez. Cu\u00e9ntame qu\u00e9 est\u00e1s construyendo y qu\u00e9 falla.',

    // Contact page
    'contact.title': 'Trabajar conmigo',
    'contact.description': 'Trabaja conmigo en tus retos de infraestructura.',
    'contact.heading': 'Sin rodeos. Cu\u00e9ntame qu\u00e9 falla.',
    'contact.p1': 'Trabajo con 2\u20133 clientes a la vez. Sin intermediarios, sin traspasos \u2014 trabajas conmigo directamente.',
    'contact.p2': 'Cu\u00e9ntame qu\u00e9 est\u00e1s construyendo, qu\u00e9 falla y qu\u00e9 has intentado. Si puedo ayudar, respondo en 48 horas con una propuesta concreta. Si no puedo, tambi\u00e9n te lo digo.',

    // Notes page
    'notes.title': 'Notas',
    'notes.description': 'Notas de ingeniería de plataformas — del hardware a Kubernetes.',
    'notes.intro1': 'La mayoría de ingenieros de plataforma aprendieron Kubernetes con tutoriales. Yo aprendí ingeniería desde el metal — hardware, firmware, backend, y luego cloud.',
    'notes.intro2': 'Por eso mis plataformas no se caen.',
    'notes.projects': 'Lo que construyo',
    'notes.articles': 'Lo que pienso',
    'notes.empty': 'Próximamente.',
    'notes.all': 'Todas las notas',

    // Note detail
    'note.prev': 'Anterior',
    'note.next': 'Siguiente',

    // Tags
    'tags.projects': 'Proyectos',
    'tags.notes': 'Notas',
    'tags.all': 'Todas las notas',

    // Footer
    'footer.blog': 'Blog de la comunidad',

    // 404
    '404.title': 'No encontrado',
    '404.text': 'Esta página no existe.',
    '404.cta': 'Ir al inicio',

    // Meta
    'meta.description': 'Ingeniero. Construyo infraestructura y productos \u2014 del hardware a Kubernetes.',
    'meta.ghchart.alt': 'Contribuciones de Manu en GitHub',
  },
} as const;
