import { api } from './client';
import type { CreditsSummary } from './types';

export function getMyCredits() {
  return api.get<CreditsSummary>('/me/credits');
}
