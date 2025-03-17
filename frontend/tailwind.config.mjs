/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  theme: {
    screens: {
      custom: '475px',
    },
    extend: {
      fontFamily: {
        roboto: ['Roboto', 'sans-serif'],
      },
      typography: {
        DEFAULT: {
          css: {
            maxWidth: '85ch',
            'code::before': {
              content: '""',
            },
            'code::after': {
              content: '""',
            },
            code: {
              fontWeight: '400',
              backgroundColor: 'var(--tw-prose-pre-bg)',
              paddingLeft: '0.25rem',
              paddingRight: '0.25rem',
              paddingTop: '0.125rem',
              paddingBottom: '0.125rem',
              borderRadius: '0.25rem',
            },
            pre: {
              backgroundColor: '#1e293b',
              color: '#e2e8f0',
              overflowX: 'auto',
            },
            table: {
              width: '100%',
              marginTop: '2rem',
              marginBottom: '2rem',
              fontSize: '0.875rem',
              lineHeight: '1.25rem',
            },
            thead: {
              borderBottomWidth: '2px',
              borderBottomColor: 'var(--tw-prose-th-borders)',
            },
            'thead th': {
              fontWeight: '600',
              paddingTop: '0.75rem',
              paddingBottom: '0.75rem',
              paddingLeft: '0.75rem',
              paddingRight: '0.75rem',
            },
            'tbody td': {
              paddingTop: '0.75rem',
              paddingBottom: '0.75rem',
              paddingLeft: '0.75rem',
              paddingRight: '0.75rem',
            },
            'tbody tr': {
              borderBottomWidth: '1px',
              borderBottomColor: 'var(--tw-prose-td-borders)',
            },
          },
        },
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
};
