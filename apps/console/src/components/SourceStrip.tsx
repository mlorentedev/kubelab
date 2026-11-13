import type { SourceView } from '../lib/contract';
import { sourceLabel } from '../lib/queue';

/** Which forges were read, and when: an unread or unreachable one never passes for an empty one. */
export function SourceStrip({ sources, now }: { sources: SourceView[]; now: Date }) {
  return (
    <ul aria-label="Sources" className="flex flex-wrap gap-2 text-xs">
      {sources.map((s) => {
        const { text, down } = sourceLabel(s, now);
        return (
          <li
            key={s.source}
            data-down={down}
            className={
              down
                ? 'rounded border border-red-500/40 bg-red-500/10 px-2 py-1 text-red-300'
                : 'rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-300'
            }
          >
            {text}
          </li>
        );
      })}
    </ul>
  );
}
