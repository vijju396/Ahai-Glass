/**
 * Recommendations at branch × SKU, which is the grain a planner orders at.
 *
 * The list above this one answers at the network: "50 branch × SKU lines are
 * flagged critical" is a count of lines, never a line, and nobody can act on
 * it because it never says which (D-104). These cards each name one branch and
 * one SKU and carry that line's own figures.
 *
 * Four things this is careful about.
 *
 * - **The ranking is the backend's, not the model's.** `urgency` and
 *   `urgency_reason` are computed from measured fields before any model sees
 *   the line, so the order is reproducible between runs. The model is asked
 *   only to explain a line that was already ranked, and `written_by_model`
 *   says whether it did.
 * - **A censored line says so.** Despatch fell short of the order there, so the
 *   ordered quantity is a lower bound on real demand and the forecast is built
 *   on an understatement. That is a badge, not a footnote.
 * - **`cannot_recommend` is not a mild severity.** It is the absence of a
 *   recommendation, and it renders as its own state with the reason — never as
 *   a recommended order of zero.
 * - **The filter narrows what is shown, never what was ranked.** The cut to the
 *   top N happened server-side on the full ranking, and the count of lines not
 *   shown is stated rather than left to be inferred.
 */
import { useMemo, useState } from 'react';
import type { LineRecommendation } from '@/api/analytics';
import { Badge, Card } from '@/components/ui/Dashboard';

const URGENCY: Record<string, { tone: string; label: string; bar: string }> = {
  critical: { tone: 'critical', label: 'Critical', bar: 'bg-[var(--ais-diamond)]' },
  high: { tone: 'high', label: 'High', bar: 'bg-amber-500' },
  medium: { tone: 'medium', label: 'Medium', bar: 'bg-slate-400' },
  cannot_recommend: { tone: 'ineligible', label: 'No recommendation', bar: 'bg-slate-300' },
};

const num = (v: number | null, digits = 0) =>
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

function Line({ line }: { line: LineRecommendation }) {
  const urgency = URGENCY[line.urgency] ?? URGENCY.medium!;
  return (
    <li className="flex gap-2.5">
      <span className={`mt-1 w-[3px] shrink-0 rounded-full ${urgency.bar}`} aria-hidden />
      <div className="flex min-w-0 flex-col gap-1">
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

        <p className="text-[10px] text-[var(--color-text-muted)]">
          {line.model && <>Forecast model <strong>{line.model}</strong>. </>}
          {line.forecast_period && <>Month {line.forecast_period}. </>}
          {line.next_step}
        </p>
      </div>
    </li>
  );
}

export function LineRecommendations({
  lines,
  counts,
  total,
  shown,
  answeredBy,
}: {
  lines: LineRecommendation[];
  counts: Record<string, number>;
  total: number;
  shown: number;
  answeredBy: string | null;
}) {
  const [branch, setBranch] = useState('');
  const [query, setQuery] = useState('');

  const branches = useMemo(
    () => [...new Set(lines.map((l) => l.branch))].sort(),
    [lines],
  );
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return lines.filter(
      (l) => (!branch || l.branch === branch) && (!q || l.sku.toLowerCase().includes(q)),
    );
  }, [lines, branch, query]);

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

  return (
    <Card>
      <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text)]">
            Per branch &amp; SKU
          </h2>
          <p className="mt-0.5 text-[10px] text-[var(--color-text-muted)]">
            Ranked by the application before any model saw them. Showing {shown} of {total} lines
            {hidden > 0 && <> — {hidden} not shown</>}.
            {counts.critical != null && (
              <>
                {' '}Across all {total}: <strong>{counts.critical}</strong> critical,{' '}
                <strong>{counts.high ?? 0}</strong> high, <strong>{counts.medium ?? 0}</strong>{' '}
                medium
                {(counts.cannot_recommend ?? 0) > 0 && (
                  <>, <strong>{counts.cannot_recommend}</strong> with no recommendation</>
                )}
                .
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
        <ul className="flex flex-col gap-3">
          {visible.map((line) => (
            <Line key={line.scope_key} line={line} />
          ))}
        </ul>
      )}
    </Card>
  );
}
