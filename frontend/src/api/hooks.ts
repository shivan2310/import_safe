import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./index";
import { toApiError } from "./errors";
import type { AnswerRequest, CreateInvestigationRequest, InvestigationStatus } from "../types";

const POLLING: ReadonlySet<InvestigationStatus> = new Set([
  "CREATED",
  "READING_LISTING",
  "PROFILE_BUILT",
  "CLASSIFIED",
  "CHECKING_REQUIREMENTS",
  "VERIFYING_CLAIMS",
  "ESTIMATING_COST",
]);

export function useInvestigation(id: string) {
  return useQuery({
    queryKey: ["investigation", id],
    queryFn: () => api.get(id).catch((e) => Promise.reject(toApiError(e))),
    retry: 1,
    refetchInterval: (q) => {
      if (q.state.status === "error") return false;
      const status = q.state.data?.status;
      return !status || POLLING.has(status) ? 1000 : false;
    },
  });
}

export function useReport(id: string, enabled = true) {
  return useQuery({
    queryKey: ["report", id],
    queryFn: () => api.report(id).catch((e) => Promise.reject(toApiError(e))),
    enabled,
    retry: 1,
  });
}

export function useHistory() {
  return useQuery({
    queryKey: ["history"],
    queryFn: () => api.list().catch((e) => Promise.reject(toApiError(e))),
  });
}

export function useCreateInvestigation() {
  return useMutation({
    mutationFn: (req: CreateInvestigationRequest) =>
      api.create(req).catch((e) => Promise.reject(toApiError(e))),
  });
}

export function useAnswer(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AnswerRequest) =>
      api.answer(id, body).catch((e) => Promise.reject(toApiError(e))),
    onSuccess: (inv) => qc.setQueryData(["investigation", id], inv),
  });
}

export function useCancel(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancel(id).catch((e) => Promise.reject(toApiError(e))),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["investigation", id] }),
  });
}

export function usePatchAssumptions(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (overrides: Record<string, number>) =>
      api.patchAssumptions(id, overrides).catch((e) => Promise.reject(toApiError(e))),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["report", id] }),
  });
}

export function useDelete() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.remove(id).catch((e) => Promise.reject(toApiError(e))),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["history"] }),
  });
}
