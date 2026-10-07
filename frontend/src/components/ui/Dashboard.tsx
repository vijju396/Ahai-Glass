/**
 * Shared building blocks for the dashboard-style pages, ported from the
 * read-only reference (`frontend_sodexo/src/components/ui/Dashboard.tsx`).
 *
 * The reference kept one definition imported by three pages, precisely so the
 * pages could not drift into different corner radii and different blues. That
 * property is worth more than the individual components, so the structure is
 * preserved exactly and only the palette and the money formatter are AIS's.
 */
import { forwardRef, useLayoutEffect, useRef } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { Area, AreaChart, ResponsiveContainer } from 'recharts';
import { Explain } from '@/components/ui/Explain';

/** AIS corporate blue. The primary series colour, replacing the reference's
 *  Sodexo orange. */
export const BLUE = '#005BAB';
/** AIS deep navy. */
export const NAVY = '#0F2754';
export const TEAL = '#0d7d78';
export const AMBER = '#a15c07';
/** A true yellow, darkened to yellow-600 so a 2px line stays legible on the
 *  light surface and does not vanish. `#eab308` reads more yellow but fails
 *  contrast against white at line weight. */
export const YELLOW = '#ca8a04';
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
  blue: { bg: 'var(--tint-blue)', line: BLUE, fill: 'rgba(0,91,171,0.16)' },
  navy: { bg: 'var(--tint-navy)', line: NAVY, fill: 'rgba(15,39,84,0.14)' },
  green: { bg: 'var(--tint-green)', line: GREEN, fill: 'rgba(21,127,74,0.16)' },
  teal: { bg: 'var(--tint-teal)', line: TEAL, fill: 'rgba(13,125,120,0.16)' },
  violet: { bg: 'var(--tint-violet)', line: VIOLET, fill: 'rgba(91,75,183,0.16)' },
  amber: { bg: 'var(--tint-amber)', line: AMBER, fill: 'rgba(161,92,7,0.16)' },
  red: { bg: 'var(--tint-red)', line: RED, fill: 'rgba(179,38,30,0.14)' },
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

export const Card = forwardRef<
  HTMLDivElement,
  { children: ReactNode; className?: string; style?: CSSProperties }
>(function Card({ children, className = '', style }, ref) {
  return (
    <div
      ref={ref}
      style={style}
      className={`rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-[var(--shadow-sm)] ${className}`}
    >
      {children}
    </div>
  );
});

/** Chart panel: colour spine, uppercase title, optional note and action slot. */
/** The expand / restore control that sits in a panel's top-right corner.
 *  Outward arrows to open, inward arrows to come back — an X was the first
 *  draft and read as "close this chart" rather than "return it to normal
 *  size", which is the opposite of what it does (D-151). */
function ExpandButton({ expanded, title, onClick }: { expanded: boolean; title: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={expanded}
      aria-label={expanded ? `Restore ${title} to normal size` : `Expand ${title}`}
      title={expanded ? 'Close (Esc)' : 'Expand'}
      className="-m-1 shrink-0 rounded p-1 text-[var(--color-text-muted)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-primary)]"
    >
      <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {expanded ? (
          <>
            <path d="M1.5 6.5H6.5V1.5" />
            <path d="M14.5 9.5H9.5V14.5" />
            <path d="M6.5 6.5L1.5 1.5" />
            <path d="M9.5 9.5L14.5 14.5" />
          </>
        ) : (
          <>
            <path d="M6.5 1.5H1.5V6.5" />
            <path d="M9.5 14.5H14.5V9.5" />
            <path d="M1.5 1.5L6.5 6.5" />
            <path d="M14.5 14.5L9.5 9.5" />
          </>
        )}
      </svg>
    </button>
  );
}

export function Panel({
  title,
  note,
  accent = BLUE,
  action,
  children,
  className = '',
  expanded,
  onToggleExpand,
  overlayStyle,
}: {
  title: string;
  note?: string;
  accent?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Omit all three and the panel renders exactly as it always has — every
   *  other page passes none of them, so none of them grows a button it did not
   *  ask for. */
  expanded?: boolean;
  onToggleExpand?: () => void;
  /** Fixed-position box the card jumps into while expanded. Supplied by the
   *  page, which is the only thing that knows where the filter bar ends. */
  overlayStyle?: CSSProperties;
}) {
  /* The card's height while it is sitting normally in the grid, re-measured on
     every render it spends there. When it lifts out into the popup the
     placeholder below takes exactly that height, so the grid keeps the same
     number of items at the same spans and NOTHING on the page behind moves
     (D-152). Measuring continuously rather than at click time is what makes it
     survive a filter change that happened while the popup was open. */
  const cardRef = useRef<HTMLDivElement>(null);
  const restingHeight = useRef<number>(0);
  useLayoutEffect(() => {
    if (!expanded && cardRef.current) restingHeight.current = cardRef.current.offsetHeight;
  });

  const popped = !!(expanded && overlayStyle);

  return (
    <>
      {/* Holds the slot. `invisible` and not `hidden`: it must still occupy the
          grid cell, it simply must not be seen. */}
      {popped && (
        <div className={`invisible ${className}`} style={{ height: restingHeight.current }} aria-hidden="true" />
      )}
      <Card
        ref={cardRef}
        className={popped ? 'z-40 flex flex-col overflow-auto' : className}
        style={popped ? overlayStyle : undefined}
      >
      <div className="mb-1 flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="h-3.5 w-[3px] rounded-full" style={{ background: accent }} />
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text)]">{title}</h3>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {action}
          {onToggleExpand && (
            <ExpandButton expanded={!!expanded} title={title} onClick={onToggleExpand} />
          )}
        </div>
      </div>
      {/* A short note orients; a long one is an explanation, and an
          explanation belongs behind a click (see Explain.tsx). 90 characters
          is about one line at this size. */}
      {note ? (
        note.length > 90 ? (
          <div className="mb-2 pl-[11px]">
            <Explain variant="note">{note}</Explain>
          </div>
        ) : (
          <p className="mb-2 pl-[11px] text-[10px] text-[var(--color-text-muted)]">{note}</p>
        )
      ) : (
        <div className="mb-2" />
      )}
      {children}
      </Card>
    </>
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

/**
 * `num` for an axis tick, where the only budget is width (D-154).
 *
 * `num` stops at thousands, so a million reads "1000.0K" and ten million
 * "10000.0K" — seven characters in a 46 px gutter, which is why the log ticks
 * on Demand by Glass Type and Demand by Value Class were cut off at the left
 * edge when a panel was expanded. A log axis reaches those decades routinely:
 * its top is `10 ** ceil(log10(max))`, so a 348K column puts a 1,000,000 tick
 * on the axis.
 *
 * `num` itself is left alone deliberately. It also sets the KPI tiles, where
 * the figure is read rather than scanned and "2602.4K units" carries four more
 * significant digits than "2.6M units" would.
 */
export const tickNum = (n: number | null | undefined): string => {
  if (n == null || !Number.isFinite(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e6) {
    const m = n / 1e6;
    // "1M" rather than "1.0M" on an exact decade, which is every tick on a log
    // axis and the common case here.
    return `${Number.isInteger(m) ? m : m.toFixed(1)}M`;
  }
  if (abs >= 1000) {
    const k = n / 1000;
    return `${Number.isInteger(k) ? k : k.toFixed(1)}K`;
  }
  return `${Math.round(n)}`;
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
