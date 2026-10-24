const newErrorId = () => `err_${Math.random().toString(36).slice(2, 10)}`;

export class ApiError extends Error {
  status: number;
  code: string | null;
  errorId: string;

  constructor(
    message: string,
    status = 0,
    opts: { code?: string | null; errorId?: string } = {}
  ) {
    super(message);
    this.status = status;
    this.code = opts.code ?? null;
    this.errorId = opts.errorId ?? newErrorId();
  }
}

export function toApiError(e: unknown): ApiError {
  if (e instanceof ApiError) return e;
  return new ApiError(e instanceof Error ? e.message : "Unexpected error");
}
