// Reemplaza src/config/env.ts y src/config/feature-flags.ts

// Obtiene variables del entorno de Astro (import.meta.env)
export const env = {
    SITE: {
      TITLE: import.meta.env.SITE_TITLE || 'mlorente.dev',
      DESCRIPTION: import.meta.env.SITE_DESCRIPTION || 'Blog personal',
      DOMAIN: import.meta.env.SITE_DOMAIN || 'localhost',
      URL: import.meta.env.SITE_URL || 'http://localhost:3000',
      MAIL: import.meta.env.SITE_MAIL || 'mlorentedev@gmail.com',
      AUTHOR: import.meta.env.SITE_AUTHOR || 'Manuel Lorente',
      KEYWORDS: import.meta.env.SITE_KEYWORDS || 'devops, cloud',
    },
    RRSS: {
      TWITTER: import.meta.env.TWITTER_URL || 'https://twitter.com/mlorentedev',
      YOUTUBE: import.meta.env.YOUTUBE_URL || 'https://youtube.com/@mlorentedev',
      GITHUB: import.meta.env.GITHUB_URL || 'https://github.com/mlorentedev',
      CALENDLY: import.meta.env.CALENDLY_URL || '',
      BUY_ME_A_COFFEE: import.meta.env.BUY_ME_A_COFFEE_URL || '',
    },
    ANALYTICS: {
      GOOGLE_ID: import.meta.env.GOOGLE_ANALYTICS_ID || '',
    },
    FEATURE_FLAGS: {
      ENABLE_HOMELABS: import.meta.env.ENABLE_HOMELABS === 'true',
      ENABLE_BLOG: import.meta.env.ENABLE_BLOG === 'true',
      ENABLE_CONTACT: import.meta.env.ENABLE_CONTACT === 'true',
    },
    API: {
      BACKEND_URL: import.meta.env.BACKEND_URL || '/api',
    }
  };