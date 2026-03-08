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
    'nav.toggle': 'Toggle menu',

    // Hero
    'hero.title': 'I build systems from hardware to cloud.',
    'hero.subtitle': '10+ years engineering across four countries. From semiconductor cleanrooms to Kubernetes clusters. I build in public and document everything.',
    'hero.cta': 'Read my notes',

    // Home sections
    'home.projects': 'What I build',
    'home.latest': 'Latest notes',
    'home.allNotes': 'All notes',

    // Newsletter (keys exist for type safety — EN landing has no newsletter)
    'newsletter.placeholder': 'you@email.com',
    'newsletter.button': 'Subscribe',
    'newsletter.hint': 'A weekly note on infrastructure, homelab, and what I\'m building. No spam.',
    'newsletter.whatYouGet': 'What you get',
    'newsletter.forYouIf': 'This is for you if',
    'newsletter.benefit1': 'A weekly note on <strong>infrastructure</strong>, homelab, and what I\'m building.',
    'newsletter.benefit2': 'Early access to guides and resources as I publish them.',
    'newsletter.benefit3': 'Zero spam. Unsubscribe anytime.',
    'newsletter.audience1': 'You\'re curious about building your own <strong>homelab</strong>.',
    'newsletter.audience2': 'You want to stop copying tutorials and start <strong>building</strong>.',
    'newsletter.audience3': 'You\'re interested in <strong>DevOps/Platform</strong> with real examples.',

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
    'nav.toggle': 'Abrir menú',

    // Hero
    'hero.title': 'Construyo sistemas del hardware al cloud.',
    'hero.subtitle': '10+ años de ingeniería en cuatro países. De la sala limpia de semiconductores a clusters Kubernetes. Construyo en público y lo documento todo.',
    'hero.cta': 'Suscríbete a mi newsletter',

    // Home sections
    'home.projects': 'Lo que construyo',
    'home.latest': 'Últimas notas',
    'home.allNotes': 'Todas las notas',

    // Newsletter (ES only — EN keys exist for type safety)
    'newsletter.placeholder': 'tu@email.com',
    'newsletter.button': 'Suscribirme',
    'newsletter.hint': 'Una nota semanal sobre infraestructura, homelab y lo que estoy construyendo. Sin spam.',
    'newsletter.whatYouGet': 'Qué recibes',
    'newsletter.forYouIf': 'Esto es para ti si',
    'newsletter.benefit1': 'Una nota semanal sobre <strong>infraestructura</strong>, homelab y lo que estoy construyendo.',
    'newsletter.benefit2': 'Acceso anticipado a guías y recursos que voy publicando.',
    'newsletter.benefit3': 'Cero spam. Te das de baja cuando quieras.',
    'newsletter.audience1': 'Tienes curiosidad por montar tu propio <strong>homelab</strong>.',
    'newsletter.audience2': 'Quieres dejar de copiar tutoriales y empezar a <strong>construir</strong>.',
    'newsletter.audience3': 'Te interesa el mundo <strong>DevOps/Platform</strong> con ejemplos reales.',

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

    // 404
    '404.title': 'No encontrado',
    '404.text': 'Esta página no existe.',
    '404.cta': 'Ir al inicio',

    // Meta
    'meta.description': 'Ingeniero. Construyo infraestructura y productos — del hardware a Kubernetes.',
    'meta.ghchart.alt': 'Contribuciones de Manu en GitHub',
  },
} as const;
