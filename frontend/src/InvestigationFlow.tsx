import ProfileMenu from './ProfileMenu';
import { api, type FullReport, type InvStatus, type PendingQuestion } from './api';
import SimilarProducts from './SimilarProducts';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import './InvestigationFlow.css';

export type ImportOrder = {
  url: string; quantity: string; state: string; city: string; purpose: string;
  variant: string; shipping: string; currency: string; shippingMode: string; certificates: string[];
};

const UI_STAGES = [
  ['Read the listing', 'Collect the product details and seller information.'],
  ['Identify the product', 'Organise its model, intended use and technical features.'],
  ['Find requirements', 'Map the checks that need supporting evidence.'],
  ['Check evidence & claims', 'Compare seller documents with official records.'],
  ['Estimate landed cost', 'Build an editable estimate from your assumptions.'],
  ['Prepare your risk report', 'Bring open questions and next actions together.'],
];

const TERMINAL: Set<InvStatus> = new Set(['REPORT_READY', 'NEEDS_INPUT', 'FAILED', 'CANCELLED', 'EXPIRED', 'DELETED']);
const POLL_MS = 2500;

function statusToStage(status: InvStatus): number {
  switch (status) {
    case 'CREATED': case 'READING_LISTING': return 0;
    case 'PROFILE_BUILT': case 'CLASSIFIED': return 1;
    case 'CHECKING_REQUIREMENTS': return 2;
    case 'VERIFYING_CLAIMS': return 3;
    case 'ESTIMATING_COST': return 4;
    default: return 5;
  }
}

const money = (v: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v);

