/**
 * Training Center.
 *
 * Three properties this page is built around:
 *
 * **The cost is shown before the run starts.** The estimate endpoint is called
 * on every option change, so nobody submits a three-hour run by accident. The
 * same figure is stored on the run and shown beside the actual duration.
 *
 * **Every model is listed, whatever happened to it.** The per-model table has
 * no status filter, and `models_missing` is rendered as an explicit defect
 * banner rather than being invisible.
 *
 * **Model identity comes from the API.** This file contains no model IDs; the
 * rows come from the run, and the tier options are the three the backend
 * accepts. `src/test/no-duplicate-registry.test.ts` scans for a second
 * registry.
 */
import { useMemo, useState } from 'react';
import { ComparisonBars } from '@/components/charts/ComparisonBars';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@/api/client';
import {
  cancelRun,
  estimateRun,
  fetchCurrentRun,
  fetchRunDetail,
  submitRun,
  trainingKeys,
} from '@/api/training';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/States';
import { StatusPill } from '@/components/ui/StatusPill';
import { useToast } from '@/components/ui/Toast';
import { formatInt, formatPct, formatSeconds } from '@/components/ui/format';
import type { ModelRunStatus } from '@/types/api';
import type { TrainingRunRequest } from '@/types/phase7';
import { Explain } from '@/components/ui/Explain';

const TIERS = [
  {
    id: 'aggregate',
    label: 'Aggregate levels',
    hint: 'National, region, branch and segment totals. Cheapest, and an aggregate is far less intermittent than the cells beneath it.',
  },
  {
    id: 'local',
    label: 'High-value local series',
    hint: 'Per-series fits for the top-N branch × SKU series by value.',
  },
  {
    id: 'pooled',
    label: 'Pooled full network',
    hint: 'One global XGBoost over the whole panel, which is what makes full-network scoring affordable.',
  },
] as const;

/** A run in one of these states is still moving, so the page keeps polling. */
const LIVE_STATES = new Set(['queued', 'running', 'cancelling']);

