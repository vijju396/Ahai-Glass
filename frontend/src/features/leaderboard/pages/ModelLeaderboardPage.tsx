/**
 * Model Leaderboard.
 *
 * The rules this page exists to enforce visually:
 *
 * - **All thirteen appear.** Rows come from the leaderboard endpoint, which
 *   never filters by status, and `models_missing` renders as a defect banner.
 * - **Both rankings, side by side.** `rank` is the AIS operational ranking
 *   (WAPE, absolute bias, MAE, model id); `legacy_rank` is the references'
 *   lowest-valid-MAPE rule. They are separate columns and never averaged.
 * - **A baseline is never champion**, and when one beats the champion the page
 *   says so in words rather than leaving the reader to compare two numbers.
 * - **`null` is not zero.** An undefined metric renders as an em dash.
 *
 * Model identity comes only from the API. This file lists no model IDs;
 * `src/test/no-duplicate-registry.test.ts` scans for a second registry.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ApiError } from '@/api/client';
import {
  fetchComparison,
  fetchLeaderboard,
  fetchScopes,
  leaderboardKeys,
} from '@/api/leaderboard';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/States';
import { StatusPill } from '@/components/ui/StatusPill';
import { formatInt } from '@/components/ui/format';
import type { ModelRunStatus } from '@/types/api';
import { WapeChart } from '../components/WapeChart';
import { ChampionPanel } from '../components/ChampionPanel';
import { DiagnosticsPanel } from '../components/DiagnosticsPanel';
import { Explain } from '@/components/ui/Explain';

const SCOPE_LEVELS = ['national', 'region', 'branch', 'segment', 'series'] as const;

function metric(value: number | null | undefined, digits = 3): string {
  return value === null || value === undefined ? '—' : value.toFixed(digits);
}

export function ModelLeaderboardPage() {
  const [scopeLevel, setScopeLevel] = useState<string>('national');
  const [scopeKey, setScopeKey] = useState<string>('NATIONAL');
  const [selectedModel, setSelectedModel] = useState<string | null>(null);

  const scopes = useQuery({
    queryKey: leaderboardKeys.scopes(scopeLevel),
    queryFn: () => fetchScopes(scopeLevel),
    retry: false,
  });

  const query = { scope_level: scopeLevel, scope_key: scopeKey };
  const board = useQuery({
    queryKey: leaderboardKeys.board(query),
    queryFn: () => fetchLeaderboard(query),
    retry: false,
  });
  const comparison = useQuery({
    queryKey: leaderboardKeys.comparison(query),
    queryFn: () => fetchComparison(query),
    retry: false,
  });

  const data = board.data;
  const registered = (data?.rows ?? []).filter((row) => !row.is_baseline);
  const baselines = (data?.rows ?? []).filter((row) => row.is_baseline);

  const onLevelChange = (level: string) => {
    setScopeLevel(level);
    setScopeKey(level === 'national' ? 'NATIONAL' : '');
    setSelectedModel(null);
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div className="eyebrow">05 &middot; Model leaderboard</div>
        <h1>Model Leaderboard</h1>
        <Explain label="About this page" variant="note">
          All thirteen registered models, always shown. A model that did not run
          reports why &mdash; Ineligible, Failed, Timed out, or Not evaluated
          (budget) &mdash; and is never replaced by a zero forecast or dropped
          from this table.
        </Explain>
      </div>

      <Card title="Scope" subtitle="Metrics from different aggregation levels are not comparable, so a scope is chosen explicitly">
        <div className="field-row">
          <label className="field">
            <span>Level</span>
            <select value={scopeLevel} onChange={(event) => onLevelChange(event.target.value)}>
              {SCOPE_LEVELS.map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Scope</span>
            <select
              value={scopeKey}
              onChange={(event) => {
                setScopeKey(event.target.value);
                setSelectedModel(null);
              }}
              disabled={scopes.isPending}
            >
              <option value="">Select a scope…</option>
              {(scopes.data?.items ?? []).map((scope) => (
                <option key={scope.scope_key} value={scope.scope_key}>
                  {scope.scope_key}
                </option>
              ))}
            </select>
            <span className="hint">
              {scopes.data
                ? `${scopes.data.total} ${scopeLevel} scope(s) in the latest run`
                : 'Loading the scopes this run reached'}
            </span>
          </label>
        </div>
      </Card>

      {board.isPending && (
        <Card>
          <LoadingBlock rows={8} label="Loading leaderboard" />
        </Card>
      )}
      {board.isError && (
        <Card>
          {board.error instanceof ApiError && board.error.status === 404 ? (
            <EmptyState title="No leaderboard for this scope yet">
              {board.error.message} {board.error.remediation}
            </EmptyState>
          ) : (
            <ErrorState error={board.error} onRetry={() => board.refetch()} />
          )}
        </Card>
      )}

      {data && (
        <>
          {data.models_missing.length > 0 && (
            <div className="callout crit" role="alert">
              <div className="h">Models missing from this leaderboard</div>
              <p>
                {data.models_missing.join(', ')} have no row at all in this
                scope. That is a defect rather than a status — a model that did
                not run should still appear, carrying its reason.
              </p>
            </div>
          )}

          {data.beaten_by_baseline && (
            <div className="callout warn">
              <div className="h">A non-registry baseline beats the champion here</div>
              <p>
                {data.best_baseline_model_id} reaches WAPE{' '}
                {metric(data.best_baseline_wape)}% against the champion&rsquo;s{' '}
                {metric(registered.find((row) => row.is_champion)?.wape ?? null)}%.
                The champion is still the best of the thirteen registered models;
                it is not the best available forecast for this scope.
              </p>
            </div>
          )}

          {data.notes.map((note) => (
            <Explain variant="callout">
              <p>{note}</p>
            </Explain>
          ))}

          <Card
            title="WAPE by model"
            subtitle="Primary AIS ranking metric — chosen because the data is full of zeros, where MAPE is undefined"
          >
            {comparison.isPending && <LoadingBlock rows={4} label="Loading comparison" />}
            {comparison.isError && (
              <ErrorState error={comparison.error} onRetry={() => comparison.refetch()} />
            )}
            {comparison.data && (
              <WapeChart
                points={comparison.data}
                caption={`${data.scope_level}/${data.scope_key} · ${data.ranked_count} ranked, ${data.excluded_count} present but unranked`}
              />
            )}
          </Card>

          <Card
            title="Registered models"
            subtitle={`${registered.length} rows · champion ${data.champion_model_id ?? 'not selected'} · challenger ${data.challenger_model_id ?? '—'} · legacy-parity winner ${data.legacy_champion_model_id ?? '—'}`}
          >
            <div className="table-scroll">
              <table className="data" data-testid="leaderboard-table">
                <thead>
                  <tr>
                    <th className="num">Rank</th>
                    <th className="num">Legacy</th>
                    <th>Model</th>
                    <th>Status</th>
                    <th>Evaluation</th>
                    <th className="num">WAPE %</th>
                    <th className="num">MAPE %</th>
                    <th className="num">Accuracy %</th>
                    <th className="num">MAE</th>
                    <th className="num">RMSE</th>
                    <th className="num">sMAPE</th>
                    <th className="num">MASE</th>
                    <th className="num">Bias</th>
                    <th className="num">Points</th>
                    <th className="num">Folds</th>
                    <th>Role</th>
                    <th>Reason</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {registered.map((row) => (
                    <tr key={row.model_id} data-model={row.model_id}>
                      <td className="num">{row.rank ?? '—'}</td>
                      <td className="num">{row.legacy_rank ?? '—'}</td>
                      <td>{row.display_name}</td>
                      <td>
                        <StatusPill status={row.status as ModelRunStatus} />
                      </td>
                      <td>{row.evaluation_mode ?? '—'}</td>
                      <td className="num">{metric(row.wape)}</td>
                      <td className="num">{metric(row.mape, 2)}</td>
                      <td className="num">{metric(row.accuracy, 1)}</td>
                      <td className="num">{formatInt(row.mae)}</td>
                      <td className="num">{formatInt(row.rmse)}</td>
                      <td className="num">{metric(row.smape, 2)}</td>
                      <td className="num">{metric(row.mase, 3)}</td>
                      <td className="num">{metric(row.bias, 2)}</td>
                      <td className="num">{formatInt(row.validation_points)}</td>
                      <td className="num">
                        {row.origins_completed}/{row.origins_total}
                      </td>
                      <td>
                        {row.is_champion && <span className="pill pill-accent">Champion</span>}
                        {row.is_challenger && <span className="pill pill-info">Challenger</span>}
                        {!row.is_champion && !row.is_challenger && '—'}
                      </td>
                      <td>{row.failure_reason ?? row.exclusion_reason ?? '—'}</td>
                      <td>
                        <button
                          type="button"
                          className="btn"
                          onClick={() =>
                            setSelectedModel(
                              selectedModel === row.model_id ? null : row.model_id,
                            )
                          }
                        >
                          {selectedModel === row.model_id ? 'Hide' : 'Diagnostics'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Explain variant="hint">
              Accuracy is <strong>informational only</strong>: it is{' '}
              <code>max(0, 100 &minus; MAPE)</code>, and MAPE is undefined
              wherever the actual is zero. Ranking uses WAPE, then absolute bias,
              then MAE, then a deterministic model-id tie-break.
            </Explain>
            {data.skill_vs_best_baseline.improvement_pct !== null && (
              <Explain variant="hint">
                Champion versus best baseline:{' '}
                {data.skill_vs_best_baseline.improvement_pct.toFixed(1)}%{' '}
                {data.skill_vs_best_baseline.champion_better ? 'better' : 'worse'}.
              </Explain>
            )}
            {data.skill_vs_best_baseline.reason && (
              <Explain variant="hint">{data.skill_vs_best_baseline.reason}</Explain>
            )}
          </Card>

          {selectedModel && (
            <DiagnosticsPanel
              modelId={selectedModel}
              scopeLevel={scopeLevel}
              scopeKey={scopeKey}
              onClose={() => setSelectedModel(null)}
            />
          )}

          <Card
            title="Non-registry baselines"
            subtitle="Naive, seasonal-naive, MA3 and MA6 — reported for comparison, never counted among the thirteen, never champion"
          >
            <div className="table-scroll">
              <table className="data" data-testid="baseline-table">
                <thead>
                  <tr>
                    <th>Method</th>
                    <th className="num">WAPE %</th>
                    <th className="num">MAE</th>
                    <th className="num">Points</th>
                    <th>Why unranked</th>
                  </tr>
                </thead>
                <tbody>
                  {baselines.map((row) => (
                    <tr key={row.model_id}>
                      <td>{row.display_name}</td>
                      <td className="num">{metric(row.wape)}</td>
                      <td className="num">{formatInt(row.mae)}</td>
                      <td className="num">{formatInt(row.validation_points)}</td>
                      <td>{row.exclusion_reason ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <ChampionPanel
            scopeLevel={scopeLevel}
            scopeKey={scopeKey}
            leaderboard={data}
          />
        </>
      )}
    </div>
  );
}
