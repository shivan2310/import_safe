/** Typed API client for ImportSafe backend (/api/investigations).
 *
 * In development, requests go to /api (proxied by Vite to localhost:8000).
 * In production, set VITE_API_URL=https://your-backend.onrender.com in Vercel.
 */
const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '');

export interface PendingQuestion {
  id: string;
  field: string;
  prompt: string;
  whyItMatters: string;
}

export interface StageStatus {
  stage: string;
  state: 'pending' | 'running' | 'done' | 'needs_input' | 'failed';
}

export interface InvStatus {
  id: string;
  status: string;
  stages: StageStatus[];
  pendingQuestion: PendingQuestion | null;
  eventCount: number;
}

export interface Check {
  ruleId: string;
  title: string;
  status: string;
  notes: string | null;
}

export interface FieldMatch {
  field: string;
  match: string;
  detail: string;
}

export interface CertComparison {
  result: string;
  summary: string;
  fieldMatches: FieldMatch[];
}

export interface Cost {
  perUnitExpected: string;
  totalExpected: string;
  label: string;
  ratesVerified: boolean;
}

export interface Evidence {
  id: string;
  title: string;
  kind: string;
  excerpt: string;
  note: string;
  retrievedAt: string;
  sourceUrl: string | null;
}

export interface FactRow {
  field: string;
  value: string;
  kind?: string;
  evidenceId?: string;
  source?: string;
}

export interface Profile {
  confirmed: FactRow[];
  claimed: FactRow[];
}

export interface Summary {
  classification: string;
  hsCode: string | null;
  productDescription: string;
}

export interface InvReport {
  outcome: string;
  riskLevel: string;
  score: number;
  disclaimer: string;
  summary: Summary | null;
  checks: Check[];
  certificationComparison: CertComparison | null;
  cost: Cost | null;
  evidence: Evidence[];
  profile: Profile;
  nextActions: string[];
}

export interface CreateOrderInput {
  url: string;
  quantity: number;
  destination?: { state: string; city: string };
  purpose?: string;
  variant?: string;
  shipping?: { amount: string; currency: string; mode: string };
  sellerCertificates?: string[];
}

async function apiFetch(path: string, init?: RequestInit) {
  const res = await fetch(`${API_BASE}${path}`, { credentials: 'include', ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body?.detail;
    const msg = typeof detail === 'object' ? detail?.code : detail;
    throw new Error(msg || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function createInvestigation(order: CreateOrderInput): Promise<{ id: string; status: string }> {
  return apiFetch('/api/investigations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(order),
  });
}

export async function getInvestigation(id: string): Promise<InvStatus> {
  return apiFetch(`/api/investigations/${id}`);
}

export async function getReport(id: string): Promise<InvReport> {
  return apiFetch(`/api/investigations/${id}/report`);
}

export async function postAnswer(
  id: string,
  questionId: string,
  value: string | null,
  skipped: boolean,
): Promise<void> {
  await apiFetch(`/api/investigations/${id}/answers`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ questionId, value, skipped }),
  });
}

export async function patchAssumptions(id: string, overrides: Record<string, string>): Promise<void> {
  await apiFetch(`/api/investigations/${id}/assumptions`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(overrides),
  });
}

export async function deleteInvestigation(id: string): Promise<void> {
  await apiFetch(`/api/investigations/${id}`, { method: 'DELETE' });
}
