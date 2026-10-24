import { Link } from "react-router-dom";
import { Trash2 } from "lucide-react";
import { useDelete, useHistory } from "../api/hooks";
import { toApiError } from "../api/errors";
import { formatDateTime, hostOf, humanize } from "../lib/format";
import { EmptyState, ErrorState, Loading } from "../components/StateViews";

export default function HistoryPage() {
  const q = useHistory();
  const del = useDelete();

  if (q.isError) {
    const err = toApiError(q.error);
    return <ErrorState message={err.message} errorId={err.errorId} onRetry={() => q.refetch()} />;
  }
  if (!q.data) return <Loading label="Loading history…" />;

  return (
    <div className="mx-auto max-w-3xl space-y-3">
      <h1 className="text-2xl font-bold text-navy">History</h1>
      {q.data.length === 0 ? (
        <EmptyState title="No investigations yet" message="Your past investigations will appear here.">
          <Link to="/" className="btn-primary">
            Start one
          </Link>
        </EmptyState>
      ) : (
        <ul className="space-y-2">
          {q.data.map((it) => (
            <li key={it.id} className="card flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate font-medium">{it.title ?? hostOf(it.url)}</p>
                <p className="text-xs text-slate-600">
                  {formatDateTime(it.createdAt)} ·{" "}
                  {it.outcome ? `${humanize(it.outcome)} · ${humanize(it.riskLevel ?? "unknown")}` : humanize(it.status)}
                </p>
              </div>
              <div className="flex gap-2">
                <Link
                  to={it.status === "REPORT_READY" ? `/investigations/${it.id}/report` : `/investigations/${it.id}`}
                  className="btn-secondary"
                >
                  Open
                </Link>
                <button
                  type="button"
                  className="btn-secondary text-red-800"
                  disabled={del.isPending}
                  onClick={() => window.confirm("Delete this investigation?") && del.mutate(it.id)}
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                  <span className="sr-only">Delete</span>
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {del.isError && <ErrorState message={toApiError(del.error).message} errorId={toApiError(del.error).errorId} />}
    </div>
  );
}
