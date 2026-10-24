import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react';
import { animate, motion, useMotionValue, useReducedMotion, useTransform } from 'framer-motion';
import './PageFlight.css';

type Flight = { target: string; start: { x: number; y: number }; end: { x: number; y: number }; width: number; height: number };
function FlightVisual({ flight }: { flight: Flight }) {
  const progress = useMotionValue(0);
  const { start, end } = flight;
  // A single broad Bezier bank has no cusp or mid-flight reversal. Choose
  // the open side of the viewport, and orient the artwork along its tangent.
  const dx = end.x-start.x, dy = end.y-start.y;
  const distance = Math.hypot(dx,dy);
  const normal = { x:-dy/Math.max(distance,1), y:dx/Math.max(distance,1) };
  const middle = { x:(start.x+end.x)/2, y:(start.y+end.y)/2 };
  const clearance = (side: number) => Math.min(
    middle.x+normal.x*side*100, flight.width-middle.x-normal.x*side*100,
    middle.y+normal.y*side*100, flight.height-middle.y-normal.y*side*100);
  const side = clearance(1)>clearance(-1) ? 1 : -1;
  const bend = Math.min(180, Math.max(70,distance*.38));
  const clamp = (v: number, max: number) => Math.max(32,Math.min(max-32,v));
  const c1 = {x:clamp(start.x+dx*.25+normal.x*side*bend,flight.width),
    y:clamp(start.y+dy*.25+normal.y*side*bend,flight.height)};
  const c2 = {x:clamp(start.x+dx*.75+normal.x*side*bend,flight.width),
    y:clamp(start.y+dy*.75+normal.y*side*bend,flight.height)};
  const point = (t: number) => {
    const u=1-t;
    return {x:u*u*u*start.x+3*u*u*t*c1.x+3*u*t*t*c2.x+t*t*t*end.x,
      y:u*u*u*start.y+3*u*u*t*c1.y+3*u*t*t*c2.y+t*t*t*end.y};
  };
  const points=Array.from({length:601},(_,i)=>point(i/600));
  let length=0, previousAngle=0;
  const samples=points.map((p,i)=>{
    if(i) length+=Math.hypot(p.x-points[i-1].x,p.y-points[i-1].y);
    const before=points[Math.max(0,i-1)],after=points[Math.min(600,i+1)];
    let angle=Math.atan2(after.y-before.y,after.x-before.x)*180/Math.PI+34;
    if(i) { while(angle-previousAngle>180) angle-=360; while(angle-previousAngle< -180) angle+=360; }
    previousAngle=angle;
    return {...p,angle,length};
  });
  function sample(t: number) {
    const target=t*length;
    let low=0,high=samples.length-1;
    while(low<high){const mid=(low+high)>>1;if(samples[mid].length<target)low=mid+1;else high=mid;}
    const a=samples[Math.max(0,low-1)],b=samples[low];
    const mix=(target-a.length)/Math.max(.0001,b.length-a.length);
    return {x:a.x+(b.x-a.x)*mix,y:a.y+(b.y-a.y)*mix,angle:a.angle+(b.angle-a.angle)*mix};
  }
  const x=useTransform(progress,t=>sample(t).x);
  const y=useTransform(progress,t=>sample(t).y);
  const rotate=useTransform(progress,t=>sample(t).angle);
  const scale=useTransform(progress,[0,.15,.85,1],[.35,.7,.7,.28]);
  const opacity=useTransform(progress,[0,.04,.96,1],[0,1,1,0]);
  useEffect(()=>{const control=animate(progress,1,{duration:2.4,ease:[.3,0,.3,1]});return ()=>control.stop();},[progress]);
  return <div className="page-flight-overlay" aria-hidden="true">
    <motion.div className="page-flight-click-ring" style={{ left:end.x, top:end.y }} initial={{ opacity:0, scale:.4 }} animate={{ opacity:[0,.8,0], scale:[.4,1,1.5] }} transition={{ delay:2.35,duration:.45 }} />
    <motion.div className="page-flight-traveller" style={{ x, y, rotate, scale, opacity }}>
      <svg viewBox="0 0 120 90" fill="none"><path d="M7 37 112 9 76 80 54 54 7 37Z" fill="#fffdf5" stroke="#6b7f5a" strokeWidth="1.6" strokeLinejoin="round"/><path d="m54 54 58-45-42 54 6 17-22-26Z" fill="#dce5d0" stroke="#6b7f5a" strokeWidth="1.3" strokeLinejoin="round"/><path d="m54 54-5 20 21-11" fill="#a9bc98" stroke="#6b7f5a" strokeWidth="1.2" strokeLinejoin="round"/><path d="m18 37 77-20" stroke="white" strokeWidth="2" strokeLinecap="round"/></svg>
    </motion.div>
  </div>;
}

