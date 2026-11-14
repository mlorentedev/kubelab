// @vitest-environment node
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

// ADR-074 D2: the console serves its own fonts. The edge's `secure-headers` allows
// `font-src 'self' data:`, so a face that points at a CDN is refused by the browser and the
// page silently falls back to the system stack, which no build step notices.
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const css = (name: string) => readFileSync(resolve(root, 'src/styles', name), 'utf8');
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '');

const faces = [...strip(css('global.css')).matchAll(/@font-face\s*{([^}]*)}/g)].map((m) => m[1]);
const declared = (face: string, prop: string) =>
  new RegExp(`${prop}\\s*:\\s*([^;]+);`).exec(face)?.[1].trim().replace(/^['"]|['"]$/g, '');

// The first family each brand token names, the one a face has to be registered under.
const brandFamilies = (token: '--font-sans' | '--font-mono') => {
  const value = new RegExp(`${token}\\s*:\\s*([^;]+);`).exec(css('brand.css'))?.[1] ?? '';
  return value.split(',')[0].trim().replace(/^['"]|['"]$/g, '');
};

describe('self-hosted fonts', () => {
  it('declares a face for the first family of each brand font token', () => {
    const registered = faces.map((f) => declared(f, 'font-family'));
    for (const token of ['--font-sans', '--font-mono'] as const) {
      expect(registered, token).toContain(brandFamilies(token));
    }
  });

  it('loads every face from a package file that exists, never a URL', () => {
    expect(faces.length).toBeGreaterThan(0);
    for (const face of faces) {
      const src = /url\(\s*['"]?([^'")]+)['"]?\s*\)/.exec(face)?.[1];
      expect(src, face).toBeTruthy();
      expect(src, 'an absolute URL would be refused by font-src').not.toMatch(/^(https?:)?\/\//);
      expect(existsSync(resolve(root, 'node_modules', src as string)), `${src} is not installed`).toBe(true);
    }
  });

  it('swaps instead of hiding the text while a font loads', () => {
    for (const face of faces) expect(declared(face, 'font-display')).toBe('swap');
  });
});
