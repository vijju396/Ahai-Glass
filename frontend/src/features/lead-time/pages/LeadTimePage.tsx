/**
 * Ordered vs dispatched time: what the master states, beside what the order
 * dates show.
 *
 * **The tab is not called "Lead Time", on purpose.** What this page measures is
 * Despatch Date minus Order Date — how long the order took to go out. A lead
 * time runs to *receipt*, and the source files hold no receipt date, so the
 * observed figure is one leg of the cycle and not the cycle. The master's
 * `Avg Lead Time` column is still called what the client calls it, because
 * renaming someone else's field would be worse; the page's own name now
 * describes its own measurement (D-133).
 *
 * This replaced Supply Intelligence in the Operations section (D-105). Both
 * halves already exist in the client's own files — `Avg Lead Time` in Location
 * Master, `Order Date` and `Despatch Date` in Orders & Receipts — and neither
 * file is edited to produce this. Subtracting one existing date column from
 * another is the same kind of derived view `MRP Value` already is.
 *
 * **It compares; it does not correct.** No master value is rewritten, no order
 * line is dropped, and nothing here feeds a forecast, a recommendation or a
 * safety-stock figure. A gap is put on screen for the client to judge, because
 * the master's number may be a deliberate planning allowance rather than a
 * claim about observed timing — and this application is not in a position to
 * know which.
 *
 * **Scoped to the workspace**, like every other page, so a two-branch figure
 * can never read as a national one — the banner states the restriction. The
 * network comparison is still available behind `?all=true` on the endpoint,
 * and that is where the four zero-day branches live.
 *
 * The charts answer what the table cannot: whether the observed duration is
 * moving, how often it lands in the tail rather than at the mean, and how the
 * two figures compare per branch and per SKU.
 */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  fetchLeadTimeObserved,
  leadTimeObservedKeys,
  type LeadTimeObservedBranch,
} from '@/api/analytics';
import { Card } from '@/components/ui/Card';
import { AMBER, RED } from '@/components/ui/Dashboard';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import { Explain } from '@/components/ui/Explain';
import { ScopeBanner } from '@/components/ui/ScopeBanner';
import {
  LeadTimeBySkuChart,
  LeadTimeDistributionChart,
  LeadTimeStatedVsObservedChart,
  LeadTimeTrendChart,
} from '@/features/lead-time/components/LeadTimeCharts';

const num = (v: number | null | undefined, digits = 1) =>
  v == null ? '—' : v.toLocaleString('en-IN', { maximumFractionDigits: digits });

const int = (v: number | null | undefined) =>
  v == null ? '—' : v.toLocaleString('en-IN');

/** A gap large enough to be worth a colour. Not a threshold from the data — a
 *  stated reading aid, and the row prints the number either way. */
const NOTABLE_GAP_DAYS = 0.5;

function GapCell({ gap }: { gap: number | null }) {
  if (gap == null) return <td className="num">—</td>;
  const colour = gap >= NOTABLE_GAP_DAYS ? RED : gap <= -NOTABLE_GAP_DAYS ? AMBER : undefined;
  return (
    <td className="num" style={{ color: colour, fontWeight: colour ? 600 : 400 }}>
      {gap > 0 ? '+' : ''}
      {num(gap)}
    </td>
  );
}

