import { FormEvent, useEffect, useState } from "react";
import type { Cost } from "../types";
import { formatINR, humanize } from "../lib/format";

const SWATCH = ["bg-navy", "bg-blue-700", "bg-sky-600", "bg-slate-400", "bg-teal-600", "bg-amber-500", "bg-orange-600", "bg-slate-600"];

export default function CostBreakdown({
  cost,
  busy,
  error,
  onApply,
}: {
  cost: Cost;
  busy: boolean;
  error: string | null;
  onApply: (overrides: Record<string, number>) => void;
}) {
  const initial = () => Object.fromEntries(cost.assumptions.map((a) => [a.key, String(a.value)]));
  const [draft, setDraft] = useState<Record<string, string>>(initial);
  // Reset the editors whenever the backend returns new numbers.
  useEffect(() => setDraft(initial()), [cost]); // eslint-disable-line react-hooks/exhaustive-deps

  const changed = cost.assumptions.filter((a) => draft[a.key] !== String(a.value));
  const invalid = changed.some((a) => draft[a.key].trim() === "" || !(Number(draft[a.key]) >= 0));

  const apply = (e: FormEvent) => {
    e.preventDefault();
    if (changed.length === 0 || invalid) return;
    onApply(Object.fromEntries(changed.map((a) => [a.key, Number(draft[a.key])])));
  };

  const counted = cost.breakdown.filter((l) => l.countsTowardTotal);
  const total = counted.reduce((s, l) => s + l.amount, 0) || 1;

  return (
    <section className="card" aria-labelledby="cost-title">
      <h2 id="cost-title" className="text-lg font-semibold">
        Landed cost
      </h2>
      <p className="text-sm font-medium text-amber-800">{cost.label}</p>

      <dl className="mt-3 grid grid-cols-3 gap-3 text-center">
        {([["Low", cost.low], ["Expected", cost.expected], ["High", cost.high]] as const).map(([k, v]) => (
          <div key={k} className={`rounded-md border p-3 ${k === "Expected" ? "border-navy bg-navy-50" : "border-slate-200"}`}>
            <dt className="text-xs uppercase tracking-wide text-slate-600">{k}</dt>
            <dd className="text-lg font-bold">{formatINR(v)}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-sm">
        Expected per unit: <span className="font-semibold">{formatINR(cost.perUnitExpected)}</span>
      </p>

      <div className="mt-3 flex h-3 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
        {counted.map((l) => {
          const i = cost.breakdown.indexOf(l);
          return <div key={l.key} className={SWATCH[i % SWATCH.length]} style={{ width: `${(l.amount / total) * 100}%` }} />;
        })}
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-sm">
          <caption className="sr-only">Cost breakdown</caption>
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="py-2 pr-3">Component</th>
              <th className="py-2 pr-3">Base · rate</th>
              <th className="py-2 pr-3">Status</th>
              <th className="py-2 text-right">Amount</th>
            </tr>
          </thead>
          <tbody>
            {cost.breakdown.map((l, i) => (
              <tr key={l.key} className="border-t border-slate-100 align-top">
                <td className="py-2 pr-3">
                  <span className="flex items-center gap-2">
                    <span className={`h-2.5 w-2.5 rounded-sm ${SWATCH[i % SWATCH.length]}`} aria-hidden="true" />
                    {l.label}
                  </span>
                  <span className="block text-xs text-slate-500">{l.formula}</span>
                </td>
                <td className="py-2 pr-3 text-slate-700">
                  {l.base}
                  {l.rate ? ` · ${l.rate}` : ""}
                </td>
                <td className="py-2 pr-3">
                  <span className="text-xs font-semibold text-slate-700">{humanize(l.status)}</span>
                  {!l.countsTowardTotal && <span className="block text-xs text-slate-500">Not added to total</span>}
                </td>
                <td className="py-2 text-right tabular-nums">{formatINR(l.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <form onSubmit={apply} className="no-print mt-5 border-t border-slate-200 pt-4">
        <h3 className="font-semibold">Assumptions</h3>
        <p className="text-xs text-slate-600">Edit any value and recalculate. All values here are labelled assumptions unless you supplied them.</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {cost.assumptions.map((a) => (
            <div key={a.key}>
              <label htmlFor={`as-${a.key}`} className="label">
                {a.label} <span className="font-normal text-slate-500">({a.unit})</span>
              </label>
              <input
                id={`as-${a.key}`}
                type="number"
                min={0}
                step="any"
                className="input"
                disabled={!a.editable || busy}
                value={draft[a.key] ?? ""}
                onChange={(e) => setDraft((p) => ({ ...p, [a.key]: e.target.value }))}
              />
              <p className="mt-0.5 text-xs text-slate-500">
                {humanize(a.status)} · {a.source}
              </p>
            </div>
          ))}
        </div>
        {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
        <button type="submit" className="btn-primary mt-3" disabled={busy || changed.length === 0 || invalid}>
          {busy ? "Recalculating…" : "Recalculate"}
        </button>
      </form>
    </section>
  );
}
