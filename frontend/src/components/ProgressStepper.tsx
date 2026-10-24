import { CheckCircle2, Circle, HelpCircle, Loader2, XCircle } from "lucide-react";
import type { Stage, StageState } from "../types";

const ICON: Record<StageState, { Icon: typeof Circle; cls: string }> = {
  pending: { Icon: Circle, cls: "text-slate-400" },
  running: { Icon: Loader2, cls: "text-navy motion-safe:animate-spin" },
  done: { Icon: CheckCircle2, cls: "text-green-700" },
  needs_input: { Icon: HelpCircle, cls: "text-amber-600" },
  failed: { Icon: XCircle, cls: "text-red-700" },
};

const TEXT: Record<StageState, string> = {
  pending: "Pending",
  running: "Running",
  done: "Done",
  needs_input: "Needs input",
  failed: "Failed",
};

export default function ProgressStepper({ stages }: { stages: Stage[] }) {
  return (
    <ol className="space-y-3" aria-label="Investigation progress">
      {stages.map((s, i) => {
        const { Icon, cls } = ICON[s.state];
        return (
          <li
            key={s.key}
            className="flex gap-3"
            aria-current={s.state === "running" ? "step" : undefined}
          >
            <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${cls}`} aria-hidden="true" />
            <div>
              <p className="font-medium">
                {i + 1}. {s.label}
                <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs font-semibold text-slate-700">
                  {TEXT[s.state]}
                </span>
              </p>
              {s.message && <p className="text-sm text-slate-600">{s.message}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
