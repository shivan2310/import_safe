import { motion, useReducedMotion } from 'framer-motion';
import { PublicShell } from './PublicPages';
import './Landing.css';
import DeliveryJourney from './DeliveryJourney';

function JourneyIllustration() {
  return <svg className="landing-illustration" viewBox="0 0 540 490" fill="none" role="img" aria-label="A paper plane follows a dotted route around a globe to a parcel in India">
    <circle cx="279" cy="218" r="174" fill="#e2e8d5" />
    <circle cx="279" cy="218" r="146" stroke="#9bac88" strokeWidth="1" />
    <ellipse cx="279" cy="218" rx="70" ry="146" stroke="#a9bc98" />
    <path d="M133 218h292M153 145c72 34 179 34 252 0M153 291c72-34 179-34 252 0M279 72v292" stroke="#a9bc98" />
    <path d="m192 134 34-12 27 15 9 27-24 18-8 31-26 5-22-22-22-9 6-27 26-26ZM309 129l33-15 31 19 9 26 27 9-4 23-33 5-11 23-28-6-8-24-21-18 5-42ZM296 242l24-7 27 19 8 38-24 34-18-9-6-32-16-18 5-25Z" fill="#c8d5b8" stroke="#9bac88" strokeLinejoin="round" />
    <path d="M41 303C-16 160 129 64 197 89c124 45-72 175-7 245 61 67 304 1 299-140-3-91-70-129-115-110" stroke="#6b7f5a" strokeWidth="1.5" strokeDasharray="3 8" strokeLinecap="round" />
    <g className="landing-paper-plane"><path d="m349 63 111-31-37 78-23-29-51-18Z" fill="#fffcf3" stroke="#6b7f5a" strokeWidth="1.6" strokeLinejoin="round"/><path d="m400 81 60-49-43 57 6 21-23-29Z" fill="#dce5d0" stroke="#6b7f5a" strokeWidth="1.5"/></g>
    <g transform="rotate(-8 180 360)"><path d="m110 321 80-30 77 31-79 34-78-35Z" fill="#efe3c2" stroke="#7c8a72" strokeWidth="1.5"/><path d="m110 321 78 35v81l-78-36v-80Z" fill="#e3d5b2" stroke="#7c8a72" strokeWidth="1.5"/><path d="m188 356 79-34v81l-79 34v-81Z" fill="#f3e8cd" stroke="#7c8a72" strokeWidth="1.5"/><path d="m144 308 78 33v30l-19 8v-30l-79-33" fill="#c4ccae" stroke="#7c8a72"/><path d="m214 388 30-13m-30 22 19-8" stroke="#7c8a72" strokeWidth="2" strokeLinecap="round"/></g>
    <circle cx="377" cy="218" r="7" fill="#6b7f5a" stroke="#f6f1e4" strokeWidth="3"/>
    <text x="52" y="85" fill="#59654f" fontSize="9" letterSpacing="2" fontFamily="Inter, sans-serif" transform="rotate(-12 52 85)">A WORLD OF POSSIBILITIES</text>
  </svg>;
}

export default function Landing() {
  const reduced = useReducedMotion();
  return <PublicShell page="home">
      <section className="landing-hero" id="home"><motion.div className="landing-hero-copy" initial={reduced ? false : { opacity: 0, y: 22 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .65 }}><div className="landing-eyebrow"><span /> FOR CURIOUS MINDS. FOR INDIAN BUYERS.</div><h1>A world of finds<br />A little more <em>clarity</em></h1><p>That product you found overseas? Give your next import a thoughtful beginning. Gather the details, ask better questions, and see your next step more clearly.</p><div className="landing-hero-actions"><a href="#sign-up" className="landing-button">Start your journey </a><a href="#how-it-works" className="landing-text-link">See how it works </a></div><div className="landing-preview-label"><span /> Explore the prototype · No payment required</div></motion.div><motion.div className="landing-hero-art" initial={reduced ? false : { opacity: 0, scale: .95 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: .8 }}><div className="delivery-globe"><JourneyIllustration /></div><DeliveryJourney /></motion.div></section>
      <div className="landing-note-strip"><span>FROM A LISTING TO A STARTING POINT</span><div>One product link <i>·</i> Your import details <i>·</i> A clearer next step</div><span>MADE WITH INDIA IN MIND</span></div>
      <section className="home-page-directory"><div className="landing-eyebrow">A LITTLE MORE TO EXPLORE</div><h2>Get to know your next step</h2><div>{[
        ['features', '01', 'The little things, connected.', 'Explore the product workspace, the details it captures, and the research features we’re building.', 'Explore features'],
        ['how-it-works', '02', 'From a find to a plan.', 'Follow a product through five steps, from the first link to the intended evidence-backed report.', 'Follow the journey'],
        ['architecture', '03', 'Under the paper folds.', 'See how React, FastAPI, and the planned TinyFish web-agent layer fit together.', 'Open architecture'],
        ['pricing', '04', 'A plan is taking shape.', 'See what you can explore today. Pricing and paid plan details will be announced later.', 'About pricing'],
      ].map(([route,number,title,text,cta]) => <a href={`#${route}`} key={route}><span>{number}</span><h3>{title}</h3><p>{text}</p><strong>{cta}</strong></a>)}</div></section>
      <section className="landing-closing"><div className="landing-eyebrow">CURIOSITY LOOKS GOOD ON YOU</div><h2>Found something?<br />Let’s start there</h2><a href="#sign-up" className="landing-button">Find your starting point</a></section>
    </PublicShell>;
}
