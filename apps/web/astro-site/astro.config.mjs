import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';
import tailwind from '@astrojs/tailwind';
import sitemap from '@astrojs/sitemap';
import node from '@astrojs/node';

const loadEnvVariables = () => {

  return {
    PUBLIC_SITE_TITLE: process.env.PUBLIC_SITE_TITLE,
    PUBLIC_SITE_DESCRIPTION: process.env.PUBLIC_SITE_DESCRIPTION,
    PUBLIC_SITE_DOMAIN: process.env.PUBLIC_SITE_DOMAIN,
    PUBLIC_SITE_URL: process.env.PUBLIC_SITE_URL,
    PUBLIC_SITE_MAIL: process.env.PUBLIC_SITE_MAIL,
    PUBLIC_SITE_AUTHOR: process.env.PUBLIC_SITE_AUTHOR,
    PUBLIC_SITE_KEYWORDS: process.env.PUBLIC_SITE_KEYWORDS,
    PUBLIC_TWITTER_URL: process.env.PUBLIC_TWITTER_URL,
    PUBLIC_YOUTUBE_URL: process.env.PUBLIC_YOUTUBE_URL,
    PUBLIC_GITHUB_URL: process.env.PUBLIC_GITHUB_URL,
    PUBLIC_CALENDLY_URL: process.env.PUBLIC_CALENDLY_URL,
    PUBLIC_BUY_ME_A_COFFEE_URL: process.env.PUBLIC_BUY_ME_A_COFFEE_URL,
    PUBLIC_GOOGLE_ANALYTICS_ID: process.env.PUBLIC_GOOGLE_ANALYTICS_ID,
    PUBLIC_GOOGLE_TAG_MANAGER_ID: process.env.PUBLIC_GOOGLE_TAG_MANAGER_ID,
    PUBLIC_ENABLE_HOMELABS: process.env.PUBLIC_ENABLE_HOMELABS,
    PUBLIC_ENABLE_BLOG: process.env.PUBLIC_ENABLE_BLOG,
    PUBLIC_ENABLE_CONTACT: process.env.PUBLIC_ENABLE_CONTACT,
    BACKEND_URL: process.env.BACKEND_URL,
    PUBLIC_ALLOWED_HOSTS: process.env.PUBLIC_ALLOWED_HOSTS,
  };
};

const envVars = loadEnvVariables();

export default defineConfig({
  site: envVars.PUBLIC_SITE_URL || 'https://cubelab.cloud',
  publicDir: 'public',
  output: 'server',
  adapter: node({
    mode: 'standalone',
  }),
  integrations: [tailwind(), sitemap(), mdx()],
  server: {
    allowedHosts: (envVars.PUBLIC_ALLOWED_HOSTS).split(',').map(h => h.trim()).filter(h => h),
  },
  vite: {
    define: {
      'import.meta.env.PUBLIC_SITE_TITLE': JSON.stringify(envVars.PUBLIC_SITE_TITLE),
      'import.meta.env.PUBLIC_SITE_DESCRIPTION': JSON.stringify(envVars.PUBLIC_SITE_DESCRIPTION),
      'import.meta.env.PUBLIC_SITE_DOMAIN': JSON.stringify(envVars.PUBLIC_SITE_DOMAIN),
      'import.meta.env.PUBLIC_SITE_URL': JSON.stringify(envVars.PUBLIC_SITE_URL),
      'import.meta.env.PUBLIC_SITE_MAIL': JSON.stringify(envVars.PUBLIC_SITE_MAIL),
      'import.meta.env.PUBLIC_SITE_AUTHOR': JSON.stringify(envVars.PUBLIC_SITE_AUTHOR),
      'import.meta.env.PUBLIC_SITE_KEYWORDS': JSON.stringify(envVars.PUBLIC_SITE_KEYWORDS),
      'import.meta.env.PUBLIC_TWITTER_URL': JSON.stringify(envVars.PUBLIC_TWITTER_URL),
      'import.meta.env.PUBLIC_YOUTUBE_URL': JSON.stringify(envVars.PUBLIC_YOUTUBE_URL),
      'import.meta.env.PUBLIC_GITHUB_URL': JSON.stringify(envVars.PUBLIC_GITHUB_URL),
      'import.meta.env.PUBLIC_CALENDLY_URL': JSON.stringify(envVars.PUBLIC_CALENDLY_URL),
      'import.meta.env.PUBLIC_BUY_ME_A_COFFEE_URL': JSON.stringify(envVars.PUBLIC_BUY_ME_A_COFFEE_URL),
      'import.meta.env.PUBLIC_GOOGLE_ANALYTICS_ID': JSON.stringify(envVars.PUBLIC_GOOGLE_ANALYTICS_ID),
      'import.meta.env.PUBLIC_GOOGLE_TAG_MANAGER_ID': JSON.stringify(envVars.PUBLIC_GOOGLE_TAG_MANAGER_ID),
      'import.meta.env.PUBLIC_ENABLE_HOMELABS': envVars.PUBLIC_ENABLE_HOMELABS,
      'import.meta.env.PUBLIC_ENABLE_BLOG': envVars.PUBLIC_ENABLE_BLOG,
      'import.meta.env.PUBLIC_ENABLE_CONTACT': envVars.PUBLIC_ENABLE_CONTACT,
      'import.meta.env.BACKEND_URL': JSON.stringify(envVars.BACKEND_URL),
      'import.meta.env.PUBLIC_ALLOWED_HOSTS': JSON.stringify(envVars.PUBLIC_ALLOWED_HOSTS),
    },
    envPrefix: ['PUBLIC_'],
  },
});

console.log('Environment variables loaded successfully:', Object.values(envVars));