export default function InvestigationFlow({ order, onBack, onLogout, historyControl }: {
  order: ImportOrder; onBack: () => void; onLogout: () => void; historyControl: ReactNode
}) {
  const reduced = useReducedMotion();
  const [invId, setInvId] = useState<string | null>(null);
  const [status, setStatus] = useState<InvStatus>('CREATED');
  const [stage, setStage] = useState(0);
  const [pendingQuestion, setPendingQuestion] = useState<PendingQuestion | null>(null);
  const [report, setReport] = useState<FullReport | null>(null);
  const [phase, setPhase] = useState<'starting' | 'running' | 'question' | 'report' | 'error'>('starting');
  const [errorMsg, setErrorMsg] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [answerValue, setAnswerValue] = useState('');
  const title = useRef<HTMLHeadingElement>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    document.title = `${phase === 'report' ? 'Risk report' : 'Investigation'} — ImportSafe`;
    window.scrollTo({ top: 0, behavior: 'instant' });
    title.current?.focus({ preventScroll: true });
  }, [phase]);

  // Create the investigation once on mount
  useEffect(() => {
    let cancelled = false;
    async function create() {
      try {
        const data = await api.createInvestigation({
          url: order.url,
          quantity: Number(order.quantity),
          purpose: order.purpose || undefined,
          variant: order.variant || undefined,
          destination: (order.state || order.city) ? { state: order.state || undefined, city: order.city || undefined } : undefined,
          shipping: order.shipping ? { amount: order.shipping, currency: order.currency, mode: order.shippingMode || undefined } : undefined,
          sellerCertificates: order.certificates.length ? order.certificates : undefined,
        });
        if (!cancelled) { setInvId(data.id); setPhase('running'); }
      } catch (err) {
        if (!cancelled) { setErrorMsg((err as Error).message || 'Could not start investigation.'); setPhase('error'); }
      }
    }
    void create();
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Elapsed clock
  useEffect(() => {
    if (phase !== 'running' && phase !== 'question') return;
    const id = window.setInterval(() => setElapsed(t => t + 1), 1000);
    return () => clearInterval(id);
  }, [phase]);

  // Poll for status while running
  useEffect(() => {
    if (phase !== 'running' || !invId) return;
    let cancelled = false;
    async function poll() {
      try {
        const data = await api.getInvestigation(invId!);
        if (cancelled) return;
        setStatus(data.status);
        setStage(statusToStage(data.status));
        if (data.status === 'NEEDS_INPUT' && data.pendingQuestion) {
          setPendingQuestion(data.pendingQuestion);
          setPhase('question');
        } else if (data.status === 'REPORT_READY') {
          const rep = await api.getReport(invId!);
          if (!cancelled) { setReport(rep); setPhase('report'); }
        } else if (data.status === 'FAILED') {
          setErrorMsg('The investigation could not be completed. Please try again.');
          setPhase('error');
        } else if (TERMINAL.has(data.status)) {
          setErrorMsg(`Investigation ended with status: ${data.status}`);
          setPhase('error');
        } else {
          pollRef.current = window.setTimeout(poll, POLL_MS);
        }
      } catch (err) {
        if (!cancelled) {
          setErrorMsg((err as Error).message || 'Lost connection to the server.');
          setPhase('error');
        }
      }
    }
    void poll();
    return () => { cancelled = true; if (pollRef.current) clearTimeout(pollRef.current); };
  }, [phase, invId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submitAnswer(skipped: boolean) {
    if (!invId || !pendingQuestion) return;
    try {
      await api.postAnswer(invId, skipped ? { questionId: pendingQuestion.id, skipped: true } : { questionId: pendingQuestion.id, value: answerValue });
      setAnswerValue(''); setPendingQuestion(null); setPhase('running');
    } catch (err) {
      setErrorMsg((err as Error).message || 'Could not submit answer.');
    }
  }

  async function handleDelete() {
    if (invId) { try { await api.deleteInvestigation(invId); } catch { /* best effort */ } }
    onBack();
  }

  const progressPct = stage / (UI_STAGES.length - 1);

  return <div className="investigation-page research-page">
    <header className="workspace-header">
      <div className="workspace-header-start">
        {historyControl}
        <a className="workspace-brand" href="#analyze" onClick={onBack}>
          <img className="site-logo" src="/logo.png" alt="" width="40" height="40" /> importsafe
        </a>
      </div>
      <nav aria-label="Workspace">
        {phase === 'report' && <button className="new-investigation-button" onClick={onBack}>New investigation</button>}
        <ProfileMenu onLogout={onLogout} />
      </nav>
    </header>

    <main className="research-main">
      <div className="research-breadcrumb">
        <span>Workspace</span><span>/</span>
        <span>{phase === 'report' ? 'Your report' : 'Investigation'}</span>
      </div>

      {phase === 'error' && (
        <div className="research-panel" style={{ textAlign: 'center', padding: '3rem 2rem' }}>
          <h2>Something went wrong</h2>
          <p style={{ marginBottom: '1.5rem' }}>{errorMsg}</p>
          <button className="research-primary" onClick={onBack}>Back to form</button>
        </div>
      )}

      {phase === 'report' && report && (
        <LiveReport order={order} report={report} onDelete={handleDelete} titleRef={title} invId={invId!} />
      )}

      {(phase === 'starting' || phase === 'running' || phase === 'question') && <>
        <div className="research-heading">
          <div className="workspace-eyebrow">FROM A FIND TO A CLEARER PLAN</div>
          <h1 ref={title} tabIndex={-1}>A little research<br /><em>A clearer direction</em></h1>
          <p>Your import details, one thoughtful step at a time.</p>
        </div>
        <div className="research-progress-layout">
          <section className="research-panel stage-panel" aria-labelledby="progress-title">
            <div className="research-panel-top">
              <h2 id="progress-title">Your investigation</h2>
              <span className="research-tag">{phase === 'question' ? 'Needs your input' : phase === 'starting' ? 'Starting…' : 'In progress'}</span>
            </div>
            <div className="research-progress-copy">
              <span>STEP {stage + 1} OF {UI_STAGES.length}</span>
              <span>{Math.round(progressPct * 100)}%</span>
            </div>
            <div className="research-progress-track" role="progressbar" aria-label="Investigation progress" aria-valuenow={stage} aria-valuemin={0} aria-valuemax={UI_STAGES.length}>
              <motion.span initial={{ scaleX: 0 }} style={{ transformOrigin: 'left' }} animate={{ scaleX: progressPct }} transition={{ duration: reduced ? 0 : .5 }} />
            </div>
            <ol className="research-stages">
              {UI_STAGES.map(([name, description], i) => (
                <li key={name} className={i < stage ? 'complete' : i === stage ? 'current' : ''} aria-current={i === stage ? 'step' : undefined}>
                  <span className="research-stage-number">{i < stage ? '✓' : String(i + 1).padStart(2, '0')}</span>
                  <div>
                    <h3>{name}</h3><p>{description}</p>
                    {i === stage && <span className="research-stage-state">{phase === 'question' ? 'Waiting for your answer' : 'Connecting to backend…'}</span>}
                  </div>
                </li>
              ))}
            </ol>
            <div className="research-progress-footer">
              <span>Elapsed {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}</span>
              <button className="research-text-button" onClick={handleDelete}>Cancel investigation</button>
            </div>
          </section>

          <aside className="research-side">
            <div className="research-orbit" aria-hidden="true"><span>↗</span><span className="orbit-label">CONNECTING THE DOTS</span></div>
            <h2>Good decisions<br />start with good questions</h2>
            <p>We'll keep the unknowns visible, so you know what to ask before you order.</p>
            <div className="research-live" role="status">
              <span className="research-live-dot" />
              {phase === 'question' ? 'Your answer is needed to continue.' : phase === 'starting' ? 'Starting investigation…' : `${UI_STAGES[stage][0]} · live`}
            </div>
            <div className="research-side-order">
              <span>YOUR IMPORT</span>
              <strong>{order.quantity} units → {order.city}</strong>
              <a href={order.url} target="_blank" rel="noreferrer">View product listing ↗</a>
            </div>
          </aside>
        </div>

        {phase === 'question' && pendingQuestion && (
          <section className="research-panel manual-panel">
            <div>
              <span className="research-section-kicker">A QUICK HANDOFF</span>
              <h2 tabIndex={-1}>{pendingQuestion.prompt}</h2>
              {pendingQuestion.whyItMatters && <p>{pendingQuestion.whyItMatters}</p>}
            </div>
            <form onSubmit={e => { e.preventDefault(); void submitAnswer(false); }}>
              <div className="research-input-grid">
                <label>
                  Your answer *
                  <input required value={answerValue} onChange={e => setAnswerValue(e.target.value)} />
                </label>
              </div>
              <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem' }}>
                <button className="research-primary" type="submit">Continue ↗</button>
                <button className="research-text-button" type="button" onClick={() => void submitAnswer(true)}>Skip this question</button>
              </div>
            </form>
          </section>
        )}
      </>}
    </main>
  </div>;
}

// ---------------------------------------------------------------------------
// Live report component — renders real backend data
// ---------------------------------------------------------------------------

const OUTCOME_LABEL: Record<string, string> = {
  proceed: 'Ready to proceed',
  proceed_with_caution: 'Proceed with caution',
  needs_review: 'Needs review',
  do_not_proceed: 'Do not proceed',
  insufficient_information: 'More information needed',
};

const RISK_LABEL: Record<string, string> = {
  low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical', unassessed: 'Unassessed',
};

const CHECK_STATUS_LABEL: Record<string, string> = {
  verified: 'Clear',
  not_applicable: 'Not applicable',
  potentially_applicable: 'May apply',
  unverified: 'Needs details',
  contradiction_detected: 'Flagged',
};

// Label map for cost breakdown lines — display names only, no backend schema changes
const COST_LABEL_MAP: Record<string, string> = {
  goods: 'Goods value',
  goods_value: 'Goods value',
  freight: 'Freight & insurance',
  landing_charge_notional: 'Landing charge (notional)',
  assessable_value: 'Assessable value',
  bcd: 'Basic customs duty',
  sws: 'Social welfare surcharge',
  igst: 'IGST',
  duties_and_taxes: 'Duties and taxes',
  port_cfs: 'Port / CFS charges',
  domestic_transport: 'Domestic transport',
  clearing: 'Clearing charges',
  certification: 'Certification',
};

function costLabel(line: { label: string; kind: string }) {
  return COST_LABEL_MAP[line.kind] ?? COST_LABEL_MAP[line.label.toLowerCase().replace(/\s+/g, '_')] ?? line.label;
}

function LiveReport({ order, report, onDelete, titleRef, invId }: {
  order: ImportOrder; report: FullReport; onDelete: () => void;
  titleRef: React.RefObject<HTMLHeadingElement | null>; invId: string;
}) {
  const reduced = useReducedMotion();
  const [done, setDone] = useState<number[]>([]);
  const [notice, setNotice] = useState('');
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const deleteDialog = useRef<HTMLDialogElement>(null);

  useEffect(() => () => { if (noticeTimer.current) clearTimeout(noticeTimer.current); }, []);
  useEffect(() => { if (deleteOpen) deleteDialog.current?.showModal(); }, [deleteOpen]);

  function showNotice(msg: string) {
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    setNotice(msg);
    noticeTimer.current = setTimeout(() => setNotice(''), 4000);
  }

  const allFacts = [
    ...report.profile.confirmed.map(f => ({ ...f, section: 'Confirmed' })),
    ...report.profile.sellerClaims.map(f => ({ ...f, section: 'Seller claims' })),
    ...report.profile.userSupplied.map(f => ({ ...f, section: 'Your input' })),
  ];

  const productName = (
    allFacts.find(f => f.field === 'name' || f.field === 'title' || f.field === 'product_name')?.value as string | undefined
  ) ?? '';

  // Build specs dict from confirmed/seller-claim facts for the search query
  const specsForSearch = Object.fromEntries(
    allFacts
      .filter(f => !['name', 'title', 'product_name', 'price', 'currency', 'moq'].includes(f.field))
      .slice(0, 8)
      .map(f => [f.field, f.value])
  );
  const quantity = report.summary.quantity ?? Number(order.quantity);

  async function exportReport() {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url;
    a.download = `importsafe-report-${report.id}.json`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showNotice('Report exported as JSON.');
  }

  const actions = report.nextActions.length ? report.nextActions : [
    { priority: 1, text: 'Ask the seller for the exact model, manufacturer and technical datasheet.' },
    { priority: 2, text: 'Request the relevant certificate, registration scope and matching model list.' },
    { priority: 3, text: 'Verify applicable requirements with the relevant authority or a qualified broker.' },
    { priority: 4, text: 'Get a written freight quote and confirm the import cost assumptions.' },
  ];

  const outcomeKey = report.outcome.toLowerCase();
  const riskKey = report.riskLevel.toLowerCase();

  return <>
    <div className="report-heading">
      <div>
        <div className="workspace-eyebrow">YOUR IMPORT, IN PERSPECTIVE</div>
        <h1 ref={titleRef} tabIndex={-1}>The bigger picture</h1>
        <p>{productName ?? 'Your product'} <span>·</span> {quantity} units <span>·</span> {order.city}{order.state ? `, ${order.state}` : ''}</p>
      </div>
      <div className="report-tools">
        <button onClick={exportReport}>Export JSON</button>
        <button onClick={() => window.print()}>Print PDF</button>
      </div>
    </div>

    <section className="report-outcome">
      <span className="outcome-symbol" aria-hidden="true">{outcomeKey === 'proceed' ? '✓' : outcomeKey === 'do_not_proceed' ? '✗' : '!'}</span>
      <div>
        <div className="research-section-kicker">OUTCOME · {(OUTCOME_LABEL[outcomeKey] ?? report.outcome).toUpperCase()}</div>
        <h2>{OUTCOME_LABEL[outcomeKey] ?? report.outcome}</h2>
        {report.reasons.length > 0 && <p>{report.reasons[0]}</p>}
      </div>
      <div className="outcome-risk">
        <span>OVERALL RISK</span>
        <strong>{RISK_LABEL[riskKey] ?? report.riskLevel}</strong>
        <small>Score: {report.score}</small>
      </div>
    </section>

    <nav className="report-section-nav" aria-label="Report sections">
      {['#report-summary', '#report-requirements', '#report-profile', '#report-cost', '#report-next'].map((href, i) => (
        <a key={href} href={href} onClick={e => { e.preventDefault(); document.getElementById(href.slice(1))?.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth' }); }}>
          {['Overview', 'Requirements', 'Profile', 'Landed cost', 'Next steps'][i]}
        </a>
      ))}
    </nav>

    <div className="report-grid">
      <section className="research-panel report-summary" id="report-summary">
        <div className="research-panel-top"><h2>01 <span>Order at a glance</span></h2></div>
        <dl className="report-facts">
          {[
            ['Quantity', `${quantity} units`],
            ['Destination', [order.city, order.state].filter(Boolean).join(', ') || 'Not specified'],
            ['Purpose', order.purpose === 'resale' ? 'Business / resale' : 'Personal use'],
            ['Classification', report.summary.classification?.value ?? 'Not determined'],
            ['BIS', report.summary.bis ? CHECK_STATUS_LABEL[report.summary.bis] ?? report.summary.bis : 'Not assessed'],
            ['Wireless approval', report.summary.wireless ? CHECK_STATUS_LABEL[report.summary.wireless] ?? report.summary.wireless : 'Not assessed'],
            ['Identity match', report.summary.identityMatch ?? 'Not established'],
            ['Illustrative cost / unit', report.summary.illustrativeCostPerUnit
              ? `${report.summary.illustrativeCostPerUnit.currency} ${report.summary.illustrativeCostPerUnit.expected}`
              : report.cost ? money(Number(report.cost.perUnitExpected)) : '—'],
          ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl>
      </section>

      <section className="research-panel report-profile" id="report-profile">
        <div className="research-panel-top"><h2>02 <span>Product profile</span></h2></div>
        {['Confirmed', 'Seller claims', 'Your input'].map(section => {
          const facts = allFacts.filter(f => f.section === section);
          return <div key={section} className="profile-group">
            <span className="profile-category">{section.toUpperCase()}</span>
            {facts.length === 0
              ? <p>No {section.toLowerCase()} facts available.</p>
              : <dl style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '.5rem .75rem', margin: 0 }}>
                  {facts.map(f => <div key={f.field}><dt style={{ fontSize: '.75rem', opacity: .6 }}>{f.field.replace(/_/g, ' ')}</dt><dd style={{ margin: 0 }}>{String(f.value)}</dd></div>)}
                </dl>}
          </div>;
        })}
      </section>
    </div>

    <section className="research-panel requirements-panel" id="report-requirements">
      <div className="research-panel-top">
        <h2>03 <span>The requirement checks</span></h2>
        <span className="research-tag">{report.checks.filter(c => c.status === 'verified' || c.status === 'not_applicable').length} clear · {report.checks.filter(c => c.status !== 'verified' && c.status !== 'not_applicable').length} open</span>
      </div>
      <p className="research-section-intro">Compliance checks identified for this product.</p>
      <div className="requirements-table">
        <div className="requirements-table-head"><span>REQUIREMENT</span><span>STATUS & REASONING</span><span>RULE VERSION</span></div>
        {report.checks.map(check => (
          <div className="requirement-row" key={check.ruleId}>
            <h3>{check.area}{check.mandatory && <span style={{ fontSize: '.7rem', marginLeft: '.5rem', opacity: .6 }}>MANDATORY</span>}</h3>
            <div>
              <span className="requirement-status">{CHECK_STATUS_LABEL[check.status] ?? check.status}</span>
              <p>{check.reasoning}</p>
            </div>
            <div><small>Rule: {check.ruleVersion}</small></div>
          </div>
        ))}
      </div>
    </section>

    {report.cost && (
      <section className="research-panel landed-panel" id="report-cost">
        <div className="research-panel-top"><h2>04 <span>A clearer view of the cost</span></h2></div>
        <p className="research-section-intro">Illustrative landed cost estimate in {report.cost.currency}.</p>
        <div className="cost-ranges">
          {[
            ['Low scenario', Number(report.cost.low), '−10% sensitivity'],
            ['Expected scenario', Number(report.cost.expected), 'Your current assumptions'],
            ['High scenario', Number(report.cost.high), '+15% sensitivity'],
          ].map(([label, value, note], i) => (
            <div key={String(label)} className={i === 1 ? 'cost-expected' : ''}>
              <span>{label}</span>
              <strong>{money(Number(value))}</strong>
              <small>{String(note)}</small>
            </div>
          ))}
        </div>
        {/* Two-column layout: cost breakdown (left) + similar products (right) */}
        <div className="cost-and-similar-layout">
          <div className="cost-breakdown">
            <h3>Where the estimate comes from</h3>
            {report.cost.breakdown.map(line => (
              <div key={line.label}>
                <span>{costLabel(line)}</span>
                <strong>{money(Number(line.amount))}</strong>
              </div>
            ))}
            <div className="cost-total">
              <span>Expected total<small>{money(Number(report.cost.perUnitExpected))} per unit</small></span>
              <strong>{money(Number(report.cost.expected))}</strong>
            </div>
          </div>
          <div className="similar-products-column">
            <SimilarProducts
              productName={productName || order.url}
              specs={specsForSearch}
              investigationId={invId}
              report={report}
            />
          </div>
        </div>
        <p className="research-fineprint">{report.cost.breakdownNote}</p>
      </section>
    )}

    <section className="research-panel next-panel" id="report-next">
      <div className="research-panel-top">
        <h2>05 <span>Your next thoughtful steps</span></h2>
        <span className="research-tag">{done.length} / {actions.length} done</span>
      </div>
      <div className="next-layout">
        <div className="action-checklist">
          {actions.sort((a, b) => a.priority - b.priority).map((action, i) => (
            <label key={action.text} className={done.includes(i) ? 'action-complete' : ''}>
              <input type="checkbox" checked={done.includes(i)}
                onChange={e => setDone(cur => e.target.checked ? [...cur, i] : cur.filter(n => n !== i))} />
              <span><small>PRIORITY {action.priority}</small>{action.text}</span>
            </label>
          ))}
        </div>
      </div>
    </section>

    <div className="report-bottom">
      <button className="delete-report" onClick={() => setDeleteOpen(true)}>Delete this report</button>
    </div>

    <div role="status" aria-live="polite" aria-atomic="true" className={notice ? 'report-toast' : 'report-toast-empty'}>{notice}</div>

    <footer className="research-report-footer">
      <p>{report.disclaimer}</p>
      <span>Report ID: {report.id}</span>
    </footer>

    <dialog ref={deleteDialog} className="delete-dialog" aria-labelledby="delete-title"
      onClose={() => setDeleteOpen(false)} onCancel={() => setDeleteOpen(false)}>
      <h2 id="delete-title">Delete this report?</h2>
      <p>This will permanently delete the investigation and its report.</p>
      <div>
        <button onClick={() => deleteDialog.current?.close()}>Keep report</button>
        <button onClick={() => { deleteDialog.current?.close(); onDelete(); }}>Delete report</button>
      </div>
    </dialog>
  </>;
}
