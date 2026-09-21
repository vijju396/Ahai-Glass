/**
 * Operational Exceptions — the AIS port of the reference's Time Punch
 * Analytics page.
 *
 * Same composition: a KPI strip, a severity doughnut with clickable segments,
 * an issue-type bar, a ranked "top entity" bar, two dimension bars, clear
 * chips, and a detail table that drills down.
 *
 * The domain change here is the one that matters most. The reference ranks
 * **employees** by punch exceptions. AIS holds no employee, attendance or
 * payroll data and must never acquire any, so the ranked entity is the
 * **branch × SKU line** and every exception is a supply or data condition with
 * a definition shown next to it. That is a deliberate substitution, recorded
 * in `docs/UI_VISUAL_PARITY.md` §3, not a cosmetic relabel.
 *
 * The reference's hour-of-day punch histogram has no AIS equivalent at all —
 * the panel is monthly, so there are no intra-day timestamps to bin. It is
 * listed as not ported rather than filled with invented values.
 */
import { Fragment, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  analyticsKeys,
  fetchAnalyticsFilters,
  fetchExceptions,
  type AnalyticsQuery,
  type ExceptionRow,
} from '@/api/analytics';
import {
  AMBER,
  BLUE,
  Badge,
  Card,
  ClearChip,
  LABEL,
  NAVY,
  Panel,
  RED,
  SERIES_COLORS,
  SLATE,
  StatTile,
  TEAL,
  TICK,
  TOOLTIP,
  VIOLET,
  num,
} from '@/components/ui/Dashboard';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import { Explain } from '@/components/ui/Explain';

const SELECT_CLASS =
  'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-xs text-[var(--color-text)]';

const SEVERITY_COLOR: Record<string, string> = { critical: RED, high: AMBER, medium: SLATE };

