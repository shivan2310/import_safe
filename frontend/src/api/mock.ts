// In-browser stand-in for the investigation API (PRD B3). It plays the role of the BACKEND:
// all classification/check/cost/risk output below is hand-written DEMO FIXTURE data, labelled
// as such (dataMode: "demo"). None of it is a real rule, rate, registry record or source.
// Replace by setting VITE_USE_MOCK=false once the real endpoints exist.
import type { Api } from "./index";
import { ApiError } from "./errors";
import { hostOf } from "../lib/format";
import type {
  Check,
  CertificationComparison,
  CostAssumption,
  CostLine,
  CreateInvestigationRequest,
  Evidence,
  Investigation,
  InvestigationStatus,
  InvestigationSummary,
  Outcome,
  Report,
  RiskLevel,
  Stage,
} from "../types";

const STORAGE_KEY = "importsafe.mock.v1";
const STEP_MS = 1800;
const LATENCY_MS = 120;
const DEMO_REGISTRATION = "R-41234567";
const RULE_VERSION = "demo-fixture-0";

const STAGES = [
  { key: "read_listing", label: "Read listing" },
  { key: "identify_product", label: "Identify product" },
  { key: "find_requirements", label: "Find requirements" },
  { key: "check_claims", label: "Check evidence and claims" },
  { key: "estimate_cost", label: "Estimate landed cost" },
  { key: "risk_report", label: "Risk report" },
];

interface MockRecord {
  id: string;
  req: CreateInvestigationRequest;
  createdAt: number;
  updatedAt: number;
  completedAt: number | null;
  stageIndex: number; // 0..STAGES.length (== complete)
  lastTick: number;
  blocked: boolean;
  answered: boolean;
  model: string | null;
  cancelled: boolean;
  overrides: Record<string, number>;
}

// ---------- storage (localStorage with in-memory fallback) ----------

let memory: Record<string, MockRecord> = {};

function load(): Record<string, MockRecord> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    /* storage unavailable */
  }
  return memory;
}

function save(db: Record<string, MockRecord>) {
  memory = db;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(db));
  } catch {
    /* storage unavailable */
  }
}

const delay = () => new Promise((r) => setTimeout(r, LATENCY_MS));

function find(db: Record<string, MockRecord>, id: string): MockRecord {
  const rec = db[id];
  if (!rec) throw new ApiError("Investigation not found.", 404);
  return rec;
}

// ---------- progress simulation ----------

const isDemoUrl = (url: string) => /demo/i.test(url);
const needsModel = (rec: MockRecord) => !isDemoUrl(rec.req.url);

function advance(rec: MockRecord, now: number) {
  if (rec.cancelled) return;
  while (rec.stageIndex < STAGES.length && !rec.blocked && now - rec.lastTick >= STEP_MS) {
    if (rec.stageIndex === 1 && needsModel(rec) && !rec.answered) {
      rec.blocked = true;
      break;
    }
    rec.stageIndex += 1;
    rec.lastTick += STEP_MS;
  }
  if (rec.stageIndex >= STAGES.length && rec.completedAt === null) rec.completedAt = now;
  rec.updatedAt = now;
}

const ACTIVITY = [
  (h: string) => `Reading listing on ${h}…`,
  () => "Identifying the product…",
  () => "Finding applicable requirements…",
  () => "Checking evidence and claims…",
  () => "Estimating landed cost…",
  () => "Building the risk report…",
];

function statusOf(rec: MockRecord): InvestigationStatus {
  if (rec.cancelled) return "CANCELLED";
  if (rec.stageIndex >= STAGES.length) return "REPORT_READY";
  if (rec.blocked) return "NEEDS_INPUT";
  return (
    ["READING_LISTING", "PROFILE_BUILT", "CHECKING_REQUIREMENTS", "VERIFYING_CLAIMS", "ESTIMATING_COST", "ESTIMATING_COST"] as const
  )[rec.stageIndex];
}

