import { createContext, useContext, useState, type ReactNode } from 'react';
import { signIn as signInApi, signUp as signUpApi } from '../api/auth';
import { setAuthToken } from '../api/client';

interface AuthContextValue {
  token: string | null;
  userEmail: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<{ loggedIn: boolean }>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const STORAGE_KEY = 'powabase_auth';
export const NEW_SIGNUP_KEY = 'powabase_new_signup';

interface StoredAuth {
  token: string;
  email: string;
}

function readStoredAuth(): StoredAuth | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredAuth;
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => {
    const stored = readStoredAuth();
    if (stored) setAuthToken(stored.token);
    return stored?.token ?? null;
  });
  const [userEmail, setUserEmail] = useState<string | null>(() => readStoredAuth()?.email ?? null);

  function persist(newToken: string, email: string) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: newToken, email }));
    setAuthToken(newToken);
    setToken(newToken);
    setUserEmail(email);
  }

  async function signIn(email: string, password: string) {
    const res = await signInApi(email, password);
    if (!res.access_token) throw new Error('Sign in did not return an access token.');
    persist(res.access_token, res.user?.email ?? email);
  }

  async function signUp(email: string, password: string): Promise<{ loggedIn: boolean }> {
    const res = await signUpApi(email, password);
    // Set unconditionally: this only ever runs from the sign-up form, so it
    // correctly marks "first ever session" even when email confirmation
    // delays the actual first login past this call.
    localStorage.setItem(NEW_SIGNUP_KEY, 'true');
    if (res.access_token) {
      persist(res.access_token, res.user?.email ?? email);
      return { loggedIn: true };
    }
    return { loggedIn: false };
  }

  function signOut() {
    localStorage.removeItem(STORAGE_KEY);
    setAuthToken(null);
    setToken(null);
    setUserEmail(null);
  }

  return (
    <AuthContext.Provider value={{ token, userEmail, signIn, signUp, signOut }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
