/**
 * A calendar month picker for the two ends of the history window.
 *
 * **Why `type="month"` and not `type="date"`.** The AIS panel is one row per
 * branch × SKU × *month* — there are no day-level values anywhere in it. A day
 * picker would invite a reader to ask for "12 Jun 2024" and get a whole month
 * back, which is the kind of quiet fabrication `docs/DATA_CONTRACT.md` exists
 * to prevent. `type="month"` opens the browser's real calendar, scoped to the
 * grain the data actually has.
 *
 * `min` and `max` come from the panel's own first and last month, so the
 * calendar cannot offer a month the data does not cover. Typed input can still
 * land outside that window, so it is clamped rather than sent as a query that
 * would return an empty page.
 *
 * An empty value means "the end of the data" — earliest for `from`, latest for
 * `to` — which is what the previous dropdowns called "Earliest month" and
 * "Latest month". That is why clearing is offered as an explicit control
 * instead of being something you have to discover.
 */
import { useId } from 'react';

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/** `2026-07` → `Jul 2026`. Returns the input unchanged if it is not a month. */
export function monthLabel(period: string | null | undefined): string {
  if (!period) return '';
  const [year, month] = period.split('-');
  const name = MONTHS[Number(month) - 1];
  return name && year ? `${name} ${year}` : period;
}

/** Keep a value inside `[min, max]`. ISO month strings sort lexically. */
function clamp(value: string, min?: string, max?: string): string {
  if (!value) return '';
  if (min && value < min) return min;
  if (max && value > max) return max;
  return value;
}

const FIELD =
  'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 ' +
  'text-xs text-[var(--color-text)] [color-scheme:light] dark:[color-scheme:dark]';

interface MonthFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  min?: string;
  max?: string;
  /** Shown under the control when nothing is selected. */
  placeholderNote: string;
}

export function MonthField({
  label,
  value,
  onChange,
  min,
  max,
  placeholderNote,
}: MonthFieldProps) {
  const id = useId();
  return (
    <span className="inline-flex flex-col gap-0.5">
      <label
        htmlFor={id}
        className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]"
      >
        {label}
      </label>
      <input
        id={id}
        type="month"
        value={value}
        min={min}
        max={max}
        aria-label={label}
        aria-describedby={value ? undefined : `${id}-note`}
        onChange={(event) => onChange(clamp(event.target.value, min, max))}
        className={FIELD}
      />
      {!value && (
        <span id={`${id}-note`} className="sr-only">
          {placeholderNote}
        </span>
      )}
    </span>
  );
}

interface MonthRangeProps {
  from: string;
  to: string;
  onFromChange: (value: string) => void;
  onToChange: (value: string) => void;
  /** The panel's own first and last month, as `YYYY-MM`. */
  first?: string | null;
  last?: string | null;
  months?: number;
}

export function MonthRange({
  from,
  to,
  onFromChange,
  onToChange,
  first,
  last,
  months,
}: MonthRangeProps) {
  const min = first ?? undefined;
  const max = last ?? undefined;
  // A backwards range returns nothing, so the pickers constrain each other:
  // `to` can never precede `from`, and `from` can never follow `to`.
  const fromMax = to || max;
  const toMin = from || min;
  const range =
    first && last
      ? `${monthLabel(first)} – ${monthLabel(last)}${months ? ` · ${months} months` : ''}`
      : null;

  return (
    <span className="inline-flex flex-wrap items-end gap-2">
      <MonthField
        label="From"
        value={from}
        onChange={onFromChange}
        min={min}
        max={fromMax}
        placeholderNote={first ? `Defaults to ${monthLabel(first)}` : 'Defaults to the earliest month'}
      />
      <span className="pb-2 text-[var(--color-text-muted)]">to</span>
      <MonthField
        label="To"
        value={to}
        onChange={onToChange}
        min={toMin}
        max={max}
        placeholderNote={last ? `Defaults to ${monthLabel(last)}` : 'Defaults to the latest month'}
      />
      {(from || to) && (
        <button
          type="button"
          className="link-button pb-2 text-[11px]"
          onClick={() => {
            onFromChange('');
            onToChange('');
          }}
        >
          Full history
        </button>
      )}
      {range && (
        <span className="pb-2 text-[10px] text-[var(--color-text-muted)]">
          Data available {range}
        </span>
      )}
    </span>
  );
}