function toInvestigation(rec: MockRecord): Investigation {
  const stages: Stage[] = STAGES.map((s, i) => {
    let state: Stage["state"] = "pending";
    let message: string | null = null;
    if (i < rec.stageIndex) state = "done";
    else if (i === rec.stageIndex && !rec.cancelled) {
      state = rec.blocked ? "needs_input" : "running";
      if (rec.blocked) message = "Waiting for one answer from you.";
    } else if (i === rec.stageIndex && rec.cancelled) {
      state = "failed";
      message = "Cancelled.";
    }
    return { key: s.key, label: s.label, state, message };
  });
  const status = statusOf(rec);
  return {
    id: rec.id,
    url: rec.req.url,
    status,
    stages,
    pendingQuestion: rec.blocked
      ? {
          id: "q_model",
          field: "model",
          prompt:
            "We could not find the model number on this listing. What model is printed on the listing or packaging?",
          whyItMatters:
            "Certificates and wireless approvals are issued per model, so we need it to check whether a certificate covers your product.",
          inputType: "text",
        }
      : null,
    activity:
      status === "REPORT_READY" || status === "CANCELLED"
        ? null
        : rec.blocked
          ? "Waiting for your answer…"
          : ACTIVITY[rec.stageIndex](hostOf(rec.req.url)),
    createdAt: new Date(rec.createdAt).toISOString(),
    updatedAt: new Date(rec.updatedAt).toISOString(),
    dataMode: "demo",
    error: null,
  };
}

// ---------- cost (demo placeholders; real engine is backend P4) ----------

const DEFAULTS: Omit<CostAssumption, "status" | "editable">[] = [
  { key: "unitPrice", label: "Unit price", unit: "USD", value: 8.15, source: "Midpoint of the demo listing's US$6.80–9.50 range" },
  { key: "fxRate", label: "USD to INR exchange rate", unit: "INR per USD", value: 83, source: "Demo placeholder, not a live rate" },
  { key: "freight", label: "Freight", unit: "INR total", value: 15000, source: "Demo placeholder, not a quote" },
  { key: "insurancePct", label: "Insurance", unit: "% of goods value", value: 1.125, source: "Demo placeholder, not an official rate" },
  { key: "landingPct", label: "Landing charges", unit: "% of CIF", value: 1, source: "Demo placeholder, not an official rate" },
  { key: "bcdPct", label: "Basic customs duty (BCD)", unit: "% of assessable value", value: 20, source: "Demo placeholder, not a tariff rate" },
  { key: "swsPct", label: "Social welfare surcharge (SWS)", unit: "% of BCD", value: 10, source: "Demo placeholder, not an official rate" },
  { key: "igstPct", label: "IGST", unit: "% of assessable value + BCD + SWS", value: 18, source: "Demo placeholder, not an official rate" },
  { key: "otherInr", label: "Clearing, port and transport charges", unit: "INR total", value: 8000, source: "Demo placeholder, not a quote" },
];

function assumptionsFor(rec: MockRecord): CostAssumption[] {
  return DEFAULTS.map((d) => {
    let { value, source } = d;
    let status: CostAssumption["status"] = "assumed";
    const ship = rec.req.shipping;
    if (d.key === "freight" && ship && ship.currency === "INR") {
      value = ship.amount;
      source = "Entered by you";
      status = "user_supplied";
    }
    const o = rec.overrides[d.key];
    if (o !== undefined) {
      value = o;
      source = "Edited by you";
      status = "user_supplied";
    }
    return { ...d, value, source, status, editable: true };
  });
}

function runCost(v: Record<string, number>, qty: number) {
  const goods = v.unitPrice * v.fxRate * qty;
  const insurance = (goods * v.insurancePct) / 100;
  const cif = goods + v.freight + insurance;
  const landing = (cif * v.landingPct) / 100;
  const assessable = cif + landing;
  const bcd = (assessable * v.bcdPct) / 100;
  const sws = (bcd * v.swsPct) / 100;
  const igst = ((assessable + bcd + sws) * v.igstPct) / 100;
  const total = goods + v.freight + insurance + bcd + sws + igst + v.otherInr;
  return { goods, insurance, cif, landing, assessable, bcd, sws, igst, total };
}

