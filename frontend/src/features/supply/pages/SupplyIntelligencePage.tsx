/**
 * Supply Intelligence.
 *
 * Two halves, deliberately separated:
 *
 * **Placement** — dead or slow stock, and zero stock against live demand. These
 * are measured from the stock snapshot and the order history, so they are
 * available even before a series-level forecast exists.
 *
 * **Replenishment** — the order recommendations, which do need a branch × SKU
 * forecast. When one does not exist the page renders the API's stated reason
 * rather than an empty table a reader might take for "nothing to order".
 *
 * Every recommendation exposes its own calculation: order-up-to level, usable
 * stock, lead time, review period, protection period, and the pre-rounding
 * requirement. Nothing is computed in this file.
 */
import { useState } from 'react';
import { ComparisonBars } from '@/components/charts/ComparisonBars';
import { useQuery } from '@tanstack/react-query';
import { ApiError } from '@/api/client';
import {
  fetchRecommendations,
  fetchSupplyOverview,
  fetchTransferableStock,
  inventoryKeys,
} from '@/api/inventory';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/States';
import { formatDays, formatInt } from '@/components/ui/format';
import { LeadTimePanels } from '@/features/supply/components/LeadTimePanels';
import { SupplyExplainer } from '@/features/supply/components/SupplyExplainer';
import { Explain } from '@/components/ui/Explain';

const SERVICE_LEVELS = [80, 90, 95] as const;

/** In-page anchors, in the order the sections appear. */
const SECTIONS: ReadonlyArray<{ id: string; label: string }> = [
  { id: 'how-to-read', label: 'How to read this' },
  { id: 'lead-time', label: 'Lead time' },
  { id: 'exposure', label: 'Inventory exposure' },
  { id: 'replenishment', label: 'Replenishment' },
  { id: 'zero-stock', label: 'Zero stock vs demand' },
  { id: 'dead-stock', label: 'Dead / slow stock' },
];

