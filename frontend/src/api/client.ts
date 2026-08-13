export class ApiError extends Error {
  status: number;
  detail: string | Record<string, unknown> | unknown[];

  constructor(status: number, detail: string | Record<string, unknown> | unknown[]) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

let authToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  isFormData?: boolean;
  query?: Record<string, string | undefined>;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, isFormData = false, query } = options;

  let url = `${API_BASE_URL}${path}`;
  if (query) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) params.set(key, value);
    }
    const qs = params.toString();
    if (qs) url += `?${qs}`;
  }

  const headers: Record<string, string> = {};
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  if (!isFormData && body !== undefined) headers['Content-Type'] = 'application/json';

  const response = await fetch(url, {
    method,
    headers,
    body: isFormData ? (body as FormData) : body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    let detail: string | Record<string, unknown> | unknown[] = response.statusText;
    try {
      const data = await response.json();
      detail = data?.detail ?? data;
    } catch {
      // no JSON body on this error response — keep statusText
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T,>(path: string, query?: Record<string, string | undefined>) =>
    request<T>(path, { method: 'GET', query }),
  post: <T,>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  postForm: <T,>(path: string, formData: FormData, query?: Record<string, string | undefined>) =>
    request<T>(path, { method: 'POST', body: formData, isFormData: true, query }),
  del: <T,>(path: string) => request<T>(path, { method: 'DELETE' }),
};