function buildCost(rec: MockRecord): Report["cost"] {
  const assumptions = assumptionsFor(rec);
  const v = Object.fromEntries(assumptions.map((a) => [a.key, a.value]));
  const st = (...keys: string[]): CostLine["status"] =>
    keys.every((k) => assumptions.find((a) => a.key === k)?.status === "user_supplied")
      ? "user_supplied"
      : "assumed";
  const qty = rec.req.quantity;
  const r = runCost(v, qty);
  const R = Math.round;
  const line = (
    key: string, label: string, base: string, rate: string | null, amount: number,
    formula: string, status: CostLine["status"], countsTowardTotal = true
  ): CostLine => ({
    key, label, base, rate, amount: R(amount), formula,
    source: "Demo placeholder assumptions (not official rates)", status, countsTowardTotal,
  });
  const breakdown: CostLine[] = [
    line("goods", "Goods value (FOB)", "Unit price × quantity × FX", null, r.goods,
      `${v.unitPrice} USD × ${qty} × ${v.fxRate}`, st("unitPrice", "fxRate")),
    line("freight", "Freight", "Total freight", null, v.freight, "As entered or assumed", st("freight")),
    line("insurance", "Insurance", "Goods value", `${v.insurancePct}%`, r.insurance,
      `goods × ${v.insurancePct}%`, st("insurancePct")),
    line("landing", "Landing charges (assessment only)", "CIF", `${v.landingPct}%`, r.landing,
      `CIF × ${v.landingPct}% — raises the assessable value; not added to the total again`,
      st("landingPct"), false),
    line("bcd", "Basic customs duty", "Assessable value", `${v.bcdPct}%`, r.bcd,
      `assessable × ${v.bcdPct}%`, st("bcdPct")),
    line("sws", "Social welfare surcharge", "BCD", `${v.swsPct}%`, r.sws,
      `BCD × ${v.swsPct}%`, st("swsPct")),
    line("igst", "IGST", "Assessable value + BCD + SWS", `${v.igstPct}%`, r.igst,
      `(assessable + BCD + SWS) × ${v.igstPct}%`, st("igstPct")),
    line("other", "Clearing, port and transport", "Total charges", null, v.otherInr,
      "As assumed or edited", st("otherInr")),
  ];
  const low = runCost({ ...v, fxRate: v.fxRate * 0.97, freight: v.freight * 0.8 }, qty).total;
  const high = runCost({ ...v, fxRate: v.fxRate * 1.03, freight: v.freight * 1.3 }, qty).total;
  return {
    currency: "INR",
    low: R(low),
    expected: R(r.total),
    high: R(high),
    perUnitExpected: R(r.total / qty),
    breakdown,
    assumptions,
    label: "Illustrative estimate, not a quote.",
  };
}

// ---------- report ----------

const CONTRADICTION_FIXTURE_NOTE =
  "Demo registration record fixture. It is not a real registry record.";

function buildComparison(rec: MockRecord, model: string | null): CertificationComparison | null {
  const claim = rec.req.sellerCertificates[0];
  if (!claim) return null;
  if (claim.trim().toUpperCase() === DEMO_REGISTRATION) {
    return {
      claimRegistrationNo: claim,
      recordRegistrationNo: DEMO_REGISTRATION,
      overall: "contradiction_detected",
      evidenceIds: ["ev_record"],
      note: CONTRADICTION_FIXTURE_NOTE,
      fieldResults: [
        { field: "Registration number", claim, record: DEMO_REGISTRATION, result: "match" },
        { field: "Manufacturer", claim: "Demo Audio Technology Co., Ltd.", record: "Example Acoustics Ltd.", result: "mismatch" },
        { field: "Model scope", claim: model ?? "Not provided", record: "BT-200", result: model ? "mismatch" : "unknown" },
        { field: "Validity", claim: "Not stated", record: "2023-01-01 to 2025-01-01 (expired)", result: "mismatch" },
        { field: "Brand", claim: null, record: null, result: "unknown" },
      ],
    };
  }
  return {
    claimRegistrationNo: claim,
    recordRegistrationNo: null,
    overall: "unverified",
    evidenceIds: [],
    note: "The registration record could not be retrieved in demo mode. Check the number manually on the relevant official registry.",
    fieldResults: ["Registration number", "Manufacturer", "Model scope", "Validity", "Brand"].map((field) => ({
      field,
      claim: field === "Registration number" ? claim : null,
      record: null,
      result: "unknown" as const,
    })),
  };
}

