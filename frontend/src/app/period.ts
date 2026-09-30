/* One period formatter, for every grain the backend can send.
 *
 * The backend decides what a period *is* (`app/ml/features/grain.py`); the
 * frontend only has to render the label it is given. Three pages had their own
 * copy of a month-only formatter, and each of them rendered an ISO week as
 * "W39 25" by accident - the `Number('W39')` fell through to the raw string.
 * One function now covers all three shapes:
 *
 *   2026-07    -> Jul 26
 *   2026-Q3    -> 2026 Q3
 *   2026-W31   -> W31 Jul 26
 *
 * The week label carries its month because a week number alone is unreadable
 * on an axis - nobody knows what W31 means without counting - and the month is
 * the unit the plan is actually read in.
 */

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
] as const;

/** The month `YYYY-MM` an ISO week reports under: the one holding its Thursday.
 *  The same rule the backend applies in `grain.period_month`, so a week lands
 *  under the same month at both ends. */
export function weekMonth(isoYear: number, isoWeek: number): string {
  /* 4 Jan is always in ISO week 1, so it anchors the year's first Monday. */
  const fourth = new Date(Date.UTC(isoYear, 0, 4));
  const isoWeekday = fourth.getUTCDay() || 7;
  const firstMonday = new Date(fourth);
  firstMonday.setUTCDate(fourth.getUTCDate() - isoWeekday + 1);
  const thursday = new Date(firstMonday);
  thursday.setUTCDate(firstMonday.getUTCDate() + (isoWeek - 1) * 7 + 3);
  const month = String(thursday.getUTCMonth() + 1).padStart(2, '0');
  return `${thursday.getUTCFullYear()}-${month}`;
}

/** A short axis label for any period the backend sends. */
export function shortPeriod(period: string): string {
  if (!period) return '';
  if (period.includes('Q')) return period.replace('-Q', ' Q');

  const weekly = /^(\d{4})-W(\d{2})$/.exec(period);
  if (weekly) {
    const isoYear = Number(weekly[1]);
    const isoWeek = Number(weekly[2]);
    const [year, month] = weekMonth(isoYear, isoWeek).split('-');
    return `W${weekly[2]} ${MONTHS[Number(month) - 1] ?? month} ${year?.slice(2) ?? ''}`;
  }

  const [year, month] = period.split('-');
  return `${MONTHS[Number(month) - 1] ?? month} ${year?.slice(2) ?? ''}`;
}

/** Whether a period label is an ISO week, for a caller that thins a long axis. */
export function isWeeklyPeriod(period: string): boolean {
  return /^\d{4}-W\d{2}$/.test(period);
}

/* The one place a grain's user-facing words live, so a control, a count and a
 * caption never disagree about what a period is called. */
const GRAIN_LABELS: Record<string, { option: string; noun: string; one: string }> = {
  weekly: { option: 'By week', noun: 'weeks', one: 'week' },
  monthly: { option: 'By month', noun: 'months', one: 'month' },
  quarterly: { option: 'By quarter', noun: 'quarters', one: 'quarter' },
};

/** The label for a grain option in a picker. */
export function grainOptionLabel(grain: string): string {
  return GRAIN_LABELS[grain]?.option ?? grain;
}

/** The plural noun for a count of periods at this grain ("122 weeks"). */
export function periodNoun(grain: string | undefined): string {
  return GRAIN_LABELS[grain ?? 'monthly']?.noun ?? 'periods';
}

/** The singular noun, for prose that names one period ("the last week"). */
export function periodNounOne(grain: string | undefined): string {
  return GRAIN_LABELS[grain ?? 'monthly']?.one ?? 'period';
}
