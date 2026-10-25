import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import Login from './Login.jsx';
import Investigation from './Investigation';
import Landing from './Landing';
import PublicPages from './PublicPages';
import PageFlight from './PageFlight';
import { supabase } from './supabase';
import type { User } from '@supabase/supabase-js';

function Frontend() {
  const [user, setUser] = useState<User | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [hash, setHash] = useState(window.location.hash);

  useEffect(() => {
    const update = () => setHash(window.location.hash);
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);

  // Restore session on load, then listen for changes
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user ?? null);
      setAuthReady(true);
    });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
    });
    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (authReady && !user && hash === '#analyze') {
      window.history.replaceState(null, '', '#login');
      setHash('#login');
    }
  }, [authReady, user, hash]);

  function openAnalyzer() {
    window.history.replaceState(null, '', '#analyze');
    setHash('#analyze');
    window.scrollTo(0, 0);
  }

  async function logout() {
    await supabase.auth.signOut();
    setUser(null);
    window.location.hash = 'login';
    setHash('#login');
    window.scrollTo(0, 0);
  }

  if (!authReady) return null;

  const mode = hash === '#sign-up' ? 'signup' : 'login';
  if (user && hash === '#analyze') return <Investigation onLogout={logout} user={user} />;
  if (hash === '#login' || hash === '#sign-up') return <Login key={mode} mode={mode} onSuccess={openAnalyzer} />;
  if (hash === '#features' || hash === '#how-it-works' || hash === '#architecture' || hash === '#pricing') {
    return <PublicPages page={hash.slice(1) as 'features' | 'how-it-works' | 'architecture' | 'pricing'} />;
  }
  return <Landing />;
}

createRoot(document.getElementById('root')!).render(<PageFlight><Frontend /></PageFlight>);