function buildReport(rec: MockRecord): Report {
  const iso = (offset: number) => new Date(rec.createdAt + offset).toISOString();
  const model = isDemoUrl(rec.req.url) ? "BT-100" : rec.model;
  const cmp = buildComparison(rec, model);
  const contradiction = cmp?.overall === "contradiction_detected";
  const title = "Portable Wireless Bluetooth Speaker (demo listing)";

  const evidence: Evidence[] = [
    {
      id: "ev_listing", label: "Product listing (demo fixture)", sourceUrl: rec.req.url,
      sourceType: "listing", retrievedAt: iso(2000), retrievalMode: "demo",
      excerpt: "Bluetooth 5.0 · Battery 1200mAh lithium polymer · MOQ 50 pieces · “BIS certified, CE, RoHS”",
    },
    {
      id: "ev_rules", label: "Rule fixtures (demo, not verified against official sources)", sourceUrl: null,
      sourceType: "rule_source", retrievedAt: iso(4000), retrievalMode: "demo",
      excerpt: "Fixture rules: bluetooth_speaker → BIS potentially applicable; wireless approval check required; labelling check required.",
    },
    {
      id: "ev_user", label: "Order details entered by you", sourceUrl: null,
      sourceType: "user_upload", retrievedAt: iso(0), retrievalMode: "demo",
      excerpt: `Quantity ${rec.req.quantity}; destination ${rec.req.destination.state}; purpose ${rec.req.purpose}.`,
    },
  ];
  if (contradiction) {
    evidence.push({
      id: "ev_record", label: "Registration record (demo fixture)", sourceUrl: null,
      sourceType: "official_portal", retrievedAt: iso(6000), retrievalMode: "demo",
      excerpt: "Registration R-41234567 · Example Acoustics Ltd. · Model scope BT-200 · Valid 2023-01-01 to 2025-01-01",
    });
  }

  const checks: Check[] = [
    { id: "chk_policy", area: "import_policy", title: "Import policy", status: "unverified",
      reasoning: "No import prohibition rule is loaded for this category in the demo fixtures. That is not confirmation that none applies.",
      ruleVersion: RULE_VERSION, ruleReviewedAt: null, evidenceIds: [] },
    { id: "chk_bis", area: "bis", title: "BIS registration",
      status: contradiction ? "contradiction_detected" : "potentially_applicable",
      reasoning: contradiction
        ? "The seller's registration record does not match the model, manufacturer and validity claimed. Treat as a potential certification mismatch."
        : "The category may need BIS registration. The seller claims “BIS certified” but gives no registration number we could verify.",
      ruleVersion: RULE_VERSION, ruleReviewedAt: null, evidenceIds: contradiction ? ["ev_rules", "ev_listing", "ev_record"] : ["ev_rules", "ev_listing"] },
    { id: "chk_wireless", area: "wireless", title: "Wireless (WPC) approval", status: "potentially_applicable",
      reasoning: "The listing shows Bluetooth 5.0, so wireless approval may apply. No approval document was found.",
      ruleVersion: RULE_VERSION, ruleReviewedAt: null, evidenceIds: ["ev_rules", "ev_listing"] },
    { id: "chk_battery", area: "battery", title: "Battery", status: "unverified",
      reasoning: "Battery type and capacity are listed, but no test report was found.",
      ruleVersion: RULE_VERSION, ruleReviewedAt: null, evidenceIds: ["ev_listing"] },
    { id: "chk_label", area: "labelling", title: "Labelling", status: "potentially_applicable",
      reasoning: "Packaging and labelling requirements may apply to this category and need confirmation.",
      ruleVersion: RULE_VERSION, ruleReviewedAt: null, evidenceIds: ["ev_rules"] },
  ];

  const open = checks.filter((c) => c.status === "potentially_applicable" || c.status === "unverified");
  let outcome: Outcome = "CONDITIONAL_IMPORT";
  let riskLevel: RiskLevel = "HIGH";
  if (!contradiction && open.length === 0) { outcome = "LIKELY_IMPORTABLE"; riskLevel = "LOW"; }
  else if (!contradiction && open.length < 3) riskLevel = "MEDIUM";

  const reasons = [
    ...(contradiction ? [{ text: "Potential certification mismatch between the seller's claim and the registration record.", checkIds: ["chk_bis"] }] : []),
    { text: "BIS and wireless requirements potentially apply and are not yet verified.", checkIds: ["chk_bis", "chk_wireless"] },
    ...(model ? [] : [{ text: "Model number unknown, so any certificate cannot be matched to this product.", checkIds: ["chk_bis"] }]),
  ];

  const cost = buildCost(rec);
  const seller = model ? `model ${model}` : "the exact model (to be confirmed)";
  return {
    id: rec.id,
    generatedAt: new Date(rec.completedAt ?? rec.updatedAt).toISOString(),
    dataMode: "demo",
    outcome,
    riskLevel,
    nextAction: contradiction
      ? "Pause the purchase. Ask the seller for certification evidence covering the exact model and factory before ordering."
      : "Pause the purchase. Get the correct certification evidence and resolve the wireless requirement before ordering.",
    reasons,
    summary: {
      title,
      quantity: rec.req.quantity,
      purpose: rec.req.purpose,
      classification: {
        value: "Bluetooth speaker",
        status: "needs_confirmation",
        candidates: [
          { label: "Bluetooth speaker", confidence: 0.72 },
          { label: "Portable audio player", confidence: 0.18 },
        ],
      },
      bis: contradiction ? "contradiction_detected" : "verification_required",
      wireless: "check_required",
      sellerClaimsBis: true,
      identityMatch: contradiction ? "mismatch" : "unresolved",
      illustrativeCostPerUnit: { currency: "INR", expected: cost.perUnitExpected },
    },
    profile: {
      confirmed: [
        { field: "Title", value: title, evidenceIds: ["ev_listing"], confidence: "high" },
        { field: "Price", value: "US$6.80 – 9.50", evidenceIds: ["ev_listing"], confidence: "high" },
        { field: "MOQ", value: "50 pieces", evidenceIds: ["ev_listing"], confidence: "high" },
        { field: "Bluetooth", value: "5.0", evidenceIds: ["ev_listing"], confidence: "high" },
        { field: "Battery", value: "1200mAh lithium polymer", evidenceIds: ["ev_listing"], confidence: "medium" },
      ],
      sellerClaims: [
        { field: "Certifications", value: "BIS certified, CE, RoHS (no registration number shown)", evidenceIds: ["ev_listing"], confidence: "low" },
      ],
      userSupplied: [
        { field: "Quantity", value: String(rec.req.quantity), evidenceIds: ["ev_user"], confidence: "high" },
        { field: "Destination", value: [rec.req.destination.city, rec.req.destination.state].filter(Boolean).join(", "), evidenceIds: ["ev_user"], confidence: "high" },
        { field: "Purpose", value: rec.req.purpose === "resale" ? "Resale" : "Personal use", evidenceIds: ["ev_user"], confidence: "high" },
        ...(rec.req.variant ? [{ field: "Variant", value: rec.req.variant, evidenceIds: ["ev_user"], confidence: "high" as const }] : []),
        ...(rec.model ? [{ field: "Model", value: rec.model, evidenceIds: ["ev_user"], confidence: "medium" as const }] : []),
        ...rec.req.sellerCertificates.map((c) => ({ field: "Certificate number", value: c, evidenceIds: ["ev_user"], confidence: "high" as const })),
      ],
    },
    checks,
    certificationComparison: cmp,
    cost,
    nextActions: [
      { priority: 1, text: "Do not pay the supplier yet." },
      { priority: 2, text: "Ask the seller for BIS registration documents covering your exact model, manufacturer and factory." },
      { priority: 3, text: "Ask the seller for wireless (WPC) approval documents for this model, if applicable." },
      { priority: 4, text: "Confirm the product classification and final duty rates with a customs broker." },
    ],
    sellerRequest:
      `Hello, before we order ${rec.req.quantity} units of this Bluetooth speaker (${seller}), please send:\n` +
      "1. BIS registration number and certificate covering this exact model, with manufacturer, factory and validity dates.\n" +
      "2. Wireless (WPC) approval documents for this model, if applicable.\n" +
      "3. Battery type, capacity and test reports.\n" +
      "4. The actual manufacturer's name and factory location.\n" +
      "Thank you.",
    evidence,
    disclaimer: "Decision support only. Not legal clearance or customs approval.",
  };
}

