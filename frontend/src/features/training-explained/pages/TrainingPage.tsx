/**
 * Training — what actually happens, with nothing taken on trust.
 *
 * Four questions, answered from `/api/training/explain`, which derives every
 * answer from the code that runs training rather than from a document:
 *
 * 1. **How is it validated?** The real fold boundaries, with the months each
 *    fold trains on and scores.
 * 2. **What are the 13 models?** Each with its own minimum-history threshold
 *    per profile, its actual hyperparameters, and whether it needs exogenous
 *    drivers.
 * 3. **Which metrics, and which one decides?** Every metric computed, its
 *    definition, its caveat, and which is primary.
 * 4. **What is tuned?** Honestly: very little, and the page says so rather
 *    than implying a search that does not happen.
 *
 * The status vocabulary is on the page too, because "Ineligible" and "Failed"
 * mean different things and a reader who conflates them will misread the
 * leaderboard.
 */
import { useQuery } from '@tanstack/react-query';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { fetchTrainingExplain, trainingExplainKeys } from '@/api/analytics';
import { AMBER, BLUE, GREEN, NAVY, Panel, RED, SLATE, StatTile, TICK, TOOLTIP, num } from '@/components/ui/Dashboard';
import { Card } from '@/components/ui/Card';
import { TrainingMonitor } from '../components/TrainingMonitor';
import { PipelineExplainer } from '../components/PipelineExplainer';
import { ScopeBanner } from '@/components/ui/ScopeBanner';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import { Explain } from '@/components/ui/Explain';

const STATUS_COLOR: Record<string, string> = {
  completed: GREEN,
  ineligible: AMBER,
  failed: RED,
  timed_out: SLATE,
  not_evaluated_budget: SLATE,
};

function Kv({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-[var(--color-border)] py-1 last:border-0">
      <span className="text-[11px] text-[var(--color-text-muted)]">{label}</span>
      <span className="text-right text-[11px] font-medium text-[var(--color-text)]">{value}</span>
    </div>
  );
}

