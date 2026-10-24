import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import type { Evidence } from "../types";
import { formatDateTime, humanize, safeHref } from "../lib/format";

export default function EvidenceDrawer({
  evidence,
  open,
  selectedId,
  onClose,
}: {
  evidence: Evidence[];
  open: boolean;
  selectedId: string | null;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (open && selectedId) {
      document.getElementById(`evidence-${selectedId}`)?.scrollIntoView({ block: "nearest" });
    }
  }, [open, selectedId]);

  if (!open) return null;
  return (
    <div className="no-print fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-slate-900/40" onClick={onClose} aria-hidden="true" />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Evidence"
        className="relative z-50 flex h-full w-full max-w-md flex-col bg-white shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 className="font-semibold">Evidence ({evidence.length})</h2>
          <button ref={closeRef} type="button" className="btn-secondary px-2 py-1" onClick={onClose}>
            <X className="h-4 w-4" aria-hidden="true" />
            <span className="sr-only">Close evidence</span>
          </button>
        </div>
        <ul className="flex-1 space-y-3 overflow-y-auto p-4">
          {evidence.map((ev, i) => {
            const href = safeHref(ev.sourceUrl);
            return (
              <li
                key={ev.id}
                id={`evidence-${ev.id}`}
                className={`rounded-md border p-3 text-sm ${
                  ev.id === selectedId ? "border-navy bg-navy-50" : "border-slate-200"
                }`}
              >
                <p className="font-semibold">
                  E{i + 1} · {ev.label}
                </p>
                <p className="mt-1 text-xs text-slate-600">
                  {humanize(ev.sourceType)} · {ev.retrievalMode === "demo" ? "DEMO fixture" : "Live"} ·
                  retrieved {formatDateTime(ev.retrievedAt)}
                </p>
                {href ? (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-1 block break-all text-xs text-blue-700 underline"
                  >
                    {href}
                  </a>
                ) : (
                  <p className="mt-1 text-xs italic text-slate-500">No source URL</p>
                )}
                {ev.excerpt && (
                  <blockquote className="mt-2 border-l-2 border-slate-300 pl-2 text-slate-800">
                    {ev.excerpt}
                  </blockquote>
                )}
              </li>
            );
          })}
        </ul>
      </aside>
    </div>
  );
}
