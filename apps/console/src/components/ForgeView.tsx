import { useEffect, useMemo, useState } from 'react';
import { countLabel, errorLine, matchesFilter } from '../lib/queue';
import { readFilter, withFilter } from '../lib/url';
import { useQueue } from '../lib/useQueue';
import { FilterBox } from './FilterBox';
import { ListLayout } from './ListLayout';
import { SourceStrip } from './SourceStrip';

/** The forge view: what is open across the declared forges. It reads the API and shows it;
 * it derives nothing (ADR-074 D7). The filter is the only view state, and it is in the URL. */
export default function ForgeView() {
  const { state, loadMore } = useQueue();
  const [q, setQ] = useState(() => readFilter(window.location.search));

  useEffect(() => {
    const next = withFilter(window.location.search, q);
    if (next !== window.location.search) {
      window.history.replaceState(null, '', `${window.location.pathname}${next}${window.location.hash}`);
    }
  }, [q]);

  const now = new Date();
  const visible = useMemo(() => state.items.filter((it) => matchesFilter(it, q)), [state.items, q]);
  const error = errorLine(state, now);

  return (
    <div className="mx-auto max-w-6xl space-y-3 p-6">
      <h1 className="text-xl font-semibold text-kl-text-primary">Forge queue</h1>
      <SourceStrip sources={state.sources} now={now} />
      <FilterBox value={q} onChange={setQ} />
      {error && (
        <p role="alert" className="text-sm text-red-400">
          {error}
        </p>
      )}
      <div className={state.error ? 'opacity-55' : undefined} data-stale={state.error !== null}>
        <ListLayout items={visible} now={now} />
      </div>
      <p className="text-sm text-kl-text-muted">
        {countLabel(state.items.length, state.total)}{' '}
        {state.next !== null && (
          <button
            type="button"
            onClick={loadMore}
            className="ml-2 rounded border border-kl-border-dark px-2 py-0.5 text-kl-text-secondary hover:bg-kl-surface-hover"
          >
            Load more
          </button>
        )}
      </p>
    </div>
  );
}
