/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        roboto: ['Roboto', 'sans-serif'],
        heading: ['Space Grotesk', 'sans-serif'],
      },
      colors: {
        primary: '#0e7490',
        'primary-dark': '#0c5e73',
        'primary-light': '#e0f7fa',
      },
      typography: {
        DEFAULT: {
          css: {
            maxWidth: '85ch',
            color: '#334155',
            a: { color: '#0e7490', textDecoration: 'none', '&:hover': { textDecoration: 'underline' } },
            strong: { color: '#0f172a' },
            h1: { color: '#0f172a' },
            h2: { color: '#0f172a' },
            h3: { color: '#0f172a' },
            'code::before': { content: '""' },
            'code::after': { content: '""' },
            code: {
              fontWeight: '400',
              backgroundColor: '#f1f5f9',
              paddingLeft: '0.25rem',
              paddingRight: '0.25rem',
              paddingTop: '0.125rem',
              paddingBottom: '0.125rem',
              borderRadius: '0.25rem',
              color: '#0e7490',
            },
            pre: {
              backgroundColor: '#0f172a',
              color: '#e2e8f0',
              overflowX: 'auto',
            },
          },
        },
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
};
