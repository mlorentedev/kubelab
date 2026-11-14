import type { ItemView, QueuePage, SourceView } from '../src/lib/contract';

export const item = (over: Partial<ItemView> = {}): ItemView => ({
  source: 'github:mlorentedev/kubelab',
  number: 1,
  kind: 'issue',
  title: 'A title',
  author: 'someone',
  assignees: [],
  labels: [],
  url: 'https://github.com/mlorentedev/kubelab/issues/1',
  updated_at: '2026-11-12T10:00:00Z',
  ...over,
});

export const source = (over: Partial<SourceView> = {}): SourceView => ({
  source: 'github:mlorentedev/kubelab',
  as_of: '2026-11-12T10:00:00Z',
  reachable: true,
  ...over,
});

export const page = (over: Partial<QueuePage> = {}): QueuePage => ({
  sources: [source()],
  items: [item()],
  total: 1,
  next: null,
  ...over,
});
