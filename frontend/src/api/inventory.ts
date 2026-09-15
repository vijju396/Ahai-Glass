import { getJson } from '@/api/client';
import type {
  RecommendationsResponse,
  SupplyOverviewResponse,
  TransferableStockResponse,
} from '@/types/phase7';

export const inventoryKeys = {
  recommendations: (query: Record<string, unknown>) =>
    ['inventory', 'recommendations', query] as const,
  overview: (branch?: string) => ['inventory', 'overview', branch ?? 'all'] as const,
  transferable: (sku: string, exclude?: string) =>
    ['inventory', 'transferable', sku, exclude ?? 'none'] as const,
};

export function fetchRecommendations(
  query: {
    forecast_run_id?: string;
    period?: string;
    service_level?: number;
    scope_level?: string;
    branch?: string;
    sku?: string;
    include_unavailable?: boolean;
    only_actionable?: boolean;
    limit?: number;
  } = {},
): Promise<RecommendationsResponse> {
  return getJson<RecommendationsResponse>('/inventory/recommendations', {
    service_level: 95,
    limit: 100,
    ...query,
  });
}

export function fetchSupplyOverview(
  branch?: string,
  limit = 25,
): Promise<SupplyOverviewResponse> {
  return getJson<SupplyOverviewResponse>('/inventory/overview', { branch, limit });
}

export function fetchTransferableStock(
  canonical_sku: string,
  exclude_branch?: string,
): Promise<TransferableStockResponse> {
  return getJson<TransferableStockResponse>('/inventory/transferable', {
    canonical_sku,
    exclude_branch,
  });
}
