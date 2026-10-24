import { AlertOctagon, AlertTriangle, CheckCircle2, HelpCircle } from "lucide-react";
import type { Outcome, RiskLevel } from "../types";

const OUTCOME: Record<Outcome, { label: string; Icon: typeof CheckCircle2 }> = {
  LIKELY_IMPORTABLE: { label: "Likely Importable", Icon: CheckCircle2 },
  CONDITIONAL_IMPORT: { label: "Conditional Import", Icon: AlertTriangle },
  HIGH_RISK_DO_NOT_PROCEED: { label: "High Risk – Do Not Proceed", Icon: AlertOctagon },
  INSUFFICIENT_INFORMATION: { label: "Insufficient Information", Icon: HelpCircle },
};

const RISK: Record<RiskLevel, { label: string; bar: string; chip: string }> = {
  LOW: { label: "Low risk", bar: "border-l-green-600", chip: "bg-green-100 text-green-900 border-green-300" },
  MEDIUM: { label: "Medium risk", bar: "border-l-amber-500", chip: "bg-amber-100 text-amber-900 border-amber-300" },
  HIGH: { label: "High risk", bar: "border-l-red-600", chip: "bg-red-100 text-red-900 border-red-300" },
  INSUFFICIENT_EVIDENCE: {
    label: "Insufficient evidence",
    bar: "border-l-slate-400",
    chip: "bg-slate-100 text-slate-800 border-slate-300",
  },
};

export default function OutcomeBanner({
  outcome,
  riskLevel,
  nextAction,
  reasons,
}: {
  outcome: Outcome;
  riskLevel: RiskLevel;
  nextAction: string;
  reasons: { text: string }[];
}) {
  const o = OUTCOME[outcome];
  const r = RISK[riskLevel];
  return (
    <section className={`card border-l-8 ${r.bar}`} aria-labelledby="outcome-title">
      <div className="flex flex-wrap items-center gap-3">
        <o.Icon className="h-7 w-7 text-navy" aria-hidden="true" />
        <h1 id="outcome-title" className="text-2xl font-bold text-navy">
          {o.label}
        </h1>
        <span className={`rounded-full border px-3 py-0.5 text-sm font-semibold ${r.chip}`}>
          Overall: {r.label}
        </span>
      </div>
      <p className="mt-3 text-base">
        <span className="font-semibold">Next action:</span> {nextAction}
      </p>
      {reasons.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-700">
          {reasons.map((x) => (
            <li key={x.text}>{x.text}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
