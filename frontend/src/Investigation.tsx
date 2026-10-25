import ProfileMenu from './ProfileMenu';
import SearchHistory, { readHistory, saveHistory, type HistoryEntry } from './SearchHistory';
import type { ImportOrder } from './InvestigationFlow';
import { useEffect, useState, type FormEvent } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import './Investigation.css';
import InvestigationFlow from './InvestigationFlow';

const states = ['Andaman and Nicobar Islands', 'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chandigarh', 'Chhattisgarh', 'Dadra and Nagar Haveli and Daman and Diu', 'Delhi', 'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jammu and Kashmir', 'Jharkhand', 'Karnataka', 'Kerala', 'Ladakh', 'Lakshadweep', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya', 'Mizoram', 'Nagaland', 'Odisha', 'Puducherry', 'Punjab', 'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura', 'Uttar Pradesh', 'Uttarakhand', 'West Bengal'];
const empty = { url: '', quantity: '', state: '', city: '', purpose: 'personal', variant: '', shipping: '', currency: 'USD', shippingMode: '' };
type Details = typeof empty;

export default function Investigation({ onLogout, user }: { onLogout: () => void; user?: { email?: string } }) {
  const reduced = useReducedMotion();
  const [details, setDetails] = useState<Details>(empty);
  const [certificates, setCertificates] = useState<string[]>([]);
  const [certificate, setCertificate] = useState('');
  const [optional, setOptional] = useState(false);
  const [error, setError] = useState('');
  const [submitted, setSubmitted] = useState<(Details & { certificates: string[] }) | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>(readHistory);
  function reopen(order: ImportOrder) {
    const { certificates: savedCertificates, ...savedDetails } = order;
    setSubmitted(null); setDetails(savedDetails); setCertificates([...savedCertificates]);
    setCertificate(''); setError(''); setOptional(true); window.scrollTo(0, 0);
  }
  function newInvestigation() {
    setSubmitted(null); setDetails({ ...empty }); setCertificates([]);
    setCertificate(''); setError(''); setOptional(false); window.scrollTo(0, 0);
  }
  const historyControl = <SearchHistory entries={history} onSelect={reopen} onNew={newInvestigation} />;
  useEffect(() => {
    if (!submitted) { document.title = 'New investigation — ImportSafe'; document.getElementById('investigation-title')?.focus({ preventScroll: true }); }
  }, [submitted]);
  const update = (key: keyof Details, value: string) => { setDetails(d => ({ ...d, [key]: value })); setError(''); setSubmitted(null); };
  function demo() {
    setDetails({ url: 'https://www.alibaba.com/product-detail/100-bluetooth-speakers.html', quantity: '100', state: 'Delhi', city: 'New Delhi', purpose: 'resale', variant: 'Black, 20W', shipping: '120', currency: 'USD', shippingMode: 'sea' });
    setCertificates([]); setCertificate(''); setSubmitted(null); setError(''); setOptional(true);
  }
  function addCertificate() {
    setSubmitted(null);
    const value = certificate.trim();
    if (value && !certificates.includes(value)) setCertificates(current => [...current, value]);
    setCertificate('');
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    // Carry every field into the local workflow; live research is not connected.
    let parsed: URL;
    try { parsed = new URL(details.url); } catch { setError('Enter a valid product URL.'); return; }
    const host = parsed.hostname.toLowerCase();
    if (!['http:', 'https:'].includes(parsed.protocol) || host === 'localhost' || host.endsWith('.local') || host === '[::1]' || /^\d+\.\d+\.\d+\.\d+$/.test(host)) {
      setError('Use a public HTTP or HTTPS marketplace listing. Local addresses aren’t supported.'); return;
    }
    if (!details.city.trim()) { setError('Enter your destination city.'); return; }
    const allCertificates = [...new Set([...certificates, certificate.trim()].filter(Boolean))];
    setCertificates(allCertificates); setCertificate('');
    const order = { ...details, certificates: allCertificates };
    const entries = [{ id: crypto.randomUUID(), time: new Date().toISOString(), order }, ...history.filter(entry => entry.order.url !== order.url)].slice(0, 20);
    setHistory(entries); saveHistory(entries);
    setSubmitted(order);
  }
  if (submitted) return <InvestigationFlow order={submitted} onBack={() => { setSubmitted(null); window.scrollTo(0, 0); }} onLogout={onLogout} historyControl={historyControl} />;
  return <div className="investigation-page">
    <header className="workspace-header"><div className="workspace-header-start">{historyControl}<a className="workspace-brand" href="#analyze"><img className="site-logo" src="/logo.png" alt="" width="40" height="40" /> importsafe</a></div><nav aria-label="Workspace"><ProfileMenu onLogout={onLogout} email={user?.email} /></nav></header>
    <main className="workspace-main">
      <motion.div initial={reduced ? false : { opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .5 }}>
        <div className="workspace-eyebrow"><span /> YOUR IMPORT JOURNEY, A LITTLE CLEARER</div>
        <div className="workspace-heading"><div><h1 id="investigation-title" tabIndex={-1}>Big ideas<br />Clearer beginnings</h1><p>Found something worth bringing home? Let’s start with the details.</p></div><div className="workspace-stamp" aria-hidden="true"><span>FROM ANYWHERE</span><svg viewBox="0 0 100 80" fill="none"><path d="m8 33 82-23-28 60-17-23L8 33Z" fill="#f6f1e4" stroke="#6b7f5a" strokeWidth="1.4"/><path d="m45 47 45-37-32 44 4 16-17-23Z" fill="#dce5d0" stroke="#6b7f5a" strokeWidth="1.2"/></svg><span>TO YOUR NEXT CHAPTER</span></div></div>
        <div className="workspace-layout">
          <form className="investigation-form" onSubmit={submit}>
            <div className="form-card-heading"><div><span className="step-number">01</span><h2>What are you bringing in?</h2></div><span className="required-note">* Required</span></div>
            <div className="form-section">
              <label htmlFor="investigation-url">Product link <span>*</span></label><div className="url-input"><input id="investigation-url" type="url" required placeholder="Paste your Alibaba or marketplace product URL" value={details.url} onChange={e => update('url', e.target.value)} /></div><p className="field-help">A direct product listing helps us start in the right place.</p>
              <div className="investigation-grid"><div><label htmlFor="investigation-quantity">Quantity <span>*</span></label><input id="investigation-quantity" type="number" required min="1" step="1" placeholder="e.g. 100" value={details.quantity} onChange={e => update('quantity', e.target.value)} /></div><div><label htmlFor="investigation-variant">Variant <small>Optional</small></label><input id="investigation-variant" placeholder="e.g. Black, 20W" value={details.variant} onChange={e => update('variant', e.target.value)} /></div></div>
            </div>
            <div className="form-section"><div className="section-title"><span className="step-number">02</span><h2>Where’s it headed?</h2></div><div className="investigation-grid"><div><label htmlFor="investigation-state">Destination state / UT <span>*</span></label><select id="investigation-state" value={details.state} onChange={e => update('state', e.target.value)} required><option value="">Select a state or territory</option>{states.map(state => <option key={state}>{state}</option>)}</select></div><div><label htmlFor="investigation-city">City <span>*</span></label><input id="investigation-city" autoComplete="address-level2" placeholder="e.g. New Delhi" required value={details.city} onChange={e => update('city', e.target.value)} /></div></div>
              <fieldset className="purpose-field"><legend>What’s it for? <span>*</span></legend><div className="purpose-options">{[{ value: 'personal', title: 'Just for me', note: 'For personal use', icon: '⌂' }, { value: 'resale', title: 'For my business', note: 'For resale or commercial use', icon: '▧' }].map(option => <label key={option.value} className={details.purpose === option.value ? 'purpose-option selected' : 'purpose-option'}><input type="radio" name="purpose" value={option.value} checked={details.purpose === option.value} onChange={e => update('purpose', e.target.value)} /><span className="purpose-icon" aria-hidden="true">{option.icon}</span><span><strong>{option.title}</strong><small>{option.note}</small></span><span className="radio-marker" aria-hidden="true" /></label>)}</div></fieldset>
            </div>
            <div className="optional-section"><button className="optional-toggle" type="button" aria-expanded={optional} aria-controls="extra-import-details" onClick={() => setOptional(!optional)}><span><strong>A few more details</strong><small>Shipping costs & seller certificates · Optional</small></span><span aria-hidden="true">{optional ? '−' : '+'}</span></button>
              {optional && <div id="extra-import-details" className="optional-content"><div className="shipping-grid"><div><label htmlFor="shipping-amount">Shipping cost</label><input id="shipping-amount" type="number" min="0" step="0.01" placeholder="0.00" value={details.shipping} onChange={e => update('shipping', e.target.value)} /></div><div><label htmlFor="shipping-currency">Currency</label><select id="shipping-currency" value={details.currency} onChange={e => update('currency', e.target.value)}><option>USD</option><option>INR</option><option>CNY</option><option>EUR</option></select></div><div><label htmlFor="shipping-mode">Shipping mode</label><select id="shipping-mode" value={details.shippingMode} onChange={e => update('shippingMode', e.target.value)}><option value="">Not sure yet</option><option value="air">Air</option><option value="sea">Sea</option></select></div></div><label htmlFor="seller-certificate">Seller certificate numbers</label><div className="certificate-input"><input id="seller-certificate" placeholder="Enter a registration or certificate number" value={certificate} onChange={e => { setCertificate(e.target.value); setSubmitted(null); }} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addCertificate(); } }} /><button type="button" disabled={!certificate.trim()} onClick={addCertificate}>Add +</button></div><p className="field-help">Add each number separately, if the seller has shared any.</p><div className="certificate-tags">{certificates.map(cert => <span key={cert}>{cert}<button type="button" aria-label={`Remove certificate ${cert}`} onClick={() => { setCertificates(current => current.filter(item => item !== cert)); setSubmitted(null); }}>×</button></span>)}</div></div>}
            </div>
            <div className="form-actions">{error && <p role="alert" className="investigation-error">{error}</p>}<button className="investigate-button" type="submit">Start demo investigation <span aria-hidden="true">↗</span></button><p>Interactive demo · Research services are not connected.</p></div>
          </form>
          <aside className="workspace-sidebar"><section className="journey-card"><div className="sidebar-eyebrow">A LITTLE CLARITY GOES A LONG WAY</div><h2>From “can I?”<br />to a clearer plan</h2><p>A few details now help shape the questions that come next.</p><ol><li><span>1</span><div><strong>Share your find</strong><p>A link, a quantity, a destination.</p></div></li><li><span>2</span><div><strong>Connect the dots</strong><p>Work through the product details and follow-up questions.</p></div></li><li><span>3</span><div><strong>See the bigger picture</strong><p>Review findings before deciding your next step.</p></div></li></ol><div className="sidebar-footnote">One thoughtful step at a time.</div></section><section className="demo-card"><span className="demo-spark" aria-hidden="true">✳</span><h3>Just looking around?</h3><p>Take a sample for a spin. We’ll fill in the details for 100 Bluetooth speakers.</p><button type="button" onClick={demo}>Try the demo <span aria-hidden="true">↗</span></button></section><p className="workspace-disclaimer">A little guidance, not a guarantee. ImportSafe supports your research; it doesn’t provide legal clearance, customs approval, or a final duty quote.</p></aside>
        </div>

        <footer className="workspace-footer"><span>Thoughtfully built for what comes next.</span><span>IMPORTSAFE · INDIA</span></footer>
      </motion.div>
    </main>
  </div>;
}
