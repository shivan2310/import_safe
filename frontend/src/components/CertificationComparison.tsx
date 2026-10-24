import type { CertificationComparison as Cmp } from "../types";
import { humanize } from "../lib/format";
import StatusBadge from "./StatusBadge";
import { EvidenceChips } from "./EvidenceContext";

const RESULT_LABEL = { match: "Match", partial: "Partial match", mismatch: "Mismatch", unknown: "Unknown" } as const;

export default function CertificationComparison({ cmp }: { cmp: Cmp }) {
  const flagged = cmp.overall === "contradiction_detected";
  return (
    <section
      className={`card border-l-4 ${flagged ? "border-l-red-600" : "border-l-amber-400"}`}
      aria-labelledby="cert-title"
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 id="cert-title" className="text-lg font-semibold">
          {flagged ? "Flagged: potential certification mismatch" : "Certification record comparison"}
        </h2>
        <StatusBadge status={cmp.overall} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="py-2 pr-3">Field</th>
              <th className="py-2 pr-3">Seller claim</th>
              <th className="py-2 pr-3">Registration record</th>
              <th className="py-2">Result</th>
            </tr>
          </thead>
          <tbody>
            {cmp.fieldResults.map((r) => (
              <tr
                key={r.field}
                className={`border-t border-slate-100 ${r.result === "mismatch" ? "bg-red-50" : ""}`}
              >
                <th scope="row" className="py-2 pr-3 text-left font-medium">{r.field}</th>
                <td className="py-2 pr-3">{r.claim ?? <span className="text-slate-500">Not provided</span>}</td>
                <td className="py-2 pr-3">{r.record ?? <span className="text-slate-500">Not available</span>}</td>
                <td className={`py-2 font-semibold ${r.result === "mismatch" ? "text-red-800" : ""}`}>
                  {RESULT_LABEL[r.result] ?? humanize(r.result)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {cmp.note && <p className="mt-3 text-sm text-slate-700">{cmp.note}</p>}
      <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
        Evidence: <EvidenceChips ids={cmp.evidenceIds} />
      </p>
    </section>
  );
}
