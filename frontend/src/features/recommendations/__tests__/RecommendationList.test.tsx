/**
 * The AI recommendations list.
 *
 * What is asserted here is mostly what the panel refuses to hide: the figures
 * behind a claim, the page those figures can be checked on, which of the two
 * writers produced the list, and the caveats that qualify all of it. A
 * recommendation someone acts on because it sounded confident is the failure
 * this panel is shaped to avoid.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import * as api from '@/api/analytics';
import { renderWithProviders } from '@/test/renderWithProviders';
import { RecommendationList } from '../components/RecommendationList';

function payload(overrides: Partial<api.RecommendationsPayload> = {}): api.RecommendationsPayload {
  return {
    items: [
      {
        title: 'Critical supply exceptions are open',
        severity: 'critical',
        observation: '3,638 branch x SKU lines are flagged critical.',
        explanation:
          'A critical exception is a line where despatch fell short of the order. ' +
          'Short despatch means the recorded order is only a lower bound on true demand.',
        next_step: 'Open Operational Exceptions and sort by units affected.',
        evidence: ['critical_lines = 3,638', 'short_despatch_lines = 2,587'],
        source: 'stock_exceptions',
        verify_on: 'Operational Exceptions',
      },
      {
        title: 'Recent demand has shifted',
        severity: 'medium',
        observation: 'National demand has shifted +23.3% over 6 months.',
        explanation: 'Drift compares recent demand against the history before it.',
        next_step: null,
        evidence: ['national_shift_pct = 23.29'],
        source: 'data_quality',
        verify_on: 'Demand Analytics',
      },
    ],
    answered_by: 'deterministic_no_key',
    sources: ['stock_exceptions', 'data_quality'],
    facts: {},
    caveats: [
      'These are things to look at, not instructions to act.',
      'Stock figures come from one snapshot dated 2026-08-01.',
    ],
    temperature: 2.0,
    model: null,
    provider_error: null,
    lines: [line()],
    lines_answered_by: 'openai',
    line_counts: { critical: 11, high: 29, medium: 0, cannot_recommend: 0 },
    lines_total: 40,
    lines_shown: 1,
    ...overrides,
  };
}

/** One ranked branch x SKU line. Censored and zero-stock by default, because
 *  that is the combination the panel has to render honestly. */
function line(overrides: Partial<api.LineRecommendation> = {}): api.LineRecommendation {
  return {
    scope_key: 'BENGALURU|FG.BA5.LFH.GCG2120000',
    branch: 'BENGALURU',
    sku: 'FG.BA5.LFH.GCG2120000',
    urgency: 'critical',
    urgency_reason: 'No usable stock against a q95 planning demand of 1,462 units a month.',
    headline: 'Zero stock against live demand',
    explanation: 'BENGALURU branch for SKU FG.BA5.LFH.GCG2120000 has zero usable stock.',
    next_step: 'Open Supply Intelligence and filter to this branch and SKU.',
    evidence: ['usable_stock: 0.0', 'q95 planning demand: 1461.53'],
    written_by_model: true,
    forecast_period: '2026-08',
    service_level: 95,
    point_forecast: 652.2,
    quantile_forecast: 1461.53,
    usable_stock: 0,
    on_order: 0,
    backorders: 0,
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
    exceptions: [],
    ...overrides,
  };
}

function stub(overrides: Partial<api.RecommendationsPayload> = {}) {
  return vi.spyOn(api, 'fetchRecommendations').mockResolvedValue(payload(overrides));
}

