import { AlertTriangle, CheckCircle2, HelpCircle, MinusCircle, XOctagon } from "lucide-react";
import type { CheckStatus } from "../types";

const CONFIG: Record<CheckStatus, { label: string; Icon: typeof AlertTriangle; cls: string }> = {
  potentially_applicable: {
    label: "Potentially applicable",
    Icon: AlertTriangle,
    cls: "bg-amber-100 text-amber-900 border border-amber-300",
  },
  verified: {
    label: "Verified",
    Icon: CheckCircle2,
    cls: "bg-green-100 text-green-900 border border-green-300",
  },
  not_applicable: {
    label: "Not applicable",
    Icon: MinusCircle,
    cls: "bg-slate-100 text-slate-700 border border-slate-300",
  },
  unverified: {
    label: "Unverified",
    Icon: HelpCircle,
    cls: "bg-white text-amber-900 border-2 border-amber-500",
  },
  contradiction_detected: {
    label: "Contradiction detected",
    Icon: XOctagon,
    cls: "bg-red-100 text-red-900 border border-red-300",
  },
};

export default function StatusBadge({ status }: { status: CheckStatus }) {
  const c = CONFIG[status];
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${c.cls}`}
    >
      <c.Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {c.label}
    </span>
  );
}
