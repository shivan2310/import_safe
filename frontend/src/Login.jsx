import React, { useEffect, useRef, useState } from 'react';
import { motion, useMotionValue, useReducedMotion, useSpring } from 'framer-motion';
import { supabase } from './supabase';
import './Login.css';

const FLIGHT_PATH = 'M 1120 -100 C 980 40 420 80 350 260 C 260 490 880 470 900 240 C 920 40 450 200 560 460 C 650 660 1080 560 1140 850';

// Alternate between the outer edges and the center. Jitter each waypoint on
// every lap, then join them with smooth curves so turns never snap.
function makeFlightRoute() {
  const between = (min, max) => min + Math.random() * (max - min);
  const points = [
    [112, -18], [between(79, 91), between(12, 24)],
    [between(7, 17), between(20, 34)], [between(9, 19), between(66, 81)],
    [between(80, 92), between(69, 84)], [between(81, 93), between(30, 45)],
    [between(36, 58), between(8, 18)], [between(7, 18), between(43, 58)],
    [between(36, 57), between(80, 90)], [between(82, 94), between(53, 65)],
    [114, 118],
  ];
  let css = `shape(from ${points[0][0]}% ${points[0][1]}%`;
  let svg = `M ${points[0][0] * 10} ${points[0][1] * 7}`;
  for (let i = 0; i < points.length - 1; i++) {
    const before = points[Math.max(0, i - 1)];
    const start = points[i];
    const end = points[i + 1];
    const after = points[Math.min(points.length - 1, i + 2)];
    const c1 = start.map((v, axis) => v + (end[axis] - before[axis]) / 6);
    const c2 = end.map((v, axis) => v - (after[axis] - start[axis]) / 6);
    css += `, curve to ${end[0]}% ${end[1]}% with ${c1[0]}% ${c1[1]}% / ${c2[0]}% ${c2[1]}%`;
    svg += ` C ${c1[0] * 10} ${c1[1] * 7} ${c2[0] * 10} ${c2[1] * 7} ${end[0] * 10} ${end[1] * 7}`;
  }
  return { css: `${css})`, svg };
}

