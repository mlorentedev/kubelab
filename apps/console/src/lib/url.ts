// View state lives in the URL, so every view is a link (ADR-074 D4).

export const FILTER_PARAM = 'q';

export function readFilter(search: string): string {
  return new URLSearchParams(search).get(FILTER_PARAM) ?? '';
}

/** The query string with the filter set, or removed when empty; other parameters are kept. */
export function withFilter(search: string, q: string): string {
  const p = new URLSearchParams(search);
  if (q) p.set(FILTER_PARAM, q);
  else p.delete(FILTER_PARAM);
  const s = p.toString();
  return s ? `?${s}` : '';
}
