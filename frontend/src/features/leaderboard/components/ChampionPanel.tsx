/**
 * Champion selection, manual override and rollback, with the audit history.
 *
 * The reason field is required and the submit button stays disabled below the
 * ten-character floor. That is a courtesy, not the enforcement: the backend
 * checks the same floor at both its schema and service boundaries, so a caller
 * that skips this form is refused too.
 *
 * Only registered models appear in the override list, and they are read from
 * the leaderboard rows rather than hardcoded. A baseline cannot be selected
 * here, and the backend refuses one regardless.
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@/api/client';
import {
  fetchChampionHistory,
  leaderboardKeys,
  overrideChampion,
  rollbackChampion,
  selectChampions,
} from '@/api/leaderboard';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { formatInt } from '@/components/ui/format';
import type { LeaderboardResponse } from '@/types/phase7';

const MIN_REASON = 10;

/** The scope kind a `model_run` scope level maps to on the champion API. */
function scopeKindFor(scopeLevel: string, scopeKey: string): string {
  if (scopeLevel === 'national') return 'overall';
  if (scopeLevel === 'segment') return scopeKey.split('=')[0] || 'value_class';
  return scopeLevel;
}

interface Props {
  scopeLevel: string;
  scopeKey: string;
  leaderboard: LeaderboardResponse;
}

