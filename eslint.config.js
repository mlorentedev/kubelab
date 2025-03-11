import js from '@eslint/js';
import globals from 'globals';
import tseslint from '@typescript-eslint/eslint-plugin';
import tsp from '@typescript-eslint/parser';
import astro from 'eslint-plugin-astro';

export default [
  js.configs.recommended,
  
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
      },
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
    },
    
    rules: {
      'no-unused-vars': 'warn',
      'no-console': 'off',
      'eqeqeq': 'error',
      'curly': 'error',
      'semi': ['error', 'always'],
      'quotes': ['error', 'single'],
      'no-duplicate-imports': 'error',
      'prefer-const': 'warn',
      'no-var': 'error',
    },
  },
  
  {
    files: ['src/**/*.{js,ts,astro}'],
    languageOptions: {
      parser: tsp,
      parserOptions: {
        project: './tsconfig.json',
      },
    },
    plugins: {
      '@typescript-eslint': tseslint,
    }, 
    rules: {
      ...tseslint.configs.recommended.rules, 
    },
  },

  {
    files: ['src/**/*.astro'],
    languageOptions: {
      parser: 'astro-eslint-parser',
      parserOptions: {
        parser: {
          ts: tsp,
        },
        extraFileExtensions: ['.astro'],
      },
    },
    plugins: {
      astro,
    },
    rules: {
      ...astro.configs.recommended.rules,
    },
  },

  {
    ignores: [
      'dist/',
      '.astro/',
      'node_modules/',
      '*.config.js',
      '*.config.mjs',
      '.github/',
      '.vscode/',
      'public/',
      '**/*.d.ts',
      '**/*.config.ts',
    ],
  },
];