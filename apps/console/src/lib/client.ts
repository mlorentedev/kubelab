import { parseQueuePage, type QueuePage } from './contract';

/** Absolute, because the app is served at `/` and the API under `/console/` on the same
 * host (ADR-074 D5). The embedded page read a relative `queue` from `/console/`. */
export const QUEUE_PATH = '/console/queue';

/**
 * Reads one page of the queue: the first when `after` is null, else the page that follows
 * that cursor. Authelia answers an expired session with a redirect to its portal, which is
 * not data and is not followed.
 */
export async function fetchQueue(after: string | null, f: typeof fetch = fetch): Promise<QueuePage> {
  const url = after ? `${QUEUE_PATH}?after=${encodeURIComponent(after)}` : QUEUE_PATH;
  const r = await f(url, { credentials: 'same-origin', redirect: 'manual' });
  if (r.type === 'opaqueredirect' || r.status === 401) {
    throw new Error('session expired, reload the page to sign in');
  }
  if (!r.ok) throw new Error(`queue answered ${r.status}`);
  return parseQueuePage(await r.json());
}
