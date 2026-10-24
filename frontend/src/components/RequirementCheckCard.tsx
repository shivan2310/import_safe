import { ChevronDown } from "lucide-react";
import type { Check } from "../types";
import { formatDateTime } from "../lib/format";
import StatusBadge from "./StatusBadge";
import { EvidenceChips } from "./EvidenceContext";

const ACCENT: Record<Check["status"], string> = {
  potentially_applicable: "border-l-amber-500",
  verified: "border-l-green-600",
  not_applicable: "border-l-slate-400",
  unverified: "border-l-amber-400",
  contradiction_detected: "border-l-red-600",
};

export default function RequirementCheckCard({ check }: { check: Check }) {
  return (
    <details className={`group rounded-lg border border-l-4 border-slate-200 bg-white shadow-sm ${ACCENT[check.status]}`}>
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 p-4">
        <span className="font-medium">{check.title}</span>
        <span className="flex items-center gap-2">
          <StatusBadge status={check.status} />
          <ChevronDown className="h-4 w-4 transition group-open:rotate-180" aria-hidden="true" />
        </span>
      </summary>
      <div className="space-y-2 border-t border-slate-100 px-4 py-3 text-sm">
        <p>{check.reasoning}</p>
        <p className="text-xs text-slate-600">
          Rule version: {check.ruleVersion ?? "none"} · Last reviewed:{" "}
          {check.ruleReviewedAt ? formatDateTime(check.ruleReviewedAt) : "not reviewed"}
        </p>
        <p className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
          Evidence: <EvidenceChips ids={check.evidenceIds} />
        </p>
      </div>
    </details>
  );
}
