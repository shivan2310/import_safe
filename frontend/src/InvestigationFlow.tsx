import { useEffect, useRef, useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import './InvestigationFlow.css';

export type ImportOrder = {
  url: string; quantity: string; state: string; city: string; purpose: string;
  variant: string; shipping: string; currency: string; shippingMode: string; certificates: string[];
};
type ProductFacts = { source: 'demo' | 'manual'; name: string; model: string; manufacturer: string; unitPrice: string; wireless: boolean; battery: boolean };
const stages = [
  ['Read the listing', 'Collect the product details and seller information.'],
  ['Identify the product', 'Organise its model, intended use and technical features.'],
  ['Find requirements', 'Map the checks that need supporting evidence.'],
  ['Check evidence & claims', 'Compare seller documents with official records.'],
  ['Estimate landed cost', 'Build an editable estimate from your assumptions.'],
  ['Prepare your risk report', 'Bring open questions and next actions together.'],
];
const money = (value: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value);

/** Local prototype adapter: no extraction, registry checks or duty lookup is simulated as fact. */
export default function InvestigationFlow({ order, onBack, onLogout }: { order: ImportOrder; onBack: () => void; onLogout: () => void }) {
  const reduced = useReducedMotion();
  const isSample = order.url === 'https://www.alibaba.com/product-detail/100-bluetooth-speakers.html';
  const [stage, setStage] = useState(0);
  const [phase, setPhase] = useState<'running' | 'manual' | 'report'>('running');
  const [elapsed, setElapsed] = useState(0);
  const [facts, setFacts] = useState<ProductFacts>({ source: isSample ? 'demo' : 'manual', name: isSample ? 'Bluetooth speaker' : '', model: '', manufacturer: '', unitPrice: isSample ? '8' : '', wireless: isSample, battery: isSample });
  const [generated, setGenerated] = useState('');
  const title = useRef<HTMLHeadingElement>(null);
  const manualTitle = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = `${phase === 'report' ? 'Risk report' : 'Investigation'} — ImportSafe`;
    if (phase === 'manual') { manualTitle.current?.scrollIntoView({ block: 'center' }); manualTitle.current?.focus({ preventScroll: true }); }
    else { window.scrollTo({ top: 0, behavior: 'instant' }); title.current?.focus({ preventScroll: true }); }
  }, [phase]);
  useEffect(() => {
    if (phase !== 'running') return;
    const next = window.setTimeout(() => {
      if (stage === 0 && !isSample && !facts.name) setPhase('manual');
      else if (stage < stages.length - 1) setStage(s => s + 1);
      else { setGenerated(new Date().toISOString()); setPhase('report'); }
    }, 1500);
    return () => clearTimeout(next);
  }, [phase, stage, isSample, facts.name]);
  useEffect(() => {
    if (phase !== 'running') return;
    const clock = window.setInterval(() => setElapsed(t => t + 1), 1000);
    return () => clearInterval(clock);
  }, [phase]);

  return <div className="investigation-page research-page">
    <header className="workspace-header"><a className="workspace-brand" href="#home"><span aria-hidden="true">↗</span> importsafe<span className="workspace-brand-dot">.</span></a><nav aria-label="Workspace"><button onClick={onBack}>← New investigation</button><button onClick={onLogout}>Log out ↗</button></nav></header>
    <main className="research-main">
      <div className="research-breadcrumb"><span>Workspace</span><span>/</span><span>{phase === 'report' ? 'Your report' : 'Investigation'}</span><span className="research-mode">INTERACTIVE DEMO</span></div>
      {phase === 'report' ? <RiskReport order={order} facts={facts} generated={generated} onDelete={onBack} titleRef={title} /> : <>
        <div className="research-heading"><div className="workspace-eyebrow">FROM A FIND TO A CLEARER PLAN</div><h1 ref={title} tabIndex={-1}>A little research.<br /><em>A clearer direction.</em></h1><p>Your import details, one thoughtful step at a time.</p></div>
        <div className="research-progress-layout">
          <section className="research-panel stage-panel" aria-labelledby="progress-title"><div className="research-panel-top"><h2 id="progress-title">Your investigation</h2><span className="research-tag">{phase === 'manual' ? 'Needs your input' : 'In progress'}</span></div>
            <div className="research-progress-copy"><span>STEP {stage + 1} OF 6</span><span>{Math.round(stage / 6 * 100)}%</span></div><div className="research-progress-track" role="progressbar" aria-label="Investigation progress" aria-valuenow={stage} aria-valuemin={0} aria-valuemax={6}><motion.span initial={{ scaleX: 0 }} style={{ transformOrigin: 'left' }} animate={{ scaleX: stage / 6 }} transition={{ duration: reduced ? 0 : .5 }} /></div>
            <ol className="research-stages">{stages.map(([name, description], i) => <li key={name} className={i < stage ? 'complete' : i === stage ? 'current' : ''} aria-current={i === stage ? 'step' : undefined}><span className="research-stage-number">{i < stage ? '✓' : String(i + 1).padStart(2, '0')}</span><div><h3>{name}</h3><p>{description}</p>{i === stage && <span className="research-stage-state">{phase === 'manual' ? 'Waiting for your details' : 'Preparing demo preview…'}</span>}</div></li>)}</ol>
            <div className="research-progress-footer"><span>Elapsed {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}</span><button className="research-text-button" onClick={onBack}>Cancel investigation</button></div>
          </section>
          <aside className="research-side"><div className="research-orbit" aria-hidden="true"><span>↗</span><span className="orbit-label">CONNECTING THE DOTS</span></div><h2>Good decisions<br />start with good questions.</h2><p>We’ll keep the unknowns visible, so you know what to ask before you order.</p><div className="research-live" role="status"><span className="research-live-dot" />{phase === 'manual' ? 'The listing needs your help.' : `${stages[stage][0]} · demo workflow`}</div><div className="research-side-order"><span>YOUR IMPORT</span><strong>{order.quantity} units → {order.city}</strong><a href={order.url} target="_blank" rel="noreferrer">View product listing ↗</a></div><p className="research-fineprint">Prototype mode. TinyFish, official-record checks and live duty data are not connected. These stages demonstrate the intended workflow.</p></aside>
        </div>
        {phase === 'manual' && <section className="research-panel manual-panel"><div><span className="research-section-kicker">A QUICK HANDOFF</span><h2 ref={manualTitle} tabIndex={-1}>Tell us what’s on the listing.</h2><p>Live listing access is unavailable in this prototype. Enter the product details to continue with a report of the open checks.</p></div><form onSubmit={event => { event.preventDefault(); setStage(1); setPhase('running'); }}><div className="research-input-grid"><label>Product name *<input required pattern=".*\S.*" value={facts.name} onChange={e => setFacts({ ...facts, name: e.target.value })} /></label><label>Unit price (USD, optional)<input type="number" min="0" step="0.01" value={facts.unitPrice} onChange={e => setFacts({ ...facts, unitPrice: e.target.value })} /></label><label>Model number<input value={facts.model} onChange={e => setFacts({ ...facts, model: e.target.value })} /></label><label>Manufacturer<input value={facts.manufacturer} onChange={e => setFacts({ ...facts, manufacturer: e.target.value })} /></label></div><div className="research-checkboxes"><label><input type="checkbox" checked={facts.wireless} onChange={e => setFacts({ ...facts, wireless: e.target.checked })} /> Listing mentions wireless connectivity</label><label><input type="checkbox" checked={facts.battery} onChange={e => setFacts({ ...facts, battery: e.target.checked })} /> Listing mentions a battery</label></div><button className="research-primary">Continue to demo report ↗</button></form></section>}
      </>}
    </main>
  </div>;
}