function Plane({ className = '' }) {
  return (
    <svg className={className} viewBox="0 0 120 90" fill="none" aria-hidden="true">
      <path d="M7 37 112 9 76 80 54 54 7 37Z" fill="#FFFDF5" stroke="#6B7F5A" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="m54 54 58-45-42 54 6 17-22-26Z" fill="#DCE5D0" stroke="#6B7F5A" strokeWidth="1.2" strokeLinejoin="round" />
      <path d="m54 54-5 20 21-11" fill="#A9BC98" stroke="#6B7F5A" strokeWidth="1.2" strokeLinejoin="round" />
      <path d="m18 37 77-20" stroke="white" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function Eye({ visible }) {
  return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" stroke="currentColor" strokeWidth="1.5" /><circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.5" />{visible && <path d="m4 3 16 18" stroke="currentColor" strokeWidth="1.5" />}</svg>;
}

/** @param {{ mode?: 'login' | 'signup', onSuccess?: (user: {email: string}) => void, onForgotPassword?: (event: import('react').MouseEvent<HTMLAnchorElement>) => void, onSignUp?: (event: import('react').MouseEvent<HTMLAnchorElement>) => void }} props */
export default function Login({ mode = 'login', onSuccess, onForgotPassword, onSignUp } = {}) {
  const isSignup = mode === 'signup';
  useEffect(() => { document.title = `${isSignup ? 'Sign up' : 'Log in'} — ImportSafe`; }, [isSignup]);
  const [name, setName] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const reducedMotion = useReducedMotion();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [passwordHelp, setPasswordHelp] = useState(false);
  const [visible, setVisible] = useState(false);
  const [focused, setFocused] = useState(false);
  const [status, setStatus] = useState('idle');
  const [errorMsg, setErrorMsg] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [trailPath, setTrailPath] = useState(FLIGHT_PATH);
  const timer = useRef(null);
  const flight = useRef(null);
  const backgroundFlights = useRef([]);
  const statusRef = useRef(status);
  const focusRef = useRef(focused);
  statusRef.current = status;
  focusRef.current = focused;
  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);
  const x = useSpring(mouseX, { stiffness: 45, damping: 22 });
  const y = useSpring(mouseY, { stiffness: 45, damping: 22 });

  // Playback rate preserves path progress when a field gains focus.
  useEffect(() => {
    if (reducedMotion || !flight.current) return;
    const duration = 24000;
    const updateRoute = () => {
      const route = makeFlightRoute();
      flight.current.style.offsetPath = route.css;
      setTrailPath(route.svg);
    };
    updateRoute();
    const animation = flight.current.animate(
      [{ offsetDistance: '0%', transform: 'scale(.8)' },
       { offsetDistance: '48%', transform: 'scale(1.1)', offset: .42 },
       { offsetDistance: '100%', transform: 'scale(.8)', offset: 22 / 24 },
       { offsetDistance: '100%', transform: 'scale(.8)' }],
      { duration, iterations: Infinity, easing: 'linear' },
    );
    const backgrounds = backgroundFlights.current.filter(Boolean).map((node, index) => node.animate(
      [{ offsetDistance: '0%' }, { offsetDistance: '100%' }],
      { duration: 18000, iterations: Infinity, delay: -index * 9000, easing: 'ease-in-out' },
    ));
    let frame;
    let lap = 0;
    const syncRate = () => {
      const nextLap = Math.floor(Number(animation.currentTime || 0) / duration);
      if (nextLap !== lap) { lap = nextLap; updateRoute(); }
      animation.playbackRate = ['error', 'success'].includes(statusRef.current) ? 0 : focusRef.current ? .6 : 1;
      frame = requestAnimationFrame(syncRate);
    };
    syncRate();
    const node = flight.current;
    return () => { cancelAnimationFrame(frame); animation.cancel(); backgrounds.forEach(a => a.cancel()); node.style.removeProperty('offset-path'); };
  }, [reducedMotion]);

  useEffect(() => () => clearTimeout(timer.current), []);

  async function submit(event) {
    event.preventDefault();
    if (status === 'loading' || status === 'success') return;
    if (isSignup && password !== confirmation) {
      setAttempt(v => v + 1);
      setErrorMsg('Those passwords don\'t match. Give it another try.');
      setStatus('error');
      return;
    }
    setStatus('loading');
    setErrorMsg('');
    try {
      let authError;
      if (isSignup) {
        const { error: signUpError } = await supabase.auth.signUp({
          email,
          password,
          options: { data: { full_name: name }, emailRedirectTo: undefined },
        });
        if (signUpError) {
          authError = signUpError;
        } else {
          // Sign in immediately so no email confirmation is required.
          const { error: signInError } = await supabase.auth.signInWithPassword({ email, password });
          authError = signInError ?? null;
        }
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        authError = error;
      }
      if (authError) {
        setAttempt(v => v + 1);
        setErrorMsg(authError.message);
        setStatus('error');
      } else {
        setStatus('success');
        timer.current = setTimeout(() => onSuccess?.({ email }), reducedMotion ? 400 : 1500);
      }
    } catch {
      setAttempt(v => v + 1);
      setErrorMsg('Something went wrong. Please try again.');
      setStatus('error');
    }
  }

  return (
    <main className={`login-page ${isSignup ? 'signup-page' : ''} ${focused ? 'is-focused' : ''} is-${status} ${reducedMotion ? 'reduce-motion' : ''}`}
      onPointerMove={event => {
        if (reducedMotion || event.pointerType === 'touch') return;
        mouseX.set((.5 - event.clientX / window.innerWidth) * 32);
        mouseY.set((.5 - event.clientY / window.innerHeight) * 32);
      }} onPointerLeave={() => { mouseX.set(0); mouseY.set(0); }}>
      <div className="login-wash" aria-hidden="true"><div className="login-blob blob-sage" /><div className="login-blob blob-gold" /></div>
      <div className="login-grain" aria-hidden="true" />
      <a className="login-brand" href="#analyze" aria-label="ImportSafe dashboard"><img className="site-logo" src="/logo.png" alt="" width="40" height="40" />importsafe</a>
      <motion.div className="flight-scene" style={{ x, y }} aria-hidden="true">
        {[0, 1].map(index => <div key={index} ref={node => { backgroundFlights.current[index] = node; }} className={`background-flight background-flight-${index}`}><Plane /></div>)}
        <svg className="flight-trail" viewBox="0 0 1000 700" preserveAspectRatio="none"><path d={trailPath} /></svg>
        <div ref={flight} className="main-flight">
          <motion.div className="plane-exit" animate={status === 'success' && !reducedMotion ? { x: [0, -70, 180, 600], y: [0, -150, -420, -1000], rotate: [0, -25, -40, -15], opacity: [1, 1, 1, 0] } : { x: 0, y: 0, rotate: 0, opacity: 1 }} transition={{ duration: 1.4, ease: 'easeIn' }}>
            <motion.div key={attempt} className="plane-wobble" animate={reducedMotion ? {} : status === 'error' ? { y: [0, 40, 28, 40], rotate: [0, -18, 15, -8, 0] } : { rotate: [-3, 3, -3] }} transition={status === 'error' ? { duration: .8 } : { duration: 3.5, repeat: Infinity, ease: 'easeInOut' }}>
              <span className="plane-shadow" /><Plane className="hero-plane" />
            </motion.div>
          </motion.div>
        </div>
      </motion.div>
      <motion.section className="login-card" aria-labelledby="login-title"
        initial={{ opacity: 0, y: reducedMotion ? 0 : 24, scale: reducedMotion ? 1 : .95 }}
        animate={{ opacity: status === 'success' ? 0 : 1, y: 0, scale: 1, x: status === 'error' && !reducedMotion ? [0, -10, 10, -6, 6, 0] : 0 }}
        transition={{ duration: .6, opacity: { duration: .6, delay: status === 'success' ? .8 : 0 } }}>
        <div className="card-kicker"><span /> {isSignup ? 'EVERY JOURNEY STARTS SOMEWHERE' : 'A LITTLE SPACE TO BEGIN AGAIN'}</div>
        <h1 id="login-title">{isSignup ? 'A fresh start' : 'Welcome back'}</h1>
        <p className="login-subtitle">{isSignup ? 'A little curiosity. A world of possibilities.' : 'Settle in. Your next chapter starts here.'}</p>
        {isSignup && <div className="signup-welcome"><span className="signup-welcome-icon" aria-hidden="true">↗</span><div><strong>Your next chapter, thoughtfully imported.</strong><span>Bring your ideas. We'll help you find your way.</span></div></div>}
        <form onSubmit={submit} onFocus={() => setFocused(true)} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false); }}>
          {isSignup && <div className="login-field"><input id="signup-name" name="name" autoComplete="name" placeholder=" " value={name} onChange={event => setName(event.target.value)} required pattern=".*\S.*" disabled={status === 'loading' || status === 'success'} /><label htmlFor="signup-name">Full name</label><span className="field-line" /></div>}
          <div className="login-field">
            <input id="login-email" type="email" name="email" autoComplete="username" placeholder=" " value={email} onChange={event => setEmail(event.target.value)} required disabled={status === 'loading' || status === 'success'} />
            <label htmlFor="login-email">Email address</label><span className="field-line" />
          </div>
          <div className="login-field password-field">
            <input id="login-password" type={visible ? 'text' : 'password'} name="password" autoComplete={isSignup ? 'new-password' : 'current-password'} minLength={isSignup ? 8 : undefined} placeholder=" " value={password} onChange={event => { setPassword(event.target.value); if (status === 'error') setStatus('idle'); }} required aria-invalid={status === 'error'} aria-describedby="login-feedback" disabled={status === 'loading' || status === 'success'} />
            <label htmlFor="login-password">Password</label><span className="field-line" />
            <button className="password-toggle" type="button" aria-label={visible ? 'Hide password' : 'Show password'} aria-pressed={visible} onClick={() => setVisible(!visible)}><Eye visible={visible} /></button>
          </div>
          {isSignup ? <><p className="signup-password-hint">Make it yours. Use at least 8 characters.</p><div className="login-field"><input id="signup-confirm" type={visible ? 'text' : 'password'} name="confirm-password" autoComplete="new-password" placeholder=" " value={confirmation} onChange={event => { setConfirmation(event.target.value); if (status === 'error') setStatus('idle'); }} required aria-invalid={status === 'error'} aria-describedby="login-feedback" disabled={status === 'loading' || status === 'success'} /><label htmlFor="signup-confirm">Confirm password</label><span className="field-line" /></div></> : <div className="forgot-row"><a href="#forgot-password" onClick={event => { event.preventDefault(); setPasswordHelp(value => !value); onForgotPassword?.(event); }} aria-expanded={passwordHelp} aria-controls="password-help">Forgot password?</a></div>}
          {passwordHelp && <p id="password-help" className="signup-demo-note" role="status">Enter your email address and we'll send you a reset link.</p>}
          <button className="login-submit" type="submit" disabled={status === 'loading' || status === 'success'} aria-busy={status === 'loading'}>
            {status === 'loading' ? <><span className="login-spinner" /> Finding your place…</> : status === 'success' ? <><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m5 12 4 4L19 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg> You're right where you belong</> : <>{isSignup ? 'Create your account' : 'Log in'} <span aria-hidden="true">↗</span></>}
          </button>
          <p id="login-feedback" className={`login-feedback ${status === 'error' ? 'has-error' : ''}`} role="status" aria-live="polite">{status === 'error' ? (errorMsg || 'Something went wrong. Please try again.') : status === 'success' ? (isSignup ? "Account created. Opening your workspace…" : "You're in. Welcome back.") : isSignup ? 'Thoughtful beginnings. Endless possibilities.' : 'Your import intelligence workspace.'}</p>
        </form>
        <div className="card-divider"><span /> MAKE YOURSELF AT HOME <span /></div>
        <p className="signup-copy">{isSignup ? 'Already found your place?' : 'New around here?'} <a href={isSignup ? '#login' : '#sign-up'} onClick={isSignup ? undefined : onSignUp}>{isSignup ? 'Log in' : 'Sign up'} <span aria-hidden="true">↗</span></a></p>
      </motion.section>
      <div className="login-bottom"><span>A softer landing for your next big thing.</span><span className="bottom-note"><span /> ROOM TO GROW</span></div>
    </main>
  );
}



