/**
 * The single HTTP client. Every request in the app goes through this module so
 * error shape, base URL and correlation IDs are handled in exactly one place.
 */
import axios, { AxiosError } from 'axios';
import type { ApiErrorBody } from '@/types/api';

export const API_BASE = import.meta.env.VITE_API_BASE ?? '/api';

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly remediation?: string;
  readonly correlationId?: string;
  readonly details?: Record<string, unknown>;

  constructor(
    message: string,
    status: number,
    code: string,
    remediation?: string,
    correlationId?: string,
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.remediation = remediation;
    this.correlationId = correlationId;
    this.details = details;
  }
}

export const http = axios.create({
  baseURL: API_BASE,
  timeout: 60_000,
  headers: { 'Content-Type': 'application/json' },
});

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorBody>) => {
    const body = error.response?.data;
    if (body?.error) {
      return Promise.reject(
        new ApiError(
          body.error.message,
          error.response?.status ?? 0,
          body.error.code,
          body.error.remediation,
          body.error.correlation_id,
          body.error.details,
        ),
      );
    }
    // A network failure or a non-JSON response: still surfaced as ApiError so
    // every consumer handles one type. The user-facing message is deliberately
    // generic, but the underlying error is kept as `cause` rather than
    // discarded - without it a transport-level failure arrives with no detail
    // at all, which is exactly the case that is hardest to diagnose.
    const wrapped = new ApiError(
      error.code === 'ECONNABORTED'
        ? 'The request timed out.'
        : 'Could not reach the API. Is the backend running on port 8000?',
      error.response?.status ?? 0,
      error.code ?? 'network_error',
    );
    wrapped.cause = error;
    return Promise.reject(wrapped);
  },
);

export async function getJson<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const { data } = await http.get<T>(path, { params });
  return data;
}

export async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const { data } = await http.post<T>(path, body);
  return data;
}
