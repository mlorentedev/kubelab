// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
	site: 'https://mlorentedev.github.io',
	base: '/kubelab',
	integrations: [
		starlight({
			title: 'KubeLab',
			social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/mlorentedev/kubelab' }],
			sidebar: [
				{ slug: 'architecture' },
				{ slug: 'hardware' },
			],
		}),
	],
});
