import { useCallback, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Printer, Trash2 } from "lucide-react";
import { useDelete, usePatchAssumptions, useReport } from "../api/hooks";
import { toApiError } from "../api/errors";
import { formatDateTime } from "../lib/format";
import OutcomeBanner from "../components/OutcomeBanner";
import OrderSummaryTable from "../components/OrderSummaryTable";
import ProductProfile from "../components/ProductProfile";
import RequirementCheckCard from "../components/RequirementCheckCard";
import CertificationComparison from "../components/CertificationComparison";
import CostBreakdown from "../components/CostBreakdown";
import ActionChecklist from "../components/ActionChecklist";
import EvidenceDrawer from "../components/EvidenceDrawer";
import { EvidenceContext } from "../components/EvidenceContext";
import { DemoBanner, ErrorState, Loading } from "../components/StateViews";

export default function ReportPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const q = useReport(id);
  const patch = usePatchAssumptions(id);
  const del = useDelete();
  const [drawer, setDrawer] = useState<{ open: boolean; id: string | null }>({ open: false, id: null });

  const evidence = q.data?.evidence;
  const ctx = useMemo(
    () => ({
      open: (evId: string) => setDrawer({ open: true, id: evId }),
      label: (evId: string) => {
        const i = evidence?.findIndex((e) => e.id === evId) ?? -1;
        return i >= 0 ? `E${i + 1}` : evId;
      },
    }),
    [evidence]
  );
  const closeDrawer = useCallback(() => setDrawer((d) => ({ ...d, open: false })), []);

  if (q.isError) {
    const err = toApiError(q.error);
    return (
      <ErrorState
        title={err.status === 409 ? "The report is not ready yet" : "Could not load the report"}
        message={err.message}
        errorId={err.errorId}
        onRetry={() => q.refetch()}
      >
        <Link to={`/investigations/${id}`} className="btn-secondary">
          Back to progress
        </Link>
      </ErrorState>
    );
  }
  if (!q.data) return <Loading label="Loading report…" />;
  const r = q.data;

  const onDelete = () => {
    if (window.confirm("Delete this investigation and all its evidence? This cannot be undone.")) {
      del.mutate(id, { onSuccess: () => nav("/history") });
    }
  };

  return (
    <EvidenceContext.Provider value={ctx}>
      <div className="space-y-4">
        {r.dataMode === "demo" && (
          <DemoBanner>
            Demo data: this report was built from labelled demo fixtures, not live retrieval. Rules,
            rates and records shown are placeholders.
          </DemoBanner>
        )}

        <OutcomeBanner outcome={r.outcome} riskLevel={r.riskLevel} nextAction={r.nextAction} reasons={r.reasons} />
        <OrderSummaryTable summary={r.summary} />
        <ProductProfile profile={r.profile} />

        <section aria-labelledby="checks-title" className="space-y-2">
          <h2 id="checks-title" className="text-lg font-semibold">
            Requirement checks
          </h2>
          {r.checks.map((c) => (
            <RequirementCheckCard key={c.id} check={c} />
          ))}
        </section>

        {r.certificationComparison && <CertificationComparison cmp={r.certificationComparison} />}

        <CostBreakdown
          cost={r.cost}
          busy={patch.isPending}
          error={patch.isError ? toApiError(patch.error).message : null}
          onApply={(overrides) => patch.mutate(overrides)}
        />

        <ActionChecklist actions={r.nextActions} sellerRequest={r.sellerRequest} />

        <div className="no-print">
          <button type="button" className="btn-secondary" onClick={() => setDrawer({ open: true, id: null })}>
            View all evidence ({r.evidence.length})
          </button>
        </div>

        <footer className="card text-sm text-slate-600">
          <p className="font-medium text-slate-800">{r.disclaimer}</p>
          <p className="mt-1">Report generated {formatDateTime(r.generatedAt)}.</p>
          {del.isError && <p role="alert" className="mt-1 text-red-700">{toApiError(del.error).message}</p>}
          <div className="no-print mt-3 flex flex-wrap gap-2">
            <button type="button" className="btn-secondary" onClick={() => window.print()}>
              <Printer className="h-4 w-4" aria-hidden="true" /> Export (print view)
            </button>
            <button type="button" className="btn-secondary text-red-800" onClick={onDelete} disabled={del.isPending}>
              <Trash2 className="h-4 w-4" aria-hidden="true" /> Delete investigation
            </button>
          </div>
        </footer>
      </div>

      <EvidenceDrawer evidence={r.evidence} open={drawer.open} selectedId={drawer.id} onClose={closeDrawer} />
    </EvidenceContext.Provider>
  );
}
