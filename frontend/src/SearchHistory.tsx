import { useEffect, useRef, useState } from 'react';
import type { ImportOrder } from './InvestigationFlow';
import './SearchHistory.css';

export type HistoryEntry = { id: string; time: string; order: ImportOrder };
const storageKey = 'importsafe-search-history';
export function readHistory(): HistoryEntry[] {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(storageKey) || '[]');
    if (!Array.isArray(saved)) return [];
    return saved.filter((item): item is HistoryEntry => item && typeof item.id === 'string' && typeof item.time === 'string' && Number.isFinite(Date.parse(item.time)) && item.order &&
      ['url', 'quantity', 'state', 'city', 'purpose', 'variant', 'shipping', 'currency', 'shippingMode'].every(key => typeof item.order[key] === 'string') &&
      /^https?:\/\//.test(item.order.url) && Array.isArray(item.order.certificates) && item.order.certificates.every((value: unknown) => typeof value === 'string')).slice(0, 20);
  } catch { return []; }
}
export function saveHistory(entries: HistoryEntry[]) {
  try { localStorage.setItem(storageKey, JSON.stringify(entries)); } catch { /* History still works for this session. */ }
}
function listingTitle(order: ImportOrder) {
  try {
    const url = new URL(order.url);
    const slug = decodeURIComponent(url.pathname.split('/').filter(Boolean).pop() || '').replace(/\.html?$/, '').replace(/[_-]+/g, ' ');
    return slug || url.hostname;
  } catch { return order.url; }
}
export default function SearchHistory({ entries, onSelect, onNew }: { entries: HistoryEntry[]; onSelect: (order: ImportOrder) => void; onNew: () => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    function outside(event: PointerEvent) { if (!root.current?.contains(event.target as Node)) setOpen(false); }
    function escape(event: KeyboardEvent) { if (event.key === 'Escape' && open) { setOpen(false); trigger.current?.focus(); } }
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [open]);
  return <div className="search-history" ref={root} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false); }}>
    <button ref={trigger} className="history-trigger" type="button" aria-label="Recent searches" aria-expanded={open} aria-controls="search-history-panel" onClick={() => setOpen(!open)}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3" stroke="currentColor" strokeWidth="1.5"/><path d="M9 4v16M13 9h4M13 13h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
    </button>
    {open && <section className="history-panel" id="search-history-panel" aria-label="Recent searches">
      <div className="history-heading"><strong>Recent searches</strong><span>Saved in this browser</span></div>
      <button className="history-new" type="button" onClick={() => { setOpen(false); onNew(); }}>+ New investigation</button>
      {entries.length ? <ul>{entries.map(entry => <li key={entry.id}><button type="button" onClick={() => { setOpen(false); onSelect(entry.order); }}>
        <strong>{listingTitle(entry.order)}</strong><span>{entry.order.quantity} units · {entry.order.city}</span><time dateTime={entry.time}>{new Date(entry.time).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</time>
      </button></li>)}</ul> : <p className="history-empty">No searches yet. Start an investigation to find it here.</p>}
    </section>}
  </div>;
}
