import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ForgeView from '../src/components/ForgeView';
import { REFRESH_MS } from '../src/lib/useQueue';
import { item, page, source } from './helpers';

const respond = (...answers: (object | number | 'redirect')[]) => {
  const f = vi.fn(async () => {
    const a = answers.length > 1 ? answers.shift()! : answers[0];
    if (a === 'redirect') return { ok: false, status: 0, type: 'opaqueredirect' } as Response;
    if (typeof a === 'number') return { ok: false, status: a, type: 'basic' } as Response;
    return { ok: true, status: 200, type: 'basic', json: async () => a } as unknown as Response;
  });
  vi.stubGlobal('fetch', f);
  return f;
};

beforeEach(() => {
  window.history.replaceState(null, '', '/');
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('ForgeView', () => {
  it('shows the sources, the rows and "N of M" from one read', async () => {
    respond(
      page({
        sources: [source(), source({ source: 'gitea:teledyne/openkm-brain', reachable: false, as_of: null })],
        items: [item({ number: 5, title: 'First', kind: 'pull' })],
        total: 9,
      }),
    );
    render(<ForgeView />);
    expect(await screen.findByText('First')).toBeTruthy();
    expect(screen.getByText('mlorentedev/kubelab #5 PR')).toBeTruthy();
    expect(screen.getByText('1 of 9 open items loaded')).toBeTruthy();
    expect(screen.getByText(/gitea:teledyne\/openkm-brain - never read - unreachable/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();
  });

  it('renders a hostile title as text, never as markup', async () => {
    respond(page({ items: [item({ title: '<img src=x onerror=alert(1)>', labels: ['<b>x</b>'] })] }));
    const { container } = render(<ForgeView />);
    expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeTruthy();
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('b')).toBeNull();
  });

  it('links each title to its forge page without handing over the opener', async () => {
    respond(page({ items: [item({ title: 'Linked', url: 'https://github.com/mlorentedev/kubelab/issues/1' })] }));
    render(<ForgeView />);
    const a = (await screen.findByText('Linked')).closest('a')!;
    expect(a.getAttribute('href')).toBe('https://github.com/mlorentedev/kubelab/issues/1');
    expect(a.getAttribute('rel')).toContain('noopener');
  });

  it('pages with Load more until the cursor is null', async () => {
    const f = respond(
      page({ items: [item({ number: 1, title: 'One' })], total: 2, next: 'cur1' }),
      page({ items: [item({ number: 2, title: 'Two' })], total: 2, next: null }),
    );
    render(<ForgeView />);
    await screen.findByText('One');
    expect(screen.getByText('1 of 2 open items loaded')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));
    await screen.findByText('Two');
    expect(f).toHaveBeenLastCalledWith('/console/queue?after=cur1', expect.anything());
    expect(screen.getByText('One')).toBeTruthy();
    expect(screen.getByText('2 of 2 open items loaded')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();
  });

  it('filters the loaded rows by text, and keeps the filter in the URL', async () => {
    respond(page({ items: [item({ number: 1, title: 'Fix Authelia' }), item({ number: 2, title: 'Bump astro' })], total: 2 }));
    render(<ForgeView />);
    await screen.findByText('Fix Authelia');
    fireEvent.change(screen.getByRole('searchbox', { name: 'Filter' }), { target: { value: 'authelia' } });
    expect(screen.queryByText('Bump astro')).toBeNull();
    expect(screen.getByText('Fix Authelia')).toBeTruthy();
    // The count still says what is loaded, not what is visible.
    expect(screen.getByText('2 of 2 open items loaded')).toBeTruthy();
    expect(window.location.search).toBe('?q=authelia');
  });

  it('opens with the filter a link carries', async () => {
    window.history.replaceState(null, '', '/?q=astro');
    respond(page({ items: [item({ number: 1, title: 'Fix Authelia' }), item({ number: 2, title: 'Bump astro' })], total: 2 }));
    render(<ForgeView />);
    await screen.findByText('Bump astro');
    expect(screen.queryByText('Fix Authelia')).toBeNull();
    expect((screen.getByRole('searchbox', { name: 'Filter' }) as HTMLInputElement).value).toBe('astro');
  });

  it('says the session expired on an Authelia redirect, and shows no rows', async () => {
    respond('redirect');
    render(<ForgeView />);
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Could not load the queue: session expired, reload the page to sign in.');
    expect(screen.queryAllByRole('listitem').length).toBe(0);
  });

  it('keeps the rows, dimmed and dated, when a later read fails', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    respond(page({ items: [item({ title: 'Kept' })] }), 503);
    const { container } = render(<ForgeView />);
    await screen.findByText('Kept');
    expect(container.querySelector('[data-stale="true"]')).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REFRESH_MS);
    });
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/queue answered 503\. The rows below are the last good read, \d+ min ago\./);
    expect(screen.getByText('Kept')).toBeTruthy();
    expect(container.querySelector('[data-stale="true"]')).not.toBeNull();
  });

  it('refreshes the source health every minute without dropping loaded rows', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    respond(
      page({ items: [item({ number: 1, title: 'One' })], total: 2, next: 'cur1' }),
      page({ items: [item({ number: 2, title: 'Two' })], total: 2, next: null }),
      page({ items: [item({ number: 99, title: 'Fresh' })], total: 2, next: 'ignored', sources: [source({ reachable: false })] }),
    );
    render(<ForgeView />);
    await screen.findByText('One');
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));
    await screen.findByText('Two');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REFRESH_MS);
    });
    await waitFor(() => expect(within(screen.getByRole('list', { name: 'Sources' })).getByText(/unreachable/)).toBeTruthy());
    expect(screen.getByText('One')).toBeTruthy();
    expect(screen.getByText('Two')).toBeTruthy();
    expect(screen.queryByText('Fresh')).toBeNull();
  });
});
