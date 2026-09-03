import { ApiError } from '../api/client';

export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (typeof err.detail === 'string') return err.detail;
    return JSON.stringify(err.detail);
  }
  if (err instanceof Error) return err.message;
  return 'Something went wrong.';
}
