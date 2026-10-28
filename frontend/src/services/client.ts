import axios from 'axios';

export type RecordData = Record<string, unknown> & { id?: string; name?: string };
export type PageData = { items: RecordData[]; total: number };
export const SESSION_KEY = 'evalforge_connection';
export const DEMO_MODE = import.meta.env.DEV && import.meta.env.VITE_ENABLE_MOCKS === 'true';
export const API_URL = (import.meta.env.VITE_API_URL || '/api/v1').replace(/\/$/, '');
export const client = axios.create({ baseURL: API_URL, timeout: 30000 });

export function storedKey(): string | null {
  try {
    return sessionStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

client.interceptors.request.use((config) => {
  if (DEMO_MODE)
    throw new Error(
      'This action is unavailable in the read-only demo. Connect to a backend to continue.'
    );
  const key = storedKey();
  if (key && !config.headers['X-API-Key']) config.headers['X-API-Key'] = key;
  return config;
});
client.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (
      axios.isAxiosError(error) &&
      error.response?.status === 401 &&
      error.config?.headers['X-API-Key'] === storedKey()
    ) {
      sessionStorage.removeItem(SESSION_KEY);
      window.dispatchEvent(new Event('evalforge:disconnected'));
    }
    return Promise.reject(error);
  }
);

export function unwrap(value: unknown): unknown {
  if (value && typeof value === 'object' && 'success' in value && 'data' in value) {
    if (value.success === false) throw new Error('The server could not complete this request.');
    return value.data;
  }
  return value;
}

export function pageData(value: unknown): PageData {
  const body = unwrap(value);
  if (Array.isArray(body)) {
    validateRecords(body);
    return { items: body, total: body.length };
  }
  if (body && typeof body === 'object') {
    const data = body as RecordData;
    const items =
      data.items ?? data.datasets ?? data.experiments ?? data.benchmark_suites ?? data.records;
    if (Array.isArray(items)) {
      validateRecords(items);
      const meta = data.meta as RecordData | undefined;
      const total = data.total ?? meta?.total_items ?? items.length;
      if (typeof total !== 'number' || !Number.isInteger(total) || total < 0)
        throw new Error('The server returned an invalid record count.');
      return { items, total };
    }
  }
  throw new Error(
    'The server returned an unexpected list format. Please retry or contact your administrator.'
  );
}

export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    const responseData = error.response?.data;
    if (responseData && typeof responseData === 'object') {
      const msg = (responseData as Record<string, unknown>).message;
      const detail = (responseData as Record<string, unknown>).detail;
      if (
        typeof msg === 'string' &&
        msg.trim() &&
        msg !== 'Internal Server Error. Please contact support.'
      ) {
        return redactText(msg.trim());
      }
      if (typeof detail === 'string' && detail.trim()) {
        return redactText(detail.trim());
      }
    }
    if (status === 401)
      return 'This API key is invalid, expired, or revoked. Connect with a valid key.';
    if (status === 403) return 'Your API key does not have permission for this action.';
    if (status === 404) return 'This resource is unavailable or outside your workspace.';
    if (status === 409) return 'An account with this email already exists. Please sign in instead.';
    if (status === 429) return 'Too many requests. Wait a moment, then retry.';
    if (status === 422 || status === 400)
      return 'The server rejected these values. Check the fields and try again.';
    if (!error.response)
      return 'Unable to reach the backend. Check your connection and server configuration, then retry.';
    return 'The server could not complete this request. Your changes have not been confirmed.';
  }
  return error instanceof Error ? redactText(error.message) : 'Something went wrong. Please retry.';
}

export async function getRecord(path: string, signal?: AbortSignal): Promise<RecordData> {
  const value = unwrap((await client.get(path, { signal })).data);
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('The server returned an unexpected response.');
  return value as RecordData;
}

export async function getPage(path: string, signal?: AbortSignal): Promise<PageData> {
  if (DEMO_MODE) {
    const { demoPage } = await import('./demo');
    return demoPage(path);
  }
  return pageData((await client.get(path, { signal })).data);
}

export async function download(path: string, filename: string): Promise<void> {
  const response = await client.get(path, { responseType: 'blob' });
  const url = URL.createObjectURL(response.data);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename.replace(/[^a-zA-Z0-9._-]/g, '_');
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function redactText(value: string): string {
  const key = storedKey();
  return (key ? value.split(key).join('[redacted]') : value).replace(
    /\b(?:ef_ent_|sk-)[A-Za-z0-9_-]{8,}/g,
    '[redacted]'
  );
}

function validateRecords(items: unknown[]): void {
  if (items.some((item) => !item || typeof item !== 'object' || Array.isArray(item)))
    throw new Error('The server returned an unexpected list format.');
}
