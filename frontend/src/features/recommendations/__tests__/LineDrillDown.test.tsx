/**
 * A count on this page has to be a way in, not just a number to read.
 *
 * The per-line list answered the network problem one level down and then
 * recreated it: twelve of 261 lines were shown, and a reader told "85 lines are
 * critical" still could not see which 85, at which branch, for which SKU. The
 * whole ranking is now listed, every count filters to exactly the lines behind
 * it, and each card opens into every figure the application holds (D-132).
 *
 * What is asserted here is the part someone acts on: that the list is complete,
 * that a filter states what it left behind rather than letting a short list
 * read as a finished one, and that a line without written prose still shows its
 * computed reason and says which it is.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import * as api from '@/api/analytics';
import { renderWithProviders } from '@/test/renderWithProviders';
import { RecommendationList } from '../components/RecommendationList';

function line(overrides: Partial<api.LineRecommendation> = {}): api.LineRecommendation {
  return {
    scope_key: 'BENGALURU|FG.AAA',
    branch: 'BENGALURU',
    sku: 'FG.AAA',
    urgency: 'critical',
    urgency_reason: 'No usable stock against a q95 planning demand of 1,462 units a month.',
    headline: 'Zero stock against live demand',
    explanation: 'BENGALURU branch for SKU FG.AAA has zero usable stock.',
    next_step: 'Open Per Branch & SKU and select this branch and SKU.',
    evidence: ['Short despatch: 368 units'],
    written_by_model: true,
    forecast_period: '2026-08',
    service_level: 95,
    point_forecast: 652.2,
    quantile_forecast: 1461.53,
    usable_stock: 0,
    on_order: 500,
    backorders: 120,
    days_of_cover: 0,
    lead_time_days: 4,
    protection_period_days: 34,
    order_up_to_level: 1632.59,
    recommended_order: 1632.59,
    model: 'var_exog',
    demand_segment: 'smooth',
    is_censored: true,
    target_source: 'order',
    unavailable_reason: null,
    exceptions: [{ type: 'Short despatch', units: 368 }],
    ...overrides,
  };
}

const LINES: api.LineRecommendation[] = [
  line(),
  line({
    scope_key: 'DELHI-1|FG.BBB',
    branch: 'DELHI-1',
    sku: 'FG.BBB',
    urgency: 'high',
    urgency_reason: '2 days of cover against a 33-day protection period.',
    // Outside the handful sent for prose.
    explanation: null,
    written_by_model: false,
    exceptions: [{ type: 'Zero stock, live demand', units: 255 }],
  }),
  line({
    scope_key: 'DELHI-1|FG.CCC',
    branch: 'DELHI-1',
    sku: 'FG.CCC',
    urgency: 'high',
    urgency_reason: '5 days of cover against a 30-day protection period.',
    explanation: null,
    written_by_model: false,
    exceptions: [],
  }),
];

function payload(overrides: Partial<api.RecommendationsPayload> = {}): api.RecommendationsPayload {
  return {
    items: [],
    answered_by: 'openai',
    sources: [],
    facts: {},
    caveats: [],
    temperature: 0.3,
    model: 'gpt-x',
    provider_error: null,
    lines: LINES,
    lines_answered_by: 'openai',
    line_counts: { critical: 1, high: 2, medium: 0, cannot_recommend: 0 },
    lines_total: 3,
    lines_shown: 3,
    lines_written: 1,
    line_exception_counts: [
      { label: 'Short despatch', lines: 1, units: 368 },
      { label: 'Zero stock, live demand', lines: 1, units: 255 },
    ],
    ...overrides,
  };
}

function stub(overrides: Partial<api.RecommendationsPayload> = {}) {
  return vi.spyOn(api, 'fetchRecommendations').mockResolvedValue(payload(overrides));
}

/** The SKUs the list is currently rendering a card for.
 *
 *  Read off the card headings rather than by text search: a SKU code also
 *  appears inside a model-written explanation, so a plain `getByText` matches
 *  prose as well as the card it belongs to. */
const shownSkus = () =>
  screen
    .getAllByRole('heading', { level: 3 })
    .map((h) => h.textContent ?? '')
    .filter((t) => t.includes('×'));

