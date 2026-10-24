import { FormEvent, useEffect, useState } from "react";
import { MessageCircleQuestion } from "lucide-react";
import type { Question } from "../types";

export default function FollowUpCard({
  question,
  busy,
  onSubmit,
  onSkip,
}: {
  question: Question;
  busy: boolean;
  onSubmit: (value: string) => void;
  onSkip: () => void;
}) {
  const [value, setValue] = useState("");
  useEffect(() => setValue(""), [question.id]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (value.trim()) onSubmit(value.trim());
  };

  return (
    <form onSubmit={submit} className="card border-l-4 border-l-amber-500" aria-labelledby="followup-title">
      <div className="flex items-start gap-3">
        <MessageCircleQuestion className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" aria-hidden="true" />
        <div className="w-full">
          <h2 id="followup-title" className="font-semibold">
            {question.prompt}
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            <span className="font-medium">Why it matters:</span> {question.whyItMatters}
          </p>
          <label htmlFor="followup-input" className="sr-only">
            Your answer
          </label>
          {question.inputType === "select" ? (
            <select
              id="followup-input"
              className="input mt-3"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            >
              <option value="">Select…</option>
              {question.options?.map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
          ) : (
            <input
              id="followup-input"
              className="input mt-3"
              type={question.inputType === "number" ? "number" : "text"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoFocus
            />
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="submit" className="btn-primary" disabled={busy || !value.trim()}>
              Submit answer
            </button>
            <button type="button" className="btn-secondary" disabled={busy} onClick={onSkip}>
              Skip
            </button>
            <span className="text-xs text-slate-500">
              Skipping marks the related check as Unverified.
            </span>
          </div>
        </div>
      </div>
    </form>
  );
}
