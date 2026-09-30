/**
 * Recommendations at branch × SKU, which is the grain a planner orders at.
 *
 * The list above this one answers at the network: "50 branch × SKU lines are
 * flagged critical" is a count of lines, never a line, and nobody can act on
 * it because it never says which (D-104). These cards each name one branch and
 * one SKU and carry that line's own figures.
 *
 * **Every ranked line is here, and every count is a way in.** Showing twelve of
 * 261 left the same problem one level down: a reader told that 85 lines are
 * critical still could not see which 85. So the whole ranking is listed, the
 * band and exception counts are buttons that filter to exactly the lines behind
 * them, and each card opens into every figure the application holds for that
 * line. The summary and the detail are both needed — one to know where to look,
 * the other to act (D-132).
 *
 * Five things this is careful about.
 *
 * - **The ranking is the backend's, not the model's.** `urgency` and
 *   `urgency_reason` are computed from measured fields before any model sees
 *   the line, so the order is reproducible between runs. The model is asked
 *   only to explain a line that was already ranked, and `written_by_model`
 *   says whether it did.
 * - **Listed is not the same as written.** Only the most urgent handful gets
 *   prose; the rest carry their computed reason, and say so rather than
 *   looking like a model chose to be brief.
 * - **A censored line says so.** Despatch fell short of the order there, so the
 *   ordered quantity is a lower bound on real demand and the forecast is built
 *   on an understatement. That is a badge, not a footnote.
 * - **`cannot_recommend` is not a mild severity.** It is the absence of a
 *   recommendation, and it renders as its own state with the reason — never as
 *   a recommended order of zero.
 * - **The filter narrows what is shown, never what was ranked.** Every filter
 *   states the count it left behind rather than letting a short list read as a
 *   complete one.
 */
import { useEffect, useMemo, useState } from 'react';
import type { LineRecommendation } from '@/api/analytics';
import { Badge, Card } from '@/components/ui/Dashboard';

const URGENCY: Record<string, { tone: string; label: string; bar: string }> = {
  critical: { tone: 'critical', label: 'Critical', bar: 'bg-[var(--ais-diamond)]' },
  high: { tone: 'high', label: 'High', bar: 'bg-amber-500' },
  medium: { tone: 'medium', label: 'Medium', bar: 'bg-slate-400' },
  cannot_recommend: { tone: 'ineligible', label: 'No recommendation', bar: 'bg-slate-300' },
};

/** The bands in the order they are acted on, not alphabetically. */
const BANDS = ['critical', 'high', 'medium', 'cannot_recommend'] as const;

/** How many cards render before the reader asks for more. 261 open cards is a
 *  slow page and an unreadable one; the count not yet rendered is stated, so a
 *  short page never reads as a short list. */
const PAGE = 25;

const num = (v: number | null | undefined, digits = 0) =>
  v == null ? '—' : v.toLocaleString('en-IN', { maximumFractionDigits: digits });

/** Only figures the line actually carries. A missing input stays absent rather
 *  than printing a zero that would read as a measurement. */