describe('drilling into the ranked lines', () => {
  it('lists every ranked line, not only the ones a model wrote about', async () => {
    stub();
    renderWithProviders(<RecommendationList />);
    await screen.findByRole('heading', { name: /Per branch/i });

    const skus = shownSkus();
    expect(skus.some((t) => t.includes('FG.AAA'))).toBe(true);
    expect(skus.some((t) => t.includes('FG.BBB'))).toBe(true);
    expect(skus.some((t) => t.includes('FG.CCC'))).toBe(true);
  });

  it('says how many lines carry a written explanation, separately from how many are shown', async () => {
    stub();
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/Showing 3 of 3 lines/)).toBeInTheDocument();
    expect(screen.getByText(/carry a written explanation/)).toBeInTheDocument();
  });

  it('marks a line with no prose as computed rather than letting it read as terse', async () => {
    stub();
    renderWithProviders(<RecommendationList />);

    expect(
      (await screen.findAllByText('computed — no written explanation')).length,
    ).toBe(2);
    // Its computed reason is still there — that is the part someone acts on.
    expect(
      screen.getByText('2 days of cover against a 33-day protection period.'),
    ).toBeInTheDocument();
  });

  it('turns an urgency count into the lines behind it', async () => {
    const user = userEvent.setup();
    stub();
    renderWithProviders(<RecommendationList />);

    await user.click(await screen.findByRole('button', { name: /Critical 1/ }));

    expect(shownSkus()).toEqual([expect.stringContaining('FG.AAA')]);
    expect(screen.getByText(/of 3 listed lines match/)).toBeInTheDocument();
  });

  it('turns a finding count into the lines behind it', async () => {
    const user = userEvent.setup();
    stub();
    renderWithProviders(<RecommendationList />);

    await user.click(
      await screen.findByRole('button', { name: /Zero stock, live demand 1/ }),
    );

    expect(shownSkus()).toEqual([expect.stringContaining('FG.BBB')]);
  });

  it('a filter is releasable, and says so', async () => {
    const user = userEvent.setup();
    stub();
    renderWithProviders(<RecommendationList />);

    await user.click(await screen.findByRole('button', { name: /Critical 1/ }));
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));

    expect(shownSkus()).toHaveLength(3);
    expect(screen.queryByText(/listed lines match/)).not.toBeInTheDocument();
  });

  it('opens one line into every figure the application holds for it', async () => {
    const user = userEvent.setup();
    stub();
    renderWithProviders(<RecommendationList />);

    const toggles = await screen.findAllByRole('button', { name: 'All figures' });
    await user.click(toggles[0]!);

    // Figures the six-number summary does not carry.
    expect(screen.getByText('Already on order')).toBeInTheDocument();
    expect(screen.getByText('Backorders')).toBeInTheDocument();
    expect(screen.getByText('Order-up-to level')).toBeInTheDocument();
    expect(screen.getByText('Average lead time')).toBeInTheDocument();
    expect(screen.getByText('Demand measured as')).toBeInTheDocument();
    // The censoring is stated as a fact, not left to a badge.
    expect(screen.getByText(/order is a lower bound/)).toBeInTheDocument();
    // And what the exception join found on this line.
    expect(screen.getByText('What was found on this line')).toBeInTheDocument();
  });

  it('closes again, so a long list does not stay open', async () => {
    const user = userEvent.setup();
    stub();
    renderWithProviders(<RecommendationList />);

    const toggles = await screen.findAllByRole('button', { name: 'All figures' });
    await user.click(toggles[0]!);
    await user.click(screen.getByRole('button', { name: 'Hide details' }));

    expect(screen.queryByText('Order-up-to level')).not.toBeInTheDocument();
  });

  it('never truncates silently — the unrendered count is stated and reachable', async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 30 }, (_, i) =>
      line({ scope_key: `B|FG.${i}`, sku: `FG.SKU${i}` }),
    );
    stub({
      lines: many,
      lines_total: 30,
      lines_shown: 30,
      line_counts: { critical: 30, high: 0, medium: 0, cannot_recommend: 0 },
    });
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/5 more match this filter/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Show all 30' }));

    expect(screen.queryByText(/more match this filter/)).not.toBeInTheDocument();
    expect(shownSkus()).toHaveLength(30);
  });

  it('an unavailable line opens to its reason, never to an order of zero', async () => {
    const user = userEvent.setup();
    stub({
      lines: [
        line({
          urgency: 'cannot_recommend',
          urgency_reason: 'No active champion is selected for this scope.',
          unavailable_reason: 'No active champion is selected for this scope.',
          recommended_order: null,
          quantile_forecast: null,
          order_up_to_level: null,
        }),
      ],
      lines_total: 1,
      lines_shown: 1,
      line_counts: { critical: 0, high: 0, medium: 0, cannot_recommend: 1 },
    });
    renderWithProviders(<RecommendationList />);

    await user.click(await screen.findByRole('button', { name: 'All figures' }));

    const panel = screen.getByText('No recommendation:').closest('div')!;
    expect(within(panel).getByText(/No active champion/)).toBeInTheDocument();
    expect(screen.queryByText('Recommended order')).not.toBeInTheDocument();
    expect(screen.queryByText('Order-up-to level')).not.toBeInTheDocument();
  });
});
