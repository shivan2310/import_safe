// Types mirror the investigation API in the PRD (B3/B5). The frontend only displays
// backend results; it contains no regulatory logic.

export type StageState = "pending" | "running" | "done" | "needs_input" | "failed";

export interface Stage {
  key: string;
  label: string;
  state: StageState;
  message: string | null;
}

export type InvestigationStatus =
  | "CREATED"
  | "READING_LISTING"
  | "PROFILE_BUILT"
  | "NEEDS_INPUT"
  | "CLASSIFIED"
  | "CHECKING_REQUIREMENTS"
  | "VERIFYING_CLAIMS"
  | "ESTIMATING_COST"
  | "REPORT_READY"
  | "FAILED"
  | "CANCELLED"
  | "EXPIRED"
  | "DELETED";

export type DataMode = "live" | "demo";
export type Outcome =
  | "LIKELY_IMPORTABLE"
  | "CONDITIONAL_IMPORT"
  | "HIGH_RISK_DO_NOT_PROCEED"
  | "INSUFFICIENT_INFORMATION";
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "INSUFFICIENT_EVIDENCE";

export interface Question {
  id: string;
  field: string;
  prompt: string;
  whyItMatters: string;
  inputType: "text" | "number" | "select";
  options?: string[];
}

export interface ApiErrorInfo {
  message: string;
  errorId: string;
}

export interface Investigation {
  id: string;
  url: string;
  status: InvestigationStatus;
  stages: Stage[];
  pendingQuestion: Question | null;
  activity: string | null;
  createdAt: string;
  updatedAt: string;
  dataMode: DataMode;
  error: ApiErrorInfo | null;
}

export interface InvestigationSummary {
  id: string;
  url: string;
  title: string | null;
  status: InvestigationStatus;
  outcome: Outcome | null;
  riskLevel: RiskLevel | null;
  createdAt: string;
}

export interface CreateInvestigationRequest {
  url: string;
  quantity: number;
  destination: { state: string; city: string | null };
  purpose: "personal_use" | "resale";
  variant: string | null;
  shipping: { amount: number; currency: string; mode: "air" | "sea" | null } | null;
  sellerCertificates: string[];
}

export type AnswerRequest =
  | { questionId: string; value: string; skipped?: false }
  | { questionId: string; skipped: true; value?: undefined };

// ---- Report ----

export type CheckStatus =
  | "potentially_applicable"
  | "verified"
  | "not_applicable"
  | "unverified"
  | "contradiction_detected";

export type CheckArea =
  | "import_policy"
  | "bis"
  | "wireless"
  | "battery"
  | "labelling"
  | "category_specific";

export interface Evidence {
  id: string;
  label: string;
  sourceUrl: string | null;
  sourceType: "listing" | "official_portal" | "user_upload" | "rule_source";
  retrievedAt: string;
  excerpt: string | null;
  retrievalMode: DataMode;
}

export interface Fact {
  field: string;
  value: string;
  evidenceIds: string[];
  confidence: "high" | "medium" | "low";
}

export interface Check {
  id: string;
  area: CheckArea;
  title: string;
  status: CheckStatus;
  reasoning: string;
  ruleVersion: string | null;
  ruleReviewedAt: string | null;
  evidenceIds: string[];
}

export interface CertificationFieldResult {
  field: string;
  claim: string | null;
  record: string | null;
  result: "match" | "partial" | "mismatch" | "unknown";
}

export interface CertificationComparison {
  claimRegistrationNo: string;
  recordRegistrationNo: string | null;
  overall: CheckStatus;
  fieldResults: CertificationFieldResult[];
  evidenceIds: string[];
  note: string | null;
}

export interface CostLine {
  key: string;
  label: string;
  base: string;
  rate: string | null;
  amount: number;
  formula: string;
  source: string;
  status: "assumed" | "user_supplied" | "calculated";
  countsTowardTotal: boolean;
}

export interface CostAssumption {
  key: string;
  label: string;
  value: number;
  unit: string;
  source: string;
  status: "assumed" | "user_supplied";
  editable: boolean;
}

export interface Cost {
  currency: string;
  low: number;
  expected: number;
  high: number;
  perUnitExpected: number;
  breakdown: CostLine[];
  assumptions: CostAssumption[];
  label: string;
}

export interface ReportSummary {
  title: string | null;
  quantity: number;
  purpose: "personal_use" | "resale";
  classification: {
    value: string | null;
    status: "confirmed" | "needs_confirmation";
    candidates: { label: string; confidence: number }[];
  };
  bis: string;
  wireless: string;
  sellerClaimsBis: boolean | null;
  identityMatch: "match" | "unresolved" | "mismatch";
  illustrativeCostPerUnit: { currency: string; expected: number } | null;
}

export interface Report {
  id: string;
  generatedAt: string;
  dataMode: DataMode;
  outcome: Outcome;
  riskLevel: RiskLevel;
  nextAction: string;
  reasons: { text: string; checkIds: string[] }[];
  summary: ReportSummary;
  profile: { confirmed: Fact[]; sellerClaims: Fact[]; userSupplied: Fact[] };
  checks: Check[];
  certificationComparison: CertificationComparison | null;
  cost: Cost;
  nextActions: { priority: number; text: string }[];
  sellerRequest: string;
  evidence: Evidence[];
  disclaimer: string;
}
