import { api } from './client';
import type { AuthResponse } from './types';

export function signUp(email: string, password: string) {
  return api.post<AuthResponse>('/auth/signup', { email, password });
}

export function signIn(email: string, password: string) {
  return api.post<AuthResponse>('/auth/signin', { email, password });
}
