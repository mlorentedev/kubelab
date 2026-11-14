import { describe, expect, it } from 'vitest';
import { readFilter, withFilter } from '../src/lib/url';

describe('filter in the URL', () => {
  it('reads q, and nothing when absent', () => {
    expect(readFilter('?q=authelia')).toBe('authelia');
    expect(readFilter('?q=a%20b%26c')).toBe('a b&c');
    expect(readFilter('')).toBe('');
  });

  it('writes q and drops it when empty, keeping other parameters', () => {
    expect(withFilter('', 'a b&c')).toBe('?q=a+b%26c');
    expect(withFilter('?q=x&view=board', 'y')).toBe('?q=y&view=board');
    expect(withFilter('?q=x&view=board', '')).toBe('?view=board');
    expect(withFilter('?q=x', '')).toBe('');
  });

  it('round-trips', () => {
    expect(readFilter(withFilter('', 'fix: <b>&</b>'))).toBe('fix: <b>&</b>');
  });
});