/** Launch from the home hero CTA, preserving the landing page during takeoff. */
export default function PageFlight({ children }: { children: ReactNode }) {
  const reduced = useReducedMotion();
  const [flight, setFlight] = useState<Flight | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const pending = useRef(false);
  useEffect(() => {
    const cancel = () => { timers.current.forEach(clearTimeout); timers.current=[]; pending.current=false; setFlight(null); };
    window.addEventListener('popstate', cancel);
    window.addEventListener('resize', cancel);
    return () => { timers.current.forEach(clearTimeout); window.removeEventListener('popstate',cancel); window.removeEventListener('resize',cancel); };
  }, []);
  useEffect(() => {
    if (flight) return;
    const heading=document.getElementById('login-title');
    if (heading) { heading.setAttribute('tabindex','-1'); heading.focus({preventScroll:true}); }
  }, [flight]);
  function navigate(event: MouseEvent<HTMLDivElement>) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = (event.target as Element).closest('a');
    if (!link || link.target === '_blank' || link.hasAttribute('download')) return;
    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin || url.pathname !== window.location.pathname || !['#login','#sign-up'].includes(url.hash) || url.hash === window.location.hash || ['#login','#sign-up'].includes(window.location.hash) || reduced) return;
    event.preventDefault();
    if (pending.current) return;
    pending.current = true;
    // On Home, all auth CTAs launch the plane from “Start your journey”.
    const heroButton = document.querySelector('.landing-hero-actions .landing-button');
    const heroRect = heroButton?.getBoundingClientRect();
    const source = heroRect && heroRect.top >= 0 && heroRect.bottom <= window.innerHeight ? heroButton! : link;
    const rect = source.getBoundingClientRect();
    const width = window.innerWidth, height = window.innerHeight;
    // Hero actions fly toward their matching header link, rather than
    // turning back into the same button they launched from.
    const headerLink = document.querySelector<HTMLAnchorElement>(`header a[href="${url.hash}"]`);
    const destination = source === link && headerLink ? headerLink : link;
    const targetRect = destination.getBoundingClientRect();
    if (targetRect.bottom < 0 || targetRect.top > height || Math.hypot(targetRect.left+targetRect.width/2-(rect.right-28),targetRect.top+targetRect.height/2-(rect.top+rect.height/2)) < 80) {
      pending.current=false; window.location.hash=url.hash; window.scrollTo(0,0); return;
    }
    const active = document.activeElement;
    if (active instanceof HTMLElement) active.blur();
    setFlight({ target:url.hash, start:{x:rect.right-28,y:rect.top+rect.height/2}, end:{x:targetRect.left+targetRect.width/2,y:targetRect.top+targetRect.height/2}, width,height });
    timers.current.push(setTimeout(() => {
      destination.animate([{ transform: 'scale(1)' }, { transform: 'scale(.93)' }, { transform: 'scale(1)' }], { duration: 280, easing: 'ease-in-out' });
    }, 2400));
    timers.current.push(setTimeout(() => { window.history.pushState(null,'',url.hash); window.dispatchEvent(new HashChangeEvent('hashchange')); window.scrollTo({top:0,behavior:'instant'}); }, 2700));
    timers.current.push(setTimeout(() => {
      pending.current=false; setFlight(null);

    }, 3300));
  }
  return <div className="page-flight-boundary" onClickCapture={navigate}>
    <motion.div inert={flight !== null} initial={false} animate={{opacity:flight ? [1,1,0,0,1] : 1}} transition={flight ? {duration:3.2,times:[0,.76,.83,.86,1],ease:'easeInOut'} : {duration:0}}>{children}</motion.div>
    <span className="flight-announcement" role="status" aria-live="polite">{flight ? flight.target==='#sign-up' ? 'Opening sign up' : 'Opening login' : ''}</span>
    {flight && <FlightVisual flight={flight} />}
  </div>;
}




