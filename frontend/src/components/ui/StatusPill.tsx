import type { ModelRunStatus } from '@/types/api';
import './ui.css';

/**
 * The full model-run status vocabulary. Every state renders distinctly: an
 * Ineligible model must never look like a Failed one, and neither may
 * disappear from a leaderboard.
 */
const STATUS_TONE: Record<ModelRunStatus, { tone: string; label: string }> = {
  queued: { tone: 'pill-neutral', label: 'Queued' },
  preparing_data: { tone: 'pill-info', label: 'Preparing data' },
  validating_eligibility: { tone: 'pill-info', label: 'Validating eligibility' },
  training: { tone: 'pill-info', label: 'Training' },
  cross_validating: { tone: 'pill-info', label: 'Cross-validating' },
  generating_forecast: { tone: 'pill-info', label: 'Generating forecast' },
  saving_artifacts: { tone: 'pill-info', label: 'Saving artifacts' },
  completed: { tone: 'pill-ok', label: 'Completed' },
  failed: { tone: 'pill-crit', label: 'Failed' },
  ineligible: { tone: 'pill-warn', label: 'Ineligible' },
  timed_out: { tone: 'pill-crit', label: 'Timed out' },
  not_evaluated_budget: { tone: 'pill-neutral', label: 'Not evaluated (budget)' },
  cancelled: { tone: 'pill-neutral', label: 'Cancelled' },
};

export function StatusPill({ status }: { status: ModelRunStatus | string }) {
  const meta = STATUS_TONE[status as ModelRunStatus] ?? { tone: 'pill-neutral', label: String(status) };
  return (
    <span className={`pill ${meta.tone}`} data-status={status}>
      {meta.label}
    </span>
  );
}

export function HealthPill({ status }: { status: 'ok' | 'degraded' | 'error' }) {
  const tone = status === 'ok' ? 'pill-ok' : status === 'degraded' ? 'pill-warn' : 'pill-crit';
  const label = status === 'ok' ? 'Healthy' : status === 'degraded' ? 'Degraded' : 'Error';
  return <span className={`pill ${tone}`}>{label}</span>;
}