export function ChampionPanel({ scopeLevel, scopeKey, leaderboard }: Props) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const scopeKind = scopeKindFor(scopeLevel, scopeKey);
  const [modelId, setModelId] = useState('');
  const [reason, setReason] = useState('');

  const history = useQuery({
    queryKey: leaderboardKeys.history(scopeKind, scopeKey),
    queryFn: () => fetchChampionHistory(scopeKind, scopeKey),
    retry: false,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['champions'] });
    queryClient.invalidateQueries({ queryKey: ['leaderboard'] });
  };

  const fail = (error: unknown) =>
    toast.notify(
      error instanceof ApiError
        ? [error.message, error.remediation].filter(Boolean).join(' ')
        : String(error),
      'error',
    );

  const select = useMutation({
    mutationFn: () => selectChampions({ scope_kinds: [scopeKind] }),
    onSuccess: (result) => {
      toast.notify(
        `${result.selected_count} champion(s) selected, ${result.skipped_count} scope(s) skipped with a stated reason.`,
        'ok',
      );
      invalidate();
    },
    onError: fail,
  });

  const override = useMutation({
    mutationFn: () =>
      overrideChampion({
        scope_kind: scopeKind,
        scope_key: scopeKey,
        model_id: modelId,
        reason,
      }),
    onSuccess: (selection) => {
      toast.notify(
        `Champion overridden to ${selection.champion_display_name}. The previous choice is superseded, not deleted.`,
        'ok',
      );
      setReason('');
      setModelId('');
      invalidate();
    },
    onError: fail,
  });

  const rollback = useMutation({
    mutationFn: () => rollbackChampion({ scope_kind: scopeKind, scope_key: scopeKey }),
    onSuccess: (selection) => {
      toast.notify(
        `Rolled back to ${selection.champion_display_name}. The rollback is itself recorded in the history.`,
        'ok',
      );
      invalidate();
    },
    onError: fail,
  });

  // Only models that completed can serve forecasts, so only they can be
  // champion. The backend refuses the rest with its own reason.
  const candidates = leaderboard.rows.filter(
    (row) => !row.is_baseline && row.status === 'completed',
  );
  const active = leaderboard.active_selection;
  const entries = history.data?.entries ?? [];
  const reasonTooShort = reason.trim().length < MIN_REASON;

  return (
    <Card
      title="Champion"
      subtitle={`${scopeKind}/${scopeKey} · every decision is appended, never overwritten`}
      actions={
        <button
          type="button"
          className="btn"
          disabled={select.isPending}
          onClick={() => select.mutate()}
        >
          {select.isPending ? 'Selecting…' : 'Run automatic selection'}
        </button>
      }
    >
      {active ? (
        <div className="metric-row" data-testid="active-champion">
          <div className="metric">
            <span className="metric-label">Active champion</span>
            <span className="metric-value">{active.champion_display_name}</span>
          </div>
          <div className="metric">
            <span className="metric-label">Source</span>
            <span className="metric-value">{active.selection_source}</span>
          </div>
          <div className="metric">
            <span className="metric-label">WAPE %</span>
            <span className="metric-value">
              {active.champion_wape === null ? '—' : active.champion_wape.toFixed(3)}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Validation points</span>
            <span className="metric-value">
              {formatInt(active.champion_validation_points)}
            </span>
          </div>
        </div>
      ) : (
        <EmptyState title="No champion selected for this scope">
          Run the automatic selection above. It is deterministic: WAPE, then
          absolute bias, then MAE, then a model-id tie-break — so two identical
          runs name the same champion.
        </EmptyState>
      )}

      {active?.beaten_by_baseline && (
        <div className="callout warn">
          <p>
            This champion is beaten by {active.best_baseline_model_id}, a
            non-registry baseline. Recorded on the selection itself so the
            comparison travels with the decision.
          </p>
        </div>
      )}
      {active?.reason && (
        <p className="hint">
          <strong>Reason on record:</strong> {active.reason}
          {active.actor ? ` — ${active.actor}` : ''}
        </p>
      )}

      <h3 style={{ marginTop: 'var(--sp-5)' }}>Manual override</h3>
      <div className="field-row">
        <label className="field">
          <span>Model</span>
          <select value={modelId} onChange={(event) => setModelId(event.target.value)}>
            <option value="">Select a model…</option>
            {candidates.map((row) => (
              <option key={row.model_id} value={row.model_id}>
                {row.display_name}
                {row.wape === null ? '' : ` · WAPE ${row.wape.toFixed(3)}%`}
              </option>
            ))}
          </select>
          <span className="hint">
            Only models that completed in this scope. Overriding to one that did
            not would claim an accuracy that was never measured.
          </span>
        </label>
        <label className="field" style={{ maxWidth: '60ch', flex: 1 }}>
          <span>Reason (required, at least {MIN_REASON} characters)</span>
          <textarea
            rows={2}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            aria-describedby="reason-hint"
          />
          <span className="hint" id="reason-hint">
            Recorded in the audit history against your name. An override without
            a reason cannot be reviewed later, so it is refused.
          </span>
        </label>
      </div>
      <div className="actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={!modelId || reasonTooShort || override.isPending}
          onClick={() => override.mutate()}
        >
          {override.isPending ? 'Overriding…' : 'Override champion'}
        </button>
        <button
          type="button"
          className="btn"
          disabled={entries.length < 2 || rollback.isPending}
          onClick={() => rollback.mutate()}
        >
          {rollback.isPending ? 'Rolling back…' : 'Roll back to previous'}
        </button>
      </div>
      {entries.length < 2 && (
        <p className="hint">
          Rollback needs a previous decision to restore; this scope has{' '}
          {entries.length} on record.
        </p>
      )}

      <h3 style={{ marginTop: 'var(--sp-5)' }}>Audit history</h3>
      {history.isPending && <LoadingBlock rows={3} label="Loading champion history" />}
      {history.isError && <ErrorState error={history.error} onRetry={() => history.refetch()} />}
      {entries.length === 0 && !history.isPending && (
        <EmptyState title="No decisions recorded yet">
          The history is the table itself: an override appends a row and
          supersedes the previous one, and a rollback appends another.
        </EmptyState>
      )}
      {entries.length > 0 && (
        <div className="table-scroll">
          <table className="data" data-testid="champion-history">
            <thead>
              <tr>
                <th>When</th>
                <th>Champion</th>
                <th>Source</th>
                <th>Actor</th>
                <th>Active</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id}>
                  <td className="mono">{new Date(entry.created_at).toLocaleString()}</td>
                  <td>{entry.champion_display_name}</td>
                  <td>{entry.selection_source}</td>
                  <td>{entry.actor ?? '—'}</td>
                  <td>{entry.is_active ? 'Yes' : 'Superseded'}</td>
                  <td>{entry.reason ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
