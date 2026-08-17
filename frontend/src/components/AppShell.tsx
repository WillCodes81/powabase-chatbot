import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { CreditsProvider, useCredits } from '../context/CreditsContext';
import { OnboardingTour } from './OnboardingTour';
import styles from './AppShell.module.css';

const STARTING_BALANCE = 50000;
const RING_RADIUS = 15;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

function TokenRing({ remaining }: { remaining: number }) {
  const pct = Math.min(1, Math.max(0, remaining / STARTING_BALANCE));
  const offset = RING_CIRCUMFERENCE * (1 - pct);
  return (
    <svg width="36" height="36" viewBox="0 0 36 36" className={styles.ring} aria-hidden="true">
      <circle cx="18" cy="18" r={RING_RADIUS} fill="none" stroke="var(--color-border-strong)" strokeWidth="3" />
      <circle
        cx="18"
        cy="18"
        r={RING_RADIUS}
        fill="none"
        stroke="url(#tokenRingGradient)"
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray={RING_CIRCUMFERENCE}
        strokeDashoffset={offset}
        transform="rotate(-90 18 18)"
      />
      <defs>
        <linearGradient id="tokenRingGradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="var(--color-accent)" />
          <stop offset="100%" stopColor="var(--color-accent-strong)" />
        </linearGradient>
      </defs>
    </svg>
  );
}

function CreditsDisplay() {
  const { credits } = useCredits();
  if (!credits) return <div className={styles.creditsPlaceholder} />;
  return (
    <div className={styles.credits}>
      <TokenRing remaining={credits.tokens_remaining} />
      <div className={styles.creditsText}>
        <p className={styles.creditsLabel}>Tokens remaining</p>
        <p className={styles.creditsValue}>{credits.tokens_remaining.toLocaleString()}</p>
      </div>
    </div>
  );
}

function AccountMenu() {
  const { userEmail, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const initial = userEmail ? userEmail.charAt(0).toUpperCase() : '?';

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return (
    <div className={styles.accountMenu} ref={rootRef} data-tour="nav-menu">
      <button
        type="button"
        className={styles.avatarButton}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
      >
        <span className="avatar">{initial}</span>
      </button>
      {open && (
        <div className={styles.dropdown} role="menu">
          {userEmail && <p className={styles.dropdownEmail}>{userEmail}</p>}
          <button
            type="button"
            role="menuitem"
            className={styles.dropdownItem}
            onClick={() => {
              setOpen(false);
              signOut();
            }}
          >
            Log out
          </button>
        </div>
      )}
    </div>
  );
}

function AppShellLayout() {
  return (
    <div className={styles.shell}>
      <header className={styles.topnav}>
        <div className={styles.brand}>
          <span className={styles.brandMark} />
          Powabase
        </div>
        <nav className={styles.nav}>
          <NavLink to="/" end className={({ isActive }) => (isActive ? styles.navLinkActive : styles.navLink)}>
            Dashboard
          </NavLink>
        </nav>
        <div className={styles.right}>
          <div data-tour="token-balance">
            <CreditsDisplay />
          </div>
          <AccountMenu />
        </div>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
      <OnboardingTour />
    </div>
  );
}

export function AppShell() {
  return (
    <CreditsProvider>
      <AppShellLayout />
    </CreditsProvider>
  );
}