function RiskReport({ order, facts, generated, onDelete, titleRef }: { order: ImportOrder; facts: ProductFacts; generated: string; onDelete: () => void; titleRef: React.RefObject<HTMLHeadingElement | null> }) {
  const reduced = useReducedMotion();
  const [activeEvidence, setActiveEvidence] = useState<number | null>(null);
  const [done, setDone] = useState<number[]>([]);
  const [notice, setNotice] = useState('');
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [cost, setCost] = useState({ price: facts.unitPrice, freight: order.shipping, fx: '84', duty: '10', surcharge: '10', tax: '18', fees: '1500' });
  const evidenceDialog = useRef<HTMLDialogElement>(null);
  const deleteDialog = useRef<HTMLDialogElement>(null);
  const evidence = [
    { title: 'Your import details', kind: 'User supplied', url: order.url, excerpt: `${order.quantity} units; ${order.city}, ${order.state}; ${order.purpose}; variant: ${order.variant || 'not provided'}.`, time: generated, note: 'Captured from this form. The linked listing has not been fetched.' },
    { title: 'Product details', kind: facts.source === 'manual' ? 'User supplied' : 'Demo fixture', url: order.url, excerpt: `${facts.name}; model: ${facts.model || 'unknown'}; manufacturer: ${facts.manufacturer || 'unknown'}. Wireless and battery indicators are unverified.`, time: generated, note: 'No seller page or official record has been retrieved.' },
    { title: 'Seller certificate numbers', kind: 'User supplied', url: '', excerpt: order.certificates.join(', ') || 'No certificate numbers provided.', time: generated, note: 'A certificate number alone does not establish validity or product coverage.' },
    { title: 'Cost assumptions', kind: 'Illustrative inputs', url: '', excerpt: `Unit price: USD ${cost.price || 'not supplied'}; freight: ${order.currency} ${cost.freight || '0'}; INR/USD: ${cost.fx}; duty: ${cost.duty}%; surcharge on duty: ${cost.surcharge}%; tax: ${cost.tax}%; other fees: INR ${cost.fees}. Sample calculator inputs, not a tariff determination.`, time: generated, note: 'No exchange-rate or tariff service was queried.' },
  ];
  useEffect(() => { if (activeEvidence !== null) evidenceDialog.current?.showModal(); }, [activeEvidence]);
  useEffect(() => { if (deleteOpen) deleteDialog.current?.showModal(); }, [deleteOpen]);
  // Explicit illustrative calculation: surcharge is a percentage of duty;
  // tax uses assessable value + duty + surcharge. Not a customs assessment.
  const n = (v: string) => Math.max(0, Number(v) || 0);
  const shippingFx: Record<string, number> = { USD: n(cost.fx), INR: 1, CNY: n(cost.fx) / 7.2, EUR: n(cost.fx) * 1.1 };
  const goods = n(cost.price) * Number(order.quantity) * n(cost.fx);
  const freight = n(cost.freight) * shippingFx[order.currency];
  const assessable = goods + freight;
  const duty = assessable * n(cost.duty) / 100;
  const surcharge = duty * n(cost.surcharge) / 100;
  const tax = (assessable + duty + surcharge) * n(cost.tax) / 100;
  const total = assessable + duty + surcharge + tax + n(cost.fees);
  const priced = cost.price !== '' && n(cost.fx) > 0;
  const tasks = ['Ask the seller for the exact model, manufacturer and technical datasheet.', 'Request the relevant certificate, registration scope and matching model list.', 'Verify applicable requirements with the relevant authority or a qualified broker.', 'Get a written freight quote and confirm the import cost assumptions.'];
  const sellerMessage = `Hello, I’m considering ${order.quantity} units of ${facts.name} for delivery to ${order.city}, ${order.state}, India. Please share the exact model and manufacturer, technical datasheet, applicable certificates and registration numbers with the covered model list, ${facts.wireless ? 'wireless specifications and any approval documents, ' : ''}${facts.battery ? 'battery chemistry, capacity and available transport test documents, ' : ''}country of origin, packaging/label photos, unit price, and a shipping quote with currency, mode and Incoterms. Please ensure all documents match the offered product. Thank you.`;
  async function copySeller() { try { await navigator.clipboard.writeText(sellerMessage); setNotice('Seller request copied.'); } catch { setNotice('Copy is unavailable. Select the seller request below and copy it manually.'); } }
  function exportReport() {
    const report = { mode: 'DEMO', generated, outcome: 'Insufficient information', overallRisk: 'Unassessed', order, product: facts, evidence, requirements: checks, cost: { assumptions: cost, currency: 'INR', estimate: priced ? total : null, illustrative: true }, actions: tasks.map((text, i) => ({ text, completed: done.includes(i) })), sellerMessage };
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = `importsafe-report-${generated.slice(0, 10)}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); setNotice('Report exported as JSON.');
  }
  const checks = [
    { title: 'Import policy & classification', detail: 'Confirm the exact product and classification before determining import policy.', status: 'Needs verification', source: 'https://www.dgft.gov.in/', rule: 'Not retrieved' },
    { title: 'BIS applicability', detail: 'Determine whether this exact product and model falls within an applicable standard or order.', status: 'Unassessed', source: 'https://www.bis.gov.in/', rule: 'Not retrieved' },
    { title: 'Wireless approval', detail: facts.wireless ? 'Wireless connectivity indicated. Frequency, power and approval documentation need review.' : 'Wireless capability has not been confirmed; establish specifications first.', status: 'Needs details', source: 'https://dot.gov.in/', rule: 'Not retrieved' },
    { title: 'Battery & transport', detail: facts.battery ? 'Battery indicated. Confirm chemistry, capacity and shipment documentation.' : 'Battery presence is unknown; ask the seller before selecting transport.', status: 'Needs details', source: '', rule: 'Not retrieved' },
    { title: 'Labelling & category checks', detail: 'Confirm intended use, packaging, labels and any category-specific obligations.', status: 'Unassessed', source: '', rule: 'Not retrieved' },
  ];
  const chip = (i: number, text = `Evidence ${String(i + 1).padStart(2, '0')}`) => <button className="evidence-chip" onClick={() => setActiveEvidence(i)}>{text} ↗</button>;
  return <>
    <div className="report-heading"><div><div className="workspace-eyebrow">YOUR IMPORT, IN PERSPECTIVE</div><h1 ref={titleRef} tabIndex={-1}>The bigger picture<span>.</span></h1><p>{facts.name} <span>·</span> {order.quantity} units <span>·</span> {order.city}, {order.state}</p></div><div className="report-tools"><button onClick={exportReport}>Export JSON ↓</button><button onClick={() => window.print()}>Print / PDF ↗</button></div></div>
    <div className="report-demo-note"><strong>Demo report</strong><span>Based on your inputs and illustrative data. No live listing, certificate or regulatory research has run.</span></div>
    <section className="report-outcome"><span className="outcome-symbol" aria-hidden="true">?</span><div><div className="research-section-kicker">OUTCOME · MORE EVIDENCE NEEDED</div><h2>Insufficient information</h2><p>Get the exact product documents and verify the applicable requirements before committing to an order.</p></div><div className="outcome-risk"><span>OVERALL RISK</span><strong>Unassessed</strong><small>Evidence is incomplete</small></div></section>
    <nav className="report-section-nav" aria-label="Report sections"><a href="#report-summary" onClick={e => { e.preventDefault(); document.getElementById('report-summary')?.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth' }); }}>Overview</a><a href="#report-requirements" onClick={e => { e.preventDefault(); document.getElementById('report-requirements')?.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth' }); }}>Requirements</a><a href="#report-cost" onClick={e => { e.preventDefault(); document.getElementById('report-cost')?.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth' }); }}>Landed cost</a><a href="#report-next" onClick={e => { e.preventDefault(); document.getElementById('report-next')?.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth' }); }}>Next steps</a><button onClick={() => setActiveEvidence(0)}>Evidence <span>04</span> ↗</button></nav>
    <div className="report-grid">
      <section className="research-panel report-summary" id="report-summary"><div className="research-panel-top"><h2>01 <span>Order at a glance</span></h2>{chip(0, 'Your inputs')}</div><dl className="report-facts">{[['Quantity', `${order.quantity} units`], ['Destination', `${order.city}, ${order.state}`], ['Purpose', order.purpose === 'resale' ? 'Business / resale' : 'Personal use'], ['Classification', 'Not determined'], ['BIS applicability', 'Not assessed'], ['Wireless approval', 'Not verified'], ['Seller BIS claim', 'Not independently retrieved'], ['Model / manufacturer match', 'Not established'], ['Illustrative cost / unit', priced ? money(total / Number(order.quantity)) : 'Add a unit price']].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></section>
      <section className="research-panel report-profile"><div className="research-panel-top"><h2>02 <span>Product profile</span></h2></div><div className="profile-group"><span className="profile-category">CONFIRMED</span><p>No product facts independently confirmed yet.</p></div><div className="profile-group"><span className="profile-category">SELLER CLAIMS</span><p>Seller claims have not been retrieved or validated.</p>{chip(2, 'Certificate inputs')}</div><div className="profile-group"><span className="profile-category">{facts.source === 'manual' ? 'USER SUPPLIED' : 'DEMO / USER INPUTS'}</span><p><strong>{facts.name}</strong><br />Variant: {order.variant || 'Not supplied'}<br />Model: {facts.model || 'Not supplied'}<br />Manufacturer: {facts.manufacturer || 'Not supplied'}</p>{chip(1)}</div></section>
    </div>
    <section className="research-panel requirements-panel" id="report-requirements"><div className="research-panel-top"><h2>03 <span>The requirement checks</span></h2><span className="research-tag">0 verified · 5 open</span></div><p className="research-section-intro">A research checklist for this product. Every open check needs a current source and a product match.</p><div className="requirements-table"><div className="requirements-table-head"><span>REQUIREMENT</span><span>STATUS & REASONING</span><span>SOURCE / RULE VERSION</span></div>{checks.map(check => <div className="requirement-row" key={check.title}><h3>{check.title}</h3><div><span className="requirement-status">{check.status}</span><p>{check.detail}</p></div><div>{check.source ? <a href={check.source} target="_blank" rel="noreferrer">Authority website ↗</a> : <span>Source needed</span>}<small>Rule version: {check.rule}</small><small>No supporting source retrieved</small></div></div>)}</div></section>
    <section className="research-panel certificate-panel"><div className="research-panel-top"><h2>04 <span>Do the documents match?</span></h2>{chip(2)}</div><p className="research-section-intro">Compare the offered product with the scope of the official registration.</p><div className="certificate-comparison"><div><span className="research-section-kicker">SELLER / USER INPUT</span><h3>{order.certificates.length ? order.certificates.join(', ') : 'No certificate supplied'}</h3><p>Model: {facts.model || 'Unknown'}<br />Manufacturer: {facts.manufacturer || 'Unknown'}</p></div><span className="comparison-symbol" aria-hidden="true">⇄</span><div><span className="research-section-kicker">OFFICIAL RECORD</span><h3>Awaiting verification</h3><p>Registration holder, covered models, validity and scope have not been retrieved.</p></div></div><p className="comparison-note">Match status: undetermined. A potential certification mismatch can only be flagged once both records are available.</p></section>
    <section className="research-panel landed-panel" id="report-cost"><div className="research-panel-top"><h2>05 <span>A clearer view of the cost</span></h2>{chip(3, 'Assumptions')}</div><p className="research-section-intro">An illustrative calculator, in INR. Edit assumptions to see the estimate change. Sample rates are not current tariff or exchange-rate advice.</p><div className="cost-ranges">{[['Low scenario', total * .9, '−10% sensitivity'], ['Expected scenario', total, 'Your current assumptions'], ['High scenario', total * 1.15, '+15% sensitivity']].map(([label, value, note], i) => <div key={String(label)} className={i === 1 ? 'cost-expected' : ''}><span>{label}</span><strong>{priced ? money(Number(value)) : '—'}</strong><small>{note}</small></div>)}</div><p className="research-fineprint">Low and high are simple sensitivity scenarios, not quoted bounds. Insurance, storage, penalties and other charges are excluded.</p><div className="cost-layout"><form className="cost-inputs" onSubmit={e => e.preventDefault()}><h3>Make the assumptions yours</h3>{([{ key: 'price', label: 'Unit price · USD', step: '.01' }, { key: 'freight', label: `Freight · ${order.currency}`, step: '.01' }, { key: 'fx', label: 'INR per USD', step: '.01' }, { key: 'duty', label: 'Duty · %', step: '.1' }, { key: 'surcharge', label: 'Surcharge on duty · %', step: '.1' }, { key: 'tax', label: 'Tax · %', step: '.1' }, { key: 'fees', label: 'Handling / other fees · INR', step: '1' }] as const).map(({ key, label, step }) => <label key={key}>{label}<input type="number" min="0" step={step} value={cost[key]} onChange={e => setCost({ ...cost, [key]: e.target.value })} /></label>)}<p className="research-fineprint">Freight conversion assumptions: CNY = USD / 7.2; EUR = USD × 1.1. Replace with your quote. Missing freight is treated as zero.</p></form><div className="cost-breakdown" aria-live="polite" aria-atomic="true"><h3>Where the estimate comes from</h3>{[[`Goods · ${order.quantity} × unit price × FX`, goods], [`Freight · ${order.shippingMode || 'mode not set'}`, freight], ['Assessable base · goods + freight', assessable], [`Duty · ${cost.duty || 0}% of base`, duty], [`Surcharge · ${cost.surcharge || 0}% of duty`, surcharge], [`Tax · ${cost.tax || 0}% of base + duty + surcharge`, tax], ['Handling / other fees', n(cost.fees)]].map(([label, amount]) => <div key={String(label)}><span>{label}</span><strong>{priced ? money(Number(amount)) : '—'}</strong></div>)}<div className="cost-total"><span>Illustrative total<small>{priced ? `${money(total / Number(order.quantity))} per unit` : 'Add a unit price to calculate'}</small></span><strong>{priced ? money(total) : '—'}</strong></div></div></div></section>
    <section className="research-panel next-panel" id="report-next"><div className="research-panel-top"><h2>06 <span>Your next thoughtful steps</span></h2><span className="research-tag">{done.length} / {tasks.length} done</span></div><div className="next-layout"><div className="action-checklist">{tasks.map((task, i) => <label key={task} className={done.includes(i) ? 'action-complete' : ''}><input type="checkbox" checked={done.includes(i)} onChange={e => setDone(current => e.target.checked ? [...current, i] : current.filter(n => n !== i))} /><span><small>PRIORITY {i + 1}</small>{task}</span></label>)}</div><div className="seller-request"><div><h3>A message to move things along</h3><button onClick={copySeller}>Copy request ↗</button></div><p>{sellerMessage}</p></div></div></section>
    <div className="report-bottom"><button className="research-text-button" onClick={() => setActiveEvidence(0)}>Explore all 4 evidence entries ↗</button><button className="delete-report" onClick={() => setDeleteOpen(true)}>Delete this report</button></div><p role="status" className="report-notice">{notice}</p>
    <footer className="research-report-footer"><p>Decision support, not legal clearance, customs approval or a final duty quote. Verify requirements and estimates before ordering.</p><span>Generated {new Date(generated).toLocaleString()} · Local demo · Not saved to a server</span></footer>
    <dialog ref={evidenceDialog} className="evidence-drawer" aria-labelledby="evidence-title" onCancel={() => setActiveEvidence(null)} onClose={() => setActiveEvidence(null)}><div className="evidence-drawer-heading"><div><span className="research-section-kicker">A CLEARER PAPER TRAIL</span><h2 id="evidence-title">Behind the findings.</h2></div><button aria-label="Close evidence drawer" onClick={() => evidenceDialog.current?.close()}>×</button></div><p>Inputs and assumptions are separated from independently retrieved evidence.</p><nav aria-label="Evidence entries">{evidence.map((entry, i) => <button key={entry.title} aria-pressed={activeEvidence === i} onClick={() => setActiveEvidence(i)}>0{i + 1} {entry.title}</button>)}</nav>{activeEvidence !== null && <article><span className="research-tag">{evidence[activeEvidence].kind}</span><h3>{evidence[activeEvidence].title}</h3><blockquote>{evidence[activeEvidence].excerpt}</blockquote><p>{evidence[activeEvidence].note}</p><dl><dt>Captured</dt><dd>{new Date(evidence[activeEvidence].time).toLocaleString()}</dd><dt>Retrieval status</dt><dd>No external source retrieved</dd></dl>{evidence[activeEvidence].url && <a href={evidence[activeEvidence].url} target="_blank" rel="noreferrer">Open submitted listing ↗</a>}</article>}</dialog>
    <dialog ref={deleteDialog} className="delete-dialog" aria-labelledby="delete-title" onClose={() => setDeleteOpen(false)} onCancel={() => setDeleteOpen(false)}><h2 id="delete-title">Clear this demo report?</h2><p>This clears the report, calculator edits and checklist. Your original form details remain available.</p><div><button onClick={() => deleteDialog.current?.close()}>Keep report</button><button onClick={() => { deleteDialog.current?.close(); onDelete(); }}>Clear report</button></div></dialog>
  </>;
}
