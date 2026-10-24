const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface Product {
  title: string | null;
  seller: string | null;
  price: number | null;
  currency: string | null;
  moq: number | null;
  source_url: string;
}

export interface AnalyzeResponse {
  mode: string;
  product: Product;
}

export async function analyze(url: string): Promise<AnalyzeResponse> {
  const res = await fetch(`${BASE}/api/v1/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}
