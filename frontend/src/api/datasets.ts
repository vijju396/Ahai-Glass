import { getJson, postJson } from '@/api/client';
import type {
  Dataset,
  DatasetCreateResponse,
  DatasetProfileResponse,
  MappingResponse,
  Page,
  ValidationResponse,
} from '@/types/api';

export const datasetKeys = {
  list: ['datasets'] as const,
  detail: (id: string) => ['datasets', id] as const,
  profile: (id: string) => ['datasets', id, 'profile'] as const,
  validation: (id: string) => ['datasets', id, 'validation'] as const,
  mapping: (id: string) => ['datasets', id, 'mapping'] as const,
};

export function fetchDatasets(): Promise<Page<Dataset>> {
  return getJson<Page<Dataset>>('/datasets');
}

export function fetchDataset(id: string): Promise<Dataset> {
  return getJson<Dataset>(`/datasets/${id}`);
}

export function fetchProfile(id: string): Promise<DatasetProfileResponse> {
  return getJson<DatasetProfileResponse>(`/datasets/${id}/profile`);
}

export function fetchValidation(id: string): Promise<ValidationResponse> {
  return getJson<ValidationResponse>(`/datasets/${id}/validation`);
}

export function fetchMapping(id: string): Promise<MappingResponse> {
  return getJson<MappingResponse>(`/datasets/${id}/mapping`);
}

export function createDataset(body: {
  name: string;
  description?: string;
}): Promise<DatasetCreateResponse> {
  return postJson<DatasetCreateResponse>('/datasets', body);
}

export function cancelIngestion(id: string): Promise<{ cancellation_requested: boolean }> {
  return postJson(`/datasets/${id}/cancel`);
}

/** True while ingestion is still working, so a page can poll. */
export function isIngestionRunning(status: string | undefined): boolean {
  return ['pending', 'reading', 'cleaning', 'validating'].includes(status ?? '');
}
