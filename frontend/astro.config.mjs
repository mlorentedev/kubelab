import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';
import tailwind from '@astrojs/tailwind';
import sitemap from '@astrojs/sitemap';
import node from '@astrojs/node';
import dotenv from 'dotenv';

// Function to load environment variables
const loadEnvVariables = () => {
  let envVars = {};
  
  try {
    // Try to load local .env file for development
    const localResult = dotenv.config({ path: '.env' });
    if (localResult.parsed) {
      envVars = { ...envVars, ...localResult.parsed };
    }
  } catch (error) {
    console.log('No .env file found, using environment variables');
  }
  
  // Use environment variables as fallback
  const envKeys = [
    'ENV', 'VERSION', 
    'PUBLIC_SITE_TITLE', 'PUBLIC_SITE_DESCRIPTION', 
    'PUBLIC_SITE_DOMAIN', 'PUBLIC_SITE_URL', 
    'PUBLIC_SITE_MAIL', 'PUBLIC_SITE_AUTHOR', 
    'PUBLIC_SITE_KEYWORDS',
    'PUBLIC_TWITTER_URL', 'PUBLIC_YOUTUBE_URL', 
    'PUBLIC_GITHUB_URL', 'PUBLIC_CALENDLY_URL',
    'PUBLIC_GOOGLE_ANALYTICS_ID', 'PUBLIC_GOOGLE_TAG_MANAGER_ID',
    'PUBLIC_ENABLE_HOMELABS', 'PUBLIC_ENABLE_BLOG', 'PUBLIC_ENABLE_CONTACT',
    'BACKEND_URL'
  ];
  
  // Add environment variables to the envVars object
  envKeys.forEach(key => {
    if (process.env[key]) {
      envVars[key] = process.env[key];
    }
  });
  
  return envVars;
};

// Load environment variables
const envVars = loadEnvVariables();

export default defineConfig({
  site: envVars.PUBLIC_SITE_URL || 'https://mlorente.dev',
  publicDir: 'public',
  output: 'server',
  adapter: node({
    mode: 'standalone',
  }),
  integrations: [tailwind(), sitemap(), mdx()],
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
      'import.meta.env.PUBLIC_GOOGLE_ANALYTICS_ID': JSON.stringify(envVars.PUBLIC_GOOGLE_ANALYTICS_ID),
      'import.meta.env.PUBLIC_ENABLE_HOMELABS': envVars.PUBLIC_ENABLE_HOMELABS === 'true',
      'import.meta.env.PUBLIC_ENABLE_BLOG': envVars.PUBLIC_ENABLE_BLOG === 'true',
      'import.meta.env.PUBLIC_ENABLE_CONTACT': envVars.PUBLIC_ENABLE_CONTACT === 'true',
      'import.meta.env.BACKEND_URL': JSON.stringify(envVars.BACKEND_URL),
    },
    envPrefix: ['PUBLIC_'],
  },
});

// Log environment variables for debugging
console.log('Environment variables loaded successfully:', Object.values(envVars));