/**
 * The pipeline panel's contract.
 *
 * This panel exists to be talked through in front of someone, so the failure
 * that matters is not a crash — it is a sentence that stays confident while the
 * run underneath it changes. Each test therefore feeds a run whose shape is
 * *different from the live one* and asserts the prose moved with it.
 *
 * The honesty rules it must not lose:
 *   - Ineligible is described as a declined fit with a reason, never a failure.
 *   - An unavailable forecast row is described as having no number, never zero.
 *   - The reconciliation method named is the one that ran, not a constant.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import * as trainingApi from '@/api/training';
import * as analyticsApi from '@/api/analytics';
import * as forecastApi from '@/api/forecasts';
import { PipelineExplainer } from '../components/PipelineExplainer';
import { renderWithProviders } from '@/test/renderWithProviders';
import { forecastRunFixture, trainingRunFixture } from '@/test/phase7Fixtures';

function monitorFixture(
  overrides: Partial<trainingApi.TrainingMonitor> = {},
): trainingApi.TrainingMonitor {
  return {
    run_id: 'train-0001',
    status: 'completed',
    stage_detail: null,
    progress_pct: 100,
    created_at: null,
    started_at: null,
    finished_at: null,
    duration_seconds: 120,
    is_live: false,
    counters: {
      total: 60,
      completed: 55,
      ineligible: 3,
      failed: 1,
      timed_out: 1,
      not_evaluated: 0,
    },
    series_requested: 4,
    series_evaluated: 4,
    restriction: null,
    folds: [
      {
        index: 0,
        name: 'primary',
        train_end: '2025-09',
        train_rows: 18,
        validate_from: '2025-10',
        validate_to: '2026-03',
        validate_months: 6,
        horizons: [1, 2, 3, 4, 5, 6],
      },
    ],
    models: [
      {
        model_id: 'auto_arima',
        display_name: 'Auto ARIMA',
        is_baseline: false,
        total: 5,
        completed: 2,
        ineligible: 3,
        failed: 0,
        timed_out: 0,
        not_evaluated: 0,
        running: 0,
        pending: 0,
        median_wape: 12,
        best_wape: 9,
        median_mape: 11,
        fit_seconds: 3,
        champion_count: 3,
        scored: 2,
        accuracy: 89,
        accuracy_series: 80,
        accuracy_aggregate: 92,
        reason: 'needs at least 18 training observations; this window has 11.',
      } as trainingApi.MonitorModel,
    ],
    registry_model_count: 13,
    baseline_model_count: 4,
    pipeline: {
      scopes_total: 5,
      scopes_by_level: { national: 1, series: 4 },
      registry_models: 13,
      baseline_models: 4,
      champions_selected: 5,
      champions_beaten_by_baseline: 2,
      champion_spread: { auto_arima: 3, lstm: 2 },
    },
    ...overrides,
  };
}

function explainFixture(): analyticsApi.TrainingExplain {
  return {
    validation: {
      method: 'rolling_origin',
      why: 'because',
      horizon_months: 6,
      min_train_periods: 12,
      panel_window: { start: '2024-01', end: '2026-07' },
      mandated_train_ends: ['2025-09'],
      origins: [],
      fold_fitted_preprocessing: 'inside each fold',
      exogenous_rule: 'no future-unknown regressors',
    },
    models: [],
    model_count: 13,
    metrics: [],
    selection: {
      primary_metric: 'mape',
      primary_metric_choices: ['mape', 'wape'],
      default_primary_metric: 'mape',
      tie_breaks: ['absolute bias', 'MAE'],
      why_bias_second: 'bias is directional',
      min_validation_points: 4,
      min_test_point_share: 0.5,
      baselines_never_champion: true,
      baselines: [{ model_id: 'naive', rule: 'last value' }],
    },
    tuning: {
      summary: 'very little',
      search_inside_folds: [],
      fixed_settings: {},
      not_tuned: [],
    },
    status_vocabulary: [],
    active_run: null,
    notes: [],
  };
}

function stub(
  monitor = monitorFixture(),
  forecast = forecastRunFixture({ training_run_id: 'train-0001' }),
) {
  vi.spyOn(trainingApi, 'fetchCurrentRun').mockResolvedValue(
    trainingRunFixture({ id: 'train-0001' }),
  );
  vi.spyOn(trainingApi, 'fetchTrainingMonitor').mockResolvedValue(monitor);
  vi.spyOn(analyticsApi, 'fetchTrainingExplain').mockResolvedValue(explainFixture());
  vi.spyOn(forecastApi, 'fetchCurrentForecastRun').mockResolvedValue(forecast);
}

/**
 * Several of these sentences are deliberately broken by `<strong>`, so
 * `findByText` on the whole phrase matches no single node. This asserts against
 * the paragraph's flattened text instead, which is what a reader actually sees.
 */
function findSentence(pattern: RegExp) {
  return screen.findByText((_content, element) => {
    if (!element) return false;
    const text = (element.textContent ?? '').replace(/\s+/g, ' ');
    if (!pattern.test(text)) return false;
    // Match the innermost element containing it, so one hit not many.
    return !Array.from(element.children).some((child) =>
      pattern.test((child.textContent ?? '').replace(/\s+/g, ' ')),
    );
  });
}

describe('PipelineExplainer', () => {
  it('derives the fit count from the run rather than stating a constant', async () => {
    stub();
    renderWithProviders(<PipelineExplainer />);
    // 13 registered + 4 baselines against 5 scopes.
    expect(await findSentence(/17 × 5 = 60 fits/)).toBeInTheDocument();
  });

  it('describes Ineligible as a declined fit with its reason, not a failure', async () => {
    stub();
    renderWithProviders(<PipelineExplainer />);
    expect(await screen.findByText(/Ineligible is not failure/i)).toBeInTheDocument();
    expect(
      screen.getByText(/needs at least 18 training observations/),
    ).toBeInTheDocument();
  });

  it('counts the models that actually won a scope, not the registry size', async () => {
    stub();
    renderWithProviders(<PipelineExplainer />);
    expect(
      await findSentence(/2 different models each won at least one scope/i),
    ).toBeInTheDocument();
  });

  it('names the reconciliation method that ran, not MinT unconditionally', async () => {
    stub(monitorFixture(), forecastRunFixture({
      training_run_id: 'train-0001',
      reconciliation_method: 'bottom_up',
    }));
    renderWithProviders(<PipelineExplainer />);
    expect(await screen.findByText(/Bottom-up aggregation/)).toBeInTheDocument();
    expect(screen.queryByText(/MinT reconciliation/)).not.toBeInTheDocument();
  });

  it('says an unavailable forecast row has no number rather than a zero', async () => {
    stub();
    renderWithProviders(<PipelineExplainer />);
    expect(await findSentence(/no number at all/i)).toBeInTheDocument();
  });

  it('flags when the live forecast came from a different training run', async () => {
    stub(monitorFixture(), forecastRunFixture({ training_run_id: 'train-9999' }));
    renderWithProviders(<PipelineExplainer />);
    expect(
      await findSentence(/a different training run \(train-99\)/),
    ).toBeInTheDocument();
  });
});