export function LeadTimePage() {
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [query, setQuery] = useState('');

  const observed = useQuery({
    queryKey: leadTimeObservedKeys.all,
    queryFn: () => fetchLeadTimeObserved(),
    retry: false,
  });

  const data = observed.data;
  const rows = useMemo(() => {
    const all = data?.branches ?? [];
    const q = query.trim().toLowerCase();
    return all.filter(
      (b) => (!onlyFlagged || Boolean(b.review)) && (!q || b.branch.toLowerCase().includes(q)),
    );
  }, [data, onlyFlagged, query]);

  return (
    <div className="flex flex-col gap-4">
      <header>
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-primary)]">
          Ordered vs dispatched time
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[var(--color-text)]">
          What the master says, and what the orders show.
        </h1>
        <Explain label="About this page" variant="note">
          Location Master supplies a lead time per branch. Orders &amp; Receipts records an
          Order Date and a Despatch Date on every line. This page puts the two beside each
          other. <strong>It is a comparison, not a correction</strong> — no value in either
          file is changed, no order line is dropped, and nothing here feeds a forecast or a
          recommended order. A gap is not automatically an error: the master&rsquo;s figure
          may be a deliberate planning allowance rather than a claim about observed timing,
          and that is for your team to say.
        </Explain>
      </header>

      <ScopeBanner scope={data?.workspace_scope} />

      {observed.isPending && <LoadingBlock rows={6} label="Reading the order dates" />}
      {observed.isError && (
        <ErrorState error={observed.error} onRetry={() => observed.refetch()} />
      )}

      {data?.empty && (
        <Card>
          <p className="text-[12px] text-[var(--color-text-muted)]">{data.reason}</p>
        </Card>
      )}

      {data && !data.empty && (
        <>
          <Card
            title="Coverage"
            subtitle="What this view is computed from, and what it had to leave out"
          >
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Figure
                label="Order lines used"
                value={int(data.scoped_lines || data.notes.lines_usable)}
                sub={
                  data.scope?.restricted
                    ? `of ${int(data.notes.lines_usable)} network-wide`
                    : undefined
                }
              />
              <Figure
                label="Branches compared"
                value={int(data.branches.length)}
                sub={data.scope?.skus ? `${data.scope.skus} SKUs` : undefined}
              />
              <Figure label="Branches to review" value={int(data.flagged_count)} tone={AMBER} />
              <Figure
                label="Lines excluded"
                value={int(data.notes.lines_out_of_range)}
                sub={
                  data.notes.worst_excluded_days != null
                    ? `worst ${num(data.notes.worst_excluded_days, 0)} days`
                    : undefined
                }
              />
            </div>
            <p className="mt-2 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
              A line is used when Despatch Date minus Order Date is between 0 and 90 days.
              The excluded lines are date errors rather than slow deliveries — the worst
              carries a despatch date in 2002 against a 2025 order. They are counted here
              rather than quietly dropped.
            </p>
          </Card>

          {data.trend && (
            <Card title="The observed duration is moving">
              <div className="flex flex-wrap items-baseline gap-3">
                <span
                  className="text-3xl font-bold leading-none"
                  style={{ color: data.trend.change_days > 0 ? RED : undefined }}
                >
                  {data.trend.change_days > 0 ? '+' : ''}
                  {num(data.trend.change_pct)}%
                </span>
                <span className="text-[12px] text-[var(--color-text-muted)]">
                  {num(data.trend.early_mean, 2)} d in {data.trend.early_periods[0]}–
                  {data.trend.early_periods[1]} against {num(data.trend.late_mean, 2)} d in{' '}
                  {data.trend.late_periods[0]}–{data.trend.late_periods[1]}
                </span>
              </div>
              <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--color-text-muted)]">
                The first third of the observed months against the last third, weighted by
                line count. This is a measured change between two windows, not a fitted
                trend — and not a forecast. It says what the order dates recorded; it does
                not say the next month will continue it.
              </p>
            </Card>
          )}

          <LeadTimeTrendChart months={data.by_month} branches={data.branches} />

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <LeadTimeDistributionChart buckets={data.distribution} />
            <LeadTimeStatedVsObservedChart branches={data.branches} />
          </div>

          {data.by_sku.length > 0 && <LeadTimeBySkuChart skus={data.by_sku} />}

          {/* Stated as its own panel because it is the finding most likely to be
              acted on incorrectly. Order -> Despatch -> Invoice looks like a
              clean cycle and is not one. */}
          <Card title="Invoice Date is not a third leg of the same cycle">
            <div className="grid grid-cols-3 gap-3">
              <Figure
                label="Invoiced before despatch"
                value={int(data.notes.invoice_before_despatch)}
                tone={RED}
              />
              <Figure label="Same day" value={int(data.notes.invoice_same_day)} />
              <Figure label="Invoiced after despatch" value={int(data.notes.invoice_after_despatch)} />
            </div>
            <p className="mt-2 text-[11px] leading-relaxed text-[var(--color-text-muted)]">
              Roughly two in five lines carry an invoice dated <em>before</em> the despatch,
              and those negatives cluster at exactly one and two days rather than scattering.
              That is a billing practice, not corrupt data — but it means Order → Despatch →
              Invoice is not a sequence, so this page reports the shape and refuses to
              average it into a duration. A &ldquo;despatch to invoice&rdquo; figure computed
              over these rows would mean nothing.
            </p>
          </Card>

          <Card
            title="Stated against observed, per branch"
            subtitle={`${rows.length} of ${data.branches.length} branches${data.cached ? ' · from the cached pass' : ''}`}
            actions={
              <div className="flex flex-wrap items-end gap-2">
                <label className="inline-flex items-center gap-1.5 text-[11px] text-[var(--color-text-muted)]">
                  <input
                    type="checkbox"
                    checked={onlyFlagged}
                    onChange={(e) => setOnlyFlagged(e.target.checked)}
                  />
                  Only branches to review
                </label>
                <input
                  type="search"
                  aria-label="Filter by branch"
                  value={query}
                  placeholder="Filter branch"
                  onChange={(e) => setQuery(e.target.value)}
                  className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-[11px]"
                />
              </div>
            }
          >
            <div className="table-scroll">
              <table className="data" data-testid="lead-time-comparison">
                <thead>
                  <tr>
                    <th>Branch</th>
                    <th className="num" title="Location Master `Avg Lead Time`">Stated avg</th>
                    <th className="num" title="Location Master `Std. LeadTime`">Stated std</th>
                    <th className="num" title="Mean of Despatch Date minus Order Date">Observed mean</th>
                    <th className="num">Observed median</th>
                    <th className="num" title="95% of this branch's lines came in under this">Observed p95</th>
                    <th className="num">Observed std</th>
                    <th className="num" title="Observed mean minus stated average">Gap</th>
                    <th className="num">Lines</th>
                    <th>To review</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((b) => (
                    <Row key={b.branch} branch={b} />
                  ))}
                </tbody>
              </table>
            </div>
            {rows.length === 0 && (
              <p className="py-3 text-[11px] text-[var(--color-text-muted)]">
                No branch matches this filter.
              </p>
            )}
            <div className="mt-2">
              <Explain variant="note" label="How to read these numbers">
                <p>
                  <strong>Gap</strong> is the observed mean minus the stated average. Positive
                  means orders took longer than the master says. <strong>p95</strong> is there
                  because the mean hides the tail, and the tail is what causes a stockout: a
                  branch averaging 3 days with a p95 of 10 stocks out on the p95 days, not the
                  average ones.
                </p>
                <p className="mt-1.5">
                  The observed spread is routinely wider than the stated one. That is worth
                  knowing before the stated standard deviation is used as a safety-stock
                  input — it is currently used nowhere.
                </p>
              </Explain>
            </div>
          </Card>

          <Card title="The other master fields, as supplied">
            <p className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
              <strong>Service Factor</strong> is a z-score — 1.0 is about 84% service, 1.65
              about 95%. It reads 1.0 for almost every branch, so plugging it into a
              reorder-point formula as-is would plan to a{' '}
              <strong>lower</strong> service level than the q95 this application currently
              uses. One row of the file carries 225, which cannot be a service factor; that
              row has no branch name and is the file&rsquo;s own totals line, excluded here.
            </p>
            <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--color-text-muted)]">
              <strong>Transit Lead Time</strong> is shown per branch below and is never added
              to the average — whether the average already includes transit is a definition
              only your team can confirm. <strong>Replenishment A/B/C</strong> are zero for
              every branch and are not used anywhere.
            </p>
            <div className="table-scroll mt-2">
              <table className="data">
                <thead>
                  <tr>
                    <th>Branch</th>
                    <th className="num">Transit</th>
                    <th className="num">Service factor</th>
                    <th className="num">Truck (MoQ)</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((b) => (
                    <tr key={b.branch}>
                      <td>{b.branch}</td>
                      <td className="num">{num(b.transit)}</td>
                      <td
                        className="num"
                        style={{ color: b.service_factor_usable ? undefined : RED }}
                        title={
                          b.service_factor_usable
                            ? undefined
                            : 'Outside 0-5, so this cannot be a service factor.'
                        }
                      >
                        {num(b.service_factor, 2)}
                      </td>
                      <td className="num">{num(b.truck_moq, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="What this page does not do">
            <ul className="flex flex-col gap-1">
              {data.caveats.map((note) => (
                <li key={note} className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
                  {note}
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}

function Figure({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] p-2.5">
      <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
        {label}
      </span>
      <span className="mt-1 block text-xl font-bold leading-none" style={{ color: tone }}>
        {value}
      </span>
      {sub && <span className="mt-0.5 block text-[10px] text-[var(--color-text-muted)]">{sub}</span>}
    </div>
  );
}

function Row({ branch: b }: { branch: LeadTimeObservedBranch }) {
  return (
    <tr>
      <td style={{ fontWeight: b.review ? 600 : 400 }}>{b.branch}</td>
      <td className="num">{num(b.stated_avg)}</td>
      <td className="num">{num(b.stated_std, 2)}</td>
      <td className="num">{num(b.observed_mean, 2)}</td>
      <td className="num">{num(b.observed_median)}</td>
      <td className="num">{num(b.observed_p95)}</td>
      <td className="num">{num(b.observed_std, 2)}</td>
      <GapCell gap={b.gap_mean} />
      <td className="num">{int(b.lines)}</td>
      <td className="text-[10px] text-[var(--color-text-muted)]">{b.review ?? ''}</td>
    </tr>
  );
}