export function ExceptionsPage() {
  const [branch, setBranch] = useState('');
  const [severity, setSeverity] = useState('');
  const [type, setType] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);

  const filtersQuery = useQuery({ queryKey: analyticsKeys.filters, queryFn: fetchAnalyticsFilters });
  const query: AnalyticsQuery = useMemo(() => ({ branch: branch || undefined }), [branch]);
  const exceptionsQuery = useQuery({
    queryKey: analyticsKeys.exceptions(query),
    queryFn: () => fetchExceptions(query),
    enabled: !!filtersQuery.data,
  });
  const data = exceptionsQuery.data;

  const toggleBranch = (name: string) => setBranch((current) => (current === name ? '' : name));
  const toggleSeverity = (name: string) => setSeverity((current) => (current === name ? '' : name));
  const toggleType = (name: string) => setType((current) => (current === name ? '' : name));

  /** Severity and type filter the table client-side: the payload already
   *  carries every row for the selected branch, so a round trip would only add
   *  latency to a selection the user made by clicking. */
  const rows = useMemo(() => {
    let filtered: ExceptionRow[] = data?.rows ?? [];
    if (severity) filtered = filtered.filter((row) => row.severity === severity);
    if (type) filtered = filtered.filter((row) => row.label === type);
    return filtered;
  }, [data, severity, type]);

  const anyFilter = branch || severity || type;

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-primary)]">
            Operational Exceptions
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[var(--color-text)]">
            What needs looking at.
          </h1>
          <Explain label="About this page" variant="note">
            Supply and data conditions on real branch × SKU lines, each with the definition it was
            found by. Click any slice or column to filter.
          </Explain>
        </div>
        <Link
          to="/assistant"
          className="rounded-lg border border-[var(--color-primary)] px-3 py-1.5 text-xs font-medium text-[var(--color-primary)] hover:bg-[var(--color-primary)]/10"
        >
          Ask the assistant
        </Link>
      </header>

      <Card className="!py-2.5">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <select
            value={branch}
            onChange={(event) => setBranch(event.target.value)}
            className={SELECT_CLASS}
            aria-label="Branch"
          >
            <option value="">All branches</option>
            {filtersQuery.data?.branches.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          {branch && <ClearChip label={branch} onClear={() => setBranch('')} />}
          {severity && <ClearChip label={`severity: ${severity}`} onClear={() => setSeverity('')} />}
          {type && <ClearChip label={type} onClear={() => setType('')} />}
          {anyFilter && (
            <button
              type="button"
              onClick={() => {
                setBranch('');
                setSeverity('');
                setType('');
              }}
              className="text-[10px] font-medium text-[var(--color-text-muted)] underline"
            >
              Clear all
            </button>
          )}
          {data && !data.empty && (
            <span className="ml-auto text-[11px] text-[var(--color-text-muted)]">
              {data.kpis.total_lines.toLocaleString('en-IN')} lines · recent window{' '}
              {data.recent_window_months} months
            </span>
          )}
        </div>
      </Card>

      {(filtersQuery.isLoading || exceptionsQuery.isLoading) && <LoadingBlock label="Finding exceptions" />}
      {filtersQuery.isError && <ErrorState error={filtersQuery.error} />}
      {exceptionsQuery.isError && <ErrorState error={exceptionsQuery.error} />}

      {data?.empty && (
        <Card>
          <p className="text-sm text-[var(--color-text)]">
            {data.reason ?? 'No exception condition is present in this selection.'}
          </p>
        </Card>
      )}

      {data && !data.empty && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <StatTile
              label="Exception lines"
              value={num(data.kpis.total_lines)}
              sublabel={`${num(data.kpis.units_affected)} units affected`}
              tint="blue"
              accent
            />
            <StatTile label="Critical" value={num(data.kpis.critical_lines)} sublabel="blocks a despatch" tint="red" />
            <StatTile label="High" value={num(data.kpis.high_lines)} sublabel="needs review" tint="amber" />
            <StatTile
              label="Short despatch"
              value={num(data.kpis.short_despatch_lines)}
              sublabel="ordered is a lower bound"
              tint="violet"
            />
            <StatTile
              label="Zero stock, live demand"
              value={num(data.kpis.zero_stock_live_demand_lines)}
              sublabel="no usable stock against recent orders"
              tint="teal"
            />
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-4">
            <Panel
              title="By Severity"
              accent={RED}
              note="Click a segment to filter the table."
              action={severity ? <ClearChip label="filtered" onClear={() => setSeverity('')} /> : undefined}
            >
              <ResponsiveContainer width="100%" height={196}>
                <PieChart>
                  <Pie
                    data={data.by_severity}
                    dataKey="lines"
                    nameKey="name"
                    cx="50%"
                    cy="46%"
                    innerRadius={50}
                    outerRadius={76}
                    paddingAngle={2}
                    stroke="none"
                    isAnimationActive={false}
                    className="cursor-pointer"
                    onClick={(entry: { name?: string }) => entry?.name && toggleSeverity(entry.name)}
                  >
                    {data.by_severity.map((row) => (
                      <Cell
                        key={row.name}
                        fill={SEVERITY_COLOR[row.severity] ?? SLATE}
                        opacity={severity && row.severity !== severity ? 0.28 : 1}
                      />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value: number) => `${num(value)} lines`} contentStyle={TOOLTIP} />
                  <Legend
                    wrapperStyle={{ fontSize: 10, cursor: 'pointer' }}
                    onClick={(entry: { value?: string }) => entry?.value && toggleSeverity(entry.value)}
                  />
                </PieChart>
              </ResponsiveContainer>
            </Panel>

            <Panel
              title="By Exception Type"
              accent={BLUE}
              note="Six real conditions. Click a column to filter."
              action={type ? <ClearChip label="filtered" onClear={() => setType('')} /> : undefined}
            >
              <ResponsiveContainer width="100%" height={196}>
                <BarChart data={data.by_type} margin={{ top: 18, right: 6, left: -12, bottom: 0 }} barCategoryGap="26%">
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis
                    dataKey="name"
                    tick={{ ...TICK, fontSize: 8 }}
                    tickLine={false}
                    interval={0}
                    angle={-25}
                    textAnchor="end"
                    height={54}
                  />
                  <YAxis tick={TICK} tickFormatter={(value: number) => num(value)} />
                  <Tooltip formatter={(value: number) => `${num(value)} lines`} contentStyle={TOOLTIP} />
                  <Bar
                    dataKey="lines"
                    radius={[5, 5, 0, 0]}
                    isAnimationActive={false}
                    className="cursor-pointer"
                    onClick={(entry: { name?: string }) => entry?.name && toggleType(entry.name)}
                  >
                    {data.by_type.map((row) => (
                      <Cell
                        key={row.type}
                        fill={SEVERITY_COLOR[row.severity] ?? BLUE}
                        opacity={type && row.name !== type ? 0.28 : 1}
                      />
                    ))}
                    <LabelList dataKey="lines" position="top" formatter={(v: number) => num(v)} style={LABEL} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Top Branch × SKU Lines" accent={VIOLET} note="Ranked by units affected — the AIS equivalent of the reference's employee ranking.">
              <ResponsiveContainer width="100%" height={196}>
                <BarChart
                  data={data.top_lines.slice(0, 8).map((row) => ({ ...row, name: `${row.branch}·${row.sku.slice(-8)}` }))}
                  layout="vertical"
                  margin={{ top: 4, right: 28, left: 4, bottom: 0 }}
                >
                  <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis type="number" tick={TICK} tickFormatter={(value: number) => num(value)} />
                  <YAxis type="category" dataKey="name" tick={{ ...TICK, fontSize: 8 }} width={104} tickLine={false} />
                  <Tooltip formatter={(value: number) => `${num(value)} units`} contentStyle={TOOLTIP} />
                  <Bar dataKey="units" radius={[0, 4, 4, 0]} isAnimationActive={false}>
                    {data.top_lines.slice(0, 8).map((row) => (
                      <Cell key={row.series_id + row.type} fill={SEVERITY_COLOR[row.severity] ?? VIOLET} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            <Panel
              title="By Branch"
              accent={TEAL}
              note="Click a column to filter to that branch."
              action={branch ? <ClearChip label="filtered" onClear={() => setBranch('')} /> : undefined}
            >
              <ResponsiveContainer width="100%" height={196}>
                <BarChart
                  data={data.by_branch.slice(0, 10)}
                  margin={{ top: 18, right: 6, left: -12, bottom: 0 }}
                  barCategoryGap="26%"
                >
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis
                    dataKey="name"
                    tick={{ ...TICK, fontSize: 8 }}
                    tickLine={false}
                    interval={0}
                    angle={-30}
                    textAnchor="end"
                    height={52}
                  />
                  <YAxis tick={TICK} tickFormatter={(value: number) => num(value)} />
                  <Tooltip formatter={(value: number) => `${num(value)} lines`} contentStyle={TOOLTIP} />
                  <Bar
                    dataKey="lines"
                    radius={[5, 5, 0, 0]}
                    isAnimationActive={false}
                    className="cursor-pointer"
                    onClick={(entry: { name?: string }) => entry?.name && toggleBranch(entry.name)}
                  >
                    {data.by_branch.slice(0, 10).map((row, index) => (
                      <Cell
                        key={row.name}
                        fill={SERIES_COLORS[index % SERIES_COLORS.length]}
                        opacity={branch && row.name !== branch ? 0.28 : 1}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            <Panel title="By Value Class" accent={NAVY} note="Which value class the affected lines sit in.">
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={data.by_product_group.slice(0, 8)} margin={{ top: 16, right: 6, left: -12, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="name" tick={{ ...TICK, fontSize: 9 }} tickLine={false} interval={0} />
                  <YAxis tick={TICK} tickFormatter={(value: number) => num(value)} />
                  <Tooltip formatter={(value: number) => `${num(value)} lines`} contentStyle={TOOLTIP} />
                  <Bar dataKey="lines" fill={NAVY} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="What each condition means" accent={AMBER} className="lg:col-span-2">
              <div className="flex flex-col gap-2">
                {Object.entries(data.types).map(([key, meta]) => (
                  <div key={key} className="border-b border-[var(--color-border)] pb-2 last:border-0 last:pb-0">
                    <div className="flex items-center gap-2">
                      <Badge status={meta.severity}>{meta.severity}</Badge>
                      <span className="text-[11px] font-semibold text-[var(--color-text)]">{meta.label}</span>
                      <span className="text-[10px] text-[var(--color-text-muted)]">measured in {meta.measure}</span>
                    </div>
                    <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--color-text-muted)]">
                      {meta.definition}
                    </p>
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          <Panel
            title="Exception detail"
            accent={RED}
            note={`${rows.length.toLocaleString('en-IN')} row(s) shown. Click a row to see the condition it was found by.`}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[11px]">
                <thead>
                  <tr className="text-[var(--color-text-muted)]">
                    <th className="pb-1 pr-3">Severity</th>
                    <th className="pb-1 pr-3">Condition</th>
                    <th className="pb-1 pr-3">Branch</th>
                    <th className="pb-1 pr-3">SKU</th>
                    <th className="pb-1 pr-3">Value class</th>
                    <th className="pb-1 pr-3 text-right">Measure</th>
                    <th className="pb-1 text-right">Months</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 60).map((row) => {
                    const id = `${row.series_id}-${row.type}`;
                    return (
                      <Fragment key={id}>
                        <tr
                          onClick={() => setExpanded((current) => (current === id ? null : id))}
                          className="cursor-pointer border-t border-[var(--color-border)] hover:bg-[var(--color-surface-2)]"
                        >
                          <td className="py-1 pr-3">
                            <Badge status={row.severity}>{row.severity}</Badge>
                          </td>
                          <td className="py-1 pr-3 text-[var(--color-text)]">{row.label}</td>
                          <td className="py-1 pr-3 text-[var(--color-text-muted)]">{row.branch}</td>
                          <td className="py-1 pr-3 font-mono text-[10px] text-[var(--color-text-muted)]">{row.sku}</td>
                          <td className="py-1 pr-3 text-[var(--color-text-muted)]">{row.value_class}</td>
                          <td className="py-1 pr-3 text-right font-medium text-[var(--color-text)]">
                            {num(row.units)} {row.measure}
                          </td>
                          <td className="py-1 text-right text-[var(--color-text-muted)]">{row.occurrences}</td>
                        </tr>
                        {expanded === id && (
                          <tr className="bg-[var(--color-surface-2)]">
                            <td colSpan={7} className="px-2 py-2 text-[11px] leading-relaxed text-[var(--color-text-muted)]">
                              <span className="font-medium text-[var(--color-text)]">How this was found: </span>
                              {row.definition}
                              <span className="ml-2 font-mono text-[10px]">{row.series_id}</span>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {rows.length > 60 && (
              <p className="mt-2 text-[10px] text-[var(--color-text-muted)]">
                Showing the 60 most severe of {rows.length.toLocaleString('en-IN')} matching rows. The charts above
                count all {data.total_rows.toLocaleString('en-IN')}.
              </p>
            )}
          </Panel>

          <Card>
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text)]">
              How to read this page
            </h3>
            <ul className="mt-2 flex flex-col gap-1.5">
              {data.notes.map((note) => (
                <li key={note} className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
                  {note}
                </li>
              ))}
              <li className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
                The reference project bins punch exceptions by hour of day. AIS demand is monthly, so
                there are no intra-day timestamps to bin and that panel has no equivalent here — it is
                recorded as not ported rather than filled with invented values.
              </li>
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
