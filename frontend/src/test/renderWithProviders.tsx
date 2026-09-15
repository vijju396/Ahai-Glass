import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { ToastProvider } from '@/components/ui/Toast';

export function renderWithProviders(ui: ReactElement, route = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    ),
  };
}

/** The full 13-model payload the real API returns, for tests that need it. */
export const MODEL_REGISTRY_FIXTURE = {
  official_model_count: 13,
  min_history_profile: 'reference',
  xgboost_training_profile: 'thorough',
  notes: [
    'q80/q90/q95 are forecast outputs calibrated from out-of-sample residuals, not additional models.',
    'Naive, seasonal-naive, MA3 and MA6 are non-registry baselines.',
  ],
  baselines: [
    { method_id: 'naive', display_name: 'Naive (last value)' },
    { method_id: 'seasonal_naive', display_name: 'Seasonal naive' },
    { method_id: 'ma3', display_name: 'Moving average (3)' },
    { method_id: 'ma6', display_name: 'Moving average (6)' },
  ],
  models: [
    ['sarimax', 'SARIMAX', 'statsmodels', 12, 'state_space', false, false, false],
    ['sarimax_exog', 'SARIMAX with exogenous variables', 'statsmodels', 12, 'state_space', true, false, false],
    ['auto_arima', 'Auto ARIMA', 'pmdarima', 24, 'state_space', false, false, true],
    ['auto_arima_exog', 'Auto ARIMA with exogenous variables', 'pmdarima', 24, 'state_space', true, false, true],
    ['xgboost', 'XGBoost', 'xgboost', 6, 'gradient_boosting', false, true, false],
    ['xgboost_exog', 'XGBoost with exogenous variables', 'xgboost', 6, 'gradient_boosting', true, true, false],
    ['exp_additive', 'Exponential Smoothing Additive', 'statsmodels', 24, 'exponential_smoothing', false, false, false],
    ['exp_additive_damped', 'Exponential Smoothing Additive Damped', 'statsmodels', 24, 'exponential_smoothing', false, false, false],
    ['exp_multiplicative', 'Exponential Smoothing Multiplicative', 'statsmodels', 24, 'exponential_smoothing', false, false, false],
    ['exp_multiplicative_damped', 'Exponential Smoothing Multiplicative Damped', 'statsmodels', 24, 'exponential_smoothing', false, false, false],
    ['var', 'VAR', 'statsmodels', 10, 'vector_autoregression', false, false, false],
    ['var_exog', 'VAR with exogenous variables', 'statsmodels', 10, 'vector_autoregression', true, false, false],
    ['lstm', 'LSTM', 'tensorflow', 14, 'neural_network', false, false, true],
  ].map(([id, name, dep, minHistory, family, exog, pooled, holdout], index) => ({
    model_id: id as string,
    display_name: name as string,
    rank: index + 1,
    dependency_module: dep as string,
    requires_exogenous: exog as boolean,
    supports_pooled_training: pooled as boolean,
    uses_fast_holdout: holdout as boolean,
    min_required_history: minHistory as number,
    min_history_reason: `Requires ${minHistory} training rows.`,
    family: family as string,
  })),
};
