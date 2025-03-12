import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';
import tailwind from '@astrojs/tailwind';
import sitemap from '@astrojs/sitemap';
import node from '@astrojs/node';

export default defineConfig({
  site: process.env.SITE_URL || 'https://mlorente.dev',
  output: 'server',
  adapter: node({
    mode: 'standalone',
  }),
  integrations: [tailwind(), sitemap(), mdx()],
  vite: {
    // Pasar todas las variables de entorno a los componentes frontend
    define: {
      'import.meta.env.SITE_TITLE': JSON.stringify(process.env.SITE_TITLE),
      'import.meta.env.SITE_DESCRIPTION': JSON.stringify(process.env.SITE_DESCRIPTION),
      'import.meta.env.SITE_DOMAIN': JSON.stringify(process.env.SITE_DOMAIN),
      'import.meta.env.SITE_URL': JSON.stringify(process.env.SITE_URL),
      'import.meta.env.SITE_MAIL': JSON.stringify(process.env.SITE_MAIL),
      'import.meta.env.SITE_AUTHOR': JSON.stringify(process.env.SITE_AUTHOR),
      'import.meta.env.SITE_KEYWORDS': JSON.stringify(process.env.SITE_KEYWORDS),
      'import.meta.env.TWITTER_URL': JSON.stringify(process.env.TWITTER_URL),
      'import.meta.env.YOUTUBE_URL': JSON.stringify(process.env.YOUTUBE_URL),
      'import.meta.env.GITHUB_URL': JSON.stringify(process.env.GITHUB_URL),
      'import.meta.env.CALENDLY_URL': JSON.stringify(process.env.CALENDLY_URL),
      'import.meta.env.BUY_ME_A_COFFEE_URL': JSON.stringify(process.env.BUY_ME_A_COFFEE_URL),
      'import.meta.env.GOOGLE_ANALYTICS_ID': JSON.stringify(process.env.GOOGLE_ANALYTICS_ID),
      'import.meta.env.ENABLE_HOMELABS': JSON.stringify(process.env.ENABLE_HOMELABS),
      'import.meta.env.ENABLE_BLOG': JSON.stringify(process.env.ENABLE_BLOG),
      'import.meta.env.ENABLE_CONTACT': JSON.stringify(process.env.ENABLE_CONTACT),
      'import.meta.env.BACKEND_URL': JSON.stringify(process.env.BACKEND_URL || '/api'),
    }
  }
});