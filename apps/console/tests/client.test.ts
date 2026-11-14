// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { QUEUE_PATH, fetchQueue } from '../src/lib/client';
import { ContractError } from '../src/lib/contract';
import { page } from './helpers';

const answer = ({ data, ...init }: Partial<Response> & { data?: unknown }): typeof fetch =>
  vi.fn(async () => ({ ok: true, status: 200, type: 'basic', json: async () => data, ...init }) as unknown as Response);

describe('fetchQueue', () => {
  it('reads the same-origin path, never following a redirect', async () => {
    const f = answer({ data: page() });
    await fetchQueue(null, f);
    expect(f).toHaveBeenCalledWith(QUEUE_PATH, { credentials: 'same-origin', redirect: 'manual' });
    expect(QUEUE_PATH).toBe('/console/queue');
  });

  it('sends the cursor, URL-encoded', async () => {
    const f = answer({ data: page() });
    await fetchQueue('a+b/c=', f);
    expect((f as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe('/console/queue?after=a%2Bb%2Fc%3D');
  });

  it('returns the validated page', async () => {
    const want = page({ total: 9 });
    expect(await fetchQueue(null, answer({ data: want }))).toEqual(want);
  });

  it.each([
    ['an Authelia redirect to its portal', { type: 'opaqueredirect', ok: false, status: 0 }],
    ['a 401', { ok: false, status: 401 }],
  ])('%s says the session expired', async (_name, init) => {
    await expect(fetchQueue(null, answer(init as Partial<Response>))).rejects.toThrow(/session expired/);
  });

  it('names the status when the API fails', async () => {
    await expect(fetchQueue(null, answer({ ok: false, status: 503 }))).rejects.toThrow('queue answered 503');
  });

  it('refuses an answer that is not the contract rather than rendering undefined', async () => {
    await expect(fetchQueue(null, answer({ data: { items: 'no' } }))).rejects.toBeInstanceOf(ContractError);
  });
});
