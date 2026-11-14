import type { ItemView } from '../lib/contract';
import { ago, itemRef } from '../lib/queue';

// Every forge value is a React text child, never HTML: titles and labels are user input.

export function LabelChips({ labels }: { labels: string[] | null }) {
  return (
    <>
      {(labels ?? []).map((l) => (
        <span key={l} className="rounded-full bg-kl-surface-hover px-2 py-0.5 text-xs text-kl-text-secondary">
          {l}
        </span>
      ))}
    </>
  );
}

/** One item as a list row. A board card (ADR-074 amendment, #3442) reuses `LabelChips` and
 * `itemRef` over the same `ItemView`, so the row is not the only place an item is drawn. */
export function ItemRow({ item, now }: { item: ItemView; now: Date }) {
  return (
    <li className="grid grid-cols-[11rem_1fr_auto_8rem_4rem] items-baseline gap-3 border-b border-kl-border-dark px-2 py-1.5 text-sm hover:bg-kl-surface-hover/50">
      <span className="truncate text-kl-text-muted">{itemRef(item)}</span>
      <a href={item.url} rel="noopener" className="truncate text-kl-text-primary hover:text-kl-accent-light hover:underline">
        {item.title}
      </a>
      <span className="flex flex-wrap justify-end gap-1">
        <LabelChips labels={item.labels} />
      </span>
      <span className="truncate text-kl-text-secondary">{item.author}</span>
      <span className="text-right text-kl-text-muted">{ago(item.updated_at, now)}</span>
    </li>
  );
}
