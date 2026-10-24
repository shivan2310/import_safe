import { useEffect, useRef, useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import './InvestigationFlow.css';
import {
  createInvestigation, getInvestigation, getReport, postAnswer,
  patchAssumptions, deleteInvestigation,
  type InvReport, type PendingQuestion, type StageStatus,
} from './api';

export type ImportOrder = {
  url: string; quantity: string; state: string; city: string; purpose: string;
  variant: string; shipping: string; currency: string; shippingMode: string; certificates: string[];
};

// ---------------------------------------------------------------------------
// Stage mapping: backend stage names → UI index 0-5
// ---------------------------------------------------------------------------

const UI_STAGES = [
  ['Read the listing', 'Collect the product details and seller information.'],
  ['Identify the product', 'Organise its model, intended use and technical features.'],
  ['Find requirements', 'Map the checks that need supporting evidence.'],
  ['Check evidence & claims', 'Compare seller documents with official records.'],
  ['Estimate landed cost', 'Build an editable estimate from your assumptions.'],
  ['Prepare your risk report', 'Bring open questions and next actions together.'],
];

const BACKEND_STAGE_TO_UI: Record<string, number> = {
  READING_LISTING: 0,
  PROFILE_BUILT: 1, CLASSIFIED: 1,
  CHECKING_REQUIREMENTS: 2,
  VERIFYING_CLAIMS: 3,
  ESTIMATING_COST: 4,
  REPORT_READY: 5,
};

function uiStageFromBackend(stages: StageStatus[]): number {
  let max = 0;
  for (const s of stages) {
    const ui = BACKEND_STAGE_TO_UI[s.stage];
    if (ui !== undefined && s.state !== 'pending') max = Math.max(max, ui);
  }
  return max;
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

const moneyFmt = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
function moneyStr(s: string) {
  const n = parseFloat(s);
  return isNaN(n) ? '—' : moneyFmt.format(n);
}

const OUTCOME_CONFIG: Record<string, { symbol: string; heading: string; kicker: string; bg: string; border: string; color: string }> = {
  likely_importable: { symbol: '✓', heading: 'Likely importable', kicker: 'OUTCOME · IMPORT APPEARS VIABLE', bg: '#d5e8d0', border: '#a8c8a0', color: '#2a5220' },
  conditional_import: { symbol: '△', heading: 'Conditional import', kicker: 'OUTCOME · CONDITIONS APPLY', bg: '#f0e9d8', border: '#d9ccb1', color: '#53452e' },
  needs_review: { symbol: '?', heading: 'Needs review', kicker: 'OUTCOME · MORE EVIDENCE NEEDED', bg: '#f0e9d8', border: '#d9ccb1', color: '#53452e' },
  likely_blocked: { symbol: '✗', heading: 'Import likely blocked', kicker: 'OUTCOME · IMPORT LIKELY RESTRICTED', bg: '#f0d8d8', border: '#d9b1b1', color: '#522020' },
};

const RISK_COLOUR: Record<string, string> = {
  low: '#2a6b20', medium: '#7a6020', high: '#8c3a20', critical: '#6b1510',
};

const CHECK_STATUS_LABEL: Record<string, string> = {
  potentially_applicable: 'Potentially applicable',
  not_applicable: 'Not applicable',
  likely_exempt: 'Likely exempt',
  verified_ok: 'Verified — OK',
  verified_issue: 'Verified — Issue',
  manual_review: 'Needs manual review',
};

const IDENTITY_LABEL: Record<string, string> = {
  verified: 'Documents match official records',
  unverified: 'Could not verify against official records',
  contradiction_detected: 'Documents contradict official records',
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

type Phase = 'creating' | 'running' | 'question' | 'loading_report' | 'report' | 'failed';

export default function InvestigationFlow({ order, onBack, onLogout }: { order: ImportOrder; onBack: () => void; onLogout: () => void }) {
  const reduced = useReducedMotion();
  const [phase, setPhase] = useState<Phase>('creating');
  const [invId, setInvId] = useState<string | null>(null);
  const [uiStage, setUiStage] = useState(0);
  const [question, setQuestion] = useState<PendingQuestion | null>(null);
  const [answer, setAnswer] = useState('');
  const [report, setReport] = useState<InvReport | null>(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const title = useRef<HTMLHeadingElement>(null);

  // Create investigation on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const qty = parseInt(order.quantity, 10);
        const data = await createInvestigation({
          url: order.url,
          quantity: isNaN(qty) ? 1 : qty,
          destination: { state: order.state, city: order.city },
          purpose: order.purpose || undefined,
          variant: order.variant || undefined,
          shipping: order.shipping
            ? { amount: order.shipping, currency: order.currency, mode: order.shippingMode }
            : undefined,
          sellerCertificates: order.certificates.length ? order.certificates : undefined,
        });
        if (!cancelled) { setInvId(data.id); setPhase('running'); }
      } catch (e: unknown) {
        if (!cancelled) {
          setErrorMsg(e instanceof Error ? e.message : 'Could not start the investigation.');
          setPhase('failed');
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Poll while running or waiting for an answer
  useEffect(() => {
    if (!invId || (phase !== 'running' && phase !== 'question')) return;
    let active = true;
    const poll = async () => {
      try {
        const status = await getInvestigation(invId);
        if (!active) return;
        setUiStage(uiStageFromBackend(status.stages));
        if (status.status === 'REPORT_READY') {
          setPhase('loading_report');
          const rpt = await getReport(invId);
          if (active) { setReport(rpt); setPhase('report'); }
        } else if (status.status === 'NEEDS_INPUT' && status.pendingQuestion) {
          setQuestion(status.pendingQuestion);
          setPhase('question');
        } else if (['FAILED', 'CANCELLED', 'EXPIRED', 'DELETED'].includes(status.status)) {
          setErrorMsg(`Investigation ended: ${status.status.toLowerCase()}`);
          setPhase('failed');
        }
      } catch {
        // transient network error — keep polling
      }
    };
    const id = window.setInterval(poll, 2000);
    poll();
    return () => { active = false; clearInterval(id); };
  }, [invId, phase]);

  // Elapsed clock
  useEffect(() => {
    if (phase === 'report' || phase === 'failed') return;
    const id = window.setInterval(() => setElapsed(t => t + 1), 1000);
    return () => clearInterval(id);
  }, [phase]);

  useEffect(() => {
    document.title = phase === 'report' ? 'Risk report — ImportSafe' : 'Investigation — ImportSafe';
    if (phase === 'report') { window.scrollTo({ top: 0, behavior: 'instant' }); title.current?.focus({ preventScroll: true }); }
  }, [phase]);

  async function handleCancel() {
    if (invId) try { await deleteInvestigation(invId); } catch { /* ignore */ }
    onBack();
  }

  async function submitAnswer(skipped: boolean) {
    if (!invId || !question) return;
    try {
      await postAnswer(invId, question.id, skipped ? null : answer, skipped);
      setQuestion(null); setAnswer(''); setPhase('running');
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : 'Could not submit answer.');
    }
  }

  async function refreshReport() {
    if (!invId) return;
    try { setReport(await getReport(invId)); } catch { /* ignore */ }
  }

  if (phase === 'report' && report) {
    return <RiskReport order={order} report={report} invId={invId!}
      onDelete={onBack} onRefresh={refreshReport} titleRef={title} />;
  }

  const isQuestion = phase === 'question' && question;

  return <div className="investigation-page research-page">
    <header className="workspace-header">
      <a className="workspace-brand" href="#home"><span aria-hidden="true">↗</span> importsafe<span className="workspace-brand-dot">.</span></a>
      <nav aria-label="Workspace">
        <button onClick={handleCancel}>← New investigation</button>
        <button onClick={onLogout}>Log out ↗</button>
      </nav>
    </header>
    <main className="research-main">
      <div className="research-breadcrumb"><span>Workspace</span><span>/</span><span>Investigation</span></div>

      {phase === 'failed' ? (
        <div className="research-heading">
          <h1 ref={title} tabIndex={-1} style={{ fontSize: 'clamp(32px,4vw,52px)' }}>Something went wrong.</h1>
          <p>{errorMsg || 'The investigation could not be completed.'}</p>
          <button className="research-primary" onClick={handleCancel} style={{ marginTop: 22 }}>Start a new investigation ↗</button>
        </div>
      ) : <>
        <div className="research-heading">
          <div className="workspace-eyebrow">FROM A FIND TO A CLEARER PLAN</div>
          <h1 ref={title} tabIndex={-1}>A little research.<br /><em>A clearer direction.</em></h1>
          <p>Your import details, one thoughtful step at a time.</p>
        </div>
        <div className="research-progress-layout">
          <section className="research-panel stage-panel" aria-labelledby="progress-title">
            <div className="research-panel-top">
              <h2 id="progress-title">Your investigation</h2>
              <span className="research-tag">{isQuestion ? 'Needs your input' : 'In progress'}</span>
            </div>
            <div className="research-progress-copy"><span>STEP {uiStage + 1} OF 6</span><span>{Math.round(uiStage / 6 * 100)}%</span></div>
            <div className="research-progress-track" role="progressbar" aria-label="Investigation progress" aria-valuenow={uiStage} aria-valuemin={0} aria-valuemax={6}>
              <motion.span initial={{ scaleX: 0 }} style={{ transformOrigin: 'left' }} animate={{ scaleX: uiStage / 6 }} transition={{ duration: reduced ? 0 : .5 }} />
            </div>
            <ol className="research-stages">
              {UI_STAGES.map(([name, description], i) => (
                <li key={name} className={i < uiStage ? 'complete' : i === uiStage ? 'current' : ''} aria-current={i === uiStage ? 'step' : undefined}>
                  <span className="research-stage-number">{i < uiStage ? '✓' : String(i + 1).padStart(2, '0')}</span>
                  <div>
                    <h3>{name}</h3><p>{description}</p>
                    {i === uiStage && <span className="research-stage-state">{isQuestion ? 'Waiting for your answer' : phase === 'creating' ? 'Starting…' : 'Working…'}</span>}
                  </div>
                </li>
              ))}
            </ol>

            {isQuestion && (
              <div style={{ borderTop: '1px solid var(--line)', paddingTop: 24, marginTop: 8 }}>
                <span className="research-section-kicker">QUICK QUESTION</span>
                <h3 style={{ fontSize: 17, marginTop: 8, fontWeight: 550 }}>{question.prompt}</h3>
                {question.whyItMatters && <p style={{ fontSize: 12, color: 'var(--soft)', margin: '6px 0 16px' }}>{question.whyItMatters}</p>}
                <form onSubmit={e => { e.preventDefault(); submitAnswer(false); }}>
                  <input value={answer} onChange={e => setAnswer(e.target.value)} placeholder="Your answer…" style={{ width: '100%', marginBottom: 12 }} />
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    <button type="submit" className="research-primary" disabled={!answer.trim()}>Submit answer ↗</button>
                    <button type="button" className="research-text-button" onClick={() => submitAnswer(true)}>Skip this question</button>
                  </div>
                </form>
              </div>
            )}

            <div className="research-progress-footer">
              <span>Elapsed {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}</span>
              <button className="research-text-button" onClick={handleCancel}>Cancel investigation</button>
            </div>
          </section>

          <aside className="research-side">
            <div className="research-orbit" aria-hidden="true"><span>↗</span><span className="orbit-label">CONNECTING THE DOTS</span></div>
            <h2>Good decisions<br />start with good questions.</h2>
            <p>We'll keep the unknowns visible, so you know what to ask before you order.</p>
            <div className="research-live" role="status">
              <span className="research-live-dot" />
              {isQuestion ? 'Waiting for your answer.' : `Step ${uiStage + 1} of 6 · running`}
            </div>
            <div className="research-side-order">
              <span>YOUR IMPORT</span>
              <strong>{order.quantity} units → {order.city}</strong>
              <a href={order.url} target="_blank" rel="noreferrer">View product listing ↗</a>
            </div>
          </aside>
        </div>
      </>}
    </main>
  </div>;
}

// ---------------------------------------------------------------------------
// Risk report — renders the full FullReport from the backend
// ---------------------------------------------------------------------------

function RiskReport({ order, report, invId, onDelete, onRefresh, titleRef }: {
  order: ImportOrder; report: InvReport; invId: string;
  onDelete: () => void; onRefresh: () => Promise<void>;
  titleRef: React.RefObject<HTMLHeadingElement | null>;
}) {
  const reduced = useReducedMotion();
  const [activeEvidence, setActiveEvidence] = useState<number | null>(null);
  const [done, setDone] = useState<number[]>([]);
  const [notice, setNotice] = useState('');
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [recalculating, setRecalculating] = useState(false);
  const [assumptions, setAssumptions] = useState({ freightInr: '', fxUsdInr: '', bcdPct: '', igstPct: '', clearingInr: '' });
  const evidenceDialog = useRef<HTMLDialogElement>(null);
  const deleteDialog = useRef<HTMLDialogElement>(null);

  useEffect(() => { if (activeEvidence !== null) evidenceDialog.current?.showModal(); }, [activeEvidence]);
  useEffect(() => { if (deleteOpen) deleteDialog.current?.showModal(); }, [deleteOpen]);

  const outcome = OUTCOME_CONFIG[report.outcome] ?? OUTCOME_CONFIG.needs_review;
  const riskColour = RISK_COLOUR[report.riskLevel] ?? '#53452e';
  const riskLabel = report.riskLevel ? report.riskLevel.charAt(0).toUpperCase() + report.riskLevel.slice(1) : '—';

  // Build product name from profile confirmed facts or summary
  const productName = (() => {
    const f = report.profile.confirmed.find(r => r.field === 'product_name' || r.field === 'title' || r.field === 'name');
    if (f) return f.value;
    if (report.summary?.productDescription) return report.summary.productDescription;
    if (report.summary?.classification) return report.summary.classification.replace(/_/g, ' ');
    return 'this product';
  })();

  const classificationLabel = report.summary?.classification?.replace(/_/g, ' ') ?? '—';

  // Seller message
  const sellerMsg = `Hello, I'm considering ${order.quantity} units of ${productName} for delivery to ${order.city}, ${order.state}, India. `
    + `Please share the exact model and manufacturer, technical datasheet, applicable certificates and registration numbers with the covered model list, `
    + `country of origin, packaging and label photos, unit price, and a shipping quote with currency, mode and Incoterms. `
    + `Please ensure all documents match the offered product. Thank you.`;

  async function copySeller() {
    try { await navigator.clipboard.writeText(sellerMsg); setNotice('Seller request copied.'); }
    catch { setNotice('Select the seller request below and copy it manually.'); }
  }

  function exportReport() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url; a.download = `importsafe-report-${new Date().toISOString().slice(0, 10)}.json`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice('Report exported as JSON.');
  }

  async function submitAssumptions(e: React.FormEvent) {
    e.preventDefault();
    const overrides: Record<string, string> = {};
    for (const [k, v] of Object.entries(assumptions)) { if (v.trim()) overrides[k] = v.trim(); }
    if (!Object.keys(overrides).length) return;
    setRecalculating(true);
    try {
      await patchAssumptions(invId, overrides);
      await new Promise(r => setTimeout(r, 3000));
      await onRefresh();
      setNotice('Cost updated.');
    } catch {
      setNotice('Could not update cost assumptions.');
    } finally {
      setRecalculating(false);
    }
  }

  async function handleDelete() {
    try { await deleteInvestigation(invId); } catch { /* ignore */ }
    deleteDialog.current?.close();
    onDelete();
  }

  const chip = (i: number, label = `Evidence ${String(i + 1).padStart(2, '0')}`) =>
    <button className="evidence-chip" onClick={() => setActiveEvidence(i)}>{label} ↗</button>;

  const openedAt = new Date().toISOString();

  return <>
    <div className="report-heading">
      <div>
        <div className="workspace-eyebrow">YOUR IMPORT, IN PERSPECTIVE</div>
        <h1 ref={titleRef} tabIndex={-1}>The bigger picture<span>.</span></h1>
        <p>{productName} <span>·</span> {order.quantity} units <span>·</span> {order.city}, {order.state}</p>
      </div>
      <div className="report-tools">
        <button onClick={exportReport}>Export JSON ↓</button>
        <button onClick={() => window.print()}>Print / PDF ↗</button>
      </div>
    </div>

    <section className="report-outcome" style={{ background: outcome.bg, borderColor: outcome.border, color: outcome.color }}>
      <span className="outcome-symbol" aria-hidden="true" style={{ borderColor: outcome.border, color: outcome.color }}>{outcome.symbol}</span>
      <div>
        <div className="research-section-kicker" style={{ color: outcome.color }}>{outcome.kicker}</div>
        <h2 style={{ color: outcome.color }}>{outcome.heading}</h2>
        <p style={{ color: outcome.color }}>{report.disclaimer}</p>
      </div>
      <div className="outcome-risk" style={{ borderColor: outcome.border }}>
        <span style={{ color: outcome.color }}>OVERALL RISK</span>
        <strong style={{ color: riskColour }}>{riskLabel}</strong>
        <small style={{ color: outcome.color }}>Score: {report.score}</small>
      </div>
    </section>

    <nav className="report-section-nav" aria-label="Report sections">
      {['#report-summary', '#report-requirements', '#report-cost', '#report-next'].map((href, i) =>
        <a key={href} href={href} onClick={e => { e.preventDefault(); document.getElementById(href.slice(1))?.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth' }); }}>
          {['Overview', 'Requirements', 'Landed cost', 'Next steps'][i]}
        </a>
      )}
      <button onClick={() => setActiveEvidence(0)}>Evidence <span>{String(report.evidence.length).padStart(2, '0')}</span> ↗</button>
    </nav>

    <div className="report-grid">
      {/* Order at a glance */}
      <section className="research-panel report-summary" id="report-summary">
        <div className="research-panel-top"><h2>01 <span>Order at a glance</span></h2></div>
        <dl className="report-facts">
          {[
            ['Quantity', `${order.quantity} units`],
            ['Destination', `${order.city}, ${order.state}`],
            ['Purpose', order.purpose === 'resale' ? 'Business / resale' : 'Personal use'],
            ['Classification', classificationLabel],
            ['HS code', report.summary?.hsCode ?? 'Not determined'],
            ['Risk score', String(report.score)],
            ['Outcome', outcome.heading],
            ['Identity check', report.certificationComparison ? IDENTITY_LABEL[report.certificationComparison.result] ?? report.certificationComparison.result : 'Not run'],
            ['Illustrative cost / unit', report.cost ? moneyStr(report.cost.perUnitExpected) : '—'],
          ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl>
      </section>

      {/* Product profile */}
      <section className="research-panel report-profile">
        <div className="research-panel-top"><h2>02 <span>Product profile</span></h2></div>
        {report.profile.confirmed.length > 0 && (
          <div className="profile-group">
            <span className="profile-category">CONFIRMED</span>
            {report.profile.confirmed.map(f => <p key={f.field}><strong>{f.field.replace(/_/g, ' ')}:</strong> {f.value}</p>)}
          </div>
        )}
        {report.profile.claimed.length > 0 && (
          <div className="profile-group">
            <span className="profile-category">SELLER CLAIMS</span>
            {report.profile.claimed.map(f => <p key={f.field}><strong>{f.field.replace(/_/g, ' ')}:</strong> {f.value}</p>)}
          </div>
        )}
        {report.profile.confirmed.length === 0 && report.profile.claimed.length === 0 && (
          <div className="profile-group"><p>No profile facts available.</p></div>
        )}
      </section>
    </div>

    {/* Requirements */}
    <section className="research-panel requirements-panel" id="report-requirements">
      <div className="research-panel-top">
        <h2>03 <span>The requirement checks</span></h2>
        <span className="research-tag">{report.checks.filter(c => c.status === 'verified_ok').length} verified · {report.checks.filter(c => c.status !== 'verified_ok' && c.status !== 'not_applicable').length} open</span>
      </div>
      <p className="research-section-intro">A research checklist for this product. Every open check needs a current source and a product match.</p>
      <div className="requirements-table">
        <div className="requirements-table-head"><span>REQUIREMENT</span><span>STATUS & NOTES</span><span>RULE ID</span></div>
        {report.checks.map(check => (
          <div className="requirement-row" key={check.ruleId}>
            <h3>{check.title}</h3>
            <div>
              <span className="requirement-status">{CHECK_STATUS_LABEL[check.status] ?? check.status}</span>
              {check.notes && <p>{check.notes}</p>}
            </div>
            <div><small>Rule: {check.ruleId}</small></div>
          </div>
        ))}
      </div>
    </section>

    {/* Certificate comparison */}
    {report.certificationComparison && (
      <section className="research-panel certificate-panel">
        <div className="research-panel-top"><h2>04 <span>Do the documents match?</span></h2></div>
        <p className="research-section-intro">Seller documents compared with official registry records.</p>
        <div className="certificate-comparison">
          <div>
            <span className="research-section-kicker">SELLER / USER INPUT</span>
            <h3>{order.certificates.length ? order.certificates.join(', ') : 'No certificate supplied'}</h3>
          </div>
          <span className="comparison-symbol" aria-hidden="true">⇄</span>
          <div>
            <span className="research-section-kicker">OFFICIAL RECORD</span>
            <h3>{IDENTITY_LABEL[report.certificationComparison.result] ?? report.certificationComparison.result}</h3>
            {report.certificationComparison.summary && <p>{report.certificationComparison.summary}</p>}
          </div>
        </div>
        {report.certificationComparison.fieldMatches.length > 0 && (
          <div style={{ marginTop: 16 }}>
            {report.certificationComparison.fieldMatches.map(fm => (
              <p key={fm.field} className="comparison-note">
                <strong>{fm.field.replace(/_/g, ' ')}:</strong> {fm.detail} <em>({fm.match})</em>
              </p>
            ))}
          </div>
        )}
      </section>
    )}

    {/* Landed cost */}
    <section className="research-panel landed-panel" id="report-cost">
      <div className="research-panel-top"><h2>05 <span>A clearer view of the cost</span></h2>{chip(0, 'Cost evidence')}</div>
      <p className="research-section-intro">
        {report.cost?.label ?? 'Illustrative landed cost estimate. Rates are not verified.'}
      </p>
      {report.cost && (
        <div className="cost-ranges">
          {([
            ['Low scenario', String(parseFloat(report.cost.totalExpected) * 0.9), '−10% sensitivity'],
            ['Expected scenario', report.cost.totalExpected, 'Backend estimate'],
            ['High scenario', String(parseFloat(report.cost.totalExpected) * 1.15), '+15% sensitivity'],
          ] as [string, string, string][]).map(([label, value, note], i) => (
            <div key={label} className={i === 1 ? 'cost-expected' : ''}>
              <span>{label}</span>
              <strong>{moneyStr(value)}</strong>
              <small>{note}</small>
            </div>
          ))}
        </div>
      )}
      <p className="research-fineprint">Low and high are simple sensitivity scenarios, not quoted bounds. Insurance, storage and penalties are excluded.</p>
      {report.cost && (
        <div className="cost-layout">
          <div className="cost-breakdown">
            <h3>Your estimate</h3>
            <div><span>Per unit (expected)</span><strong>{moneyStr(report.cost.perUnitExpected)}</strong></div>
            <div className="cost-total"><span>Total (expected)<small>{order.quantity} units</small></span><strong>{moneyStr(report.cost.totalExpected)}</strong></div>
          </div>
          <form className="cost-inputs" onSubmit={submitAssumptions}>
            <h3>Adjust assumptions</h3>
            {([
              { key: 'freightInr' as const, label: 'Freight · INR' },
              { key: 'fxUsdInr' as const, label: 'INR per USD' },
              { key: 'bcdPct' as const, label: 'Basic customs duty · %' },
              { key: 'igstPct' as const, label: 'IGST · %' },
              { key: 'clearingInr' as const, label: 'Clearing fees · INR' },
            ]).map(({ key, label }) => (
              <label key={key}>{label}
                <input type="number" min="0" step="0.01" placeholder="Backend default"
                  value={assumptions[key]}
                  onChange={e => setAssumptions(a => ({ ...a, [key]: e.target.value }))} />
              </label>
            ))}
            <button type="submit" className="research-primary" disabled={recalculating} style={{ gridColumn: '1/-1', marginTop: 4 }}>
              {recalculating ? 'Recalculating…' : 'Update estimate ↗'}
            </button>
            <p className="research-fineprint" style={{ gridColumn: '1/-1' }}>
              {report.cost.ratesVerified ? 'Rates have been verified.' : 'Rates are illustrative placeholders, not verified tariff or exchange-rate data.'}
            </p>
          </form>
        </div>
      )}
    </section>

    {/* Next steps */}
    <section className="research-panel next-panel" id="report-next">
      <div className="research-panel-top">
        <h2>06 <span>Your next thoughtful steps</span></h2>
        <span className="research-tag">{done.length} / {report.nextActions.length} done</span>
      </div>
      <div className="next-layout">
        <div className="action-checklist">
          {report.nextActions.map((action, i) => (
            <label key={i} className={done.includes(i) ? 'action-complete' : ''}>
              <input type="checkbox" checked={done.includes(i)} onChange={e => setDone(d => e.target.checked ? [...d, i] : d.filter(n => n !== i))} />
              <span><small>PRIORITY {i + 1}</small>{action}</span>
            </label>
          ))}
        </div>
        <div className="seller-request">
          <div><h3>A message to move things along</h3><button onClick={copySeller}>Copy request ↗</button></div>
          <p>{sellerMsg}</p>
        </div>
      </div>
    </section>

    <div className="report-bottom">
      <button className="research-text-button" onClick={() => setActiveEvidence(0)}>
        Explore all {report.evidence.length} evidence {report.evidence.length === 1 ? 'entry' : 'entries'} ↗
      </button>
      <button className="delete-report" onClick={() => setDeleteOpen(true)}>Delete this report</button>
    </div>
    <p role="status" className="report-notice">{notice}</p>

    <footer className="research-report-footer">
      <p>{report.disclaimer}</p>
      <span>Generated {new Date(openedAt).toLocaleString()} · ImportSafe</span>
    </footer>

    {/* Evidence drawer */}
    <dialog ref={evidenceDialog} className="evidence-drawer" aria-labelledby="evidence-title"
      onCancel={() => setActiveEvidence(null)} onClose={() => setActiveEvidence(null)}>
      <div className="evidence-drawer-heading">
        <div><span className="research-section-kicker">A CLEARER PAPER TRAIL</span><h2 id="evidence-title">Behind the findings.</h2></div>
        <button aria-label="Close evidence drawer" onClick={() => evidenceDialog.current?.close()}>×</button>
      </div>
      <p>Sources and extractions separated from assumptions.</p>
      <nav aria-label="Evidence entries">
        {report.evidence.map((entry, i) => (
          <button key={entry.id} aria-pressed={activeEvidence === i} onClick={() => setActiveEvidence(i)}>
            {String(i + 1).padStart(2, '0')} {entry.title}
          </button>
        ))}
      </nav>
      {activeEvidence !== null && activeEvidence < report.evidence.length && (() => {
        const e = report.evidence[activeEvidence];
        return <article>
          <span className="research-tag">{e.kind}</span>
          <h3>{e.title}</h3>
          <blockquote>{e.excerpt}</blockquote>
          <p>{e.note}</p>
          <dl>
            <dt>Retrieved</dt><dd>{new Date(e.retrievedAt).toLocaleString()}</dd>
            <dt>Source</dt><dd>{e.sourceUrl ?? 'No external source'}</dd>
          </dl>
          {e.sourceUrl && <a href={e.sourceUrl} target="_blank" rel="noreferrer">Open source ↗</a>}
        </article>;
      })()}
    </dialog>

    {/* Delete dialog */}
    <dialog ref={deleteDialog} className="delete-dialog" aria-labelledby="delete-title"
      onClose={() => setDeleteOpen(false)} onCancel={() => setDeleteOpen(false)}>
      <h2 id="delete-title">Delete this report?</h2>
      <p>This permanently removes the investigation and all findings from the server.</p>
      <div>
        <button onClick={() => deleteDialog.current?.close()}>Keep report</button>
        <button onClick={handleDelete}>Delete report</button>
      </div>
    </dialog>
  </>;
}