// ---------- API ----------

const PRIVATE_HOST = /^(localhost|127\.|10\.|192\.168\.|169\.254\.|0\.0\.0\.0)/i;

export const mockApi: Api = {
  async create(req) {
    await delay();
    let host = "";
    try {
      host = new URL(req.url).hostname;
    } catch {
      throw new ApiError("URL rejected: not a valid http(s) address.", 422);
    }
    if (PRIVATE_HOST.test(host)) {
      throw new ApiError("URL rejected: internal or private addresses are not allowed.", 422);
    }
    const db = load();
    const now = Date.now();
    const id = `inv_${Math.random().toString(36).slice(2, 8)}`;
    db[id] = {
      id, req, createdAt: now, updatedAt: now, completedAt: null, stageIndex: 0,
      lastTick: now, blocked: false, answered: false, model: null, cancelled: false, overrides: {},
    };
    save(db);
    return { id, status: "CREATED" };
  },

  async get(id) {
    await delay();
    const db = load();
    const rec = find(db, id);
    advance(rec, Date.now());
    save(db);
    return toInvestigation(rec);
  },

  async list() {
    await delay();
    const db = load();
    const now = Date.now();
    return Object.values(db)
      .sort((a, b) => b.createdAt - a.createdAt)
      .map((rec): InvestigationSummary => {
        advance(rec, now);
        const done = rec.stageIndex >= STAGES.length && !rec.cancelled;
        const rep = done ? buildReport(rec) : null;
        return {
          id: rec.id, url: rec.req.url, title: rep?.summary.title ?? null, status: statusOf(rec),
          outcome: rep?.outcome ?? null, riskLevel: rep?.riskLevel ?? null,
          createdAt: new Date(rec.createdAt).toISOString(),
        };
      });
  },

  async answer(id, body) {
    await delay();
    const db = load();
    const rec = find(db, id);
    if (!rec.blocked) throw new ApiError("No question is waiting for an answer.", 409);
    rec.model = body.skipped ? null : (body.value ?? "").trim() || null;
    rec.answered = true;
    rec.blocked = false;
    rec.lastTick = Date.now();
    save(db);
    return toInvestigation(rec);
  },

  async cancel(id) {
    await delay();
    const db = load();
    find(db, id).cancelled = true;
    save(db);
  },

  async remove(id) {
    await delay();
    const db = load();
    find(db, id);
    delete db[id];
    save(db);
  },

  async patchAssumptions(id, overrides) {
    await delay();
    const db = load();
    const rec = find(db, id);
    const known = new Set(DEFAULTS.map((d) => d.key));
    for (const [k, v] of Object.entries(overrides)) {
      if (!known.has(k) || !Number.isFinite(v) || v < 0) {
        throw new ApiError(`Invalid assumption: ${k}`, 400);
      }
      rec.overrides[k] = v;
    }
    save(db);
  },

  async report(id) {
    await delay();
    const db = load();
    const rec = find(db, id);
    advance(rec, Date.now());
    save(db);
    if (rec.cancelled || rec.stageIndex < STAGES.length) {
      throw new ApiError("The report is not ready yet.", 409);
    }
    return buildReport(rec);
  },
};