export function SupplyIntelligencePage() {
  const [serviceLevel, setServiceLevel] = useState<number>(95);
  const [branch, setBranch] = useState<string>('');
  const [onlyActionable, setOnlyActionable] = useState(false);
  const [transferSku, setTransferSku] = useState<string | null>(null);

  const overview = useQuery({
    queryKey: inventoryKeys.overview(branch || undefined),
    queryFn: () => fetchSupplyOverview(branch || undefined, 25),
    retry: false,
  });

  const recommendationQuery = {
    service_level: serviceLevel,
    branch: branch || undefined,
    only_actionable: onlyActionable,
    limit: 50,
  };
  const recommendations = useQuery({
    queryKey: inventoryKeys.recommendations(recommendationQuery),
    queryFn: () => fetchRecommendations(recommendationQuery),
    retry: false,
  });

  const transferable = useQuery({
    queryKey: inventoryKeys.transferable(transferSku ?? '', branch || undefined),
    queryFn: () => fetchTransferableStock(transferSku as string, branch || undefined),
    enabled: Boolean(transferSku),
    retry: false,
  });

  const totals = overview.data?.totals;
  const rows = recommendations.data?.items ?? [];

  return (
    <div className="stack">
      <div className="page-head">
        <div className="eyebrow">07 &middot; Supply Intelligence</div>
        <h1>Supply Intelligence</h1>
        <Explain label="About this page" variant="note">
          Cover, unfilled demand, misplaced stock and order recommendations.
          Every recommendation is a{' '}
          <strong>current-snapshot estimate</strong> and exposes the inputs it
          was computed from.
        </Explain>
      </div>

      {/* This page is very long. Without these the sections below the first
          screenful are reachable only by scrolling past several hundred table
          rows, which is how the lead-time panels ended up invisible. */}
      <nav className="section-nav" aria-label="Sections on this page">
        {SECTIONS.map((section) => (
          <a key={section.id} href={`#${section.id}`}>
            {section.label}
          </a>
        ))}
      </nav>

      <section id="how-to-read">
        <SupplyExplainer />
      </section>

      <Card title="Filters">
        <div className="field-row">
          <label className="field">
            <span>Service level</span>
            <select
              value={serviceLevel}
              onChange={(event) => setServiceLevel(Number(event.target.value))}
            >
              {SERVICE_LEVELS.map((level) => (
                <option key={level} value={level}>
                  q{level}
                </option>
              ))}
            </select>
            <span className="hint">
              The quantile the order-up-to level is sized on. q80/q90/q95 are
              forecast outputs, not additional models.
            </span>
          </label>
          <label className="field">
            <span>Branch (optional)</span>
            <input
              value={branch}
              onChange={(event) => setBranch(event.target.value.toUpperCase())}
              placeholder="e.g. JAIPUR"
            />
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={onlyActionable}
              onChange={(event) => setOnlyActionable(event.target.checked)}
            />
            <span>
              <strong>Only rows with something to order</strong>
              <span className="hint">
                Off by default: a row that could not be recommended for is one a
                planner needs to see.
              </span>
            </span>
          </label>
        </div>
      </Card>

      {/* Lead time sits above the recommendation tables because the
          protection period every one of them uses is built from it. These
          panels expose the two source columns that reached no screen at all
          before: the spread and the transit split. */}
      <section id="lead-time" className="flex flex-col gap-2">
        <div>
          <div className="eyebrow">Lead time</div>
          <Explain variant="hint">
            Days from order to receipt, per branch, from the lead-time source file. The
            replenishment protection period below is built from the average alone, so the
            spread shown here is not yet reflected in any recommended quantity.
          </Explain>
        </div>
        <LeadTimePanels />
      </section>

      {overview.isPending && (
        <Card>
          <LoadingBlock rows={5} label="Loading supply overview" />
        </Card>
      )}
      {overview.isError && (
        <Card>
          {overview.error instanceof ApiError && overview.error.status === 404 ? (
            <EmptyState title="No completed forecast run yet">
              {overview.error.message} {overview.error.remediation}
            </EmptyState>
          ) : (
            <ErrorState error={overview.error} onRetry={() => overview.refetch()} />
          )}
        </Card>
      )}

      {totals && overview.data && (
        <>
          <div className="tiles">
            <div className="tile">
              <div className="k">Positions with stock</div>
              <div className="v">{formatInt(totals.positions_with_stock)}</div>
              <div className="s">of {formatInt(totals.positions)} branch × SKU</div>
            </div>
            <div className="tile is-warn">
              <div className="k">Dead or slow positions</div>
              <div className="v">{formatInt(totals.dead_or_slow_positions)}</div>
              <div className="s">
                {formatInt(totals.dead_stock_units)} units
                {totals.dead_stock_value === null
                  ? ''
                  : ` · ₹${formatInt(totals.dead_stock_value)}`}
              </div>
            </div>
            <div className="tile is-crit">
              <div className="k">Zero stock, live demand</div>
              <div className="v">{formatInt(totals.zero_stock_live_demand_positions)}</div>
              <div className="s">
                {formatInt(totals.unfilled_recent_demand_units)} units of recent
                demand
              </div>
            </div>
            <div className="tile">
              <div className="k">Negative stock rows</div>
              <div className="v">{formatInt(totals.negative_stock_rows)}</div>
              <div className="s">Surfaced, not clamped away</div>
            </div>
            <div className="tile">
              <div className="k">Stock snapshot</div>
              <div className="v">{overview.data.stock_snapshot_date}</div>
              <div className="s">Review period {overview.data.review_period_days} d</div>
            </div>
          </div>

          <div className="grid-2">
            <Card id="exposure" title="Inventory exposure" subtitle="Snapshot positions · counts are separate measures, not additive"><ComparisonBars unit="Positions" labels={['With stock', 'Dead / slow', 'Zero stock / live demand']} series={[{ name: 'Branch × SKU positions', values: [totals.positions_with_stock, totals.dead_or_slow_positions, totals.zero_stock_live_demand_positions] }]} /></Card>
            <Card title="Replenishment priorities" subtitle="Five largest available order recommendations in the returned page"><ComparisonBars labels={[...rows].filter(r => r.recommended_order !== null).sort((a,b) => b.recommended_order! - a.recommended_order!).slice(0,5).map(r => r.canonical_sku ?? r.scope_key)} series={[{ name: 'Recommended units', values: [...rows].filter(r => r.recommended_order !== null).sort((a,b) => b.recommended_order! - a.recommended_order!).slice(0,5).map(r => r.recommended_order) }]} /><Explain variant="note">Filtered to the loaded recommendation page. The table below retains branch identity, unavailable rows and calculation inputs.</Explain></Card>
          </div>
          {overview.data.caveats.map((caveat) => (
            <Explain variant="callout">
              <p>{caveat}</p>
            </Explain>
          ))}
        </>
      )}

      <Card
        id="replenishment"
        title={`Order recommendations · q${serviceLevel}`}
        subtitle={
          recommendations.data
            ? `${recommendations.data.total} row(s) for ${recommendations.data.period} at ${recommendations.data.scope_level} level`
            : 'Loading recommendations'
        }
      >
        {recommendations.isPending && <LoadingBlock rows={6} label="Loading recommendations" />}
        {recommendations.isError && (
          <ErrorState error={recommendations.error} onRetry={() => recommendations.refetch()} />
        )}
        {recommendations.data?.unavailable_reason && (
          <EmptyState title="No recommendations can be produced yet">
            {recommendations.data.unavailable_reason}
          </EmptyState>
        )}
        {rows.length > 0 && (
          <>
            <div className="table-scroll">
              <table className="data" data-testid="recommendation-table">
                <thead>
                  <tr>
                    <th>Branch × SKU</th>
                    <th className="num">Order</th>
                    <th className="num">Order-up-to</th>
                    <th className="num">q{serviceLevel}/month</th>
                    <th className="num">Point/month</th>
                    <th className="num">Usable stock</th>
                    <th className="num">On order</th>
                    <th className="num">Backorders</th>
                    <th className="num">Lead time</th>
                    <th className="num">Review</th>
                    <th className="num">Protection</th>
                    <th className="num">Cover</th>
                    <th>Model</th>
                    <th>Reason / warnings</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.scope_key}>
                      <td className="mono">{row.scope_key}</td>
                      <td className="num">
                        {row.recommended_order === null
                          ? '—'
                          : formatInt(row.recommended_order)}
                      </td>
                      <td className="num">{formatInt(row.order_up_to_level)}</td>
                      <td className="num">{formatInt(row.monthly_quantile_forecast)}</td>
                      <td className="num">{formatInt(row.monthly_point_forecast)}</td>
                      <td className="num">{formatInt(row.usable_stock_on_hand)}</td>
                      <td className="num">{formatInt(row.confirmed_stock_on_order)}</td>
                      <td className="num">{formatInt(row.backorders)}</td>
                      <td className="num">{formatDays(row.lead_time_days)}</td>
                      <td className="num">{formatDays(row.review_period_days)}</td>
                      <td className="num">{formatDays(row.protection_period_days)}</td>
                      <td className="num">{formatDays(row.days_of_cover)}</td>
                      <td>{row.forecast_model_id ?? '—'}</td>
                      <td>
                        {row.unavailable_reason ? (
                          <strong>{row.unavailable_reason}</strong>
                        ) : row.warnings.length > 0 ? (
                          <details>
                            <summary>{row.warnings.length} warning(s)</summary>
                            <ul>
                              {row.warnings.map((warning) => (
                                <li key={warning}>{warning}</li>
                              ))}
                            </ul>
                          </details>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Explain variant="hint">
              <strong>How each row is computed:</strong> protection period ={' '}
              review period + lead time; order-up-to = q{serviceLevel} monthly
              forecast scaled to the protection period; recommended order =
              order-up-to &minus; usable stock &minus; on order + backorders.
              The pre-rounding requirement is kept as{' '}
              <code>raw_recommended_order</code> so any MOQ or case-pack
              rounding is visible.
            </Explain>
            {(recommendations.data?.notes ?? []).map((note) => (
              <Explain variant="hint">
                {note}
              </Explain>
            ))}
          </>
        )}
      </Card>

      {overview.data && overview.data.zero_stock_live_demand.length > 0 && (
        <Card
          id="zero-stock"
          title="Zero stock against live demand"
          subtitle="A placement problem, not necessarily a shortage — the units may exist at another branch"
        >
          <div className="table-scroll">
            <table className="data" data-testid="zero-stock-table">
              <thead>
                <tr>
                  <th>Branch</th>
                  <th>SKU</th>
                  <th className="num">Usable stock</th>
                  <th className="num">Recent demand</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {overview.data.zero_stock_live_demand.map((row) => (
                  <tr key={`${row.canonical_branch}-${row.canonical_sku}`}>
                    <td>{row.canonical_branch}</td>
                    <td className="mono">{row.canonical_sku}</td>
                    <td className="num">{formatInt(row.usable_qty)}</td>
                    <td className="num">{formatInt(row.recent_demand)}</td>
                    <td>
                      <button
                        type="button"
                        className="btn"
                        onClick={() => setTransferSku(row.canonical_sku ?? null)}
                      >
                        Who holds it?
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {transferSku && (
        <Card
          title={`Stock held elsewhere · ${transferSku}`}
          actions={
            <button type="button" className="btn" onClick={() => setTransferSku(null)}>
              Close
            </button>
          }
        >
          {transferable.isPending && <LoadingBlock rows={4} label="Loading holders" />}
          {transferable.isError && (
            <ErrorState error={transferable.error} onRetry={() => transferable.refetch()} />
          )}
          {transferable.data && (
            <>
              {transferable.data.holders.length === 0 ? (
                <EmptyState title="No other branch holds this SKU">
                  This is a genuine shortage rather than a placement problem: the
                  units do not exist anywhere in the snapshot.
                </EmptyState>
              ) : (
                <div className="table-scroll">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Branch</th>
                        <th className="num">Usable</th>
                        <th className="num">Closing</th>
                        <th>Class</th>
                      </tr>
                    </thead>
                    <tbody>
                      {transferable.data.holders.map((holder) => (
                        <tr key={holder.canonical_branch}>
                          <td>{holder.canonical_branch}</td>
                          <td className="num">{formatInt(holder.usable_qty)}</td>
                          <td className="num">{formatInt(holder.closing_qty)}</td>
                          <td>{holder.stock_class ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <Explain variant="hint">{transferable.data.caveat}</Explain>
            </>
          )}
        </Card>
      )}

      {overview.data && overview.data.dead_stock.length > 0 && (
        <Card
          id="dead-stock"
          title="Dead or slow-moving stock"
          subtitle="Usable stock where that exact branch × SKU had no ordered demand in the last six months of history"
        >
          <div className="table-scroll">
            <table className="data" data-testid="dead-stock-table">
              <thead>
                <tr>
                  <th>Branch</th>
                  <th>SKU</th>
                  <th className="num">Usable stock</th>
                  <th className="num">Value</th>
                  <th>Class</th>
                </tr>
              </thead>
              <tbody>
                {overview.data.dead_stock.map((row) => (
                  <tr key={`${row.canonical_branch}-${row.canonical_sku}`}>
                    <td>{row.canonical_branch}</td>
                    <td className="mono">{row.canonical_sku}</td>
                    <td className="num">{formatInt(row.usable_qty)}</td>
                    <td className="num">
                      {row.closing_value === null ? '—' : `₹${formatInt(row.closing_value)}`}
                    </td>
                    <td>{row.stock_class ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Explain variant="hint">
            A placement signal, not an instruction to scrap.
          </Explain>
        </Card>
      )}

    </div>
  );
}
