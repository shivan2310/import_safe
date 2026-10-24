import { FormEvent, useState } from "react";
import { Plus, X } from "lucide-react";
import type { CreateInvestigationRequest } from "../types";
import { isValidHttpUrl } from "../lib/format";
import { ErrorState } from "./StateViews";
import type { ApiError } from "../api/errors";

export const DEMO_URL = "https://www.alibaba.com/product-detail/demo-bluetooth-speaker";

interface FormState {
  url: string;
  quantity: string;
  state: string;
  city: string;
  purpose: "" | "personal_use" | "resale";
  variant: string;
  shippingAmount: string;
  shippingCurrency: string;
  shippingMode: "" | "air" | "sea";
  certInput: string;
  certs: string[];
}

const EMPTY: FormState = {
  url: "", quantity: "", state: "", city: "", purpose: "", variant: "",
  shippingAmount: "", shippingCurrency: "INR", shippingMode: "", certInput: "", certs: [],
};

const DEMO: FormState = {
  ...EMPTY, url: DEMO_URL, quantity: "100", state: "Delhi", city: "New Delhi", purpose: "resale",
};

export default function InvestigationForm({
  onSubmit,
  submitting,
  error,
}: {
  onSubmit: (req: CreateInvestigationRequest) => void;
  submitting: boolean;
  error: ApiError | null;
}) {
  const [f, setF] = useState<FormState>(EMPTY);
  const [touched, setTouched] = useState<Set<string>>(new Set());

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));
  const touch = (k: string) => setTouched((p) => new Set(p).add(k));

  const qty = Number(f.quantity);
  const errors: Record<string, string | null> = {
    url: isValidHttpUrl(f.url) ? null : "Enter a full http(s) product link.",
    quantity: f.quantity !== "" && Number.isInteger(qty) && qty >= 1 ? null : "Enter a whole number, 1 or more.",
    state: f.state.trim() ? null : "Destination state is required.",
    purpose: f.purpose ? null : "Choose personal use or resale.",
    shipping:
      f.shippingAmount === "" || (Number.isFinite(Number(f.shippingAmount)) && Number(f.shippingAmount) >= 0)
        ? null
        : "Enter a valid amount.",
  };
  const valid = Object.values(errors).every((e) => e === null);
  const showErr = (k: string) => (touched.has(k) ? errors[k] : null);

  const addCert = () => {
    const c = f.certInput.trim();
    if (c && !f.certs.includes(c)) setF((p) => ({ ...p, certs: [...p.certs, c], certInput: "" }));
    else set("certInput", "");
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid || !f.purpose) return;
    const certs = f.certInput.trim() && !f.certs.includes(f.certInput.trim())
      ? [...f.certs, f.certInput.trim()]
      : f.certs;
    onSubmit({
      url: f.url.trim(),
      quantity: qty,
      destination: { state: f.state.trim(), city: f.city.trim() || null },
      purpose: f.purpose,
      variant: f.variant.trim() || null,
      shipping:
        f.shippingAmount === ""
          ? null
          : { amount: Number(f.shippingAmount), currency: f.shippingCurrency, mode: f.shippingMode || null },
      sellerCertificates: certs,
    });
  };

  const Err = ({ k }: { k: string }) =>
    showErr(k) ? (
      <p id={`${k}-err`} className="mt-1 text-xs text-red-700">
        {showErr(k)}
      </p>
    ) : null;

  return (
    <form onSubmit={submit} noValidate className="card space-y-4" aria-label="New investigation">
      <div>
        <label htmlFor="url" className="label">
          Product URL <span aria-hidden="true">*</span>
        </label>
        <input
          id="url" type="url" className="input" required aria-required="true"
          placeholder="https://www.alibaba.com/product-detail/…"
          value={f.url} onChange={(e) => set("url", e.target.value)} onBlur={() => touch("url")}
          aria-invalid={!!showErr("url")} aria-describedby={showErr("url") ? "url-err" : undefined}
        />
        <Err k="url" />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <label htmlFor="quantity" className="label">
            Quantity <span aria-hidden="true">*</span>
          </label>
          <input
            id="quantity" type="number" min={1} step={1} className="input" required aria-required="true"
            value={f.quantity} onChange={(e) => set("quantity", e.target.value)} onBlur={() => touch("quantity")}
            aria-invalid={!!showErr("quantity")} aria-describedby={showErr("quantity") ? "quantity-err" : undefined}
          />
          <Err k="quantity" />
        </div>
        <div>
          <label htmlFor="state" className="label">
            Destination state <span aria-hidden="true">*</span>
          </label>
          <input
            id="state" className="input" required aria-required="true" placeholder="Delhi"
            value={f.state} onChange={(e) => set("state", e.target.value)} onBlur={() => touch("state")}
            aria-invalid={!!showErr("state")} aria-describedby={showErr("state") ? "state-err" : undefined}
          />
          <Err k="state" />
        </div>
        <div>
          <label htmlFor="city" className="label">City</label>
          <input
            id="city" className="input" placeholder="New Delhi"
            value={f.city} onChange={(e) => set("city", e.target.value)}
          />
        </div>
      </div>

      <fieldset>
        <legend className="label">
          Purpose <span aria-hidden="true">*</span>
        </legend>
        <div className="flex gap-4">
          {([["personal_use", "Personal use"], ["resale", "Resale"]] as const).map(([v, l]) => (
            <label key={v} className="flex items-center gap-2 text-sm">
              <input
                type="radio" name="purpose" value={v} checked={f.purpose === v}
                onChange={() => { set("purpose", v); touch("purpose"); }}
              />
              {l}
            </label>
          ))}
        </div>
        <Err k="purpose" />
      </fieldset>

      <div>
        <label htmlFor="variant" className="label">Variant (optional)</label>
        <input
          id="variant" className="input" placeholder="Black, 20W"
          value={f.variant} onChange={(e) => set("variant", e.target.value)}
        />
      </div>

      <fieldset>
        <legend className="label">Shipping cost, if known (optional)</legend>
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label htmlFor="shipAmount" className="sr-only">Shipping amount</label>
            <input
              id="shipAmount" type="number" min={0} className="input" placeholder="Amount"
              value={f.shippingAmount} onChange={(e) => set("shippingAmount", e.target.value)}
              onBlur={() => touch("shipping")}
            />
          </div>
          <div>
            <label htmlFor="shipCurrency" className="sr-only">Currency</label>
            <select
              id="shipCurrency" className="input" value={f.shippingCurrency}
              onChange={(e) => set("shippingCurrency", e.target.value)}
            >
              <option>INR</option>
              <option>USD</option>
              <option>CNY</option>
            </select>
          </div>
          <div>
            <label htmlFor="shipMode" className="sr-only">Shipping mode</label>
            <select
              id="shipMode" className="input" value={f.shippingMode}
              onChange={(e) => set("shippingMode", e.target.value as FormState["shippingMode"])}
            >
              <option value="">Mode (optional)</option>
              <option value="air">Air</option>
              <option value="sea">Sea</option>
            </select>
          </div>
        </div>
        <Err k="shipping" />
      </fieldset>

      <div>
        <label htmlFor="cert" className="label">Seller certificate numbers (optional)</label>
        <div className="flex gap-2">
          <input
            id="cert" className="input" placeholder="Registration / licence number"
            value={f.certInput} onChange={(e) => set("certInput", e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCert(); } }}
          />
          <button type="button" className="btn-secondary" onClick={addCert}>
            <Plus className="h-4 w-4" aria-hidden="true" /> Add
          </button>
        </div>
        {f.certs.length > 0 && (
          <ul className="mt-2 flex flex-wrap gap-2" aria-label="Certificate numbers added">
            {f.certs.map((c) => (
              <li key={c} className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium">
                {c}
                <button
                  type="button" aria-label={`Remove ${c}`}
                  onClick={() => set("certs", f.certs.filter((x) => x !== c))}
                >
                  <X className="h-3 w-3" aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {error && <ErrorState title="Could not start the investigation" message={error.message} errorId={error.errorId} />}

      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" className="btn-primary" disabled={!valid || submitting}>
          {submitting ? "Starting…" : "Investigate"}
        </button>
        <button type="button" className="btn-secondary" onClick={() => { setF(DEMO); setTouched(new Set()); }}>
          Try demo: 100 Bluetooth speakers
        </button>
      </div>
    </form>
  );
}
