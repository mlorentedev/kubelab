/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  theme: {
    screens: {
      custom: '875px',
    },
    extend: {
      typography: {
        DEFAULT: {
          css: {
            maxWidth: '85ch',
          },
        },
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
};
