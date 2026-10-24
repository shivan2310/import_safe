import { useState } from "react";
import { Check, Copy } from "lucide-react";

export default function ActionChecklist({
  actions,
  sellerRequest,
}: {
  actions: { priority: number; text: string }[];
  sellerRequest: string;
}) {
  const [done, setDone] = useState<Set<number>>(new Set());
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");

  const toggle = (p: number) =>
    setDone((prev) => {
      const next = new Set(prev);
      next.has(p) ? next.delete(p) : next.add(p);
      return next;
    });

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sellerRequest);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  };

  return (
    <section className="card" aria-labelledby="next-title">
      <h2 id="next-title" className="mb-3 text-lg font-semibold">
        What to do next
      </h2>
      <ol className="space-y-2">
        {[...actions].sort((a, b) => a.priority - b.priority).map((a) => (
          <li key={a.priority}>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={done.has(a.priority)}
                onChange={() => toggle(a.priority)}
              />
              <span className={done.has(a.priority) ? "text-slate-500 line-through" : ""}>{a.text}</span>
            </label>
          </li>
        ))}
      </ol>
      <div className="no-print mt-4 flex flex-wrap items-center gap-3">
        <button type="button" className="btn-primary" onClick={copy}>
          {copyState === "copied" ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
          Copy seller request
        </button>
        <span role="status" className="text-sm text-slate-600">
          {copyState === "copied" && "Copied to clipboard."}
          {copyState === "failed" && "Could not copy. Select the text below and copy it manually."}
        </span>
      </div>
      <details className="mt-3">
        <summary className="cursor-pointer text-sm font-medium text-slate-700">Preview seller request</summary>
        <pre className="mt-2 whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-sm">{sellerRequest}</pre>
      </details>
    </section>
  );
}
