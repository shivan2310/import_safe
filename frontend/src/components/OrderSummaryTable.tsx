import type { ReactNode } from "react";
import type { ReportSummary } from "../types";
import { formatINR, humanize } from "../lib/format";

export default function OrderSummaryTable({ summary }: { summary: ReportSummary }) {
  const c = summary.classification;
  const rows: [string, ReactNode][] = [
    ["Product", summary.title ?? "Unknown"],
    ["Quantity", summary.quantity],
    ["Purpose", summary.purpose === "resale" ? "Resale" : "Personal use"],
    [
      "Classification",
      <>
        {c.value ?? "Unknown"} ({humanize(c.status)})
        {c.candidates.length > 1 && (
          <ul className="mt-1 text-xs text-slate-600">
            {c.candidates.map((x) => (
              <li key={x.label}>
                {x.label}: {Math.round(x.confidence * 100)}% confidence
              </li>
            ))}
          </ul>
        )}
      </>,
    ],
    ["BIS applicability", humanize(summary.bis)],
    ["Wireless approval", humanize(summary.wireless)],
    ["Seller claims BIS", summary.sellerClaimsBis === null ? "Unknown" : summary.sellerClaimsBis ? "Yes (unverified claim)" : "No"],
    ["Model / manufacturer match", humanize(summary.identityMatch)],
    [
      "Illustrative cost per unit",
      summary.illustrativeCostPerUnit
        ? `${formatINR(summary.illustrativeCostPerUnit.expected)} (estimate, not a quote)`
        : "Unknown",
    ],
  ];
  return (
    <section className="card" aria-labelledby="summary-title">
      <h2 id="summary-title" className="mb-3 text-lg font-semibold">
        Order summary
      </h2>
      <table className="w-full text-sm">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k} className="border-t border-slate-100 align-top first:border-t-0">
              <th scope="row" className="w-2/5 py-2 pr-3 text-left font-medium text-slate-600">
                {k}
              </th>
              <td className="py-2">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
