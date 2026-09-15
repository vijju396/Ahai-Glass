/**
 * Shared building blocks for the dashboard-style pages, ported from the
 * read-only reference (`frontend_sodexo/src/components/ui/Dashboard.tsx`).
 *
 * The reference kept one definition imported by three pages, precisely so the
 * pages could not drift into different corner radii and different blues. That
 * property is worth more than the individual components, so the structure is
 * preserved exactly and only the palette and the money formatter are AIS's.
 */
import type { ReactNode } from 'react';
import { Area, AreaChart, ResponsiveContainer } from 'recharts';

/** AIS corporate blue. The primary series colour, replacing the reference's
 *  Sodexo orange. */
export const BLUE = '#005BAB';
/** AIS deep navy. */
export const NAVY = '#0F2754';
export const TEAL = '#0d7d78';
export const AMBER = '#a15c07';
export const VIOLET = '#5b4bb7';
export const GREEN = '#157f4a';
export const RED = '#b3261e';
export const SLATE = '#64748b';

/** Series palette. The first two are AIS brand; the rest are semantic
 *  supporting colours chosen for hue separation and AA contrast, and are NOT
 *  described anywhere in the UI as official AIS colours. */
export const SERIES_COLORS = [BLUE, NAVY, TEAL, VIOLET, AMBER, GREEN, RED, '#0369a1'];

export const TICK = { fontSize: 10, fill: 'var(--color-text-muted)' };
export const TOOLTIP = {
  background: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  fontSize: 12,
  color: 'var(--color-text)',
};
export const LABEL = { fontSize: 10, fill: 'var(--color-text-muted)', fontWeight: 600 };

export type TintName = 'blue' | 'navy' | 'green' | 'teal' | 'violet' | 'amber' | 'red';

/** Soft tinted tile backgrounds, one per metric family, so the eye can find a
 *  metric without reading every label. */
export const TINTS: Record<TintName, { bg: string; line: string; fill: string }> = {
  blue: { bg: '#eef5fc', line: BLUE, fill: 'rgba(0,91,171,0.16)' },
  navy: { bg: '#eef1f7', line: NAVY, fill: 'rgba(15,39,84,0.14)' },
  green: { bg: '#eff8f2', line: GREEN, fill: 'rgba(21,127,74,0.16)' },
  teal: { bg: '#eef8f7', line: TEAL, fill: 'rgba(13,125,120,0.16)' },
  violet: { bg: '#f2f0fb', line: VIOLET, fill: 'rgba(91,75,183,0.16)' },
  amber: { bg: '#fdf6e9', line: AMBER, fill: 'rgba(161,92,7,0.16)' },
  red: { bg: '#fdf1f0', line: RED, fill: 'rgba(179,38,30,0.14)' },
};

/**
 * KPI tile: one label, one number, and a sparkline of that number's own trend.
 * Nothing else — the reference stripped deltas out of here on purpose, because
 * the strip became unreadable, and left the detail to the panels below.
 */
