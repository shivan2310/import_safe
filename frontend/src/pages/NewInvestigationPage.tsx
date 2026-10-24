import { useNavigate } from "react-router-dom";
import InvestigationForm from "../components/InvestigationForm";
import { useCreateInvestigation } from "../api/hooks";
import { toApiError } from "../api/errors";

export default function NewInvestigationPage() {
  const nav = useNavigate();
  const create = useCreateInvestigation();

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-3xl font-bold text-navy">Can I import this?</h1>
      <p className="mb-5 mt-1 text-slate-600">Paste a product link. We investigate before you order.</p>
      <InvestigationForm
        submitting={create.isPending}
        error={create.error ? toApiError(create.error) : null}
        onSubmit={(req) => create.mutate(req, { onSuccess: ({ id }) => nav(`/investigations/${id}`) })}
      />
      <p className="mt-4 text-xs text-slate-500">
        ImportSafe is decision support. It is not legal clearance, customs approval or a duty quote.
      </p>
    </div>
  );
}
