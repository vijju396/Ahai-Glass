/**
 * Navigation: six destinations, grouped by what a reader is trying to do.
 *
 * `index` is a stable identifier, not a position. Numbers are never reassigned
 * when a destination is removed, so gaps in the sequence are expected and are
 * the record of what went away.
 *
 * Removed from the UI on request:
 *
 * - `1` Executive Command Center, `9` Data & Model Monitoring,
 *   `10` Connections & Settings (D-052)
 * - `2` Data Studio, `3` Mapping & Validation, `11` Demand Analytics,
 *   `12` Operational Exceptions, `4` Training Center, `5` Model Leaderboard,
 *   `6` Forecast Explorer (D-057) - replaced by the four analysis and
 *   modelling tabs below, which cover the same ground for the scoped
 *   workspace.
 * - `24` Ordered vs Dispatched Time, and with it the whole Operations
 *   section, which held nothing else (D-161).
 *
 * Every removed page's component still exists under `src/features/`; none is
 * routed or linked. This project has no git history, so unrouting is the
 * reversible form of removal.
 */
export interface NavItem {
  index: number;
  label: string;
  path: string;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

export const NAV_SECTIONS: NavSection[] = [
  {
    label: 'Analysis',
    items: [
      { index: 20, label: 'Overall Analysis', path: '/overall' },
      { index: 21, label: 'Per Branch & SKU', path: '/series' },
    ],
  },
  {
    label: 'Modelling',
    items: [
      { index: 22, label: 'Training', path: '/training' },
      { index: 23, label: 'Forecasting', path: '/forecasting' },
    ],
  },
  /* The Operations section held exactly one destination - index 24, Ordered
     vs Dispatched Time - and both were removed from the UI on request
     (D-161). Removing the item empties the section, so the section goes with
     it rather than rendering a heading over nothing. Restoring it is this
     block, the route line, and the index: the page and its components are
     untouched under `features/lead-time`, as is the endpoint they read,
     `/analytics/lead-time-observed`. */
  {
    label: 'Assistant',
    items: [
      { index: 13, label: 'AI Assistant', path: '/assistant' },
      { index: 14, label: 'AI Recommendations', path: '/recommendations' },
    ],
  },
];

export const NAV_ITEMS: NavItem[] = NAV_SECTIONS.flatMap((section) => section.items);

/** Where the app opens. Overall Analysis: the question a reader has before
 *  they know what to filter. */
export const LANDING_PATH = '/overall';

/** The destinations a test holds the app to - all six, listed explicitly so
 *  removing one is a deliberate edit here rather than a filter quietly
 *  returning a shorter array. Index 8 (Scenario Planner) and index 7 (Supply
 *  Intelligence) were removed from the UI on request; their pages, APIs and
 *  tests are untouched, so either route can be restored by putting the item
 *  and the index back. Index 24 (Ordered vs Dispatched Time) took Supply
 *  Intelligence's place in the Operations section (D-105) and was renamed
 *  there (D-133); it has now gone the same way (D-161), taking the Operations
 *  section with it, since it was the only thing in it. */
export const REQUIRED_NAV_INDEXES = [20, 21, 22, 23, 13, 14] as const;

export const REQUIRED_NAV_ITEMS: NavItem[] = NAV_ITEMS.filter((item) =>
  (REQUIRED_NAV_INDEXES as readonly number[]).includes(item.index),
).sort((a, b) => a.index - b.index);
