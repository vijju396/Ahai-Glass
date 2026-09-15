import { useQuery } from '@tanstack/react-query';
import { datasetKeys, fetchDatasets, isIngestionRunning } from '@/api/datasets';
import type { Dataset } from '@/types/api';

/**
 * The most recent dataset, polled while its ingestion is still running.
 *
 * Ingestion streams ~2.6 M rows and takes roughly eight minutes, so pages poll
 * rather than block. Polling stops the moment the version reaches a terminal
 * status.
 */
export function useActiveDataset() {
  const query = useQuery({
    queryKey: datasetKeys.list,
    queryFn: fetchDatasets,
    refetchInterval: (query) => {
      const latest = query.state.data?.items?.[0]?.latest_version;
      return isIngestionRunning(latest?.status) ? 3000 : false;
    },
  });

  const dataset: Dataset | undefined = query.data?.items?.[0];
  const version = dataset?.latest_version ?? undefined;

  return {
    ...query,
    dataset,
    version,
    isRunning: isIngestionRunning(version?.status),
    hasCompleted:
      version?.status === 'completed' || version?.status === 'completed_with_failures',
  };
}
