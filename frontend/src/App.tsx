import { FormEvent, useState } from "react";
import { analyze, AnalyzeResponse } from "./api";

const show = (v: unknown) => (v === null || v === undefined ? "Unknown" : String(v));

export default function App() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      setResult(await analyze(url.trim()));
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  const p = result?.product;
  return (
    <main className="container">
      <h1>ImportSafe</h1>
      <p className="tagline">Can I import this? Paste a product URL to check.</p>
      <form onSubmit={onSubmit} className="form">
        <input
          type="url"
          required
          placeholder="https://www.alibaba.com/product-detail/..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <button type="submit" disabled={loading || !url.trim()}>
          {loading ? "Analyzing…" : "Analyze"}
        </button>
      </form>
      {error && <p className="error">{error}</p>}
      {result && p && (
        <section className="result">
          <span className="badge">{result.mode} DATA</span>
          <h2>{show(p.title)}</h2>
          <dl>
            <dt>Seller</dt><dd>{show(p.seller)}</dd>
            <dt>Price</dt><dd>{p.price === null ? "Unknown" : `${p.price} ${p.currency ?? ""}`}</dd>
            <dt>MOQ</dt><dd>{show(p.moq)}</dd>
            <dt>Source</dt><dd className="src">{p.source_url}</dd>
          </dl>
        </section>
      )}
    </main>
  );
}
