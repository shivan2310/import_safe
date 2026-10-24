import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import Login from './Login.jsx';
import Investigation from './Investigation';
import Landing from './Landing';
import PublicPages from './PublicPages';
import PageFlight from './PageFlight';

function Frontend() {
  const [signedIn, setSignedIn] = useState(false);
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const update = () => setHash(window.location.hash);
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  // The landing page is public; only the workspace requires demo sign-in.
  useEffect(() => {
    if (!signedIn && hash === '#analyze') {
      window.history.replaceState(null, '', '#login');
      setHash('#login');
    }
  }, [signedIn, hash]);
  function openAnalyzer() {
    setSignedIn(true);
    window.location.hash = 'analyze';
    setHash('#analyze');
    window.scrollTo(0, 0);
  }
  function logout() {
    setSignedIn(false);
    window.location.hash = 'login';
    setHash('#login');
    window.scrollTo(0, 0);
  }
  const mode = hash === '#sign-up' ? 'signup' : 'login';
  if (signedIn && hash === '#analyze') return <Investigation onLogout={logout} />;
  if (hash === '#login' || hash === '#sign-up') return <Login key={mode} mode={mode} onSuccess={openAnalyzer} />;
  if (hash === '#features' || hash === '#how-it-works' || hash === '#architecture' || hash === '#pricing') {
    return <PublicPages page={hash.slice(1) as 'features' | 'how-it-works' | 'architecture' | 'pricing'} />;
  }
  return <Landing />;
}

createRoot(document.getElementById('root')!).render(<PageFlight><Frontend /></PageFlight>);