export function TrainingCenterPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [tiers, setTiers] = useState<string[]>(['aggregate']);
  const [maxLocal, setMaxLocal] = useState(100);

  const request: TrainingRunRequest = useMemo(
    () => ({ tiers, max_local_series: maxLocal }),
    [tiers, maxLocal],
  );

  const estimate = useQuery({
    queryKey: trainingKeys.estimate(request),
    queryFn: () => estimateRun(request),
    enabled: tiers.length > 0,
    retry: false,
  });

  const current = useQuery({
    queryKey: trainingKeys.current,
    queryFn: fetchCurrentRun,
    retry: false,
    refetchInterval: (query) =>
      LIVE_STATES.has(query.state.data?.status ?? '') ? 2000 : false,
  });

  const runId = current.data?.id;
  const detail = useQuery({
    queryKey: trainingKeys.detail(runId ?? ''),
    queryFn: () => fetchRunDetail(runId as string),
    enabled: Boolean(runId),
    refetchInterval: LIVE_STATES.has(current.data?.status ?? '') ? 3000 : false,
  });

  const submit = useMutation({
    mutationFn: () => submitRun(request),
    onSuccess: (run) => {
      toast.notify(
        `Run ${run.id.slice(0, 8)} is queued. Progress appears below; nothing runs inside the request.`,
        'ok',
      );
      queryClient.invalidateQueries({ queryKey: trainingKeys.current });
    },
    onError: (error) =>
      toast.notify(
        error instanceof ApiError
          ? [error.message, error.remediation].filter(Boolean).join(' ')
          : String(error),
        'error',
      ),
  });

  const cancel = useMutation({
    mutationFn: () => cancelRun(runId as string),
    onSuccess: () => {
      toast.notify(
        'Cancellation requested. The rows already written are kept - a partial run that says it is partial is more useful than one that deletes its own evidence.',
        'info',
      );
      queryClient.invalidateQueries({ queryKey: trainingKeys.current });
    },
  });

  const toggleTier = (tier: string) =>
    setTiers((previous) =>
      previous.includes(tier)
        ? previous.filter((item) => item !== tier)
        : [...previous, tier],
    );

  const run = current.data;
  const rows = detail.data?.model_runs ?? [];
  const registered = rows.filter((row) => !row.is_baseline);
  const baselines = rows.filter((row) => row.is_baseline);

  return (
    <div className="stack">
      <div className="page-head">
        <div className="eyebrow">04 &middot; Training Center</div>
        <h1>Training Center</h1>
        <Explain label="About this page" variant="note">
          Submit a run, watch every one of the thirteen models, and cancel where
          it is safe. The estimated cost is shown before the run starts and
          stored beside what it actually took.
        </Explain>
      </div>

      {run && <Card title="Evaluation coverage" subtitle="Latest run · every outcome retained, including budget exclusions"><ComparisonBars unit="Model evaluations" labels={['Completed', 'Ineligible', 'Failed', 'Timed out', 'Not evaluated']} series={[{ name: 'Evaluations', values: [run.model_runs_completed, run.model_runs_ineligible, run.model_runs_failed, run.model_runs_timed_out, run.model_runs_not_evaluated] }]} height={240} /></Card>}
      <Card
        title="Submit a run"
        subtitle="Tiers execute cheapest-first, so a cancelled run still produced its most aggregated results"
      >
        <fieldset className="field-group">
          <legend className="visually-hidden">Tiers</legend>
          {TIERS.map((tier) => (
            <label key={tier.id} className="check-row">
              <input
                type="checkbox"
                checked={tiers.includes(tier.id)}
                onChange={() => toggleTier(tier.id)}
              />
              <span>
                <strong>{tier.label}</strong>
                <span className="hint">{tier.hint}</span>
              </span>
            </label>
          ))}
        </fieldset>

        {tiers.includes('local') && (
          <label className="field">
            <span>Local series cap</span>
            <input
              type="number"
              min={1}
              max={68675}
              value={maxLocal}
              onChange={(event) => setMaxLocal(Number(event.target.value) || 1)}
            />
            <span className="hint">
              Per-series fits are the expensive tier. The cap is what keeps the
              run bounded on a 68,675-series panel.
            </span>
          </label>
        )}

        {estimate.isPending && <LoadingBlock rows={2} label="Estimating run cost" />}
        {estimate.isError && <ErrorState error={estimate.error} onRetry={() => estimate.refetch()} />}
        {estimate.data && (
          <div className="estimate" data-testid="run-estimate">
            <div className="metric-row">
              <div className="metric">
                <span className="metric-label">Estimated</span>
                <span className="metric-value">{estimate.data.estimated_human}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Upper bound</span>
                <span className="metric-value">{estimate.data.estimated_human_upper}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Model fits</span>
                <span className="metric-value">{formatInt(estimate.data.total_fits)}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Workers</span>
                <span className="metric-value">{estimate.data.workers}</span>
              </div>
            </div>
            <Explain variant="hint">{estimate.data.provenance}</Explain>
            {estimate.data.tiers.map((tier) =>
              tier.notes.length ? (
                <p key={tier.tier} className="hint">
                  <strong>{tier.tier}:</strong> {tier.notes.join(' ')}
                </p>
              ) : null,
            )}
          </div>
        )}

        <div className="actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={tiers.length === 0 || submit.isPending}
            onClick={() => submit.mutate()}
          >
            {submit.isPending ? 'Submitting…' : 'Start training run'}
          </button>
          {run && LIVE_STATES.has(run.status) && (
            <button
              type="button"
              className="btn"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate()}
            >
              Cancel run
            </button>
          )}
        </div>
      </Card>

      <Card
        title="Current run"
        subtitle={run ? `${run.tiers} · ${run.status}` : 'No run has been submitted yet'}
      >
        {current.isPending && <LoadingBlock rows={3} label="Loading current run" />}
        {current.isError &&
          (current.error instanceof ApiError && current.error.status === 404 ? (
            <EmptyState title="No training run yet">
              Submit one above. Nothing on this page is populated with placeholder
              figures.
            </EmptyState>
          ) : (
            <ErrorState error={current.error} onRetry={() => current.refetch()} />
          ))}
        {run && (
          <>
            <div className="metric-row">
              <div className="metric">
                <span className="metric-label">Progress</span>
                <span className="metric-value">{formatPct(run.progress_pct, 1)}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Estimated</span>
                <span className="metric-value">{formatSeconds(run.estimated_seconds)}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Actual</span>
                <span className="metric-value">{formatSeconds(run.duration_seconds)}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Series evaluated</span>
                <span className="metric-value">{formatInt(run.series_evaluated)}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Residuals</span>
                <span className="metric-value">{formatInt(run.residuals_recorded)}</span>
              </div>
            </div>
            <progress
              max={100}
              value={run.progress_pct}
              aria-label="Training progress"
              style={{ width: '100%' }}
            />
            {run.stage_detail && <Explain variant="hint">{run.stage_detail}</Explain>}
            {run.failure_reason && (
              <Explain variant="hint">
                <strong>Failure:</strong> {run.failure_reason}
              </Explain>
            )}
            <div className="metric-row" data-testid="status-counts">
              {[
                ['Completed', run.model_runs_completed],
                ['Ineligible', run.model_runs_ineligible],
                ['Failed', run.model_runs_failed],
                ['Timed out', run.model_runs_timed_out],
                ['Not evaluated (budget)', run.model_runs_not_evaluated],
              ].map(([label, value]) => (
                <div className="metric" key={String(label)}>
                  <span className="metric-label">{label}</span>
                  <span className="metric-value">{formatInt(Number(value))}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>

      {detail.data && detail.data.models_missing.length > 0 && (
        <Card title="Models missing from this run">
          <p role="alert">
            These registered models have <strong>no row at all</strong> in this
            run: {detail.data.models_missing.join(', ')}. That is a defect, not
            a status — every model the run asked about should have written a row
            whatever its outcome.
          </p>
        </Card>
      )}

      <Card
        title="Per-model status"
        subtitle={
          detail.data
            ? `${detail.data.model_runs_matching} rows across every scope this run reached · status is never filtered`
            : 'Awaiting a run'
        }
      >
        {detail.isPending && runId && <LoadingBlock rows={6} label="Loading model rows" />}
        {!runId && (
          <EmptyState title="No per-model rows yet">
            A run writes one row per (scope, model) it asked about — including the
            ones that were ineligible, failed, timed out, or were never reached.
          </EmptyState>
        )}
        {registered.length > 0 && (
          <div className="table-scroll">
            <table className="data" data-testid="model-run-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Scope</th>
                  <th>Status</th>
                  <th>Evaluation</th>
                  <th className="num">WAPE</th>
                  <th className="num">Points</th>
                  <th className="num">Folds</th>
                  <th className="num">Fit</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {registered.map((row) => (
                  <tr key={row.id}>
                    <td>{row.display_name}</td>
                    <td className="mono">
                      {row.scope_level}/{row.scope_key}
                    </td>
                    <td>
                      <StatusPill status={row.status as ModelRunStatus} />
                    </td>
                    <td>{row.evaluation_mode ?? '—'}</td>
                    <td className="num">{formatPct(row.wape)}</td>
                    <td className="num">{formatInt(row.validation_points)}</td>
                    <td className="num">
                      {row.origins_completed}/{row.origins_total}
                    </td>
                    <td className="num">{formatSeconds(row.fit_seconds)}</td>
                    <td>{row.failure_reason ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {baselines.length > 0 && (
          <>
            <h3 style={{ marginTop: 'var(--sp-5)' }}>Non-registry baselines</h3>
            <Explain variant="hint">
              Naive, seasonal-naive, MA3 and MA6. Reported for comparison and
              never counted among the thirteen — and never champion, even when
              one of them wins.
            </Explain>
            <div className="table-scroll">
              <table className="data" data-testid="baseline-table">
                <thead>
                  <tr>
                    <th>Method</th>
                    <th>Scope</th>
                    <th className="num">WAPE</th>
                    <th className="num">MAE</th>
                    <th className="num">Points</th>
                  </tr>
                </thead>
                <tbody>
                  {baselines.map((row) => (
                    <tr key={row.id}>
                      <td>{row.display_name}</td>
                      <td className="mono">
                        {row.scope_level}/{row.scope_key}
                      </td>
                      <td className="num">{formatPct(row.wape)}</td>
                      <td className="num">{formatInt(row.mae)}</td>
                      <td className="num">{formatInt(row.validation_points)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
