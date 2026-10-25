import { useEffect, useRef, useState } from 'react';
import './ProfileMenu.css';

export default function ProfileMenu({ onLogout, email }: { onLogout: () => void; email?: string }) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const profile = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    function dismiss(event: PointerEvent) {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    }
    function escape(event: KeyboardEvent) {
      if (event.key === 'Escape' && open) {
        setOpen(false);
        trigger.current?.focus();
      }
    }
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('pointerdown', dismiss);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  return <div className="profile-menu" ref={container} onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false);
  }}>
    <button ref={trigger} type="button" className="profile-menu-trigger" aria-expanded={open} aria-controls="profile-options" onClick={() => setOpen(!open)}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="1.5"/><path d="M4 21v-2a8 8 0 0 1 16 0v2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
      Profile
    </button>
    {open && <div className="profile-menu-options" id="profile-options">
      <button type="button" onClick={() => { setOpen(false); profile.current?.showModal(); }}>Profile</button>
      <button type="button" className="profile-menu-logout" onClick={onLogout}>Log out</button>
    </div>}
    <dialog ref={profile} className="profile-dialog" aria-labelledby="profile-title">
      <h2 id="profile-title">Your profile</h2>
      {email && <p><strong>{email}</strong></p>}
      <button type="button" onClick={() => profile.current?.close()}>Close</button>
    </dialog>
  </div>;
}
