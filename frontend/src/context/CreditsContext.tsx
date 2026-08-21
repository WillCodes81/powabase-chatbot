import { createContext, useContext, type ReactNode } from 'react';
import { getMyCredits } from '../api/credits';
import { useAsync } from '../hooks/useAsync';
import type { CreditsSummary } from '../api/types';

interface CreditsContextValue {
  credits: CreditsSummary | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

const CreditsContext = createContext<CreditsContextValue | undefined>(undefined);

export function CreditsProvider({ children }: { children: ReactNode }) {
  const { data, loading, error, reload } = useAsync(() => getMyCredits(), []);
  return <CreditsContext.Provider value={{ credits: data, loading, error, reload }}>{children}</CreditsContext.Provider>;
}

export function useCredits(): CreditsContextValue {
  const ctx = useContext(CreditsContext);
  if (!ctx) throw new Error('useCredits must be used within CreditsProvider');
  return ctx;
}
