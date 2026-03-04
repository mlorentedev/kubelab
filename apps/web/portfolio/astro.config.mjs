import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';
import tailwind from '@astrojs/tailwind';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: 'https://mlorente.dev',
  output: 'static',
  integrations: [tailwind(), sitemap(), mdx()],
});
