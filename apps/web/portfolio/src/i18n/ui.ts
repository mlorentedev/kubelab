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
    'nav.consulting': 'Consulting',
    'nav.toggle': 'Toggle menu',

    // Hero
    'hero.title': 'Engineer from silicon to cloud',
    'hero.subtitle': 'My personal site about side hustles, notes, CLIs, and products built across three continents — that boost my productivity and pay the (some) bills.',
    'hero.cta': 'Read my notes',

    // Home sections
    'home.stack': 'What I work with',
    'home.projects': 'What I build',
    'home.community': 'Community & background',
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

    // Lead magnet — NODO (keys exist for type safety — EN landing has no lead magnet)
    'leadMagnet.pitch1': 'Everything you see here — the projects, the notes, the errors — is documented so my AI remembers it for me. Each session I pick up where I left off. No repeating context. No falling into the same mistakes.',
    'leadMagnet.pitch2': 'Yours probably doesn\'t. Every session you start from zero.',
    'leadMagnet.pitch3': 'In 5 days I\'ll teach you the system. Works with any tool. Any project.',
    'leadMagnet.button': 'Start the course',
    'leadMagnet.placeholder': 'you@email.com',
    'leadMagnet.success': 'Done! Check your email.',
    'leadMagnet.error': 'Please enter a valid email.',
    'leadMagnet.comingSoon': 'Coming soon.',
    'leadMagnet.courseDesc': 'A 5-day course. One email per day. From zero to a complete memory system for your AI. 5-10 minutes each.',
    'leadMagnet.microNote': '5 days. Unsubscribe anytime.',

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
    'meta.description': 'Engineer from silicon to cloud. Infrastructure, Kubernetes, and what breaks in production.',
    'meta.ghchart.alt': "Manu's GitHub contribution chart",
  },
  es: {
    // Nav
    'nav.notes': 'Notas',
    'nav.consulting': 'Consultoría',
    'nav.toggle': 'Abrir menú',

    // Hero
    'hero.title': 'Hazlo tú',
    'hero.subtitle': 'A mí también me creaba ansiedad poder producir cosas que no era ni capaz de imaginar hace 5 años. De hecho, me aterra. Ahora abrazo el cambio',
    'hero.cta': 'Empieza ahora',

    // Home sections
    'home.stack': 'Con qué trabajo',
    'home.projects': 'Lo que construyo',
    'home.community': 'Comunidad y más',
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

    // Lead magnet — NODO (ES — primary monetization funnel)
    'leadMagnet.pitch1': 'Lunes: le explico el proyecto a Copilot. Martes: le explico otro a Claude. Miércoles: Copilot no recuerda el lunes.',
    'leadMagnet.pitch2': 'Un día creé un fichero de texto. Uno. Y ese error no volvió a pasar.',
    'leadMagnet.pitch3': 'En 5 días te enseño el sistema que uso. Funciona con cualquier herramienta. Cualquier proyecto.',
    'leadMagnet.button': 'Empezar el curso',
    'leadMagnet.placeholder': 'tu@email.com',
    'leadMagnet.success': '¡Listo! Revisa tu email.',
    'leadMagnet.error': 'Por favor, introduce un email válido.',
    'leadMagnet.comingSoon': 'Próximamente. Apúntalo y te aviso.',
    'leadMagnet.courseDesc': '5 días. Un email al día. 5-10 minutos cada uno.',
    'leadMagnet.microNote': 'Te das de baja cuando quieras.',

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
    'meta.description': 'Ingeniero. Del silicio a Kubernetes. Infraestructura real, decisiones reales, documentado mientras construyo.',
    'meta.ghchart.alt': 'Contribuciones de Manu en GitHub',
  },
} as const;
