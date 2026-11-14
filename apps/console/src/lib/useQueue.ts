import { useCallback, useEffect, useReducer, useRef } from 'react';
import { fetchQueue } from './client';
import type { QueuePage } from './contract';
import { initialState, queueReducer, type QueueState } from './queue';

export const REFRESH_MS = 60_000;

export interface Queue {
  state: QueueState;
  /** Appends the next page, when there is one. */
  loadMore: () => void;
}

/**
 * Reads the queue: the first page on mount, then again every minute so the health of the
 * sources stays live, and the next page on demand. The merge rules are `queueReducer`'s.
 * One read at a time: a refresh landing during an append would replace its rows.
 */
export function useQueue(read: (after: string | null) => Promise<QueuePage> = fetchQueue): Queue {
  const [state, dispatch] = useReducer(queueReducer, initialState);
  const latest = useRef(state);
  latest.current = state;
  const busy = useRef(false);

  const load = useCallback(
    async (more: boolean) => {
      if (busy.current) return;
      const after = more ? latest.current.next : null;
      if (more && after === null) return;
      busy.current = true;
      try {
        dispatch({ type: 'read', page: await read(after), more, at: new Date() });
      } catch (e) {
        dispatch({ type: 'failed', message: e instanceof Error ? e.message : String(e) });
      } finally {
        busy.current = false;
      }
    },
    [read],
  );

  useEffect(() => {
    void load(false);
    const id = setInterval(() => void load(false), REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  return { state, loadMore: useCallback(() => void load(true), [load]) };
}