describe('RecommendationList', () => {
  it('shows each item with its observation and plain-language explanation', async () => {
    stub();
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText('Critical supply exceptions are open')).toBeInTheDocument();
    expect(screen.getByText(/3,638 branch x SKU lines are flagged critical/)).toBeInTheDocument();
    expect(screen.getByText(/only a lower bound on true demand/)).toBeInTheDocument();
  });

  it('prints the figures a claim rests on', async () => {
    // The reader must be able to check the number, not just the sentence.
    stub();
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText('critical_lines = 3,638')).toBeInTheDocument();
    expect(screen.getByText('short_despatch_lines = 2,587')).toBeInTheDocument();
  });

  it('names the page each item can be verified on', async () => {
    stub();
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/check on Operational Exceptions/)).toBeInTheDocument();
    expect(screen.getByText(/check on Demand Analytics/)).toBeInTheDocument();
  });

  it('says a template wrote the list when no key is configured', async () => {
    // A template list and a model list read identically on a screen.
    stub();
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/no API key configured/i)).toBeInTheDocument();
  });

  it('says the model wrote the list, and at what temperature', async () => {
    stub({ answered_by: 'openai', model: 'gpt-4.1-mini' });
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/Written by the model from measured facts/i)).toBeInTheDocument();
    // Worth stating: at 2.0 the same facts give a different list each run.
    expect(screen.getByText(/temperature 2/)).toBeInTheDocument();
  });

  it('does not advertise a temperature the list was not written at', async () => {
    stub({ answered_by: 'deterministic_no_key' });
    renderWithProviders(<RecommendationList />);

    await screen.findByText('Critical supply exceptions are open');
    expect(screen.queryByText(/temperature/i)).toBeNull();
  });

  it('says the provider failed rather than presenting the fallback as a model answer', async () => {
    stub({ answered_by: 'deterministic_after_provider_error', provider_error: 'APITimeoutError' });
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/the provider failed/i)).toBeInTheDocument();
  });

  it('carries the caveats that qualify the whole list', async () => {
    stub();
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/not instructions to act/)).toBeInTheDocument();
    expect(screen.getByText(/snapshot dated 2026-08-01/)).toBeInTheDocument();
  });

  it('explains an empty list instead of rendering nothing', async () => {
    // Nothing to report and nothing loaded look identical otherwise.
    stub({ items: [] });
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/Nothing met the bar for a recommendation/)).toBeInTheDocument();
    expect(screen.getByText(/dropped rather than softened/)).toBeInTheDocument();
  });

  it('re-reads the data on request', async () => {
    // It owns a page now, so it does not collapse - a page that hides its
    // only content is a worse control than no control. Refresh replaces it,
    // and matters more at temperature 2.0, where a re-read genuinely differs.
    const spy = stub();
    renderWithProviders(<RecommendationList />);
    await screen.findByText('Critical supply exceptions are open');

    // Two passes, not one: the computed pass renders in about six seconds and
    // the written pass replaces its wording when it arrives (D-104).
    expect(spy).toHaveBeenCalledWith(false);
    expect(spy).toHaveBeenCalledWith(true);
    expect(spy).toHaveBeenCalledTimes(2);

    await userEvent.click(screen.getByRole('button', { name: 'Refresh recommendations' }));

    expect(spy).toHaveBeenCalledTimes(4);
    expect(screen.getByText('Critical supply exceptions are open')).toBeInTheDocument();
  });

  it('asks for the computed pass first, so content is not behind the prose', async () => {
    const spy = stub();
    renderWithProviders(<RecommendationList />);
    await screen.findByText('Critical supply exceptions are open');

    // The fast pass must be the first call. Asking for prose first would put
    // a thirty-five second wait in front of figures that were ready in six.
    expect(spy.mock.calls[0]).toEqual([false]);
  });
});

describe('per branch x SKU lines', () => {
  it('names the branch and the SKU rather than counting lines', async () => {
    stub();
    renderWithProviders(<RecommendationList />);

    // The SKU appears in the card heading and again inside the explanation,
    // which is the point: the prose names the line rather than saying "this SKU".
    const named = await screen.findAllByText(/FG\.BA5\.LFH\.GCG2120000/);
    expect(named.length).toBeGreaterThanOrEqual(1);
    expect(named[0]!.textContent).toContain('BENGALURU');
  });

  it('shows the computed reason, not only the model prose', async () => {
    // The ranking is the application's; the model explains it. If the model
    // failed, the reason must still be on the card.
    stub();
    renderWithProviders(<RecommendationList />);

    expect(
      await screen.findByText(/No usable stock against a q95 planning demand/),
    ).toBeInTheDocument();
  });

  it('flags censored demand, because the order is a lower bound there', async () => {
    stub();
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText('Censored demand')).toBeInTheDocument();
  });

  it('says how many ranked lines it is not showing', async () => {
    stub();
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/Showing 1 of 40 lines/)).toBeInTheDocument();
    expect(screen.getByText(/39 not shown/)).toBeInTheDocument();
  });

  it('renders an unavailable line as an absence, never as an order of zero', async () => {
    stub({
      lines: [
        line({
          urgency: 'cannot_recommend',
          urgency_reason: 'No active champion is selected for this scope.',
          recommended_order: null,
          quantile_forecast: null,
          unavailable_reason: 'No active champion is selected for this scope.',
        }),
      ],
    });
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText('No recommendation')).toBeInTheDocument();
    expect(screen.getByText(/Nothing was substituted/)).toBeInTheDocument();
    expect(screen.queryByText('Recommended order')).not.toBeInTheDocument();
  });

  it('marks a template-written line so it does not read as model-written', async () => {
    stub({ lines: [line({ written_by_model: false })], lines_answered_by: 'deterministic_after_provider_error' });
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText('template')).toBeInTheDocument();
    expect(
      screen.getByText(/figures and the ranking are unaffected/),
    ).toBeInTheDocument();
  });

  it('filters by branch without changing what was ranked', async () => {
    const user = userEvent.setup();
    stub({
      lines: [line(), line({ scope_key: 'DELHI-1|FG.ZZZ', branch: 'DELHI-1', sku: 'FG.ZZZ' })],
      lines_shown: 2,
    });
    renderWithProviders(<RecommendationList />);

    expect(await screen.findByText(/FG\.ZZZ/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Location'), 'BENGALURU');

    expect(screen.queryByText(/FG\.ZZZ/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/FG\.BA5\.LFH\.GCG2120000/).length).toBeGreaterThan(0);
    // The ranked total is unchanged by a client-side filter.
    expect(screen.getByText(/of 40 lines/)).toBeInTheDocument();
  });
});
