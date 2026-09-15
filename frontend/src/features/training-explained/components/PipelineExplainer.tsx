/**
 * The whole chain, on one panel: panel → scopes → fits → folds → champion →
 * forecast.
 *
 * Everything this answers was answerable before, but only by asking in
 * conversation: how many models run, against how many scopes, what a "fold"
 * cuts, why a model can be Ineligible without having failed, how a champion is
 * chosen, and what happens between the champion and the number on the
 * Forecasting page. The rules lived on this page; the *shape* of the run did
 * not, and the shape is what makes the rules legible.
 *
 * Every figure is read from `/api/training/{run}/monitor` and
 * `/api/training/explain`. There is no prose number in this file — a run with a
 * different grid renders different sentences, which is the only way an
 * explanation stays true after the thing it explains changes.
 */
import { useQuery } from '@tanstack/react-query';
import {
  fetchCurrentRun,
  fetchTrainingMonitor,
  monitorKeys,
  trainingKeys,
} from '@/api/training';
import { fetchTrainingExplain, trainingExplainKeys } from '@/api/analytics';
import { fetchCurrentForecastRun, forecastKeys } from '@/api/forecasts';
import { AMBER, BLUE, GREEN, NAVY, Panel, SLATE, TEAL, VIOLET, num } from '@/components/ui/Dashboard';
import { LoadingBlock } from '@/components/ui/States';

/** Human names for the hierarchy levels, in the order they nest. */
const LEVEL_ORDER = ['national', 'region', 'branch', 'segment', 'series'];
const LEVEL_LABEL: Record<string, string> = {
  national: 'National total',
  region: 'Region totals',
  branch: 'Branch totals',
  segment: 'Segment totals',
  series: 'Branch × SKU series',
};

function Step({
  n,
  title,
  accent,
  children,
}: {
  n: number;
  title: string;
  accent: string;
  children: React.ReactNode;
}) {
  return (
    <li className="relative pl-9">
      <span
        className="absolute left-0 top-0 flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold text-white"
        style={{ background: accent }}
        aria-hidden
      >
        {n}
      </span>
      <h3 className="text-[12px] font-semibold text-[var(--color-text)]">{title}</h3>
      <div className="mt-1 flex flex-col gap-1.5 text-[11px] leading-relaxed text-[var(--color-text-muted)]">
        {children}
      </div>
    </li>
  );
}

/** A number the reader should be able to point at while being talked through it. */
function Fact({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded border border-[var(--color-border)] bg-[var(--color-surface-muted,transparent)] px-2 py-1.5">
      <div className="text-[15px] font-semibold tabular-nums text-[var(--color-text)]">{value}</div>
      <div className="text-[9px] uppercase tracking-[0.07em] text-[var(--color-text-muted)]">{label}</div>
    </div>
  );
}

