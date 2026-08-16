import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { CreditsProvider, useCredits } from '../context/CreditsContext';
import styles from './AppShell.module.css';

function CreditsDisplay() {
  const { credits } = useCredits();
  if (!credits) return null;
  return (
    <div className={styles.credits}>
      <p className={styles.creditsLabel}>Tokens remaining</p>
      <p className={styles.creditsValue}>{credits.tokens_remaining.toLocaleString()}</p>
    </div>
  );
}

function AppShellLayout() {
  const { userEmail, signOut } = useAuth();

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.brandMark} />
          Powabase
        </div>
        <nav className={styles.nav}>
          <NavLink to="/" end className={({ isActive }) => (isActive ? styles.navLinkActive : styles.navLink)}>
            Dashboard
          </NavLink>
        </nav>
        <CreditsDisplay />
        <div className={styles.account}>
          {userEmail && <span className={styles.email}>{userEmail}</span>}
          <button type="button" className="btn btn-ghost" onClick={signOut}>
            Sign out
          </button>
        </div>
      </aside>
      <main className={styles.main}>
        <Outlet />
      </main>
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