function Figures({ line }: { line: LineRecommendation }) {
  const rows: Array<[string, string]> = [];
  if (line.quantile_forecast != null)
    rows.push([`q${line.service_level ?? 95} demand / month`, num(line.quantile_forecast)]);
  if (line.point_forecast != null) rows.push(['Point forecast / month', num(line.point_forecast)]);
  if (line.usable_stock != null) rows.push(['Usable stock', num(line.usable_stock)]);
  if (line.days_of_cover != null) rows.push(['Days of cover', num(line.days_of_cover)]);
  if (line.protection_period_days != null)
    rows.push(['Protection period', `${num(line.protection_period_days)} d`]);
  if (line.recommended_order != null) rows.push(['Recommended order', num(line.recommended_order)]);
  if (!rows.length) return null;
  return (
    <dl className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-0.5 sm:grid-cols-3">
      {rows.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-2 border-b border-[var(--color-border)] py-0.5">
          <dt className="truncate text-[10px] text-[var(--color-text-muted)]">{label}</dt>
          <dd className="shrink-0 text-[10px] font-semibold text-[var(--color-text)]">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Everything the application holds for this line, behind a disclosure.
 *
 *  Separate from `Figures` on purpose: that grid is the six numbers an order
 *  decision turns on, and burying them under a click would be worse than not
 *  showing the rest at all. This is the audit — where the lead time came from,
 *  what is already on order, what the exception join found — for the reader who
 *  has decided this is the line they care about. */
function AllFigures({ line }: { line: LineRecommendation }) {
  const rows: Array<[string, string]> = [];
  const put = (label: string, value: string | number | null | undefined, unit = '') => {
    if (value == null || value === '') return;
    rows.push([label, typeof value === 'number' ? `${num(value)}${unit}` : String(value)]);
  };

  put('Forecast month', line.forecast_period);
  put('Forecast model', line.model);
  put('Demand pattern', line.demand_segment);
  put('Service level', line.service_level == null ? null : `q${line.service_level}`);
  put('Point forecast / month', line.point_forecast);
  put('Planning demand / month', line.quantile_forecast);
  put('Usable stock', line.usable_stock);
  put('Already on order', line.on_order);
  put('Backorders', line.backorders);
  put('Days of cover', line.days_of_cover);
  put('Average lead time', line.lead_time_days, ' d');
  put('Protection period', line.protection_period_days, ' d');
  put('Order-up-to level', line.order_up_to_level);
  put('Recommended order', line.recommended_order);
  put('Demand measured as', line.target_source);
  rows.push([
    'Despatch fell short',
    line.is_censored ? 'yes — order is a lower bound' : 'no',
  ]);

  return (
    <div className="mt-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] p-2.5">
      <dl className="grid grid-cols-1 gap-x-5 gap-y-0.5 sm:grid-cols-2">
        {rows.map(([label, value]) => (
          <div
            key={label}
            className="flex justify-between gap-3 border-b border-[var(--color-border)] py-0.5"
          >
            <dt className="shrink-0 text-[10px] text-[var(--color-text-muted)]">{label}</dt>
            {/* Right-aligned but allowed to wrap. `shrink-0` here pushed the one
                long value ("yes — ordered quantity is a lower bound") past the
                panel edge. */}
            <dd className="min-w-0 text-right text-[10px] font-semibold tabular-nums text-[var(--color-text)]">
              {value}
            </dd>
          </div>
        ))}
      </dl>

      {line.exceptions.length > 0 && (
        <div className="mt-2">
          <p className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
            What was found on this line
          </p>
          <ul className="mt-1 flex flex-col gap-0.5">
            {line.exceptions.map((e, i) => (
              <li
                key={`${e.type}-${i}`}
                className="flex justify-between gap-3 text-[10px] text-[var(--color-text)]"
              >
                <span>{e.type}</span>
                <span className="shrink-0 tabular-nums font-semibold">
                  {e.units == null ? '—' : `${num(e.units)} units`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {line.unavailable_reason && (
        <p className="mt-2 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
          <strong>No recommendation:</strong> {line.unavailable_reason}
        </p>
      )}

      <p className="mt-2 text-[9px] leading-relaxed text-[var(--color-text-muted)]">
        Stock is one snapshot; demand history ends a month earlier, so anything
        stock-derived is a current estimate and not a trend. Nothing here is an
        instruction to act — this project has no inventory-policy backtest.
      </p>
    </div>
  );
}

function Line({ line }: { line: LineRecommendation }) {
  const [open, setOpen] = useState(false);
  const urgency = URGENCY[line.urgency] ?? URGENCY.medium!;
  return (
    <li className="flex gap-2.5">
      <span className={`mt-1 w-[3px] shrink-0 rounded-full ${urgency.bar}`} aria-hidden />
      <div className="flex min-w-0 grow flex-col gap-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <h3 className="text-[13px] font-semibold text-[var(--color-text)]">
            {line.branch} <span className="text-[var(--color-text-muted)]">×</span> {line.sku}
          </h3>
          <Badge status={urgency.tone}>{urgency.label}</Badge>
          {line.is_censored && (
            <span
              className="rounded-full border border-amber-300 bg-amber-50 px-1.5 py-px text-[9px] font-medium text-amber-700"
              title="Despatch fell short of the order on this line, so its ordered quantity is a lower bound on real demand and this forecast is built on an understatement."
            >
              Censored demand
            </span>
          )}
          {!line.written_by_model && line.explanation && (
            <span className="text-[9px] text-[var(--color-text-muted)]">template</span>
          )}
          {!line.explanation && (
            // Not a model that chose to be brief. This line was ranked and is
            // shown in full; it was simply outside the handful sent for prose.
            <span className="text-[9px] text-[var(--color-text-muted)]">
              computed — no written explanation
            </span>
          )}
          <button
            type="button"
            className="link-button ml-auto shrink-0 text-[10px]"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? 'Hide details' : 'All figures'}
          </button>
        </div>

        {/* The application's own reason, always shown. The model explains it;
            it does not replace it, and if the model failed this is still here. */}
        <p className="text-[12px] font-medium leading-relaxed text-[var(--color-text)]">
          {line.urgency_reason}
        </p>

        {line.explanation && line.explanation !== line.urgency_reason && (
          <p className="text-[12px] leading-relaxed text-[var(--color-text-muted)]">
            {line.explanation}
          </p>
        )}

        {line.unavailable_reason ? (
          <p className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
            <strong>Nothing was substituted.</strong> This is not a recommended order of zero.
          </p>
        ) : (
          <Figures line={line} />
        )}

        {line.evidence.length > 0 && (
          <ul className="mt-1 flex flex-wrap gap-1">
            {line.evidence.map((e) => (
              <li
                key={e}
                className="rounded border border-[var(--color-border)] bg-[var(--color-surface-2)] px-1.5 py-px font-mono text-[9px] text-[var(--color-text-muted)]"
              >
                {e}
              </li>
            ))}
          </ul>
        )}

        {open && <AllFigures line={line} />}

        <p className="text-[10px] text-[var(--color-text-muted)]">
          {line.model && <>Forecast model <strong>{line.model}</strong>. </>}
          {line.forecast_period && <>Month {line.forecast_period}. </>}
          {line.next_step}
        </p>
      </div>
    </li>
  );
}

/** A count that is also the way to see what it counts. */
function FilterChip({
  label,
  count,
  detail,
  active,
  onClick,
}: {
  label: string;
  count: number;
  detail?: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      title={detail}
      className={`rounded-full border px-2 py-0.5 text-[10px] transition-colors ${
        active
          ? 'border-[var(--color-primary)] bg-[var(--color-primary)] text-white'
          : 'border-[var(--color-border)] bg-[var(--color-surface-2)] text-[var(--color-text)] hover:border-[var(--color-primary)]'
      }`}
    >
      {label} <strong className="tabular-nums">{count.toLocaleString('en-IN')}</strong>
    </button>
  );
}

export function LineRecommendations({
  lines,
  counts,
  total,
  shown,
  written,
  exceptionCounts,
  answeredBy,
}: {
  lines: LineRecommendation[];
  counts: Record<string, number>;
  total: number;
  shown: number;
  written?: number;
  exceptionCounts?: Array<{ label: string; lines: number; units: number }>;
  answeredBy: string | null;
}) {
  const [branch, setBranch] = useState('');
  const [query, setQuery] = useState('');
  const [band, setBand] = useState('');
  const [exception, setException] = useState('');
  const [limit, setLimit] = useState(PAGE);

  const branches = useMemo(() => [...new Set(lines.map((l) => l.branch))].sort(), [lines]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return lines.filter(
      (l) =>
        (!branch || l.branch === branch) &&
        (!q || l.sku.toLowerCase().includes(q)) &&
        (!band || l.urgency === band) &&
        (!exception || (l.exceptions ?? []).some((e) => e.type === exception)),
    );
  }, [lines, branch, query, band, exception]);

  // Back to the top of the list whenever the filter changes: keeping a "show
  // 150" from a previous filter would silently render a different slice of a
  // different list.
  useEffect(() => setLimit(PAGE), [branch, query, band, exception]);

  if (!lines.length) {
    return (
      <Card>
        <p className="text-[11px] text-[var(--color-text-muted)]">
          No branch × SKU line could be ranked. A line needs a stored forecast and a stock
          position; without both there is nothing measured to recommend from.
        </p>
      </Card>
    );
  }

  const hidden = total - shown;
  const filtered = visible.length !== lines.length;
  const rendered = visible.slice(0, limit);
  const remaining = visible.length - rendered.length;

  return (
    <Card>
      <div className="mb-2 flex flex-col gap-2">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text)]">
              Per branch &amp; SKU
            </h2>
            <p className="mt-0.5 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
              Ranked by the application before any model saw them. Showing {shown} of {total} lines
              {hidden > 0 && <> — {hidden} not shown</>}.
              {written != null && written < shown && (
                <>
                  {' '}
                  <strong>{written}</strong> carry a written explanation; the rest carry the
                  reason the application computed, and their own figures.
                </>
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="inline-flex flex-col gap-0.5">
              <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
                Location
              </span>
              <select
                aria-label="Location"
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
                className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-[11px] text-[var(--color-text)]"
              >
                <option value="">All locations</option>
                {branches.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
            </label>
            <label className="inline-flex flex-col gap-0.5">
              <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
                SKU
              </span>
              <input
                type="search"
                aria-label="Filter by SKU"
                value={query}
                placeholder="Type to narrow"
                onChange={(e) => setQuery(e.target.value)}
                className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-[11px] text-[var(--color-text)]"
              />
            </label>
          </div>
        </div>

        {/* The counts, as buttons. Reading "85 critical" and then having no way
            to see which 85 is the gap this closes — the summary tells you where
            to look, the filter takes you there. */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
            Urgency
          </span>
          {BANDS.filter((key) => (counts[key] ?? 0) > 0).map((key) => (
            <FilterChip
              key={key}
              label={URGENCY[key]!.label}
              count={counts[key] ?? 0}
              active={band === key}
              onClick={() => setBand(band === key ? '' : key)}
            />
          ))}
        </div>

        {(exceptionCounts?.length ?? 0) > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
              What was found
            </span>
            {exceptionCounts!.map((e) => (
              <FilterChip
                key={e.label}
                label={e.label}
                count={e.lines}
                detail={`${num(e.units)} units across ${e.lines} lines on this page`}
                active={exception === e.label}
                onClick={() => setException(exception === e.label ? '' : e.label)}
              />
            ))}
          </div>
        )}

        {filtered && (
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[10px] text-[var(--color-text-muted)]">
              <strong>{visible.length}</strong> of {lines.length} listed lines match.
            </p>
            <button
              type="button"
              className="link-button text-[10px]"
              onClick={() => {
                setBranch('');
                setQuery('');
                setBand('');
                setException('');
              }}
            >
              Clear filters
            </button>
          </div>
        )}
      </div>

      {answeredBy === 'deterministic_after_provider_error' && (
        <p className="mb-2 text-[10px] text-amber-700">
          The model could not be reached for these lines, so the wording comes from templates.
          The figures and the ranking are unaffected — they are computed, not written.
        </p>
      )}

      {visible.length === 0 ? (
        <p className="py-3 text-[11px] text-[var(--color-text-muted)]">
          No line matches this filter. {hidden > 0 && `${hidden} of ${total} ranked lines are not on this page.`}
        </p>
      ) : (
        <>
          <ul className="flex flex-col gap-3">
            {rendered.map((line) => (
              <Line key={line.scope_key} line={line} />
            ))}
          </ul>
          {remaining > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[var(--color-border)] pt-2">
              <button
                type="button"
                className="link-button text-[11px]"
                onClick={() => setLimit((v) => v + PAGE)}
              >
                Show {Math.min(PAGE, remaining)} more
              </button>
              <button
                type="button"
                className="link-button text-[11px]"
                onClick={() => setLimit(visible.length)}
              >
                Show all {visible.length}
              </button>
              {/* Never a silent cut. */}
              <span className="text-[10px] text-[var(--color-text-muted)]">
                {remaining} more match this filter.
              </span>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
