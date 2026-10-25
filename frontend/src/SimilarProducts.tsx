import { api, type FullReport, type SimilarProduct } from './api';
import { useEffect, useRef, useState } from 'react';
import './SimilarProducts.css';

// ---------------------------------------------------------------------------
// Compare modal
// ---------------------------------------------------------------------------

function CompareModal({
  product,
  original,
  report,
  onClose,
}: {
  product: SimilarProduct;
  original: { name?: string; quantity: number };
  report: FullReport;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialogRef.current?.showModal(); }, []);

  const origCost = report.cost ? Number(report.cost.expected) : null;
  const origPerUnit = report.cost ? Number(report.cost.perUnitExpected) : null;

  // Simple illustrative cost ratio based on price
  let altTotal: number | null = null;
  let altPerUnit: number | null = null;
  let costNote = '';
  if (origCost && product.price && report.cost) {
    const altPriceNum = parseFloat(product.price.replace(/[^0-9.]/g, ''));
    const origGoods = report.cost.breakdown.find(l => l.kind === 'goods' || l.label.toLowerCase().includes('goods'));
    if (origGoods && altPriceNum > 0 && !isNaN(altPriceNum)) {
      const origGoodsAmt = Number(origGoods.amount);
      const fxHint = report.cost.assumptions.find(a => a.name.toLowerCase().includes('fx') || a.name.toLowerCase().includes('rate'));
      const fxRate = fxHint?.value ? Number(fxHint.value) : (product.currency === 'USD' ? 84 : 1);
      const altGoodsInr = altPriceNum * original.quantity * fxRate;
      const ratio = origGoodsAmt > 0 ? altGoodsInr / origGoodsAmt : 1;
      const fixedCosts = report.cost.breakdown
        .filter(l => l.kind === 'fixed' || l.label.toLowerCase().includes('clearing') || l.label.toLowerCase().includes('port') || l.label.toLowerCase().includes('transport'))
        .reduce((sum, l) => sum + Number(l.amount), 0);
      altTotal = (origCost - fixedCosts) * ratio + fixedCosts;
      altPerUnit = altTotal / original.quantity;
      costNote = 'Illustrative — same logistics & duty assumptions, price adjusted.';
    }
  }

  const money = (v: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v);
  const origProfileName = report.profile.confirmed.find(f => f.field === 'name' || f.field === 'title')?.value as string | undefined;

  return (
    <dialog ref={dialogRef} className="compare-dialog" aria-labelledby="compare-title"
      onClose={onClose} onCancel={onClose}>
      <div className="compare-dialog-head">
        <div>
          <span className="research-section-kicker">SIDE-BY-SIDE COMPARISON</span>
          <h2 id="compare-title">Compare products</h2>
        </div>
        <button aria-label="Close comparison" onClick={() => dialogRef.current?.close()}>×</button>
      </div>

      <div className="compare-grid">
        <div className="compare-col compare-original">
          <span className="compare-col-label">YOUR PRODUCT</span>
          <h3>{String(origProfileName ?? original.name ?? 'Original product')}</h3>
          {origCost !== null && <div className="compare-cost-highlight">
            <span>Estimated landed cost</span>
            <strong>{money(origCost)}</strong>
            {origPerUnit !== null && <small>{money(origPerUnit)} / unit</small>}
          </div>}
        </div>
        <div className="compare-divider" aria-hidden="true">⇄</div>
        <div className="compare-col compare-alternative">
          <span className="compare-col-label">ALTERNATIVE</span>
          <h3>{product.name}</h3>
          <p className="compare-seller">{product.seller.name}
            {product.seller.verificationStatus === 'fixture' && <span className="compare-badge fixture-badge">Sample</span>}
            {product.seller.verificationStatus === 'marketplace_listed' && <span className="compare-badge marketplace-badge">Alibaba listing</span>}
          </p>
          {product.price && <div className="compare-price">
            <span>Supplier quoted</span>
            <strong>{product.price} {product.currency ?? ''}</strong>
            {product.moq && <small>MOQ: {product.moq}</small>}
          </div>}
          {altTotal !== null && <div className="compare-cost-highlight alt">
            <span>Illustrative landed cost</span>
            <strong>{money(altTotal)}</strong>
            {altPerUnit !== null && <small>{money(altPerUnit)} / unit</small>}
          </div>}
        </div>
      </div>

      {altTotal !== null && origCost !== null && (
        <div className="compare-diff">
          <span>Estimated difference: </span>
          <strong className={altTotal < origCost ? 'diff-lower' : 'diff-higher'}>
            {altTotal < origCost ? '−' : '+'}{money(Math.abs(altTotal - origCost))}
          </strong>
          <small> ({altTotal < origCost ? '-' : '+'}{Math.round(Math.abs((altTotal - origCost) / origCost) * 100)}%)</small>
        </div>
      )}

      <div className="compare-info">
        {product.origin && <div><span>Origin</span><span>{product.origin}</span></div>}
        {product.sourceUrl && <div><span>Source</span>
          <a href={product.sourceUrl} target="_blank" rel="noopener noreferrer">View on Alibaba ↗</a>
        </div>}
      </div>

      <div className="compare-footer">
        {costNote && <p className="research-fineprint">{costNote}</p>}
        <p className="research-fineprint">
          Alternative cost is illustrative only. Actual duties, freight, and certification requirements
          depend on the specific product, HS code, and applicable rules. Not a customs assessment.
        </p>
        <p className="research-fineprint">
          {product.seller.verificationStatus === 'marketplace_listed'
            ? 'This seller was found on a public marketplace. Their identity and product quality have not been independently verified.'
            : 'This is sample data for illustration. It does not represent a real seller or product.'}
        </p>
      </div>

      <div className="compare-actions">
        <button onClick={() => dialogRef.current?.close()}>Close</button>
        {product.sourceUrl && (
          <a className="compare-view-btn" href={product.sourceUrl} target="_blank" rel="noopener noreferrer">
            View product ↗
          </a>
        )}
      </div>
    </dialog>
  );
}

