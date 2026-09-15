import { getJson, http, postJson } from '@/api/client';
import type { MappingDetail, PreprocessingRun } from '@/types/api';

export const mappingKeys = {
  current: (datasetId: string) => ['mapping', 'current', datasetId] as const,
  detail: (mappingId: string) => ['mapping', mappingId] as const,
  preprocessing: (mappingId: string) => ['mapping', mappingId, 'preprocessing'] as const,
};

export function fetchCurrentMapping(datasetId: string): Promise<MappingDetail> {
  return getJson<MappingDetail>(`/datasets/${datasetId}/mapping/current`);
}

export function createMapping(datasetId: string, notes?: string): Promise<MappingDetail> {
  return postJson<MappingDetail>(`/datasets/${datasetId}/mapping/versions`, { notes });
}

export interface AssignmentEdit {
  source_role: string;
  column_name: string;
  role: string;
  rationale?: string;
}

export async function updateAssignments(
  mappingId: string,
  assignments: AssignmentEdit[],
): Promise<MappingDetail> {
  const { data } = await http.patch<MappingDetail>(`/mappings/${mappingId}`, { assignments });
  return data;
}

export async function updateMappingConfig(
  mappingId: string,
  config: Record<string, string | number>,
): Promise<MappingDetail> {
  const { data } = await http.patch<MappingDetail>(`/mappings/${mappingId}`, { config });
  return data;
}

export function confirmMapping(mappingId: string, confirmedBy: string): Promise<MappingDetail> {
  return postJson<MappingDetail>(`/mappings/${mappingId}/confirm`, {
    confirmed_by: confirmedBy,
  });
}

export function startPreprocessing(mappingId: string): Promise<PreprocessingRun> {
  return postJson<PreprocessingRun>(`/mappings/${mappingId}/preprocess`);
}

export function fetchPreprocessing(mappingId: string): Promise<PreprocessingRun> {
  return getJson<PreprocessingRun>(`/mappings/${mappingId}/preprocessing`);
}

export function isPreprocessingRunning(status: string | undefined): boolean {
  return status === 'pending' || status === 'running';
}
