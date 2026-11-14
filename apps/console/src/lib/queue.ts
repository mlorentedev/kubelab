// The forge view's logic, apart from React so it is tested without a DOM. It formats and
// merges what the API answers; it derives nothing the API owns (ADR-074 D7).
import type { ItemView, QueuePage, SourceView } from './contract';

/** Age as the embedded page showed it: minutes under an hour, hours under two days, then days. */
export function ago(iso: string, now: Date = new Date()): string {
  const m = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60000));
  if (m < 60) return `${m} min`;
  if (m < 2880) return `${Math.round(m / 60)} h`;
  return `${Math.round(m / 1440)} d`;
}

/** `owner/repo #n`, with ` PR` on a pull request. The forge prefix is dropped, the owner is not:
 * two forges can host the same repository name. */
export function itemRef(it: ItemView): string {
  const repo = it.source.split(':')[1] ?? it.source;
  return `${repo} #${it.number}${it.kind === 'pull' ? ' PR' : ''}`;
}

/** The text filter: title, author, source and labels, case-insensitive. */
export function matchesFilter(it: ItemView, q: string): boolean {
  if (!q) return true;
  const text = [it.title, it.author, it.source, ...(it.labels ?? [])].join(' ').toLowerCase();
  return text.includes(q.toLowerCase());
}

/** The filter reads loaded pages only, so the count says how much is loaded. */
export const countLabel = (loaded: number, total: number): string => `${loaded} of ${total} open items loaded`;

export function sourceLabel(s: SourceView, now: Date = new Date()): { text: string; down: boolean } {
  const when = s.as_of ? `read ${ago(s.as_of, now)} ago` : 'never read';
  return { text: `${s.source} - ${when}${s.reachable ? '' : ' - unreachable'}`, down: !s.reachable };
}

export interface QueueState {
  sources: SourceView[];
  items: ItemView[];
  total: number;
  next: string | null;
  pages: number;
  /** When the last good read landed; the rows below an error are dated by it. */
  readAt: Date | null;
  error: string | null;
}

export const initialState: QueueState = {
  sources: [],
  items: [],
  total: 0,
  next: null,
  pages: 0,
  readAt: null,
  error: null,
};

export type QueueAction =
  | { type: 'read'; page: QueuePage; more: boolean; at: Date }
  | { type: 'failed'; message: string };

/**
 * A read of the first page replaces the rows, and a read with `more` appends the next.
 * With more than one page loaded, a reread of the first page refreshes the sources and the
 * total and keeps the rows and the cursor, so the health banner stays live without dropping
 * what was loaded. A failure keeps everything and records the error.
 */
export function queueReducer(state: QueueState, action: QueueAction): QueueState {
  if (action.type === 'failed') return { ...state, error: action.message };
  const { page, more, at } = action;
  const base = { ...state, sources: page.sources, total: page.total, readAt: at, error: null };
  if (!more && state.pages > 1) return base;
  return {
    ...base,
    items: more ? [...state.items, ...page.items] : page.items,
    pages: more ? state.pages + 1 : 1,
    next: page.next,
  };
}

/** The banner for a failed read. The rows stay, so it says how old they are. */
export function errorLine(state: QueueState, now: Date = new Date()): string {
  if (!state.error) return '';
  const last = state.readAt ? ` The rows below are the last good read, ${ago(state.readAt.toISOString(), now)} ago.` : '';
  return `Could not load the queue: ${state.error}.${last}`;
}
