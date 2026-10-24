import type {
  AnswerRequest,
  CreateInvestigationRequest,
  Investigation,
  InvestigationStatus,
  InvestigationSummary,
  Report,
} from "../types";
import { httpApi } from "./http";
import { mockApi } from "./mock";

export interface Api {
  create(req: CreateInvestigationRequest): Promise<{ id: string; status: InvestigationStatus }>;
  get(id: string): Promise<Investigation>;
  list(): Promise<InvestigationSummary[]>;
  answer(id: string, body: AnswerRequest): Promise<Investigation>;
  cancel(id: string): Promise<void>;
  remove(id: string): Promise<void>;
  patchAssumptions(id: string, overrides: Record<string, number>): Promise<void>;
  report(id: string): Promise<Report>;
}

export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";
export const api: Api = USE_MOCK ? mockApi : httpApi;
