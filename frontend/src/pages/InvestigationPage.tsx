import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Clock } from "lucide-react";
import { useAnswer, useCancel, useInvestigation } from "../api/hooks";
import ProgressStepper from "../components/ProgressStepper";
import FollowUpCard from "../components/FollowUpCard";
import { EmptyState, ErrorState, Loading } from "../components/StateViews";
import { formatElapsed, hostOf } from "../lib/format";
import { toApiError } from "../api/errors";

function useElapsed(startIso: string | undefined, stopped: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (stopped) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [stopped]);
  if (!startIso) return 0;
  return Math.max(0, Math.floor((now - new Date(startIso).getTime()) / 1000));
}

export default function InvestigationPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const q = useInvestigation(id);
  const answer = useAnswer(id);
  const cancel = useCancel(id);
  const inv = q.data;

  const finished = !!inv && ["REPORT_READY", "FAILED", "CANCELLED", "EXPIRED", "DELETED"].includes(inv.status);
  const elapsed = useElapsed(inv?.createdAt, finished);

  useEffect(() => {
    if (inv?.status === "REPORT_READY") nav(`/investigations/${id}/report`, { replace: true });
  }, [inv?.status, id, nav]);

  if (q.isError) {
    const err = toApiError(q.error);
    return (
      <ErrorState
        title={err.status === 404 ? "Investigation not found" : "Could not load this investigation"}
        message={err.message}
        errorId={err.errorId}
        onRetry={() => q.refetch()}
      >
        <Link to="/" className="btn-secondary">
          Start a new investigation
        </Link>
      </ErrorState>
    );
  }
  if (!inv) return <Loading label="Loading investigation…" />;

  if (inv.status === "FAILED") {
    return (
      <ErrorState
        title="We could not complete this investigation"
        message={inv.error?.message ?? "We could not read this page."}
        errorId={inv.error?.errorId}
      >
        <Link to="/" className="btn-secondary">
          Start over
        </Link>
      </ErrorState>
    );
  }
  if (inv.status === "CANCELLED" || inv.status === "EXPIRED" || inv.status === "DELETED") {
    return (
      <EmptyState
        title={inv.status === "CANCELLED" ? "Investigation cancelled" : "Investigation no longer available"}
        message="No report was produced."
      >
        <Link to="/" className="btn-primary">
          New investigation
        </Link>
      </EmptyState>
    );
  }

  const active = !finished;
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold text-navy">Investigating</h1>
          <p className="break-all text-sm text-slate-600">{hostOf(inv.url)}</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1 text-sm tabular-nums text-slate-600">
            <Clock className="h-4 w-4" aria-hidden="true" />
            <span className="sr-only">Elapsed time</span>
            {formatElapsed(elapsed)}
          </span>
          {active && (
            <button type="button" className="btn-secondary" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
              Cancel
            </button>
          )}
        </div>
      </div>

      <div className="card">
        <ProgressStepper stages={inv.stages} />
        <p role="status" aria-live="polite" className="mt-4 text-sm text-slate-600">
          {inv.activity}
        </p>
      </div>

      {inv.pendingQuestion && (
        <FollowUpCard
          question={inv.pendingQuestion}
          busy={answer.isPending}
          onSubmit={(value) => answer.mutate({ questionId: inv.pendingQuestion!.id, value })}
          onSkip={() => answer.mutate({ questionId: inv.pendingQuestion!.id, skipped: true })}
        />
      )}
      {answer.isError && (
        <ErrorState message={toApiError(answer.error).message} errorId={toApiError(answer.error).errorId} />
      )}
    </div>
  );
}