export function PipelineExplainer() {
  const current = useQuery({
    queryKey: trainingKeys.current,
    queryFn: fetchCurrentRun,
    retry: false,
  });
  const runId = current.data?.id;

  const monitor = useQuery({
    queryKey: monitorKeys.run(runId ?? ''),
    queryFn: () => fetchTrainingMonitor(runId as string),
    enabled: Boolean(runId),
    retry: false,
  });
  const explain = useQuery({
    queryKey: trainingExplainKeys.all,
    queryFn: fetchTrainingExplain,
    retry: false,
  });
  // Step 6 names the reconciliation method that actually ran. It is a request
  // option, not a constant, so naming MinT in prose would go quietly wrong the
  // first time someone runs bottom-up.
  const forecast = useQuery({
    queryKey: forecastKeys.current,
    queryFn: fetchCurrentForecastRun,
    retry: false,
  });

  if (monitor.isPending || explain.isPending) {
    return (
      <Panel title="How a forecast is produced, end to end" accent={NAVY}>
        <LoadingBlock rows={6} label="Reading the run" />
      </Panel>
    );
  }
  if (!monitor.data || !explain.data) return null;

  const m = monitor.data;
  const p = m.pipeline;
  const e = explain.data;
  const folds = m.folds;
  const fits = m.counters.total;
  const modelsPerScope = p.registry_models + p.baseline_models;
  const horizonCount = folds[0]?.horizons.length ?? e.validation.horizon_months;

  const levels = LEVEL_ORDER.filter((l) => p.scopes_by_level[l]);
  const winners = Object.entries(p.champion_spread);
  // Scaled to the leader, not to the scope count: at 9 wins out of 49 the
  // longest bar would otherwise be 48px and the shortest 5px, which reads as
  // "nothing won much" rather than showing the shape of the spread.
  const topWins = winners.reduce((best, [, count]) => Math.max(best, count), 1);
  const fc = forecast.data;
  const method = fc?.reconciliation_method ?? null;
  const METHOD_LABEL: Record<string, string> = {
    mint_shrinkage: 'MinT reconciliation (shrinkage covariance)',
    mint_variance: 'MinT reconciliation (variance scaling)',
    bottom_up: 'Bottom-up aggregation',
    proportional: 'Proportional top-down disaggregation',
    none: 'No reconciliation',
  };
  const nameOf = (id: string) =>
    m.models.find((row) => row.model_id === id)?.display_name ?? id;

  // Ineligible is the status people misread as failure, so the panel names the
  // models it actually happened to rather than only defining the word.
  const ineligible = m.models
    .filter((row) => row.ineligible > 0)
    .sort((a, b) => b.ineligible - a.ineligible);
  const ineligibleTotal = m.counters.ineligible;

  return (
    <Panel
      title="How a forecast is produced, end to end"
      accent={NAVY}
      note={`Run ${m.run_id.slice(0, 8)} · every figure below is this run's, not an illustration.`}
    >
      <div className="mb-3 grid grid-cols-2 gap-2 lg:grid-cols-5">
        <Fact value={num(p.scopes_total)} label="Scopes forecast" />
        <Fact value={`${p.registry_models} + ${p.baseline_models}`} label="Models + baselines" />
        <Fact value={num(fits)} label="Model fits" />
        <Fact value={`${folds.length} × ${horizonCount}`} label="Folds × horizons" />
        <Fact value={num(p.champions_selected)} label="Champions chosen" />
      </div>

      <ol className="flex flex-col gap-3.5">
        <Step n={1} title="The panel is cut into scopes" accent={BLUE}>
          <p>
            A scope is one thing to forecast. This run has <strong>{p.scopes_total}</strong>,
            and they are not all the same size — they are the levels of one hierarchy, so a
            branch total and the SKUs inside it are both forecast and then made to agree
            (step 6).
          </p>
          <div className="table-scroll">
            <table className="data">
              <thead>
                <tr>
                  <th>Level</th>
                  <th className="num">Scopes</th>
                  <th>What one row is</th>
                </tr>
              </thead>
              <tbody>
                {levels.map((level) => (
                  <tr key={level}>
                    <td className="font-semibold">{LEVEL_LABEL[level] ?? level}</td>
                    <td className="num">{p.scopes_by_level[level]}</td>
                    <td className="text-[10px]">
                      {level === 'series'
                        ? 'One SKU in one branch — the grain planning happens on, and the hardest to forecast'
                        : `Demand summed to ${level}, which is smoother and therefore more predictable`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Step>

        <Step n={2} title="Every model is fitted on every scope" accent={TEAL}>
          <p>
            Not one model per SKU, and not one model for everything.{' '}
            <strong>All {modelsPerScope} candidates run against all {p.scopes_total} scopes</strong> —{' '}
            {p.registry_models} registered models plus {p.baseline_models} trivial baselines kept
            for comparison — which is {num(modelsPerScope)} × {p.scopes_total} ={' '}
            <strong>{num(fits)} fits</strong>
            {m.duration_seconds ? ` in ${Math.round(m.duration_seconds)} seconds` : ''}.
          </p>
          <p>
            The baselines ({e.selection.baselines.map((b) => b.model_id).join(', ')}) can never be
            champion. They are the floor: a registered model that cannot beat "next month equals
            this month" has not earned its complexity, and{' '}
            <strong>{p.champions_beaten_by_baseline} of the {p.champions_selected} scope
            champions</strong> on this run were still beaten by a baseline on their own scope —
            which the leaderboard says in words rather than leaving two numbers to be compared.
          </p>
        </Step>

        <Step n={3} title="Each fit is scored on months it was never shown" accent={BLUE}>
          <p>
            {e.validation.method.replace(/_/g, ' ')} — the history is cut at a date, the model
            trains only on what came before, and is scored on what came after. Never a random
            split: with a time series that would let the model see next year while predicting
            last month.
          </p>
          <div className="table-scroll">
            <table className="data">
              <thead>
                <tr>
                  <th>Fold</th>
                  <th>Trains on</th>
                  <th className="num">Months</th>
                  <th>Scored on</th>
                  <th className="num">Horizons</th>
                </tr>
              </thead>
              <tbody>
                {folds.map((fold) => (
                  <tr key={fold.index ?? fold.name}>
                    <td className="font-semibold">{fold.name ?? `Fold ${fold.index}`}</td>
                    <td className="mono text-[10px]">up to {fold.train_end}</td>
                    <td className="num">{fold.train_rows ?? '—'}</td>
                    <td className="mono text-[10px]">
                      {fold.validate_from} → {fold.validate_to}
                    </td>
                    <td className="num">{fold.horizons.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            Two folds rather than one because a model that happens to suit a single quarter is
            not a good model. Every fit is therefore scored {folds.length} × {horizonCount} ={' '}
            {folds.length * horizonCount} times before it is allowed to compete.
          </p>
        </Step>

        <Step n={4} title="A model that cannot run keeps its row and its reason" accent={AMBER}>
          <p>
            <strong>Ineligible is not failure.</strong> It means the data did not meet a
            requirement the model states up front — Auto ARIMA needs eighteen months, and
            multiplicative smoothing divides by the level so a single zero month rules it out
            arithmetically. Nothing broke; the model declined, and said why.
          </p>
          {ineligibleTotal > 0 ? (
            <>
              <p>
                On this run <strong>{ineligibleTotal} of {num(fits)}</strong> fits were
                ineligible, all from {ineligible.length} models:
              </p>
              <ul className="ml-4 list-disc">
                {ineligible.map((row) => (
                  <li key={row.model_id}>
                    <strong>{row.display_name}</strong> — {row.ineligible} of {row.total} scopes
                    {row.reason ? `: ${row.reason}` : ''}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p>Every model met every requirement on every scope in this run.</p>
          )}
          <p>
            {m.counters.failed} fits <strong>failed</strong> (the fit raised) and{' '}
            {m.counters.timed_out} <strong>timed out</strong>. Those are different words for
            different things, and none of them is ever replaced by a zero forecast — a model
            that did not run must not look like a model that predicted nothing.
          </p>
        </Step>

        <Step n={5} title="A champion is chosen per scope, not once overall" accent={GREEN}>
          <p>
            This is the step that surprises people. There is no single best model. For{' '}
            <strong>each</strong> of the {p.scopes_total} scopes, the candidate with the lowest{' '}
            {e.selection.primary_metric.toUpperCase()} wins that scope alone, tie-broken by{' '}
            {e.selection.tie_breaks.join(' → ')}. The rule is deterministic: the same rows always
            give the same champion.
          </p>
          <p>
            Which is why the leaderboard and the Forecasting page can name different models and
            both be right — the leaderboard ranks average performance across all scopes, while
            Forecasting names the winner of the one scope you are looking at.
          </p>
          {winners.length > 0 && (
            <>
              <p>
                On this run <strong>{winners.length} different models</strong> each won at least
                one scope:
              </p>
              <div className="flex flex-col gap-1">
                {winners.map(([id, count]) => (
                  <div key={id} className="flex items-center gap-2">
                    <span className="w-[190px] shrink-0 truncate text-[10px] text-[var(--color-text)]">
                      {nameOf(id)}
                    </span>
                    <span
                      className="h-2.5 rounded-sm"
                      style={{
                        width: `${(count / topWins) * 240}px`,
                        minWidth: '3px',
                        background: VIOLET,
                      }}
                    />
                    <span className="text-[10px] tabular-nums text-[var(--color-text-muted)]">
                      {count}
                    </span>
                  </div>
                ))}
              </div>
              <p>
                A concentrated spread would mean one family suits every series; this spread means
                the scopes genuinely differ, and picking per scope is buying something real.
              </p>
            </>
          )}
        </Step>

        <Step n={6} title="The champions are refitted, then made to agree" accent={SLATE}>
          <p>
            Scoring is over. Each scope&apos;s champion is refitted on its{' '}
            <strong>whole</strong> history — including the months held back for validation,
            which no longer need holding back — and projects {horizonCount} months forward.
          </p>
          <p>
            Every point forecast carries q80 / q90 / q95 beside it: the level below which demand
            lands that often, taken from the model&apos;s own past errors. A planner stocks to an
            upper quantile, not to the point.
          </p>
          <p>
            Then the levels are reconciled. Forecast independently, the{' '}
            {p.scopes_by_level.series ?? 0} series would not sum to the branch totals, and two
            numbers that disagree are worse than one.{' '}
            {method ? (METHOD_LABEL[method] ?? method) : 'The chosen reconciliation method'}{' '}
            adjusts every level until they agree, and the size of the adjustment is stored
            separately from the forecast rather than folded into it — so what the model said and
            what coherence required stay distinguishable.
          </p>
          {fc && (
            <p>
              The live forecast was produced from{' '}
              <strong>
                {fc.training_run_id === m.run_id
                  ? 'this run’s champions'
                  : `a different training run (${String(fc.training_run_id).slice(0, 8)})`}
              </strong>{' '}
              at origin {fc.origin_period} — {p.scopes_total} scopes × {horizonCount} months,
              of which {num(fc.rows_written)} carry a number.{' '}
              {fc.coherent
                ? 'The stored levels were re-checked from the persisted rows and they agree.'
                : 'The stored levels do not yet agree — shown rather than hidden.'}
            </p>
          )}
          {fc && fc.rows_unavailable > 0 && (
            <p>
              The remaining <strong>{num(fc.rows_unavailable)}</strong> are stored with a reason
              and <strong>no number at all</strong>, not a zero. A champion can win on
              validation and still be unable to refit on the full history — a scope whose
              companion series went flat, for instance — and a planner who sees zero where the
              honest answer is &quot;this one could not be forecast&quot; will order against it.
            </p>
          )}
        </Step>
      </ol>
    </Panel>
  );
}
