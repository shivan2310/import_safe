import { supabase } from './supabase';

const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '');

async function apiFetch(path: string, init?: RequestInit) {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err: ApiError = new Error(body?.detail?.message ?? `HTTP ${res.status}`) as ApiError;
    err.status = res.status;
    err.code = body?.detail?.code ?? String(res.status);
    throw err;
  }
  return res.json();
}

export interface ApiError extends Error {
  status: number;
  code: string;
}

export type InvStatus =
  | 'CREATED' | 'READING_LISTING' | 'PROFILE_BUILT' | 'CLASSIFIED'
  | 'CHECKING_REQUIREMENTS' | 'VERIFYING_CLAIMS' | 'ESTIMATING_COST'
  | 'REPORT_READY' | 'NEEDS_INPUT' | 'FAILED' | 'CANCELLED' | 'EXPIRED' | 'DELETED';

export interface PendingQuestion {
  id: string;
  field: string;
  prompt: string;
  whyItMatters: string;
}

export interface InvStatusResponse {
  id: string;
  status: InvStatus;
  stages: { stage: string; state: string }[];
  pendingQuestion: PendingQuestion | null;
  eventCount: number;
}

export interface ReportCostLine { label: string; amount: string; kind: string }
export interface ReportAssumption { name: string; value: string | null; source: string; verified: boolean; userSupplied: boolean }
export interface ReportCost {
  currency: string; quantity: number;
  low: string; expected: string; high: string;
  perUnitLow: string; perUnitExpected: string; perUnitHigh: string;
  breakdown: ReportCostLine[];
  assumptions: ReportAssumption[];
  breakdownNote: string;
}

export interface FullReport {
  id: string;
  outcome: string;
  riskLevel: string;
  score: number;
  nextAction: string | null;
  nextActions: { priority: number; text: string }[];
  reasons: string[];
  summary: {
    quantity: number | null;
    classification: { value: string | null; status: string; confidence: string; candidateHsCodes: string[] } | null;
    bis: string | null;
    wireless: string | null;
    sellerClaimsBis: boolean;
    identityMatch: string;
    illustrativeCostPerUnit: { currency: string; expected: string } | null;
  };
  profile: {
    confirmed: { field: string; value: unknown; kind: string; evidenceId?: string }[];
    sellerClaims: { field: string; value: unknown; kind: string }[];
    userSupplied: { field: string; value: unknown; kind: string }[];
  };
  checks: { ruleId: string; area: string; status: string; reasoning: string; mandatory: boolean; ruleVersion: string; requiresEvidence: string[] }[];
  certificationComparison: {
    result: string; reasoning: string; conflicts: string[]; recordReliable: boolean;
    fieldResults: { field: string; claimValue: string | null; recordValue: string | null; result: string; reason: string }[];
    sellerRequestList: string[];
  } | null;
  cost: ReportCost | null;
  evidence: { id: string; sourceUrl: string; retrievedAt: string; excerpt: string | null; sourceType: string }[];
  ruleVersions: string[];
  questionsSkipped: string[];
  disclaimer: string;
}

export interface SimilarProductSeller {
  name: string;
  verificationStatus: 'marketplace_listed' | 'fixture' | 'unverified';
}

export interface SimilarProduct {
  id: string;
  name: string;
  seller: SimilarProductSeller;
  price: string | null;
  currency: string | null;
  moq: string | null;
  origin: string | null;
  sourceUrl: string | null;
  matchReasons: string[];
  isFixture: boolean;
}

export interface SimilarProductsResponse {
  products: SimilarProduct[];
  dataSource: 'live' | 'fixture' | 'cache' | 'empty';
  isFixture: boolean;
  disclaimer: string;
}

export const api = {
  createInvestigation(body: {
    url: string; quantity: number; purpose?: string; variant?: string;
    destination?: { state?: string; city?: string };
    shipping?: { amount?: string; currency?: string; mode?: string };
    sellerCertificates?: string[];
  }) {
    return apiFetch('/api/investigations', { method: 'POST', body: JSON.stringify(body) }) as Promise<{ id: string; status: InvStatus }>;
  },

  getInvestigation(id: string) {
    return apiFetch(`/api/investigations/${id}`) as Promise<InvStatusResponse>;
  },

  getReport(id: string) {
    return apiFetch(`/api/investigations/${id}/report`) as Promise<FullReport>;
  },

  postAnswer(id: string, body: { questionId: string; value?: string; skipped?: boolean }) {
    return apiFetch(`/api/investigations/${id}/answers`, { method: 'POST', body: JSON.stringify(body) }) as Promise<{ ok: boolean }>;
  },

  patchAssumptions(id: string, body: { freightInr?: string; fxUsdInr?: string; bcdPct?: string; igstPct?: string; clearingInr?: string }) {
    return apiFetch(`/api/investigations/${id}/assumptions`, { method: 'PATCH', body: JSON.stringify(body) }) as Promise<{ ok: boolean; recalculating: boolean }>;
  },

  deleteInvestigation(id: string) {
    return apiFetch(`/api/investigations/${id}`, { method: 'DELETE' }) as Promise<{ ok: boolean; deleted: string }>;
  },

  getSimilarProducts(body: { productName: string; specs?: Record<string, unknown>; investigationId?: string }) {
    return apiFetch('/api/products/similar', { method: 'POST', body: JSON.stringify(body) }) as Promise<SimilarProductsResponse>;
  },
};
