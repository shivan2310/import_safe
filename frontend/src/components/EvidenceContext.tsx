import { createContext, useContext } from "react";

interface EvidenceCtx {
  open: (id: string) => void;
  label: (id: string) => string;
}

export const EvidenceContext = createContext<EvidenceCtx>({
  open: () => {},
  label: (id) => id,
});

/** Evidence chips: each opens the evidence drawer. No chips = the statement is an assumption. */
export function EvidenceChips({ ids }: { ids: string[] }) {
  const { open, label } = useContext(EvidenceContext);
  if (ids.length === 0) {
    return <span className="text-xs italic text-slate-500">No evidence attached (assumption)</span>;
  }
  return (
    <span className="inline-flex flex-wrap gap-1">
      {ids.map((id) => (
        <button
          key={id}
          type="button"
          onClick={() => open(id)}
          className="rounded border border-navy/30 bg-navy-50 px-1.5 py-0.5 text-xs font-medium text-navy hover:bg-navy/10"
          aria-label={`Open evidence ${label(id)}`}
        >
          {label(id)}
        </button>
      ))}
    </span>
  );
}
