// The JSON `GET /console/queue` answers, as apps/api/src/internal/console/console.go
// writes it (queueView, sourceView, itemView, writeView). The console renders these values and
// derives none of them (ADR-074 D7). `tests/contract.test.ts` and the Go test
// TestFixturesMatchTheQueueContract keep the fixtures, this file and the handler in step.

export interface SourceView {
  /** `<forge>:<owner>/<repo>`, e.g. `github:mlorentedev/kubelab`. */
  source: string;
  /** When the source was last read; null when it never was. */
  as_of: string | null;
  reachable: boolean;
}

export interface ItemView {
  source: string;
  number: number;
  kind: 'issue' | 'pull';
  title: string;
  author: string;
  /** Go marshals a nil slice as null. */
  assignees: string[] | null;
  labels: string[] | null;
  url: string;
  updated_at: string;
}

/** A write the outbox still owes, or one that failed in the last 24 hours (ADR-066 A2). */
export interface WriteView {
  id: number;
  action: 'create' | 'add_label' | 'remove_label' | 'add_assignee' | 'remove_assignee' | 'close' | 'reopen';
  /** `<forge>:<owner>/<repo>`, the same form as an item's. */
  source: string;
  /** Null for a create the forge has not answered. */
  number: number | null;
  /** A create's title, or the label or login of the others. Never an issue body. */
  detail: string;
  /** `pending` until the forge confirms (an in-flight write is shown as pending); `failed` is terminal. */
  status: 'pending' | 'failed';
  error: string | null;
  queued_at: string;
}

export interface QueuePage {
  sources: SourceView[];
  items: ItemView[];
  /** Every open item of the declared sources, not the page's length. */
  total: number;
  /** Cursor of the following page; null on the last. */
  next: string | null;
  /** The outbox's writes. Not paged: every page carries them. */
  writes: WriteView[];
}

export class ContractError extends Error {}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

function need<T>(ok: boolean, what: string, v: T): T {
  if (!ok) throw new ContractError(`unexpected queue answer: ${what}`);
  return v;
}

const stringArrayOrNull = (v: unknown, what: string): string[] | null =>
  need(v === null || (Array.isArray(v) && v.every((x) => typeof x === 'string')), what, v as string[] | null);

function parseSource(raw: unknown): SourceView {
  need(isObject(raw), 'source is not an object', raw);
  const s = raw as Record<string, unknown>;
  return {
    source: need(typeof s.source === 'string', 'source.source', s.source as string),
    as_of: need(s.as_of === null || typeof s.as_of === 'string', 'source.as_of', s.as_of as string | null),
    reachable: need(typeof s.reachable === 'boolean', 'source.reachable', s.reachable as boolean),
  };
}

function parseItem(raw: unknown): ItemView {
  need(isObject(raw), 'item is not an object', raw);
  const i = raw as Record<string, unknown>;
  return {
    source: need(typeof i.source === 'string', 'item.source', i.source as string),
    number: need(typeof i.number === 'number', 'item.number', i.number as number),
    kind: need(i.kind === 'issue' || i.kind === 'pull', 'item.kind', i.kind as ItemView['kind']),
    title: need(typeof i.title === 'string', 'item.title', i.title as string),
    author: need(typeof i.author === 'string', 'item.author', i.author as string),
    assignees: stringArrayOrNull(i.assignees, 'item.assignees'),
    labels: stringArrayOrNull(i.labels, 'item.labels'),
    url: need(typeof i.url === 'string', 'item.url', i.url as string),
    updated_at: need(typeof i.updated_at === 'string', 'item.updated_at', i.updated_at as string),
  };
}

const WRITE_ACTIONS = ['create', 'add_label', 'remove_label', 'add_assignee', 'remove_assignee', 'close', 'reopen'];

function parseWrite(raw: unknown): WriteView {
  need(isObject(raw), 'write is not an object', raw);
  const w = raw as Record<string, unknown>;
  return {
    id: need(typeof w.id === 'number', 'write.id', w.id as number),
    action: need(typeof w.action === 'string' && WRITE_ACTIONS.includes(w.action), 'write.action', w.action as WriteView['action']),
    source: need(typeof w.source === 'string', 'write.source', w.source as string),
    number: need(w.number === null || typeof w.number === 'number', 'write.number', w.number as number | null),
    detail: need(typeof w.detail === 'string', 'write.detail', w.detail as string),
    status: need(w.status === 'pending' || w.status === 'failed', 'write.status', w.status as WriteView['status']),
    error: need(w.error === null || typeof w.error === 'string', 'write.error', w.error as string | null),
    queued_at: need(typeof w.queued_at === 'string', 'write.queued_at', w.queued_at as string),
  };
}

/** Checks a decoded answer against the contract, so a shape the API changed fails loudly
 * here rather than rendering `undefined` in a row. */
export function parseQueuePage(raw: unknown): QueuePage {
  need(isObject(raw), 'not an object', raw);
  const q = raw as Record<string, unknown>;
  need(Array.isArray(q.sources), 'sources', q.sources);
  need(Array.isArray(q.items), 'items', q.items);
  need(Array.isArray(q.writes), 'writes', q.writes);
  return {
    sources: (q.sources as unknown[]).map(parseSource),
    items: (q.items as unknown[]).map(parseItem),
    total: need(typeof q.total === 'number', 'total', q.total as number),
    next: need(q.next === null || typeof q.next === 'string', 'next', q.next as string | null),
    writes: (q.writes as unknown[]).map(parseWrite),
  };
}
