import { useState } from "react";
import type { Fact, Report } from "../types";
import { EvidenceChips } from "./EvidenceContext";

function FactRow({ fact }: { fact: Fact }) {
  return (
    <li className="flex flex-wrap items-baseline justify-between gap-2 border-t border-slate-100 py-2 first:border-t-0">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{fact.field}</p>
        <p className="text-sm">{fact.value}</p>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500">{fact.confidence} confidence</span>
        <EvidenceChips ids={fact.evidenceIds} />
      </div>
    </li>
  );
}

const TABS = [
  { key: "confirmed", label: "Confirmed facts", note: "Read from the listing." },
  { key: "sellerClaims", label: "Seller claims", note: "Claimed by the seller. Not independently verified." },
  { key: "userSupplied", label: "User-supplied", note: "Entered by you." },
] as const;

export default function ProductProfile({ profile }: { profile: Report["profile"] }) {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("confirmed");
  const active = TABS.find((t) => t.key === tab)!;
  const facts = profile[tab];
  return (
    <section className="card" aria-labelledby="profile-title">
      <h2 id="profile-title" className="mb-3 text-lg font-semibold">
        Product profile
      </h2>
      <div role="tablist" aria-label="Fact provenance" className="flex flex-wrap gap-2 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            type="button"
            id={`tab-${t.key}`}
            aria-selected={tab === t.key}
            aria-controls="profile-panel"
            onClick={() => setTab(t.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              tab === t.key ? "border-navy text-navy" : "border-transparent text-slate-600 hover:text-slate-900"
            }`}
          >
            {t.label} ({profile[t.key].length})
          </button>
        ))}
      </div>
      <div role="tabpanel" id="profile-panel" aria-labelledby={`tab-${tab}`} className="pt-3">
        <p className="mb-2 text-xs text-slate-600">{active.note}</p>
        {facts.length === 0 ? (
          <p className="text-sm italic text-slate-500">None.</p>
        ) : (
          <ul>
            {facts.map((f) => (
              <FactRow key={f.field + f.value} fact={f} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
