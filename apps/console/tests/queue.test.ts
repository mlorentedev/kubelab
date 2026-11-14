import { describe, expect, it } from 'vitest';
import {
  ago,
  countLabel,
  errorLine,
  initialState,
  itemRef,
  matchesFilter,
  queueReducer,
  sourceLabel,
} from '../src/lib/queue';
import { item, page, source } from './helpers';

const NOW = new Date('2026-11-12T12:00:00Z');

describe('ago', () => {
  it.each([
    ['2026-11-12T11:59:30Z', '1 min'],
    ['2026-11-12T11:15:00Z', '45 min'],
    ['2026-11-12T11:00:00Z', '1 h'],
    ['2026-11-11T13:00:00Z', '23 h'],
    ['2026-11-10T12:00:00Z', '2 d'],
    ['2026-10-13T12:00:00Z', '30 d'],
  ])('%s reads %s', (iso, text) => {
    expect(ago(iso, NOW)).toBe(text);
  });

  it('never shows a negative age when the forge clock is ahead of ours', () => {
    expect(ago('2026-11-12T12:05:00Z', NOW)).toBe('0 min');
  });
});

describe('itemRef', () => {
  it('names the repository and number, and marks a pull request', () => {
    expect(itemRef(item({ source: 'github:mlorentedev/kubelab', number: 42 }))).toBe('mlorentedev/kubelab #42');
    expect(itemRef(item({ source: 'gitea:teledyne/openkm-brain', number: 7, kind: 'pull' }))).toBe(
      'teledyne/openkm-brain #7 PR',
    );
  });
});

describe('matchesFilter', () => {
  const it1 = item({
    title: 'Fix the Authelia redirect',
    author: 'Manu',
    source: 'gitea:teledyne/openkm-brain',
    labels: ['area:auth', 'priority:p1'],
  });

  it.each([
    ['', true],
    ['authelia', true],
    ['AUTHELIA', true],
    ['manu', true],
    ['openkm', true],
    ['gitea', true],
    ['priority:p1', true],
    ['nothing like it', false],
  ])('%j matches: %s', (q, want) => {
    expect(matchesFilter(it1, q)).toBe(want);
  });

  it('reads an item whose labels the API sent as null', () => {
    expect(matchesFilter(item({ labels: null, title: 'x' }), 'x')).toBe(true);
  });
});

describe('countLabel', () => {
  it('says how much is loaded, since the filter reads loaded pages only', () => {
    expect(countLabel(40, 120)).toBe('40 of 120 open items loaded');
    expect(countLabel(0, 0)).toBe('0 of 0 open items loaded');
  });
});

describe('sourceLabel', () => {
  it('says when a source was read', () => {
    expect(sourceLabel(source({ as_of: '2026-11-12T11:00:00Z' }), NOW)).toEqual({
      text: 'github:mlorentedev/kubelab - read 1 h ago',
      down: false,
    });
  });

  it('flags an unreachable source and a never-read one, so neither passes for an empty forge', () => {
    expect(sourceLabel(source({ as_of: '2026-11-12T11:00:00Z', reachable: false }), NOW)).toEqual({
      text: 'github:mlorentedev/kubelab - read 1 h ago - unreachable',
      down: true,
    });
    expect(sourceLabel(source({ as_of: null, reachable: false }), NOW)).toEqual({
      text: 'github:mlorentedev/kubelab - never read - unreachable',
      down: true,
    });
  });
});

describe('queueReducer', () => {
  const t1 = new Date('2026-11-12T12:00:00Z');
  const t2 = new Date('2026-11-12T12:01:00Z');

  it('starts empty and unread', () => {
    expect(initialState).toMatchObject({ items: [], total: 0, next: null, pages: 0, readAt: null, error: null });
  });

  it('a first read replaces the rows and records the cursor', () => {
    const s = queueReducer(
      initialState,
      { type: 'read', page: page({ items: [item({ number: 1 }), item({ number: 2 })], total: 5, next: 'c1' }), more: false, at: t1 },
    );
    expect(s.items.map((i) => i.number)).toEqual([1, 2]);
    expect(s).toMatchObject({ total: 5, next: 'c1', pages: 1, readAt: t1, error: null });
  });

  it('loading more appends and moves the cursor', () => {
    const first = queueReducer(initialState, { type: 'read', page: page({ items: [item({ number: 1 })], total: 2, next: 'c1' }), more: false, at: t1 });
    const s = queueReducer(first, { type: 'read', page: page({ items: [item({ number: 2 })], total: 2, next: null }), more: true, at: t2 });
    expect(s.items.map((i) => i.number)).toEqual([1, 2]);
    expect(s).toMatchObject({ pages: 2, next: null });
  });

  it('a refresh over one page replaces it', () => {
    const first = queueReducer(initialState, { type: 'read', page: page({ items: [item({ number: 1 })], next: null }), more: false, at: t1 });
    const s = queueReducer(first, { type: 'read', page: page({ items: [item({ number: 9 })], next: null }), more: false, at: t2 });
    expect(s.items.map((i) => i.number)).toEqual([9]);
  });

  it('a refresh over several pages keeps the rows and the cursor, and refreshes sources and total', () => {
    let s = queueReducer(initialState, { type: 'read', page: page({ items: [item({ number: 1 })], total: 2, next: 'c1' }), more: false, at: t1 });
    s = queueReducer(s, { type: 'read', page: page({ items: [item({ number: 2 })], total: 2, next: 'c2' }), more: true, at: t1 });
    const fresh = page({
      items: [item({ number: 77 })],
      total: 3,
      next: 'other',
      sources: [source({ reachable: false })],
    });
    s = queueReducer(s, { type: 'read', page: fresh, more: false, at: t2 });
    expect(s.items.map((i) => i.number)).toEqual([1, 2]);
    expect(s.next).toBe('c2');
    expect(s.pages).toBe(2);
    expect(s.total).toBe(3);
    expect(s.sources[0].reachable).toBe(false);
    expect(s.readAt).toBe(t2);
  });

  it('a failed read keeps the rows and the last good read time, and records the error', () => {
    const ok = queueReducer(initialState, { type: 'read', page: page({ items: [item({ number: 1 })] }), more: false, at: t1 });
    const s = queueReducer(ok, { type: 'failed', message: 'queue answered 503' });
    expect(s.items).toHaveLength(1);
    expect(s.readAt).toBe(t1);
    expect(s.error).toBe('queue answered 503');
  });

  it('the next good read clears the error', () => {
    const bad = queueReducer(initialState, { type: 'failed', message: 'boom' });
    const s = queueReducer(bad, { type: 'read', page: page(), more: false, at: t1 });
    expect(s.error).toBeNull();
  });
});

describe('errorLine', () => {
  it('is empty without an error', () => {
    expect(errorLine(initialState, NOW)).toBe('');
  });

  it('with no good read yet, only says what failed', () => {
    const s = queueReducer(initialState, { type: 'failed', message: 'queue answered 503' });
    expect(errorLine(s, NOW)).toBe('Could not load the queue: queue answered 503.');
  });

  it('with rows on screen, dates them so a failed read never passes for a current one', () => {
    let s = queueReducer(initialState, { type: 'read', page: page(), more: false, at: new Date('2026-11-12T11:00:00Z') });
    s = queueReducer(s, { type: 'failed', message: 'queue answered 503' });
    expect(errorLine(s, NOW)).toBe('Could not load the queue: queue answered 503. The rows below are the last good read, 1 h ago.');
  });
});