export function TrainingPage() {
  const query = useQuery({
    queryKey: trainingExplainKeys.all,
    queryFn: fetchTrainingExplain,
    retry: false,
  });
  const data = query.data;

  if (query.isPending) {
    return (
      <Card>
        <LoadingBlock rows={10} label="Reading the training configuration" />
      </Card>
    );
  }
  if (query.isError || !data) {
    return (
      <Card>
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      </Card>
    );
  }

  const run = data.active_run;
  const statuses = Object.entries(run?.model_run_statuses ?? {}).map(([status, count]) => ({
    status,
    label: status.replace(/_/g, ' '),
    count,
  }));
  const relaxedDiffers = data.models.filter(
    (m) => m.min_history.reference !== m.min_history.monthly_relaxed,
  );

  return (
    <div className="flex flex-col gap-4">
      <header>
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-primary)]">
          Training
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[var(--color-text)]">
          How the models are trained and judged.
        </h1>
        <Explain label="About this page" variant="note">
          Every figure below is read out of the code that runs training — the fold
          boundaries from the fold builder, the thresholds from each model&apos;s own
          eligibility check, the ranking rule from the champion selector. Nothing here is a
          restated summary that could drift.
        </Explain>
      </header>

      <ScopeBanner scope={data.workspace_scope} />

      {/* The monitor goes first, above the design explanation. The page used
          to answer only "how does training work"; the question someone has
          while a run is in flight is "is it working, and which models are
          refusing", and that has to be visible before the theory. */}
      <TrainingMonitor />

      {/* The chain, before the rules. Someone seeing this for the first time
          needs to know the shape of a run - how many scopes, how many fits,
          who won what - before the fold thresholds and metric definitions
          below mean anything. */}
      <PipelineExplainer />

      {/* ---- 1. Validation ------------------------------------------- */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Registered models" value={String(data.model_count)} sublabel="fixed set, never substituted" tint="navy" accent />
        <StatTile label="Validation" value={`${data.validation.origins.length} folds`} sublabel={data.validation.method} tint="blue" />
        <StatTile label="Horizon" value={`${data.validation.horizon_months} months`} sublabel={`min ${data.validation.min_train_periods} training months per fold`} tint="teal" />
        <StatTile label="Ranked on" value={data.selection.primary_metric.toUpperCase()} sublabel={`tie-breaks: ${data.selection.tie_breaks.join(' → ')}`} tint="green" />
      </div>

      <Panel
        title="Validation design"
        accent={BLUE}
        note={data.validation.why}
      >
        <div className="table-scroll">
          <table className="data">
            <thead>
              <tr>
                <th>Fold</th>
                <th>Trains on</th>
                <th className="num">Months</th>
                <th>Scores</th>
              </tr>
            </thead>
            <tbody>
              {data.validation.origins.map((o) => (
                <tr key={o.name}>
                  <td className="font-semibold">{o.name}</td>
                  <td className="mono text-[11px]">
                    {o.train_start} → {o.train_end}
                  </td>
                  <td className="num">{o.train_months}</td>
                  <td className="mono text-[11px]">
                    {o.validation_start} → {o.validation_end}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-2 flex flex-col gap-1.5">
          <p className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
            <strong>Fold-fitted preprocessing.</strong> {data.validation.fold_fitted_preprocessing}
          </p>
          <p className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
            <strong>Exogenous drivers.</strong> {data.validation.exogenous_rule}
          </p>
          <p className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
            Panel window {data.validation.panel_window.start} → {data.validation.panel_window.end}.
            Mandated training cut-offs: {data.validation.mandated_train_ends.join(', ')}.
          </p>
        </div>
      </Panel>

      {/* ---- 2. The models ------------------------------------------- */}
      <Panel
        title={`The ${data.model_count} registered models`}
        accent={NAVY}
        note={`Minimum history is per model and per profile. ${relaxedDiffers.length} of ${data.model_count} models have a lower threshold under 'monthly_relaxed' — which is why that profile makes all 13 eligible on a 28-month panel.`}
      >
        <div className="table-scroll max-h-[520px]">
          <table className="data">
            <thead>
              <tr>
                <th>Model</th>
                <th>Family</th>
                <th className="num">Min history (reference)</th>
                <th className="num">Min history (relaxed)</th>
                <th>Exogenous</th>
                <th>Pooled</th>
                <th>Hyperparameters actually used</th>
              </tr>
            </thead>
            <tbody>
              {data.models.map((m) => (
                <tr key={m.model_id}>
                  <td className="font-semibold">{m.display_name}</td>
                  <td className="text-[11px]">{m.family ?? '—'}</td>
                  <td className="num">{m.min_history.reference}</td>
                  <td className="num">
                    {m.min_history.monthly_relaxed}
                    {m.min_history.monthly_relaxed !== m.min_history.reference && (
                      <span className="ml-1 text-[9px] text-[var(--color-text-muted)]">lower</span>
                    )}
                  </td>
                  <td>{m.requires_exogenous ? 'required' : '—'}</td>
                  <td>{m.supports_pooled_training ? 'yes' : '—'}</td>
                  <td className="mono text-[10px]">
                    {Object.entries(m.parameters)
                      .slice(0, 4)
                      .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
                      .join('  ') || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-[var(--color-text-muted)]">
          The four baselines — {data.selection.baselines.map((b) => b.model_id).join(', ')} — are
          not among these and can never be champion. They exist so a registered model that
          cannot beat a trivial rule is visibly failing to earn its complexity.
        </p>
      </Panel>

      {/* ---- 3. Metrics --------------------------------------------- */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Panel
          title="Metrics computed on every model run"
          accent={GREEN}
          note={`Ranked on ${data.selection.primary_metric.toUpperCase()}. ${data.selection.why_bias_second}`}
        >
          <div className="flex flex-col gap-2">
            {data.metrics.map((metric) => (
              <div key={metric.key} className="border-b border-[var(--color-border)] pb-2 last:border-0">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-[12px] font-semibold text-[var(--color-text)]">{metric.label}</span>
                  <span className="text-[10px] text-[var(--color-text-muted)]">
                    {metric.unit} · {metric.lower_is_better ? 'lower is better' : 'higher is better'}
                  </span>
                  {metric.key === data.selection.primary_metric && (
                    <span className="rounded-full border border-[var(--color-primary)] px-1.5 text-[9px] font-semibold text-[var(--color-primary)]">
                      decides the champion
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--color-text)]">{metric.definition}</p>
                {metric.caveat && (
                  <p className="mt-0.5 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
                    {metric.caveat}
                  </p>
                )}
              </div>
            ))}
          </div>
        </Panel>

        <div className="flex flex-col gap-3">
          <Panel title="Champion selection" accent={BLUE} note="Deterministic: the same rows always produce the same champion.">
            <Kv label="Primary metric" value={data.selection.primary_metric.toUpperCase()} />
            <Kv label="Tie-breaks, in order" value={data.selection.tie_breaks.join(' → ')} />
            <Kv label="Minimum validation points" value={String(data.selection.min_validation_points)} />
            <Kv label="Minimum test-point share" value={String(data.selection.min_test_point_share)} />
            <Kv label="A baseline may be champion" value={data.selection.baselines_never_champion ? 'never' : 'yes'} />
            <Kv label="Switchable to" value={data.selection.primary_metric_choices.join(' / ')} />
          </Panel>

          <Panel
            title="What is tuned"
            accent={AMBER}
            note={data.tuning.summary}
          >
            <div className="flex flex-col gap-1.5">
              {data.tuning.search_inside_folds.map((row) => (
                <p key={row.model_id} className="text-[11px] leading-relaxed text-[var(--color-text)]">
                  <span className="mono text-[10px] font-semibold">{row.model_id}</span> — {row.what}
                </p>
              ))}
            </div>
            <div className="mt-2 border-t border-[var(--color-border)] pt-2">
              <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
                Not tuned
              </span>
              <ul className="mt-1 flex flex-col gap-1">
                {data.tuning.not_tuned.map((line) => (
                  <li key={line} className="text-[10px] leading-relaxed text-[var(--color-text-muted)]">
                    {line}
                  </li>
                ))}
              </ul>
            </div>
            <div className="mt-2 border-t border-[var(--color-border)] pt-2">
              {Object.entries(data.tuning.fixed_settings).map(([k, v]) => (
                <Kv key={k} label={k.replace(/_/g, ' ')} value={<span className="mono text-[10px]">{String(v)}</span>} />
              ))}
            </div>
          </Panel>
        </div>
      </div>

      {/* ---- 4. The active run and the status vocabulary ------------- */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Panel
          title="Most recent run"
          accent={run?.status?.startsWith('completed') ? GREEN : AMBER}
          note={
            run
              ? `Run ${run.id.slice(0, 8)} · ${run.status.replace(/_/g, ' ')}${run.duration_seconds ? ` · ${Math.round(run.duration_seconds)} s` : ''}`
              : 'No training run has been submitted yet.'
          }
        >
          {run ? (
            <>
              {statuses.length > 0 && (
                <ResponsiveContainer width="100%" height={170}>
                  <BarChart data={statuses} margin={{ top: 8, right: 6, left: -18, bottom: 0 }}>
                    <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                    <XAxis dataKey="label" tick={{ ...TICK, fontSize: 8 }} tickLine={false} interval={0} angle={-20} textAnchor="end" height={40} />
                    <YAxis tick={TICK} width={40} />
                    <Tooltip contentStyle={TOOLTIP} formatter={(v: number) => `${num(v)} model runs`} />
                    <Bar dataKey="count" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                      {statuses.map((s) => (
                        <Cell key={s.status} fill={STATUS_COLOR[s.status] ?? SLATE} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
              <div className="mt-1">
                <Kv label="Tiers" value={run.tiers.join(', ') || '—'} />
                <Kv label="History profile" value={run.min_history_profile} />
                <Kv label="XGBoost profile" value={run.xgboost_training_profile} />
                <Kv label="Series evaluated" value={num(run.series_evaluated)} />
                <Kv label="Per-model timeout" value={run.per_model_timeout_seconds ? `${run.per_model_timeout_seconds} s` : 'none'} />
              </div>
            </>
          ) : (
            <p className="py-3 text-[11px] text-[var(--color-text-muted)]">
              Nothing to show until a run exists. No placeholder figures are shown here.
            </p>
          )}
        </Panel>

        <Panel
          title="What each status means"
          accent={SLATE}
          note="These are not interchangeable. A model that did not run keeps its row and its reason — it is never shown as zero error."
        >
          <div className="flex flex-col gap-2">
            {data.status_vocabulary.map((row) => (
              <div key={row.status} className="border-b border-[var(--color-border)] pb-1.5 last:border-0">
                <span
                  className="mono text-[10px] font-semibold"
                  style={{ color: STATUS_COLOR[row.status] ?? SLATE }}
                >
                  {row.status.replace(/_/g, ' ')}
                </span>
                <p className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">{row.meaning}</p>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Card>
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text)]">
          Caveats that apply to every number on this page
        </h2>
        <ul className="mt-2 flex flex-col gap-1.5">
          {data.notes.map((note) => (
            <li key={note} className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
              {note}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
