import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';
import tailwind from '@astrojs/tailwind';
import sitemap from '@astrojs/sitemap';
import node from '@astrojs/node';
import dotenv from 'dotenv';

const result = dotenv.config('.env');

export default defineConfig({
  site: process.env.PUBLIC_SITE_URL,
  output: 'server',
  adapter: node({
    mode: 'standalone',
  }),
  integrations: [tailwind(), sitemap(), mdx()],
  vite: {
    define: {
      'import.meta.env.PUBLIC_SITE_TITLE': JSON.stringify(process.env.PUBLIC_SITE_TITLE),
      'import.meta.env.PUBLIC_SITE_DESCRIPTION': JSON.stringify(
        process.env.PUBLIC_SITE_DESCRIPTION
      ),
      'import.meta.env.PUBLIC_SITE_DOMAIN': JSON.stringify(process.env.PUBLIC_SITE_DOMAIN),
      'import.meta.env.PUBLIC_SITE_URL': JSON.stringify(process.env.PUBLIC_SITE_URL),
      'import.meta.env.PUBLIC_SITE_MAIL': JSON.stringify(process.env.PUBLIC_SITE_MAIL),
      'import.meta.env.PUBLIC_SITE_AUTHOR': JSON.stringify(process.env.PUBLIC_SITE_AUTHOR),
      'import.meta.env.PUBLIC_SITE_KEYWORDS': JSON.stringify(process.env.PUBLIC_SITE_KEYWORDS),
      'import.meta.env.PUBLIC_TWITTER_URL': JSON.stringify(process.env.PUBLIC_TWITTER_URL),
      'import.meta.env.PUBLIC_YOUTUBE_URL': JSON.stringify(process.env.PUBLIC_YOUTUBE_URL),
      'import.meta.env.PUBLIC_GITHUB_URL': JSON.stringify(process.env.PUBLIC_GITHUB_URL),
      'import.meta.env.PUBLIC_CALENDLY_URL': JSON.stringify(process.env.PUBLIC_CALENDLY_URL),
      'import.meta.env.PUBLIC_GOOGLE_ANALYTICS_ID': JSON.stringify(
        process.env.PUBLIC_GOOGLE_ANALYTICS_ID
      ),
      'import.meta.env.PUBLIC_ENABLE_HOMELABS': process.env.PUBLIC_ENABLE_HOMELABS === 'true',
      'import.meta.env.PUBLIC_ENABLE_BLOG': process.env.PUBLIC_ENABLE_BLOG === 'true',
      'import.meta.env.PUBLIC_ENABLE_CONTACT': process.env.PUBLIC_ENABLE_CONTACT === 'true',
      'import.meta.env.PUBLIC_BACKEND_URL': JSON.stringify(process.env.BACKEND_URL),
    },
    envPrefix: ['PUBLIC_'],
  },
});

// Check if the environment variables are loaded correctly
if (result.error) {
  throw result.error;
}
console.log('Environment variables loaded successfully: ', result.parsed);
