import type { ReactNode } from "react";
import { AlertCircle, Inbox, Info, RotateCw } from "lucide-react";

export function ErrorState({
  title = "Something went wrong",
  message,
  errorId,
  onRetry,
  children,
}: {
  title?: string;
  message: string;
  errorId?: string;
  onRetry?: () => void;
  children?: ReactNode;
}) {
  return (
    <div role="alert" className="card border-l-4 border-l-red-600">
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-700" aria-hidden="true" />
        <div className="min-w-0">
          <h2 className="font-semibold text-slate-900">{title}</h2>
          <p className="mt-1 text-sm text-slate-700">{message}</p>
          {errorId && <p className="mt-1 text-xs text-slate-500">Error ID: {errorId}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            {onRetry && (
              <button type="button" className="btn-secondary" onClick={onRetry}>
                <RotateCw className="h-4 w-4" aria-hidden="true" /> Retry
              </button>
            )}
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  message,
  children,
}: {
  title: string;
  message?: string;
  children?: ReactNode;
}) {
  return (
    <div className="card text-center">
      <Inbox className="mx-auto h-8 w-8 text-slate-400" aria-hidden="true" />
      <h2 className="mt-2 font-semibold">{title}</h2>
      {message && <p className="mt-1 text-sm text-slate-600">{message}</p>}
      {children && <div className="mt-4 flex justify-center gap-2">{children}</div>}
    </div>
  );
}

export function DemoBanner({ children }: { children: ReactNode }) {
  return (
    <div
      role="note"
      className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
    >
      <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p role="status" className="py-10 text-center text-sm text-slate-600">
      {label}
    </p>
  );
}