// ---------------------------------------------------------------------------
// Product card
// ---------------------------------------------------------------------------

function ProductCard({ product, onCompare }: { product: SimilarProduct; onCompare: () => void }) {
  return (
    <div className="sp-card">
      <div className="sp-card-head">
        <div className="sp-card-placeholder" aria-hidden="true">
          <svg viewBox="0 0 40 40" fill="none"><rect x="5" y="8" width="30" height="24" rx="4" stroke="currentColor" strokeWidth="1.5"/><circle cx="14" cy="17" r="3" stroke="currentColor" strokeWidth="1.5"/><path d="m7 30 9-8 6 5 6-8 7 11" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/></svg>
        </div>
        <div className="sp-card-title">
          <p className="sp-product-name">{product.name}</p>
          <p className="sp-seller-name">
            {product.seller.name}
            {product.seller.verificationStatus === 'fixture' && (
              <span className="sp-badge sp-badge-fixture">Sample</span>
            )}
            {product.seller.verificationStatus === 'marketplace_listed' && (
              <span className="sp-badge sp-badge-marketplace">Alibaba</span>
            )}
          </p>
        </div>
      </div>

      <div className="sp-card-details">
        {product.price && (
          <div><span>Price</span><strong>{product.price} {product.currency ?? ''}</strong></div>
        )}
        {product.moq && <div><span>MOQ</span><strong>{product.moq}</strong></div>}
        {product.origin && <div><span>Origin</span><strong>{product.origin}</strong></div>}
      </div>

      <div className="sp-card-footer">
        <button className="sp-compare-btn" onClick={onCompare}>Compare landed cost</button>
        {product.sourceUrl && (
          <a className="sp-view-link" href={product.sourceUrl} target="_blank" rel="noopener noreferrer">
            View product ↗
          </a>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function SimilarProducts({
  productName,
  specs,
  investigationId,
  report,
}: {
  productName: string;
  specs?: Record<string, unknown>;
  investigationId: string;
  report: FullReport;
}) {
  const [products, setProducts] = useState<SimilarProduct[]>([]);
  const [status, setStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [isFixture, setIsFixture] = useState(false);
  const [dataSource, setDataSource] = useState('');
  const [disclaimer, setDisclaimer] = useState('');
  const [compareTarget, setCompareTarget] = useState<SimilarProduct | null>(null);

  useEffect(() => {
    if (!productName.trim()) return;
    setStatus('loading');
    api.getSimilarProducts({ productName, specs, investigationId })
      .then(res => {
        setProducts(res.products);
        setIsFixture(res.isFixture);
        setDataSource(res.dataSource);
        setDisclaimer(res.disclaimer);
        setStatus('done');
      })
      .catch(() => setStatus('error'));
  }, [productName, investigationId]); // eslint-disable-line react-hooks/exhaustive-deps

  const quantity = report.summary.quantity ?? 1;
  const origProfileName = report.profile.confirmed.find(f => f.field === 'name' || f.field === 'title')?.value as string | undefined;

  return (
    <div className="sp-panel">
      <div className="sp-panel-head">
        <h3>Similar Products</h3>
        <p>Compare alternatives from marketplace listings.</p>
        {isFixture && (
          <div className="sp-fixture-notice" role="status">
            <strong>Sample data</strong> — these listings are illustrative, not real products or sellers.
          </div>
        )}
      </div>

      {status === 'loading' && (
        <div className="sp-state">
          <span className="sp-spinner" aria-hidden="true" />
          <span>Searching for similar products…</span>
        </div>
      )}

      {status === 'error' && (
        <div className="sp-state sp-state-empty">
          <p>Could not retrieve alternatives right now.</p>
        </div>
      )}

      {status === 'done' && products.length === 0 && (
        <div className="sp-state sp-state-empty">
          <p>No similar products found for this listing.</p>
          {dataSource !== 'fixture' && (
            <p className="research-fineprint">Try a broader search or check the product name.</p>
          )}
        </div>
      )}

      {status === 'done' && products.length > 0 && (
        <div className="sp-cards">
          {products.map(p => (
            <ProductCard key={p.id} product={p} onCompare={() => setCompareTarget(p)} />
          ))}
        </div>
      )}

      {status === 'done' && disclaimer && (
        <p className="sp-disclaimer research-fineprint">{disclaimer}</p>
      )}

      {compareTarget && (
        <CompareModal
          product={compareTarget}
          original={{ name: origProfileName, quantity }}
          report={report}
          onClose={() => setCompareTarget(null)}
        />
      )}
    </div>
  );
}