export function StatTile({
  label,
  value,
  spark,
  sparkKey,
  tint = 'teal',
  accent = false,
  sublabel,
}: {
  label: string;
  value: string;
  spark?: Array<Record<string, unknown>>;
  sparkKey?: string;
  tint?: TintName;
  accent?: boolean;
  sublabel?: string;
}) {
  const t = TINTS[tint];
  const stroke = accent ? 'rgba(255,255,255,0.9)' : t.line;
  const fill = accent ? 'rgba(255,255,255,0.28)' : t.fill;

  return (
    <div
      className={`relative flex flex-col overflow-hidden rounded-xl border p-3 shadow-[var(--shadow-sm)] ${
        accent ? 'border-transparent' : 'border-[var(--color-border)]'
      }`}
      style={accent ? { background: `linear-gradient(135deg,${BLUE} 0%,${NAVY} 100%)` } : { background: t.bg }}
    >
      <span
        className={`text-[10px] font-semibold uppercase tracking-[0.08em] ${
          accent ? 'text-white/70' : 'text-[var(--color-text-muted)]'
        }`}
      >
        {label}
      </span>
      <span className={`mt-1 text-2xl font-bold leading-none ${accent ? 'text-white' : 'text-[var(--color-text)]'}`}>
        {value}
      </span>
      {sublabel && (
        <span className={`mt-0.5 text-[10px] ${accent ? 'text-white/70' : 'text-[var(--color-text-muted)]'}`}>
          {sublabel}
        </span>
      )}
      {spark && sparkKey && spark.length > 1 && (
        <div className="-mx-3 -mb-3 mt-3 h-11">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={spark} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
              <Area
                type="monotone"
                dataKey={sparkKey}
                stroke={stroke}
                fill={fill}
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-[var(--shadow-sm)] ${className}`}
    >
      {children}
    </div>
  );
}

/** Chart panel: colour spine, uppercase title, optional note and action slot. */
export function Panel({
  title,
  note,
  accent = BLUE,
  action,
  children,
  className = '',
}: {
  title: string;
  note?: string;
  accent?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={className}>
      <div className="mb-1 flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="h-3.5 w-[3px] rounded-full" style={{ background: accent }} />
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text)]">{title}</h3>
        </div>
        {action}
      </div>
      {note ? (
        <p className="mb-2 pl-[11px] text-[10px] text-[var(--color-text-muted)]">{note}</p>
      ) : (
        <div className="mb-2" />
      )}
      {children}
    </Card>
  );
}

/** Removable filter pill. Most filters get set by clicking a chart, so there
 *  has to be a visible way to take one back off. */
export function ClearChip({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <button
      type="button"
      onClick={onClear}
      className="rounded-full border border-[var(--color-primary)] bg-[var(--color-primary)]/10 px-2 py-0.5 text-[10px] font-medium text-[var(--color-primary)]"
      title="Clear this filter"
      aria-label={`Clear filter: ${label}`}
    >
      {label} ✕
    </button>
  );
}

export function MiniTable({ rows }: { rows: Array<{ label: string; value: string }> }) {
  if (!rows.length) {
    return <p className="py-3 text-[11px] text-[var(--color-text-muted)]">Nothing to show for this selection.</p>;
  }
  return (
    <div className="flex flex-col gap-1 text-xs">
      {rows.map((r) => (
        <div key={r.label} className="flex justify-between gap-3 border-b border-[var(--color-border)] py-1 last:border-0">
          <span className="min-w-0 truncate text-[var(--color-text-muted)]">{r.label}</span>
          <span className="shrink-0 font-medium text-[var(--color-text)]">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Indian-numbering money formatter. The reference's `money()` printed US
 * dollars in millions; AIS demand value is rupees, and Indian business
 * reporting uses lakh and crore — rendering ₹8.9Cr as "$0.89M" would be a
 * translation error rather than a port.
 */
export const inr = (n: number | null | undefined): string => {
  if (n == null || !Number.isFinite(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e7) return `₹${(n / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `₹${(n / 1e5).toFixed(2)}L`;
  if (abs >= 1000) return `₹${Math.round(n / 1000)}K`;
  return `₹${Math.round(n)}`;
};

export const num = (n: number | null | undefined): string => {
  if (n == null || !Number.isFinite(n)) return '—';
  return Math.abs(n) >= 1000 ? `${(n / 1000).toFixed(1)}K` : `${Math.round(n)}`;
};

export const pct = (n: number | null | undefined, digits = 1): string =>
  n == null || !Number.isFinite(n) ? '—' : `${n.toFixed(digits)}%`;

const BADGE_STYLES: Record<string, string> = {
  completed: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  failed: 'border-red-200 bg-red-50 text-red-700',
  ineligible: 'border-slate-200 bg-slate-100 text-slate-600',
  timed_out: 'border-amber-200 bg-amber-50 text-amber-700',
  not_evaluated_budget: 'border-slate-200 bg-slate-50 text-slate-500',
  champion: 'border-[var(--color-primary)]/40 bg-[var(--color-primary)]/10 text-[var(--color-primary)]',
  critical: 'border-red-200 bg-red-50 text-red-700',
  high: 'border-amber-200 bg-amber-50 text-amber-700',
  medium: 'border-slate-200 bg-slate-100 text-slate-600',
};

export function Badge({ status, children }: { status: string; children: ReactNode }) {
  const style = BADGE_STYLES[status] ?? 'border-slate-200 bg-slate-100 text-slate-600';
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${style}`}>
      {children}
    </span>
  );
}
