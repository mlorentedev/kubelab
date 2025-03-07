import js from '@eslint/js';
import globals from 'globals';

export default [
  // Base recommended configuration
  js.configs.recommended,
  
  // Global configuration
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
    
    // Base rules
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
  
  // Explicitly include source files
  {
    files: ['src/**/*.{js,ts,astro}'],
  },
  
  // Ignore patterns
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