import type { ItemView } from '../lib/contract';
import { ItemRow } from './ItemRow';

/** The list layout over already-filtered items. It owns no data and no query: a board layout
 * takes the same `items` (ADR-074 amendment, #3442). */
export function ListLayout({ items, now }: { items: ItemView[]; now: Date }) {
  return (
    <ul aria-label="Items" className="border-t border-kl-border-dark">
      {items.map((it) => (
        <ItemRow key={`${it.source}#${it.number}`} item={it} now={now} />
      ))}
    </ul>
  );
}
