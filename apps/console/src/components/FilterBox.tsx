export function FilterBox({ value, onChange }: { value: string; onChange: (q: string) => void }) {
  return (
    <input
      type="search"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="Filter by title, label, author or repository"
      aria-label="Filter"
      className="w-full max-w-md rounded-md border border-kl-border-dark bg-kl-surface-dark px-3 py-1.5 text-sm text-kl-text-primary placeholder:text-kl-text-muted focus:border-kl-primary focus:outline-none"
    />
  );
}
