import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import tailwindcss from '@tailwindcss/vite';

import { fixtureApi } from './dev/fixture-api.ts';

// Static output served by nginx (ADR-074 D2): no server rendering, no Node at runtime.
// Tailwind 4 runs as a Vite plugin and is configured in `src/styles/global.css`.
//
// `fixtureApi` exists only for `astro dev`. Authelia's cookie is scoped to the console
// host, so a dev server on localhost cannot call a real `/console/` with a session
// (ADR-074, Consequences). It answers the API's JSON from recorded fixtures instead.
export default defineConfig({
  output: 'static',
  integrations: [react()],
  vite: { plugins: [tailwindcss(), fixtureApi()] },
});
